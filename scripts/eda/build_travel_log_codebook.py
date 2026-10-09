"""Build a local profiler allowlist from documented travel-log field ranges."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

from validate_travel_log_code_domains import (
    GROUPS,
    MAPPING,
    allowed,
    codebook as read_codebook,
    codebook_file,
    no_symlink,
    read_rows,
)

ROOT = Path(__file__).resolve().parents[2]
RESULTS_ROOT = ROOT / "results/eda/travel-log-2023"
REGIONS = ("west", "east", "jeju-islands")
UNRESOLVED = {"TRAVEL_MISSION", "TRAVEL_MISSION_CHECK", "EXPND_SE"}
TABULAR_EXTENSIONS = {".csv", ".json", ".jsonl", ".ndjson"}
CODEA_PATTERN = re.compile(r"^tc_codea(?:_.+)?\.csv$", re.I)


def codea_file(codebook_root: Path, region: str) -> Path:
    if not no_symlink(codebook_root):
        raise ValueError("code_table_path_invalid")
    root = codebook_root.resolve(strict=True)
    if root.name.upper() != "TL_CSV" or f"2023-travel-log-{region}" not in root.parts:
        raise ValueError("code_table_region_or_role_invalid")
    found = []
    for base, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = [name for name in dirs if not (Path(base) / name).is_symlink()]
        found.extend(Path(base) / name for name in files if CODEA_PATTERN.fullmatch(name))
    if len(found) != 1 or not no_symlink(found[0]):
        raise ValueError("code_table_mapping_unavailable")
    return found[0]


def has_symlink_component(path: Path) -> bool:
    current = Path(path.anchor)
    for part in path.absolute().parts[1:]:
        current /= part
        if current.is_symlink():
            return True
    return False


def build_spec(input_root: Path, region: str, codebook_root: Path) -> dict:
    if region not in REGIONS or has_symlink_component(input_root):
        raise ValueError("input_region_invalid")
    root = input_root.resolve(strict=True)
    if not root.is_dir() or f"2023-travel-log-{region}" not in root.parts:
        raise ValueError("input_root_invalid")
    codea_path = codea_file(codebook_root, region)
    codeb_path = codebook_file(codebook_root, region)
    codea_groups = {
        row["CD_A"] for row in read_rows(codea_path, {"CD_A"})
        if row["CD_A"] and row["CD_A"].strip()
    }
    codeb_groups = read_codebook(codeb_path)
    group_validation = {}
    for group in sorted(GROUPS):
        documented = set().union(*(
            allowed(ranges)
            for fields in MAPPING.values()
            for field_group, ranges in fields.values()
            if field_group == group
        ))
        actual = codeb_groups[group]
        group_validation[group] = (
            "valid" if group in codea_groups and actual == documented else "unresolved"
        )

    paths = []
    for base, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(name for name in dirs if not (Path(base) / name).is_symlink())
        for name in sorted(files):
            path = Path(base) / name
            if not path.is_symlink() and path.suffix.lower() in TABULAR_EXTENSIONS:
                paths.append(path)
    paths.sort(key=lambda path: path.relative_to(root).as_posix())

    tables: dict[str, dict[str, list[str]]] = {}
    unresolved_fields: dict[str, list[str]] = {}
    column_groups: dict[str, dict[str, str]] = {}
    for index, path in enumerate(paths, 1):
        if path.suffix.lower() != ".csv":
            continue
        alias = f"table_{index:06d}{path.suffix.lower()}"
        field_map = next(
            (fields for table, fields in MAPPING.items()
             if path.name.upper().startswith(f"{table}_")),
            None,
        )
        if not field_map:
            continue
        direct = {}
        unresolved = []
        for field, (_group, ranges) in field_map.items():
            column_groups.setdefault(alias, {})[field] = _group
            if field in UNRESOLVED:
                unresolved.append(field)
            else:
                direct[field] = sorted(allowed(ranges) & codeb_groups[_group])
        if direct:
            tables[alias] = direct
        if unresolved:
            unresolved_fields[alias] = sorted(unresolved)
    if not tables and not unresolved_fields:
        raise ValueError("mapped_inputs_missing")
    return {
        "source": f"AI Hub 2023 {region} official travel-log manual; documented ranges",
        "tables": tables,
        "unresolved_fields": unresolved_fields,
        "column_groups": column_groups,
        "group_validation": group_validation,
    }


def write_spec(spec: dict, output: Path) -> None:
    if has_symlink_component(output):
        raise ValueError("output_path_invalid")
    resolved = output.resolve(strict=False)
    if not resolved.is_relative_to(RESULTS_ROOT.resolve()) or resolved == RESULTS_ROOT.resolve():
        raise ValueError("output_path_invalid")
    if not output.parent.is_dir() or output.exists():
        raise ValueError("output_destination_invalid")
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", str(output)], cwd=ROOT, check=False,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    if ignored.returncode != 0:
        raise ValueError("output_not_ignored")
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=output.parent, prefix=".codebook-spec-", delete=False
    ) as stream:
        temp = Path(stream.name)
        json.dump(spec, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    os.replace(temp, output)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--codebook-root", type=Path, required=True)
    parser.add_argument("--region", choices=REGIONS, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        spec = build_spec(args.input_root, args.region, args.codebook_root)
        write_spec(spec, args.output)
    except (OSError, ValueError) as exc:
        reason = str(exc) if isinstance(exc, ValueError) else "input_or_output_unavailable"
        raise SystemExit(f"allowlist generation stopped: {reason}") from None
    print("allowlist JSON generated; values and paths were not printed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
