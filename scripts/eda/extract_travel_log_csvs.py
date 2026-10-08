"""Safely extract selected CSV members from approved regional ZIP archives."""

from __future__ import annotations

import argparse
import os
import shutil
import stat
import struct
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from validate_capital_codebook import has_symlink_component

MAX_ARCHIVE_MEMBERS = 20_000
MAX_CENTRAL_DIRECTORY_BYTES = 32 << 20
MAX_MEMBER_DEPTH = 64
MAX_DECLARED_ARCHIVE_BYTES = 16 << 30
MAX_CSV_FILE_BYTES = 4 << 30
MAX_CSV_TOTAL_BYTES = 16 << 30
MAX_CSV_FILES = 20_000
CHUNK_BYTES = 1 << 20
REGIONS = ("capital", "west", "east", "jeju-islands")
ROLES = ("Other", "TL_csv", "TL_gps_data", "VL_csv", "VL_gps_data")


class ExtractionBlocked(Exception):
    """A path or archive failed a conservative validation check."""


@dataclass(frozen=True)
class CsvMember:
    info: zipfile.ZipInfo
    relative: PurePosixPath
    size: int


@dataclass(frozen=True)
class ArchivePlan:
    role: str
    path: Path
    members: tuple[CsvMember, ...]
    archive_size: int
    archive_mtime_ns: int


def parse_archive_spec(value: str) -> tuple[str, Path]:
    role, separator, raw_path = value.partition("=")
    if not separator or role not in ROLES or not raw_path:
        raise argparse.ArgumentTypeError(
            "--archive 형식은 Other|TL_csv|TL_gps_data|VL_csv|VL_gps_data=/raw/archive.zip 입니다."
        )
    return role, Path(raw_path)


def safe_member_path(name: str) -> PurePosixPath:
    if not name or "\\" in name or "\x00" in name or name.startswith("/"):
        raise ExtractionBlocked
    parts = name.split("/")
    if parts[-1] == "":
        parts.pop()
    if (
        not parts
        or len(parts) > MAX_MEMBER_DEPTH
        or any(part in ("", ".", "..") or ":" in part for part in parts)
    ):
        raise ExtractionBlocked
    return PurePosixPath(*parts)


def preflight_zip_directory(path: Path) -> tuple[int, int]:
    """Bound ZIP central-directory fields before ZipFile.infolist()."""
    file_size = path.stat().st_size
    tail_size = min(file_size, 22 + 65_535)
    with path.open("rb") as stream:
        stream.seek(file_size - tail_size)
        tail = stream.read(tail_size)
        marker = tail.rfind(b"PK\x05\x06")
        if marker < 0 or marker + 22 > len(tail):
            raise ExtractionBlocked
        (
            signature,
            disk,
            directory_disk,
            disk_entries,
            total_entries,
            directory_size,
            directory_offset,
            comment_size,
        ) = struct.unpack_from("<4s4H2LH", tail, marker)
        if signature != b"PK\x05\x06" or marker + 22 + comment_size != len(tail):
            raise ExtractionBlocked
        eocd_offset = file_size - tail_size + marker
        if disk != 0 or directory_disk != 0 or disk_entries != total_entries:
            raise ExtractionBlocked

        if (
            total_entries == 0xFFFF
            or directory_size == 0xFFFFFFFF
            or directory_offset == 0xFFFFFFFF
        ):
            locator_offset = eocd_offset - 20
            if locator_offset < 0:
                raise ExtractionBlocked
            stream.seek(locator_offset)
            locator = stream.read(20)
            if len(locator) != 20:
                raise ExtractionBlocked
            locator_sig, zip64_disk, zip64_offset, disk_count = struct.unpack("<4sLQL", locator)
            if locator_sig != b"PK\x06\x07" or zip64_disk != 0 or disk_count != 1:
                raise ExtractionBlocked
            stream.seek(zip64_offset)
            record = stream.read(56)
            if len(record) != 56:
                raise ExtractionBlocked
            values = struct.unpack("<4sQ2H2L4Q", record)
            if values[0] != b"PK\x06\x06" or values[4] != 0 or values[5] != 0:
                raise ExtractionBlocked
            if values[6] != values[7]:
                raise ExtractionBlocked
            total_entries, directory_size, directory_offset = values[7], values[8], values[9]

    if (
        total_entries < 1
        or total_entries > MAX_ARCHIVE_MEMBERS
        or directory_size > MAX_CENTRAL_DIRECTORY_BYTES
        or directory_offset + directory_size > file_size
    ):
        raise ExtractionBlocked
    return total_entries, directory_size


def _member_kinds(
    archive: zipfile.ZipFile, expected_entries: int
) -> tuple[list[tuple[zipfile.ZipInfo, PurePosixPath, bool]], int]:
    infos = archive.infolist()
    if not infos or len(infos) != expected_entries or len(infos) > MAX_ARCHIVE_MEMBERS:
        raise ExtractionBlocked
    members: list[tuple[zipfile.ZipInfo, PurePosixPath, bool]] = []
    kinds: dict[str, bool] = {}
    total_declared = 0
    for info in infos:
        relative = safe_member_path(info.filename)
        key = relative.as_posix().casefold()
        mode = (info.external_attr >> 16) & 0xFFFF
        file_type = stat.S_IFMT(mode)
        if file_type == stat.S_IFLNK or key in kinds or info.flag_bits & 1:
            raise ExtractionBlocked
        is_directory = info.is_dir() or file_type == stat.S_IFDIR
        if info.file_size < 0 or info.compress_size < 0:
            raise ExtractionBlocked
        kinds[key] = is_directory
        total_declared += info.file_size
        if total_declared > MAX_DECLARED_ARCHIVE_BYTES:
            raise ExtractionBlocked
        members.append((info, relative, is_directory))

    file_keys = {key for key, is_directory in kinds.items() if not is_directory}
    for key in kinds:
        parts = key.split("/")
        if any("/".join(parts[:depth]) in file_keys for depth in range(1, len(parts))):
            raise ExtractionBlocked
    return members, total_declared


def checked_csv_members(
    archive: zipfile.ZipFile, expected_entries: int
) -> tuple[list[CsvMember], int]:
    entries, _total_declared = _member_kinds(archive, expected_entries)
    selected = [
        CsvMember(info, relative, info.file_size)
        for info, relative, is_directory in entries
        if not is_directory and relative.suffix.casefold() == ".csv"
    ]
    total_bytes = sum(member.size for member in selected)
    if (
        not selected
        or len(selected) > MAX_CSV_FILES
        or total_bytes > MAX_CSV_TOTAL_BYTES
        or any(member.size > MAX_CSV_FILE_BYTES for member in selected)
    ):
        raise ExtractionBlocked
    return selected, total_bytes


def prepare_plans(
    raw_root_arg: Path,
    region: str,
    archive_specs: list[tuple[str, Path]],
) -> tuple[Path, Path, list[ArchivePlan]]:
    if has_symlink_component(raw_root_arg):
        raise ExtractionBlocked
    raw_root = raw_root_arg.resolve(strict=True)
    if not raw_root.is_dir() or not archive_specs:
        raise ExtractionBlocked
    region_root_arg = raw_root / f"2023-travel-log-{region}"
    if has_symlink_component(region_root_arg):
        raise ExtractionBlocked
    region_root = region_root_arg.resolve(strict=True)
    if not region_root.is_dir():
        raise ExtractionBlocked

    roles: set[str] = set()
    paths: set[Path] = set()
    plans: list[ArchivePlan] = []
    for role, requested in archive_specs:
        if role in roles or has_symlink_component(requested):
            raise ExtractionBlocked
        roles.add(role)
        archive_path = requested.resolve(strict=True)
        if not archive_path.is_file():
            raise ExtractionBlocked
        try:
            archive_path.relative_to(region_root)
        except ValueError:
            raise ExtractionBlocked from None
        if archive_path in paths:
            raise ExtractionBlocked
        paths.add(archive_path)
        before = archive_path.stat()
        expected_entries, _directory_size = preflight_zip_directory(archive_path)
        with zipfile.ZipFile(archive_path, "r") as archive:
            members, _total_bytes = checked_csv_members(archive, expected_entries)
        plans.append(
            ArchivePlan(
                role=role,
                path=archive_path,
                members=tuple(members),
                archive_size=before.st_size,
                archive_mtime_ns=before.st_mtime_ns,
            )
        )
    return raw_root, region_root, plans


def prepare_output(region_root: Path, output_arg: Path) -> Path:
    if has_symlink_component(output_arg):
        raise ExtractionBlocked
    output = output_arg.resolve(strict=False)
    try:
        output.relative_to(region_root)
    except ValueError:
        raise ExtractionBlocked from None
    if output == region_root or output.exists() or not output.parent.is_dir():
        raise ExtractionBlocked
    return output


def _copy_member(archive: zipfile.ZipFile, member: CsvMember, destination: Path) -> None:
    copied = 0
    with archive.open(member.info, "r") as source, destination.open("xb") as target:
        while True:
            chunk = source.read(CHUNK_BYTES)
            if not chunk:
                break
            copied += len(chunk)
            if copied > member.size:
                raise ExtractionBlocked
            target.write(chunk)
    if copied != member.size or destination.stat().st_size != member.size:
        raise ExtractionBlocked


def _extract_plan(plan: ArchivePlan, output: Path, raw_root: Path) -> None:
    current = plan.path.stat()
    if (current.st_size, current.st_mtime_ns) != (plan.archive_size, plan.archive_mtime_ns):
        raise ExtractionBlocked
    total_bytes = sum(member.size for member in plan.members)
    required_space = max(total_bytes, 3 * plan.archive_size)
    if shutil.disk_usage(raw_root).free < required_space:
        raise ExtractionBlocked

    role_root = output / plan.role
    role_root.mkdir(mode=0o700, exist_ok=False)
    with zipfile.ZipFile(plan.path, "r") as archive:
        for member in plan.members:
            destination = role_root.joinpath(*member.relative.parts)
            if not destination.resolve(strict=False).is_relative_to(role_root.resolve(strict=True)):
                raise ExtractionBlocked
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            _copy_member(archive, member, destination)
    after = plan.path.stat()
    if (after.st_size, after.st_mtime_ns) != (plan.archive_size, plan.archive_mtime_ns):
        raise ExtractionBlocked


def verify_inventory(output: Path, plans: list[ArchivePlan]) -> None:
    expected_roles = {plan.role for plan in plans}
    if {path.name for path in output.iterdir()} != expected_roles:
        raise ExtractionBlocked
    for plan in plans:
        role_root = output / plan.role
        expected = {member.relative.as_posix(): member.size for member in plan.members}
        found: dict[str, int] = {}
        found_directories: set[str] = set()
        expected_directories = {
            "/".join(member.relative.parts[:depth])
            for member in plan.members
            for depth in range(1, len(member.relative.parts))
        }
        for current, directories, names in os.walk(role_root, followlinks=False):
            base = Path(current)
            if any((base / name).is_symlink() for name in directories + names):
                raise ExtractionBlocked
            directories[:] = sorted(directories)
            found_directories.update(
                (base / name).relative_to(role_root).as_posix() for name in directories
            )
            for name in names:
                path = base / name
                relative = path.relative_to(role_root).as_posix()
                if path.suffix.casefold() != ".csv" or relative in found:
                    raise ExtractionBlocked
                found[relative] = path.stat().st_size
        if found != expected or found_directories != expected_directories:
            raise ExtractionBlocked


def extract_archives(raw_root: Path, plans: list[ArchivePlan], output: Path) -> None:
    output.mkdir(mode=0o700, exist_ok=False)
    reservation = output.stat()
    completed = False
    try:
        for plan in plans:
            _extract_plan(plan, output, raw_root)
        verify_inventory(output, plans)
        completed = True
    finally:
        if not completed and output.exists() and not output.is_symlink():
            current = output.stat()
            if (current.st_dev, current.st_ino) == (reservation.st_dev, reservation.st_ino):
                shutil.rmtree(output)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="승인된 regional ZIP에서 지정한 표 역할의 CSV만 안전 추출합니다."
    )
    parser.add_argument("--raw-root", required=True, type=Path)
    parser.add_argument("--region", required=True, choices=REGIONS)
    parser.add_argument(
        "--archive", action="append", required=True, type=parse_archive_spec,
        metavar="ROLE=PATH",
        help="반복 지정: Other|TL_csv|TL_gps_data|VL_csv|VL_gps_data=/raw/archive.zip",
    )
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--confirm-approved", action="store_true", required=True)
    parser.add_argument("--confirm-terms", action="store_true", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        raw_root, region_root, plans = prepare_plans(args.raw_root, args.region, args.archive)
        output = prepare_output(region_root, args.output)
        extract_archives(raw_root, plans, output)
    except Exception:
        print("status: blocked_or_extraction_failed", file=sys.stderr)
        return 2
    print("status: completed")
    print("integrity: CRC_declared_sizes_and_final_inventory_verified")
    print("archive: preserved")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
