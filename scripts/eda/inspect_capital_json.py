"""Inspect documented capital caption-JSON structure and photo-ID linkage safely.

JSON values, paths, captions, tokens, and identifiers are used only in memory.
The ignored output contains documented schema labels and k-suppressed buckets.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

import duckdb
from interpret_capital_codebook import ScanFailure, find_table, projected_rows
from validate_capital_codebook import RESULTS_ROOT, has_symlink_component

REPO_ROOT = Path(__file__).resolve().parents[2]
K = 10
MAX_JSON_FILES = 10_000
MAX_JSON_BYTES = 1 << 30
MAX_FILE_BYTES = 16 << 20
SECTIONS = {
    "Info": ("Info",),
    "images": ("images",),
    "caption": ("caption",),
    "licenses": ("licenses",),
}
FIELDS = {
    "Info": ("DATASET_NM", "DATASET_DETAIL"),
    "images": (
        "PHOTO_FILE_ID",
        "PHOTO_FILE_NM",
        "PHOTO_FILE_SAVE_PATH",
        "PHOTO_FILE_RESOLUTION",
        "PHOTO_FILE_DT",
        "PHOTO_FILE_X_COORD",
        "PHOTO_FILE_Y_COORD",
        "VISIT_AREA_NM",
        "LANDMARK",
    ),
    "caption": ("IMG_CAPTION", "TOKEN", "TIME_STAMP"),
    "licenses": ("NAME",),
}
TYPE_NAMES = ("string", "number", "boolean", "object", "array", "null", "other")
ARRAY_LENGTH_BUCKETS = ("0", "1_lt10", "10plus")
METRICS = (
    "cohort",
    "present",
    "missing",
    *(f"type_{name}" for name in TYPE_NAMES),
    "empty",
    "nonempty",
    *(f"array_length_{name}" for name in ARRAY_LENGTH_BUCKETS),
)
OUTPUT_FIELDS = ("record_type", "section", "field", "metric", "bucket", "status")


def bucket(value: int) -> str:
    if value == 0:
        return "0"
    return "<10" if value < K else "10+"


def py_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, str):
        return "string"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    return "other"


def is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value == "" or value.isspace()
    if isinstance(value, (list, dict)):
        return len(value) == 0
    return False


def collect_json_files(root: Path) -> list[Path] | None:
    files: list[Path] = []
    total_bytes = 0
    for current, directories, names in os.walk(root, followlinks=False):
        base = Path(current)
        directories[:] = [name for name in directories if not (base / name).is_symlink()]
        for name in names:
            path = base / name
            if path.suffix.lower() != ".json" or path.is_symlink():
                continue
            try:
                size = path.stat().st_size
            except OSError:
                return None
            if size > MAX_FILE_BYTES:
                return None
            total_bytes += size
            files.append(path)
            if len(files) > MAX_JSON_FILES or total_bytes > MAX_JSON_BYTES:
                return None
    return files


def prepare_paths(raw_arg: str, input_arg: str, json_arg: str, output_arg: str, overwrite: bool):
    raw_path = Path(raw_arg).expanduser()
    input_path = Path(input_arg).expanduser()
    json_path = Path(json_arg).expanduser()
    output_path = Path(output_arg).expanduser()
    if any(has_symlink_component(item) for item in (raw_path, input_path, json_path, output_path)):
        return None
    try:
        raw_root = raw_path.resolve(strict=True)
        input_root = input_path.resolve(strict=True)
        json_root = json_path.resolve(strict=True)
        output = output_path.resolve(strict=False)
        input_root.relative_to(raw_root)
        json_root.relative_to(input_root)
        output.relative_to(RESULTS_ROOT.resolve(strict=True))
    except (OSError, ValueError):
        return None
    if (
        not raw_root.is_dir()
        or not input_root.is_dir()
        or not json_root.is_dir()
        or json_root == input_root
        or output.suffix.lower() != ".csv"
        or not output.parent.is_dir()
        or not output.parent.resolve().is_relative_to(RESULTS_ROOT.resolve())
    ):
        return None
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", "--no-index", str(output)],
        cwd=REPO_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if ignored.returncode != 0 or (output.exists() and not overwrite):
        return None
    return input_root, json_root, output


def add_metric(
    rows: list[dict[str, str]],
    record_type: str,
    section: str,
    field: str,
    metric: str,
    value: int,
    status: str = "k_suppressed_bucket",
) -> None:
    rows.append(
        {
            "record_type": record_type,
            "section": section,
            "field": field,
            "metric": metric,
            "bucket": bucket(value),
            "status": status,
        }
    )


def save(path: Path, rows: list[dict[str, str]]) -> bool:
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="",
            dir=path.parent,
            prefix=".json-structure-",
            delete=False,
        ) as stream:
            temporary = stream.name
            writer = csv.DictWriter(stream, fieldnames=OUTPUT_FIELDS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        return True
    except OSError:
        if temporary:
            Path(temporary).unlink(missing_ok=True)
        return False


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Inspect allowlisted capital JSON structure safely."
    )
    parser.add_argument("--raw-root", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--json-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    paths = prepare_paths(args.raw_root, args.input, args.json_root, args.output, args.overwrite)
    if paths is None:
        print("status: blocked_path_or_output", file=sys.stderr)
        return 2
    input_root, json_root, output = paths
    files = collect_json_files(json_root)
    if files is None:
        print("status: blocked_json_scan_bound", file=sys.stderr)
        return 2

    document_cohort = len(files)
    parsed_document_cohort = 0
    root_object_cohort = 0
    root_types: Counter[str] = Counter()
    parse_errors = 0
    section_types: dict[str, Counter[str]] = {section: Counter() for section in SECTIONS}
    section_present: Counter[str] = Counter()
    field_counts: dict[tuple[str, str], Counter[str]] = {
        (section, field): Counter() for section, fields in FIELDS.items() for field in fields
    }
    json_photo_id_present = 0
    json_photo_id_matches = 0
    json_photo_id_unmatched = 0

    con = duckdb.connect(database=":memory:")
    try:
        photo_table = find_table(input_root, "TN_TOUR_PHOTO", region_suffix=True)
        if photo_table is None:
            print("status: blocked_photo_table_mapping", file=sys.stderr)
            return 2
        photo_rows = projected_rows(con, photo_table, ("PHOTO_FILE_ID",))
        if photo_rows is None:
            print("status: blocked_photo_id_scan", file=sys.stderr)
            return 2
        photo_ids: set[str] = set()
        try:
            for (value,) in photo_rows:
                if isinstance(value, str) and value != "" and not value.isspace():
                    photo_ids.add(value)
        except ScanFailure:
            print("status: blocked_photo_id_scan", file=sys.stderr)
            return 2

        try:
            for path in files:
                try:
                    with path.open("r", encoding="utf-8-sig") as stream:
                        data = json.load(stream)
                except (OSError, UnicodeError, json.JSONDecodeError):
                    parse_errors += 1
                    continue
                parsed_document_cohort += 1
                root_type = py_type(data)
                root_types[root_type] += 1
                if not isinstance(data, dict):
                    for section in SECTIONS:
                        section_types[section]["missing"] += 1
                        for field in FIELDS[section]:
                            field_counts[(section, field)]["missing"] += 1
                    continue
                root_object_cohort += 1
                for section, aliases in SECTIONS.items():
                    present_aliases = [key for key in aliases if key in data]
                    if not present_aliases:
                        section_types[section]["missing"] += 1
                        for field in FIELDS[section]:
                            field_counts[(section, field)]["missing"] += 1
                        continue
                    section_present[section] += 1
                    value = data[present_aliases[0]]
                    section_types[section][py_type(value)] += 1
                    if not isinstance(value, dict):
                        for field in FIELDS[section]:
                            field_counts[(section, field)]["missing"] += 1
                        continue
                    for field in FIELDS[section]:
                        counts = field_counts[(section, field)]
                        if field not in value:
                            counts["missing"] += 1
                            continue
                        cell = value[field]
                        counts["present"] += 1
                        counts[f"type_{py_type(cell)}"] += 1
                        counts["empty" if is_empty(cell) else "nonempty"] += 1
                        if isinstance(cell, list):
                            size = len(cell)
                            counts[
                                "array_length_0"
                                if size == 0
                                else "array_length_1_lt10"
                                if size < 10
                                else "array_length_10plus"
                            ] += 1
                    if section == "images":
                        image_id = value.get("PHOTO_FILE_ID")
                        if isinstance(image_id, str) and image_id != "" and not image_id.isspace():
                            json_photo_id_present += 1
                            if image_id in photo_ids:
                                json_photo_id_matches += 1
                            else:
                                json_photo_id_unmatched += 1
        except (OSError, MemoryError):
            print("status: blocked_json_scan", file=sys.stderr)
            return 2
    finally:
        con.close()

    rows: list[dict[str, str]] = []
    for section in SECTIONS:
        add_metric(
            rows, "section", section, "(section)", "parsed_document_cohort", parsed_document_cohort
        )
        add_metric(rows, "section", section, "(section)", "present", section_present[section])
        add_metric(
            rows,
            "section",
            section,
            "(section)",
            "missing",
            section_types[section]["missing"],
        )
        for type_name in TYPE_NAMES:
            add_metric(
                rows,
                "section",
                section,
                "(section)",
                f"type_{type_name}",
                section_types[section][type_name],
            )
    for (section, field), counts in field_counts.items():
        add_metric(rows, "field", section, field, "parsed_document_cohort", parsed_document_cohort)
        add_metric(rows, "field", section, field, "present", counts["present"])
        add_metric(rows, "field", section, field, "missing", counts["missing"])
        for metric in (f"type_{name}" for name in TYPE_NAMES):
            add_metric(rows, "field", section, field, metric, counts[metric])
        for metric in (
            "empty",
            "nonempty",
            *(f"array_length_{name}" for name in ARRAY_LENGTH_BUCKETS),
        ):
            add_metric(rows, "field", section, field, metric, counts[metric])
    add_metric(rows, "run", "json", "(files)", "document_cohort", document_cohort)
    add_metric(rows, "run", "json", "(files)", "parsed_document_cohort", parsed_document_cohort)
    add_metric(rows, "run", "json", "(files)", "root_object_cohort", root_object_cohort)
    for type_name in TYPE_NAMES:
        add_metric(rows, "run", "json", "(files)", f"root_type_{type_name}", root_types[type_name])
    add_metric(rows, "run", "json", "(files)", "parse_errors", parse_errors)
    add_metric(
        rows, "link", "images", "PHOTO_FILE_ID", "parsed_document_cohort", parsed_document_cohort
    )
    add_metric(rows, "link", "images", "PHOTO_FILE_ID", "json_id_present", json_photo_id_present)
    add_metric(rows, "link", "images", "PHOTO_FILE_ID", "matched_rows", json_photo_id_matches)
    add_metric(rows, "link", "images", "PHOTO_FILE_ID", "unmatched_rows", json_photo_id_unmatched)
    rows.append(
        {
            "record_type": "link",
            "section": "images",
            "field": "VISIT_AREA_ID",
            "metric": "documented_json_identifier",
            "bucket": "not_documented",
            "status": "no_visit_id_join_attempted",
        }
    )
    if not save(output, rows):
        print("status: artifact_write_failed", file=sys.stderr)
        return 2
    print("status: completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
