"""Classify capital code-domain anomalies against documented code references.

Raw values and reference labels stay in memory. The ignored artifact contains
only official role/field labels, cause classes, and k-suppressed buckets.
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
from validate_capital_codebook import CODEBOOK, has_symlink_component, ql

REPO_ROOT = Path(__file__).resolve().parents[2]
RESULTS_ROOT = REPO_ROOT / "results" / "eda" / "travel-log-2023"
K = 10
TARGETS = {
    ("TN_TRAVEL", "TRAVEL_MISSION"): ("MIS", CODEBOOK["TN_TRAVEL"]["TRAVEL_MISSION"]),
    ("TN_TRAVEL", "TRAVEL_MISSION_CHECK"): (
        "MIS",
        CODEBOOK["TN_TRAVEL"]["TRAVEL_MISSION_CHECK"],
    ),
    ("TN_ACTIVITY_HIS", "EXPND_SE"): ("EXP", CODEBOOK["TN_ACTIVITY_HIS"]["EXPND_SE"]),
}
REF_FIELDS = {
    "TC_CODEA": ("cd_a", "cd_nm", "cd_memo", "cd_memo2"),
    "TC_CODEB": ("cd_a", "cd_b", "cd_nm", "cd_memo", "cd_memo2"),
}
REF_TEXT_MARKERS = ("기타", "무응답", "미상", "모름", "없음", "해당없음", "해당 없음")


def qi(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def read_header(path: Path) -> tuple[list[str], str] | None:
    try:
        with path.open("rb") as stream:
            prefix = stream.read(4)
        encoding = (
            "utf-16" if prefix.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)) else "utf-8"
        )
        with path.open("r", encoding=encoding, newline="") as stream:
            header = next(csv.reader(stream), None)
    except (OSError, UnicodeError, csv.Error):
        return None
    if not header or len(header) != len(set(header)):
        return None
    return header, encoding


def find_table(root: Path, role: str, region_suffix: bool) -> Path | None:
    tail = r"_.+_E\.csv$" if region_suffix else r"_.+\.csv$"
    pattern = re.compile(rf"^{re.escape(role)}{tail}", re.IGNORECASE)
    matches: list[Path] = []
    for current, directories, filenames in os.walk(root, followlinks=False):
        base = Path(current)
        directories[:] = [name for name in directories if not (base / name).is_symlink()]
        for filename in filenames:
            path = base / filename
            if path.is_symlink():
                continue
            if pattern.fullmatch(filename):
                matches.append(path)
    return matches[0] if len(matches) == 1 else None


class ScanFailure(Exception):
    pass


def projected_rows(
    connection: duckdb.DuckDBPyConnection, path: Path, fields: tuple[str, ...]
) -> Iterator[tuple[str | None, ...]] | None:
    parsed = read_header(path)
    if parsed is None:
        return None
    header, encoding = parsed
    if not set(fields).issubset(header):
        return None
    columns = "{" + ", ".join(f"{ql(name)}: 'VARCHAR'" for name in header) + "}"
    source = (
        f"read_csv({ql(str(path))}, header=true, auto_detect=false, "
        f"columns={columns}, encoding={ql(encoding)})"
    )
    select = ", ".join(qi(field) for field in fields)
    try:
        cursor = connection.execute(f"SELECT {select} FROM {source}")
    except (duckdb.Error, OSError):
        return None

    def batches():
        try:
            while batch := cursor.fetchmany(4096):
                yield from batch
        except (duckdb.Error, OSError) as exc:
            raise ScanFailure from exc

    return batches()


def bucket(value: int) -> str:
    if value == 0:
        return "0"
    return "<10" if value < K else "10+"


def classify(
    value: str,
    code_group: str,
    allowed: frozenset[str],
    refs: dict[str, set[str]],
    labels: dict[str, str],
) -> str:
    if re.search(r"[,;|/]", value):
        parts = re.split(r"[,;|/]", value)
        if any(part == "" for part in parts):
            return "delimited_representation_with_empty_component"
        if any(any(character.isspace() for character in part) for part in parts):
            return "delimited_representation_with_whitespace"
        if all(part in allowed for part in parts):
            if all(f"{code_group}\x1f{part}" in refs for part in parts):
                return "multiple_exact_hwp_and_reference_codes_delimited"
            return "multiple_exact_hwp_domain_codes_delimited"
        if all(f"{code_group}\x1f{part}" in refs for part in parts):
            return "multiple_exact_reference_codes_delimited"
        return "delimited_components_not_fully_mapped"
    if any(character.isspace() for character in value):
        return "whitespace_or_format_representation"
    if value in allowed:
        return "in_domain"
    ref_key = f"{code_group}\x1f{value}"
    if ref_key in refs:
        label = labels.get(ref_key, "")
        if any(marker in label for marker in REF_TEXT_MARKERS):
            return "reference_table_special_category"
        return "reference_table_entry_outside_manual_range"
    if value in refs.get("*\x1f*", set()):
        return "reference_entry_for_other_code_group"
    if value.isascii() and value.isdigit():
        return "undocumented_numeric_code"
    return "undocumented_non_numeric_representation"


def prepare_paths(raw_arg: str, input_arg: str, output_arg: str, overwrite: bool):
    raw_path = Path(raw_arg).expanduser()
    input_path = Path(input_arg).expanduser()
    output_path = Path(output_arg).expanduser()
    if any(has_symlink_component(item) for item in (raw_path, input_path, output_path)):
        return None
    try:
        raw_root = raw_path.resolve(strict=True)
        input_root = input_path.resolve(strict=True)
        output = output_path.resolve(strict=False)
        input_root.relative_to(raw_root)
        output.relative_to(RESULTS_ROOT.resolve(strict=True))
    except (OSError, ValueError):
        return None
    if (
        not raw_root.is_dir()
        or not input_root.is_dir()
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
    return raw_root, input_root, output


def save(path: Path, rows: list[dict[str, str]]) -> bool:
    columns = ["table_role", "field", "cause_class", "cohort_bucket", "anomaly_bucket", "status"]
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", newline="", dir=path.parent, prefix=".codebook-", delete=False
        ) as stream:
            temporary = stream.name
            writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
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
        description="Classify capital code anomalies without emitting values."
    )
    parser.add_argument("--raw-root", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    paths = prepare_paths(args.raw_root, args.input, args.output, args.overwrite)
    if paths is None:
        print("status: blocked_path_or_output", file=sys.stderr)
        return 2
    _, input_root, output = paths
    con = duckdb.connect(database=":memory:")
    try:
        refs: dict[str, set[str]] = {"*\x1f*": set()}
        labels: dict[str, str] = {}
        for role in ("TC_CODEA", "TC_CODEB"):
            path = find_table(input_root, role, region_suffix=False)
            if path is None:
                print("status: blocked_reference_mapping", file=sys.stderr)
                return 2
            fields = REF_FIELDS[role]
            rows = projected_rows(con, path, fields)
            if rows is None:
                print("status: blocked_reference_scan", file=sys.stderr)
                return 2
            try:
                for reference_row in rows:
                    record = dict(zip(fields, reference_row, strict=True))
                    cd_a = record.get("cd_a")
                    cd_b = record.get("cd_b")
                    if cd_a is not None:
                        refs["*\x1f*"].add(cd_a)
                    if cd_b is not None:
                        refs["*\x1f*"].add(cd_b)
                        key = f"{cd_a}\x1f{cd_b}"
                        refs[key] = {cd_b}
                        text = " ".join(
                            part
                            for part in (
                                record.get("cd_nm"),
                                record.get("cd_memo"),
                                record.get("cd_memo2"),
                            )
                            if part
                        )
                        labels[key] = text
            except ScanFailure:
                print("status: blocked_reference_scan", file=sys.stderr)
                return 2
        results: list[dict[str, str]] = []
        for (role, field), (group, allowed) in TARGETS.items():
            path = find_table(input_root, role, region_suffix=True)
            if path is None:
                print("status: blocked_source_mapping", file=sys.stderr)
                return 2
            rows = projected_rows(con, path, (field,))
            if rows is None:
                print("status: blocked_source_scan", file=sys.stderr)
                return 2
            classified: dict[str, int] = {}
            cohort = 0
            try:
                for (value,) in rows:
                    if value is None or value == "" or value.isspace():
                        continue
                    cohort += 1
                    cause = classify(value, group, allowed, refs, labels)
                    if cause != "in_domain":
                        classified[cause] = classified.get(cause, 0) + 1
            except ScanFailure:
                print("status: blocked_source_scan", file=sys.stderr)
                return 2
            if not classified:
                classified["no_out_of_domain_rows"] = 0
            for cause, count in sorted(classified.items()):
                status = (
                    "interpretation_required"
                    if cause not in ("no_out_of_domain_rows",)
                    else "no_reportable_anomaly"
                )
                results.append(
                    {
                        "table_role": role,
                        "field": field,
                        "cause_class": cause,
                        "cohort_bucket": "<10" if cohort < K else "10+",
                        "anomaly_bucket": bucket(count),
                        "status": status,
                    }
                )
    finally:
        con.close()
    if not save(output, results):
        print("status: artifact_write_failed", file=sys.stderr)
        return 2
    print("status: completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
