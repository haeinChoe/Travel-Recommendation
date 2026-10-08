"""Inspect approved SbL ZIP JSON structure without extracting member files.

JSON members are streamed from the archive and parsed in memory; only coarse
structural types and key-count bands are serialized. Member names, paths, keys,
and values are never written or printed.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import shutil
import stat
import struct
import sys
import tempfile
import zipfile
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any, TextIO

from profile_travel_log import (
    RESULTS_ROOT,
    _public_count,
    has_symlink_component,
    is_within,
)

K = 10
MAX_ARCHIVE_MEMBERS = 20_000
MAX_CENTRAL_DIRECTORY_BYTES = 32 << 20
MAX_ARCHIVE_DECLARED_BYTES = 1 << 40
MAX_JSON_FILES = 10_000
MAX_JSON_BYTES = 1 << 30
MAX_JSON_FILE_BYTES = 16 << 20
REGIONS = ("capital", "west", "east", "jeju-islands")
ROLES = ("SbL",)
ARTIFACTS = ("archive_metadata.csv", "run_metadata.json")
CSV_FIELDS = (
    "region", "archive_role", "metric", "category", "count", "status",
)


class ArchiveBlocked(Exception):
    """An archive or path failed a conservative validation check."""


def parse_archive_spec(value: str) -> tuple[str, Path]:
    role, separator, raw_path = value.partition("=")
    if not separator or role not in ROLES or not raw_path:
        raise argparse.ArgumentTypeError(
            "--archive 형식은 SbL=/raw/archive.zip 입니다."
        )
    return role, Path(raw_path)


def preflight_zip_directory(path: Path) -> tuple[int, int]:
    """Bound central-directory metadata before zipfile materializes entries."""
    file_size = path.stat().st_size
    tail_size = min(file_size, 22 + 65_535)
    with path.open("rb") as stream:
        stream.seek(file_size - tail_size)
        tail = stream.read(tail_size)
        marker = tail.rfind(b"PK\x05\x06")
        if marker < 0 or marker + 22 > len(tail):
            raise ArchiveBlocked
        (
            signature, disk, directory_disk, disk_entries, total_entries,
            directory_size, directory_offset, comment_size,
        ) = struct.unpack_from("<4s4H2LH", tail, marker)
        if signature != b"PK\x05\x06" or marker + 22 + comment_size != len(tail):
            raise ArchiveBlocked
        eocd_offset = file_size - tail_size + marker
        if disk != 0 or directory_disk != 0 or disk_entries != total_entries:
            raise ArchiveBlocked

        if (
            total_entries == 0xFFFF
            or directory_size == 0xFFFFFFFF
            or directory_offset == 0xFFFFFFFF
        ):
            locator_offset = eocd_offset - 20
            if locator_offset < 0:
                raise ArchiveBlocked
            stream.seek(locator_offset)
            locator = stream.read(20)
            if len(locator) != 20:
                raise ArchiveBlocked
            locator_sig, zip64_disk, zip64_offset, disk_count = struct.unpack("<4sLQL", locator)
            if locator_sig != b"PK\x06\x07" or zip64_disk != 0 or disk_count != 1:
                raise ArchiveBlocked
            stream.seek(zip64_offset)
            record = stream.read(56)
            if len(record) != 56:
                raise ArchiveBlocked
            values = struct.unpack("<4sQ2H2L4Q", record)
            if values[0] != b"PK\x06\x06" or values[4] != 0 or values[5] != 0:
                raise ArchiveBlocked
            if values[6] != values[7]:
                raise ArchiveBlocked
            total_entries, directory_size, directory_offset = values[7], values[8], values[9]

    if (
        total_entries < 1
        or total_entries > MAX_ARCHIVE_MEMBERS
        or directory_size > MAX_CENTRAL_DIRECTORY_BYTES
        or directory_offset + directory_size > file_size
    ):
        raise ArchiveBlocked
    return total_entries, directory_size


def safe_member_name(name: str) -> PurePosixPath:
    if not name or "\\" in name or "\x00" in name or name.startswith("/"):
        raise ArchiveBlocked
    parts = name.split("/")
    if parts[-1] == "":
        parts.pop()
    if not parts or len(parts) > 64 or any(
        part in ("", ".", "..") or ":" in part for part in parts
    ):
        raise ArchiveBlocked
    return PurePosixPath(*parts)


def checked_infos(archive: zipfile.ZipFile, expected_entries: int) -> list[zipfile.ZipInfo]:
    infos = archive.infolist()
    if not infos or len(infos) != expected_entries or len(infos) > MAX_ARCHIVE_MEMBERS:
        raise ArchiveBlocked
    seen: set[str] = set()
    total_declared = 0
    for info in infos:
        relative = safe_member_name(info.filename)
        key = relative.as_posix().casefold()
        mode = (info.external_attr >> 16) & 0xFFFF
        if key in seen or (mode and stat.S_ISLNK(mode)):
            raise ArchiveBlocked
        seen.add(key)
        if info.file_size < 0 or info.compress_size < 0:
            raise ArchiveBlocked
        total_declared += info.file_size
        if total_declared > MAX_ARCHIVE_DECLARED_BYTES:
            raise ArchiveBlocked
        if info.flag_bits & 1 and relative.suffix.casefold() == ".json":
            raise ArchiveBlocked
    return infos


def safe_distribution(counts: Counter[str]) -> list[tuple[str, int]]:
    """Apply k suppression and complementary suppression to a category set."""
    positive = [(key, count) for key, count in counts.items() if count > 0]
    total = sum(count for _, count in positive)
    if total == 0:
        return [("none", 0)]
    if total < K:
        return [("<suppressed>", total)]
    shown = sorted(((key, n) for key, n in positive if n >= K), key=lambda item: -item[1])
    hidden = sum(n for _, n in positive if n < K)
    while 0 < hidden < K and shown:
        hidden += shown.pop()[1]
    result = shown
    if hidden:
        result.append(("<suppressed>", hidden))
    return result


def type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    if isinstance(value, str):
        return "string"
    if isinstance(value, (int, float)):
        return "number"
    return "other"


def key_count_band(value: int) -> str:
    if value == 0:
        return "0"
    if value < 5:
        return "1-4"
    if value < 10:
        return "5-9"
    return "10+"


def parse_json_structure(stream: TextIO) -> tuple[str, int | None, Counter[str], Counter[str]]:
    """Read one JSON document but return only generic structure statistics."""
    try:
        value = json.load(stream)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        return "invalid_json", None, Counter(), Counter()
    root = type_name(value)
    key_bands: Counter[str] = Counter()
    child_types: Counter[str] = Counter()
    if isinstance(value, dict):
        key_bands[key_count_band(len(value))] += 1
        child_types.update(type_name(item) for item in value.values())
    elif isinstance(value, list):
        child_types.update(type_name(item) for item in value)
    return root, len(value) if isinstance(value, (dict, list)) else None, key_bands, child_types


def validate_archive_paths(
    raw_root_arg: Path, region: str, archive_specs: list[tuple[str, Path]]
) -> tuple[Path, list[tuple[str, Path]]]:
    if has_symlink_component(raw_root_arg):
        raise ArchiveBlocked
    raw_root = raw_root_arg.resolve(strict=True)
    if not raw_root.is_dir():
        raise ArchiveBlocked
    region_root_arg = raw_root / f"2023-travel-log-{region}"
    if has_symlink_component(region_root_arg):
        raise ArchiveBlocked
    region_root = region_root_arg.resolve(strict=True)
    if not region_root.is_dir():
        raise ArchiveBlocked
    resolved: list[tuple[str, Path]] = []
    roles: set[str] = set()
    paths: set[Path] = set()
    for role, requested in archive_specs:
        if role in roles or has_symlink_component(requested):
            raise ArchiveBlocked
        roles.add(role)
        path = requested.resolve(strict=True)
        if not path.is_file() or not is_within(path, region_root):
            raise ArchiveBlocked
        if path in paths:
            raise ArchiveBlocked
        paths.add(path)
        resolved.append((role, path))
    return raw_root, resolved


def inspect_archive(role: str, path: Path) -> list[dict[str, Any]]:
    if role not in ROLES:
        raise ArchiveBlocked
    before = path.stat()
    expected_entries, _ = preflight_zip_directory(path)
    rows: list[dict[str, Any]] = []
    try:
        with zipfile.ZipFile(path, "r") as archive:
            infos = checked_infos(archive, expected_entries)
            json_infos: list[zipfile.ZipInfo] = []
            for info in infos:
                if info.is_dir():
                    continue
                suffix = PurePosixPath(info.filename).suffix.casefold()
                if suffix == ".json":
                    json_infos.append(info)

            total_json_bytes = sum(info.file_size for info in json_infos)
            if (
                len(json_infos) > MAX_JSON_FILES
                or total_json_bytes > MAX_JSON_BYTES
                or any(info.file_size > MAX_JSON_FILE_BYTES for info in json_infos)
            ):
                raise ArchiveBlocked
            root_types: Counter[str] = Counter()
            key_bands: Counter[str] = Counter()
            child_types: Counter[str] = Counter()
            valid_documents = 0
            for info in json_infos:
                with archive.open(info, "r") as member:
                    with io.TextIOWrapper(member, encoding="utf-8-sig") as text_stream:
                        root, _top_level_len, keys, children = parse_json_structure(text_stream)
                root_types[root] += 1
                if root != "invalid_json":
                    valid_documents += 1
                key_bands.update(keys)
                child_types.update(children)
            rows.extend(
                distribution_rows(role, "json_root_type", root_types, "parsed_json_members")
            )
            if valid_documents < K:
                rows.append(
                    {
                        "archive_role": role,
                        "metric": "json_top_level_key_count_band",
                        "category": "<suppressed>",
                        "count": _public_count(valid_documents, K),
                        "status": "json_cohort_below_k",
                    }
                )
                rows.append(
                    {
                        "archive_role": role,
                        "metric": "json_top_level_child_type",
                        "category": "<suppressed>",
                        "count": _public_count(valid_documents, K),
                        "status": "json_cohort_below_k",
                    }
                )
            else:
                rows.extend(distribution_rows(role, "json_top_level_key_count_band", key_bands))
                rows.extend(distribution_rows(role, "json_top_level_child_type", child_types))
            if not json_infos:
                rows.append(
                    {
                        "archive_role": role,
                        "metric": "json_root_type",
                        "category": "none",
                        "count": "0",
                        "status": "no_json_members",
                    }
                )
        after = path.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ArchiveBlocked
    except ArchiveBlocked:
        raise
    except Exception:
        raise ArchiveBlocked from None
    return rows


def distribution_rows(
    role: str, metric: str, counts: Counter[str], cohort_label: str | None = None
) -> list[dict[str, Any]]:
    output = []
    for category, count in safe_distribution(counts):
        output.append(
            {
                "archive_role": role,
                "metric": metric,
                "category": category,
                "count": _public_count(count, K),
                "status": "aggregate" if cohort_label is None else cohort_label,
            }
        )
    return output


def public_rows(region: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"region": region, **row} for row in rows]


def write_outputs(output: Path, region: str, rows: list[dict[str, Any]], roles: list[str]) -> None:
    resolved_output = output.resolve(strict=False)
    if (
        not is_within(resolved_output, RESULTS_ROOT.resolve())
        or resolved_output == RESULTS_ROOT.resolve()
        or has_symlink_component(output.absolute())
        or resolved_output.exists()
    ):
        raise ArchiveBlocked
    RESULTS_ROOT.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix="archive-metadata-", dir=RESULTS_ROOT))
    try:
        csv_path = stage / ARTIFACTS[0]
        with csv_path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(public_rows(region, rows))
        metadata = {
            "region": region,
            "archive_roles": sorted(roles),
            "k": K,
            "count_policy": "0/<10/10+ with complementary suppression",
            "json_policy": (
                "SbL JSON members parsed in memory; raw values, member names, paths, "
                "and keys are not serialized"
            ),
            "limits": {
                "archive_members_max": MAX_ARCHIVE_MEMBERS,
                "central_directory_bytes_max": MAX_CENTRAL_DIRECTORY_BYTES,
                "json_members_max": MAX_JSON_FILES,
                "json_total_uncompressed_bytes_max": MAX_JSON_BYTES,
                "json_member_uncompressed_bytes_max": MAX_JSON_FILE_BYTES,
                "nested_archives": "not traversed",
            },
        }
        (stage / ARTIFACTS[1]).write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        resolved_output.parent.mkdir(parents=True, exist_ok=True)
        stage.rename(resolved_output)
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="승인된 SbL ZIP의 JSON 구조 메타데이터만 안전 집계합니다."
    )
    parser.add_argument("--raw-root", required=True, type=Path)
    parser.add_argument("--region", required=True, choices=REGIONS)
    parser.add_argument(
        "--archive", action="append", required=True, type=parse_archive_spec,
        metavar="ROLE=PATH", help="SbL=/approved/raw/archive.zip만 지정할 수 있습니다.",
    )
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--confirm-approved", action="store_true", required=True)
    parser.add_argument("--confirm-terms", action="store_true", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        _raw_root, archives = validate_archive_paths(
            args.raw_root, args.region, args.archive
        )
        rows: list[dict[str, Any]] = []
        for role, path in archives:
            rows.extend(inspect_archive(role, path))
        write_outputs(args.output, args.region, rows, [role for role, _ in archives])
    except (ArchiveBlocked, OSError, ValueError, zipfile.BadZipFile, RuntimeError):
        print("[중단] ZIP 또는 경로를 안전하게 검증하지 못했습니다.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
