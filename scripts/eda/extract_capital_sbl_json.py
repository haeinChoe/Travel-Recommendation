"""Extract only JSON members from an explicitly approved capital SbL archive.

The source archive is read-only. Member names and paths are never logged.
A new mode-0700 wrapper and its ``json`` child are reserved exclusively;
failures clean up only those paths created by this invocation.
"""

from __future__ import annotations

import argparse
import os
import shutil
import stat
import struct
import zipfile
from pathlib import Path, PurePosixPath

from validate_capital_codebook import has_symlink_component

MAX_JSON_FILES = 10_000
MAX_JSON_BYTES = 1 << 30
MAX_FILE_BYTES = 16 << 20
MAX_ARCHIVE_MEMBERS = 20_000
MAX_CENTRAL_DIRECTORY_BYTES = 32 << 20
MAX_MEMBER_DEPTH = 64
K = 10


class ExtractionBlocked(Exception):
    pass


def bucket(value: int) -> str:
    if value == 0:
        return "0"
    return "<10" if value < K else "10+"


def safe_member_path(name: str) -> PurePosixPath:
    if not name or "\\" in name or "\x00" in name:
        raise ExtractionBlocked
    if name.startswith("//"):
        raise ExtractionBlocked
    raw_parts = name.split("/")
    if name.startswith("/"):
        raw_parts = raw_parts[1:]
    if raw_parts and raw_parts[-1] == "":
        raw_parts = raw_parts[:-1]
    if (
        not raw_parts
        or len(raw_parts) > MAX_MEMBER_DEPTH
        or any(part in ("", ".", "..") or ":" in part for part in raw_parts)
    ):
        raise ExtractionBlocked
    return PurePosixPath(*raw_parts)


def preflight_zip_directory(path: Path) -> tuple[int, int]:
    """Bound central-directory metadata before zipfile materializes members."""
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
            total_entries = values[7]
            directory_size = values[8]
            directory_offset = values[9]

    if (
        total_entries < 1
        or total_entries > MAX_ARCHIVE_MEMBERS
        or directory_size > MAX_CENTRAL_DIRECTORY_BYTES
        or directory_offset + directory_size > file_size
    ):
        raise ExtractionBlocked
    return total_entries, directory_size


def checked_members(archive: zipfile.ZipFile):
    members: list[tuple[zipfile.ZipInfo, PurePosixPath]] = []
    kinds: dict[str, bool] = {}
    infos = archive.infolist()
    if not infos or len(infos) > MAX_ARCHIVE_MEMBERS:
        raise ExtractionBlocked
    for info in infos:
        mode = (info.external_attr >> 16) & 0xFFFF
        if mode and stat.S_ISLNK(mode):
            raise ExtractionBlocked
        relative = safe_member_path(info.filename)
        key = relative.as_posix().casefold()
        is_dir = info.is_dir()
        if key in kinds:
            raise ExtractionBlocked
        kinds[key] = is_dir
        if not is_dir and relative.suffix.casefold() == ".json":
            if info.flag_bits & 1:
                raise ExtractionBlocked
            members.append((info, relative))

    ordered_keys = sorted(kinds)
    file_keys = {key for key, is_dir in kinds.items() if not is_dir}
    for index, key in enumerate(ordered_keys):
        parts = key.split("/")
        if any("/".join(parts[:depth]) in file_keys for depth in range(1, len(parts))):
            raise ExtractionBlocked
        if not kinds[key] and index + 1 < len(ordered_keys):
            if ordered_keys[index + 1].startswith(key + "/"):
                raise ExtractionBlocked

    total_bytes = sum(info.file_size for info, _ in members)
    max_file = max((info.file_size for info, _ in members), default=0)
    if (
        not members
        or len(members) > MAX_JSON_FILES
        or total_bytes > MAX_JSON_BYTES
        or max_file > MAX_FILE_BYTES
    ):
        raise ExtractionBlocked
    return members, total_bytes


def prepare_paths(raw_arg: str, capital_arg: str, archive_arg: str, output_arg: str):
    raw_path = Path(raw_arg).expanduser()
    capital_path = Path(capital_arg).expanduser()
    archive_path = Path(archive_arg).expanduser()
    output_path = Path(output_arg).expanduser()
    if any(has_symlink_component(p) for p in (raw_path, capital_path, archive_path, output_path)):
        raise ExtractionBlocked
    raw_root = raw_path.resolve(strict=True)
    capital_input = capital_path.resolve(strict=True)
    archive = archive_path.resolve(strict=True)
    output = output_path.resolve(strict=False)
    capital_input.relative_to(raw_root)
    archive.relative_to(raw_root)
    output.relative_to(capital_input)
    if (
        not raw_root.is_dir()
        or not capital_input.is_dir()
        or not archive.is_file()
        or output == capital_input
        or output.parent != capital_input
        or output.exists()
    ):
        raise ExtractionBlocked
    return raw_root, capital_input, archive, output


def extract(archive_path: Path, capital_input: Path, output: Path) -> int:
    before = archive_path.stat()
    expected_members, _ = preflight_zip_directory(archive_path)
    if expected_members > MAX_ARCHIVE_MEMBERS:
        raise ExtractionBlocked
    # Atomic mode-0700 wrapper creation reserves this unique output location.
    # Reserve the final child with mkdir(exist_ok=False) too; no rename-over-
    # empty-directory race is possible on filesystems without renameat2.
    output.mkdir(mode=0o700, exist_ok=False)
    stage = output / "json"
    stage_created = False
    completed = False
    try:
        stage.mkdir(mode=0o700, exist_ok=False)
        stage_created = True
        with zipfile.ZipFile(archive_path, "r") as archive:
            members, total_bytes = checked_members(archive)
            if len(archive.infolist()) != expected_members:
                raise ExtractionBlocked
            required_bytes = max(total_bytes, 3 * before.st_size)
            if shutil.disk_usage(capital_input).free < required_bytes:
                raise ExtractionBlocked

            for info, relative in members:
                destination = stage.joinpath(*relative.parts)
                if not destination.resolve(strict=False).is_relative_to(stage.resolve(strict=True)):
                    raise ExtractionBlocked
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info, "r") as source, destination.open("xb") as target:
                    shutil.copyfileobj(source, target, 1024 * 1024)
                if destination.stat().st_size != info.file_size:
                    raise ExtractionBlocked

            count = 0
            size = 0
            for current, directories, names in os.walk(stage, followlinks=False):
                base = Path(current)
                if any((base / name).is_symlink() for name in directories + names):
                    raise ExtractionBlocked
                directories[:] = sorted(directories)
                for name in names:
                    path = base / name
                    if path.suffix.casefold() != ".json":
                        raise ExtractionBlocked
                    count += 1
                    size += path.stat().st_size
            if count != len(members) or size != total_bytes:
                raise ExtractionBlocked

            after = archive_path.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise ExtractionBlocked
        completed = True
        return count
    finally:
        if not completed:
            if stage_created and stage.exists() and not stage.is_symlink():
                shutil.rmtree(stage)
            # Remove only our empty wrapper reservation; never recurse into an
            # unexpected path that may have appeared after reservation.
            try:
                output.rmdir()
            except OSError:
                pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Safely extract approved capital SbL JSON members only.")
    parser.add_argument("--archive", required=True)
    parser.add_argument("--raw-root", required=True)
    parser.add_argument("--capital-input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--confirm-approved", action="store_true", required=True)
    parser.add_argument("--confirm-terms", action="store_true", required=True)
    args = parser.parse_args()
    try:
        _, capital_input, archive, output = prepare_paths(
            args.raw_root, args.capital_input, args.archive, args.output
        )
        count = extract(archive, capital_input, output)
    except (
        ExtractionBlocked,
        OSError,
        ValueError,
        OverflowError,
        struct.error,
        zipfile.BadZipFile,
        RuntimeError,
    ):
        print("status: blocked_or_extraction_failed")
        return 2
    print("status: completed")
    print(f"json_files_bucket: {bucket(count)}")
    print("integrity: CRC_and_declared_sizes_verified")
    print("output_reservation: atomic_wrapper_and_json_child")
    print("archive: preserved")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
