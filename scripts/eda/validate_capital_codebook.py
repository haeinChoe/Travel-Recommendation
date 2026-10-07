"""Validate documented capital CSV code domains with a privacy-safe summary.

Only the explicitly mapped columns below are projected from matching CSV tables.
The input is read-only; output contains bucketed aggregates only and must remain
under the repository's ignored results directory.
"""

from __future__ import annotations

import argparse
import codecs
import csv
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path

import duckdb

REPO_ROOT = Path(__file__).resolve().parents[2]
RESULTS_ROOT = REPO_ROOT / "results" / "eda" / "travel-log-2023"
K = 10


def numeric_range(first: int, last: int) -> frozenset[str]:
    return frozenset(str(value) for value in range(first, last + 1))


def union_ranges(*ranges: tuple[int, int], extras: tuple[int, ...] = ()) -> frozenset[str]:
    values = {str(value) for value in extras}
    for first, last in ranges:
        values.update(str(value) for value in range(first, last + 1))
    return frozenset(values)


# Transcribed from the user-provided AI Hub 71776 capital data manual.
# Both mission fields intentionally share the same union domain.
CODEBOOK: dict[str, dict[str, frozenset[str]]] = {
    "TN_TRAVELLER_MASTER": {
        "EDU_NM": numeric_range(1, 8),
        "EDU_FNSH_SE": numeric_range(1, 5),
        "MARR_STTS": numeric_range(1, 5),
        "JOB_NM": numeric_range(1, 13),
        "JOB_ETC": numeric_range(1, 3),
        "INCOME": numeric_range(1, 12),
        "HOUSE_INCOME": numeric_range(1, 12),
        "TRAVEL_TERM": numeric_range(1, 4),
        **{f"TRAVEL_STYL_{index}": numeric_range(1, 7) for index in range(1, 9)},
        **{f"TRAVEL_MOTIVE_{index}": numeric_range(1, 10) for index in range(1, 4)},
    },
    "TN_TRAVEL": {
        "TRAVEL_MISSION": union_ranges((1, 13), (21, 28)),
        "TRAVEL_MISSION_CHECK": union_ranges((1, 13), (21, 28)),
    },
    "TN_COMPANION_INFO": {
        "REL_CD": numeric_range(1, 11),
        "COMPANION_GENDER": numeric_range(1, 2),
        "COMPANION_AGE_GRP": numeric_range(1, 8),
        "COMPANION_SITUATION": numeric_range(1, 3),
    },
    "TN_MOVE_HIS": {
        "MVMN_CD_1": union_ranges((1, 16), extras=(50,)),
        "MVMN_CD_2": union_ranges((1, 16), extras=(50,)),
    },
    "TN_MVMN_CONSUME_HIS": {"MVMN_SE": union_ranges((1, 16), extras=(50,))},
    "TN_LODGE_CONSUME_HIS": {
        "LODGING_TYPE_CD": numeric_range(1, 12),
        "PAYMENT_MTHD_SE": numeric_range(1, 5),
    },
    "TN_ACTIVITY_HIS": {
        "ACTIVITY_TYPE_CD": union_ranges((1, 7), extras=(99,)),
        "EXPND_SE": numeric_range(1, 5),
        "ADMISSION_SE": numeric_range(1, 2),
    },
    "TN_VISIT_AREA_INFO": {
        "VISIT_AREA_TYPE_CD": union_ranges((1, 13), (21, 24)),
        "VISIT_CHC_REASON_CD": numeric_range(1, 11),
        "DGSTFN": numeric_range(1, 5),
        "REVISIT_INTENTION": numeric_range(1, 5),
        "RCMDTN_INTENTION": numeric_range(1, 5),
    },
}


def ql(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def qident(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def has_symlink_component(path: Path) -> bool:
    if path.is_absolute():
        current = Path(path.anchor)
        parts = path.parts[1:]
    else:
        current = Path.cwd()
        parts = path.parts
    for part in parts:
        if part in ("", "."):
            continue
        if part == "..":
            current = current.parent
            continue
        current /= part
        if current.is_symlink():
            return True
    return False


def read_header(path: Path) -> tuple[list[str], str] | None:
    try:
        with path.open("rb") as stream:
            prefix = stream.read(4)
        if prefix.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
            encoding = "utf-16"
        else:
            encoding = "utf-8"
        with path.open("r", encoding=encoding, newline="") as stream:
            header = next(csv.reader(stream), None)
    except (OSError, UnicodeError, csv.Error):
        return None
    if not header or len(header) != len(set(header)):
        return None
    return header, encoding


def bucket(value: int) -> str:
    if value == 0:
        return "0"
    return "<10" if value < K else "10+"


def csv_files(input_root: Path) -> Iterator[Path]:
    for current, directories, filenames in os.walk(input_root, followlinks=False):
        base = Path(current)
        directories[:] = [name for name in directories if not (base / name).is_symlink()]
        for filename in filenames:
            candidate = base / filename
            if candidate.suffix.lower() == ".csv" and not candidate.is_symlink():
                yield candidate


def table_paths(input_root: Path) -> dict[str, list[Path]]:
    patterns = {
        role: re.compile(rf"^{re.escape(role)}_.+_E\.csv$", re.IGNORECASE) for role in CODEBOOK
    }
    matches = {role: [] for role in CODEBOOK}
    for path in csv_files(input_root):
        for role, pattern in patterns.items():
            if pattern.fullmatch(path.name):
                matches[role].append(path)
    return matches


def prepare_paths(
    raw_root_arg: str, input_arg: str, output_arg: str, overwrite: bool
) -> tuple[Path, Path] | None:
    raw_root_path = Path(raw_root_arg).expanduser()
    input_path = Path(input_arg).expanduser()
    output_path = Path(output_arg).expanduser()
    if (
        has_symlink_component(raw_root_path)
        or has_symlink_component(input_path)
        or has_symlink_component(output_path)
    ):
        return None
    try:
        raw_root = raw_root_path.resolve(strict=True)
        input_root = input_path.resolve(strict=True)
        output_resolved = output_path.resolve(strict=False)
        input_root.relative_to(raw_root)
        output_resolved.relative_to(RESULTS_ROOT.resolve(strict=True))
    except (OSError, ValueError):
        return None
    if not raw_root.is_dir() or not input_root.is_dir() or output_resolved.suffix.lower() != ".csv":
        return None
    if not output_resolved.parent.is_dir() or not output_resolved.parent.resolve().is_relative_to(
        RESULTS_ROOT.resolve()
    ):
        return None
    check = subprocess.run(
        ["git", "check-ignore", "-q", "--no-index", str(output_resolved)],
        cwd=REPO_ROOT,
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if check.returncode != 0 or (output_resolved.exists() and not overwrite):
        return None
    return input_root, output_resolved


def scan_table(
    connection: duckdb.DuckDBPyConnection,
    path: Path,
    role: str,
    header: list[str],
    encoding: str,
) -> list[dict[str, str]] | None:
    fields = CODEBOOK[role]
    if not set(fields).issubset(header):
        return None

    # Declaring all columns as VARCHAR avoids semantic/type inference. The query
    # projects only the documented allowlist; DuckDB's CSV reader applies column
    # projection while scanning.
    columns = "{" + ", ".join(f"{ql(name)}: 'VARCHAR'" for name in header) + "}"
    source = (
        f"read_csv({ql(str(path))}, header=true, auto_detect=false, "
        f"columns={columns}, encoding={ql(encoding)})"
    )
    expressions: list[str] = []
    field_names = list(fields)
    for index, field in enumerate(field_names):
        col = qident(field)
        is_missing = f"({col} IS NULL OR regexp_full_match({col}, '[[:space:]]*'))"
        nonblank = f"NOT {is_missing}"
        allowed = ", ".join(ql(value) for value in sorted(fields[field]))
        expressions.extend(
            [
                f"count(*) FILTER (WHERE {nonblank}) AS cohort_{index}",
                f"count(*) FILTER (WHERE {is_missing}) AS missing_{index}",
                f"count(*) FILTER (WHERE {nonblank} AND {col} NOT IN ({allowed})) "
                f"AS mismatch_{index}",
            ]
        )
    try:
        result = connection.execute(f"SELECT {', '.join(expressions)} FROM {source}").fetchone()
    except (duckdb.Error, OSError):
        return None
    if result is None:
        return None

    rows: list[dict[str, str]] = []
    for index, field in enumerate(field_names):
        cohort, missing, mismatch = result[index * 3 : index * 3 + 3]
        if cohort < K:
            mismatch_bucket = "<10"
            status = "suppressed_cohort_below_k"
        elif mismatch == 0:
            mismatch_bucket = "0"
            status = "no_reportable_mismatch"
        elif mismatch < K:
            mismatch_bucket = "<10"
            status = "no_reportable_mismatch"
        else:
            mismatch_bucket = "10+"
            status = "anomaly_requires_interpretation"
        rows.append(
            {
                "table_role": role,
                "field": field,
                "cohort_bucket": "<10" if cohort < K else "10+",
                "missing_bucket": bucket(missing),
                "mismatch_bucket": mismatch_bucket,
                "status": status,
            }
        )
    return rows


def write_artifact(path: Path, rows: list[dict[str, str]]) -> bool:
    columns = [
        "table_role",
        "field",
        "cohort_bucket",
        "missing_bucket",
        "mismatch_bucket",
        "status",
    ]
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", newline="", dir=path.parent, prefix=".codebook-", delete=False
        ) as stream:
            temp_name = stream.name
            writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
        return True
    except OSError:
        if temp_name:
            try:
                Path(temp_name).unlink(missing_ok=True)
            except OSError:
                pass
        return False


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate documented capital CSV code domains safely."
    )
    parser.add_argument("--raw-root", required=True, help="Designated local raw-data root")
    parser.add_argument("--input", required=True, help="Local extracted capital input directory")
    parser.add_argument("--output", required=True, help="Ignored results CSV destination")
    parser.add_argument(
        "--overwrite", action="store_true", help="Replace the exact requested artifact"
    )
    args = parser.parse_args()

    paths = prepare_paths(args.raw_root, args.input, args.output, args.overwrite)
    if paths is None:
        print("validation_status: blocked_path_or_output", file=sys.stderr)
        return 2
    input_root, output_path = paths
    collected: list[dict[str, str]] = []
    connection = duckdb.connect(database=":memory:")
    try:
        matches = table_paths(input_root)
        for role in CODEBOOK:
            role_paths = matches[role]
            if len(role_paths) != 1 or has_symlink_component(role_paths[0]):
                print("validation_status: blocked_table_mapping", file=sys.stderr)
                return 2
            path = role_paths[0]
            parsed = read_header(path)
            if parsed is None:
                print("validation_status: blocked_header_mapping", file=sys.stderr)
                return 2
            header, encoding = parsed
            table_rows = scan_table(connection, path, role, header, encoding)
            if table_rows is None:
                print("validation_status: blocked_column_scan", file=sys.stderr)
                return 2
            collected.extend(table_rows)
    finally:
        connection.close()

    if not write_artifact(output_path, collected):
        print("validation_status: artifact_write_failed", file=sys.stderr)
        return 2
    print("validation_status: completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
