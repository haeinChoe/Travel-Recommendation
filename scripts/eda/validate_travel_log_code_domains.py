"""Compare documented travel-log domains with regional CSVs; emit buckets only."""

from __future__ import annotations

import argparse
import csv
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results/eda/travel-log-2023"
SUFFIX = {"west": "G", "east": "F", "jeju-islands": "H"}
K = 10

# Field -> documented code group and inclusive ranges in the four regional manuals.
MAPPING = {
    "TN_TRAVELLER_MASTER": {
        **{f"TRAVEL_STYL_{i}": ("TSY", ((1, 7),)) for i in range(1, 9)},
        **{f"TRAVEL_MOTIVE_{i}": ("TMT", ((1, 10),)) for i in range(1, 4)},
        **dict(zip(("EDU_NM EDU_FNSH_SE MARR_STTS JOB_NM JOB_ETC INCOME HOUSE_INCOME TRAVEL_TERM").split(),
                   (("EDU", ((1, 8),)), ("EFS", ((1, 5),)), ("MAR", ((1, 5),)), ("JOB", ((1, 13),)),
                    ("JOE", ((1, 3),)), ("INC", ((1, 12),)), ("INC", ((1, 12),)), ("TTM", ((1, 4),))))),
    },
    "TN_TRAVEL": {"TRAVEL_MISSION": ("MIS", ((1, 13), (21, 28))),
                  "TRAVEL_MISSION_CHECK": ("MIS", ((1, 13), (21, 28)))},
    "TN_COMPANION_INFO": dict(zip("REL_CD COMPANION_GENDER COMPANION_AGE_GRP COMPANION_SITUATION".split(),
                                   (("TCR", ((1, 11),)), ("GEN", ((1, 2),)), ("AGE", ((1, 8),)), ("CST", ((1, 3),))))),
    "TN_MOVE_HIS": {"MVMN_CD_1": ("MOV", ((1, 16), (50, 50))),
                    "MVMN_CD_2": ("MOV", ((1, 16), (50, 50)))},
    "TN_MVMN_CONSUME_HIS": {"MVMN_SE": ("MOV", ((1, 16), (50, 50)))},
    "TN_LODGE_CONSUME_HIS": {"LODGING_TYPE_CD": ("HTY", ((1, 12),)),
                             "PAYMENT_MTHD_SE": ("PAY", ((1, 5),))},
    "TN_ACTIVITY_HIS": {"ACTIVITY_TYPE_CD": ("ACT", ((1, 7), (99, 99))),
                        "EXPND_SE": ("EXP", ((1, 5),)), "ADMISSION_SE": ("AMS", ((1, 2),))},
    "TN_VISIT_AREA_INFO": {
        "VISIT_AREA_TYPE_CD": ("VIS", ((1, 13), (21, 24))),
        "VISIT_CHC_REASON_CD": ("REN", ((1, 11),)), "DGSTFN": ("DGS", ((1, 5),)),
        "REVISIT_INTENTION": ("REP", ((1, 5),)), "RCMDTN_INTENTION": ("REC", ((1, 5),)),
    },
}
GROUP_FIELDS = {"TRAVEL_MISSION", "TRAVEL_MISSION_CHECK", "EXPND_SE"}
GROUPS = {group for fields in MAPPING.values() for group, _ in fields.values()}
CODEBOOK_PATTERN = re.compile(r"^tc_codeb(?:_.+)?\.csv$", re.I)


class InputError(ValueError):
    """A safe, non-identifying input validation error."""


def bucket(n: int) -> str:
    return "0" if n == 0 else "<10" if n < K else "10+"


def allowed(ranges: tuple[tuple[int, int], ...]) -> set[str]:
    return {str(n) for low, high in ranges for n in range(low, high + 1)}


def summarize(values, field: str, code_values: set[str], domain_ok: bool) -> dict[str, str]:
    _, ranges = next(
        spec for fields in MAPPING.values() for name, spec in fields.items() if name == field
    )
    permitted = allowed(ranges)
    observed = blank = outside = group_miss = 0
    for value in values:
        if value is None or not value.strip():
            blank += 1
            continue
        observed += 1
        outside += value not in permitted
        if field in GROUP_FIELDS:
            group_miss += value not in code_values
    return summarize_counts(field, (observed, blank, outside, group_miss), domain_ok)


def summarize_counts(field: str, counts, domain_ok: bool) -> dict[str, str]:
    observed, blank, outside, group_miss = counts
    status = "unresolved_candidate" if outside else "valid" if observed >= K else "unresolved_below_k"
    group_status = "not_checked"
    if field in GROUP_FIELDS:
        group_status = ("unresolved_codebook_domain" if not domain_ok else
                        "unresolved_candidate" if group_miss else
                        "valid" if observed >= K else "unresolved_below_k")
    return {"field": field, "observed_bucket": bucket(observed), "blank_bucket": bucket(blank),
            "range_unmatched_bucket": bucket(outside), "range_status": status,
            "group_unmatched_bucket": bucket(group_miss) if field in GROUP_FIELDS else "not_checked",
            "group_status": group_status}


def read_rows(path: Path, columns: set[str]):
    """Yield only requested string columns; reject ambiguous/missing headers safely."""
    try:
        with path.open("rb") as binary:
            prefix = binary.read(4)
        encoding = "utf-16" if prefix.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
        with path.open("r", encoding=encoding, newline="") as stream:
            reader = csv.reader(stream)
            names = next(reader, [])
            normalized = [name.strip().upper() for name in names]
            if len(normalized) != len(set(normalized)) or not columns <= set(normalized):
                raise InputError("input_header_invalid")
            positions = {name: normalized.index(name) for name in columns}
            for row in reader:
                yield {name: row[index] if index < len(row) else None
                       for name, index in positions.items()}
    except (OSError, UnicodeError, csv.Error) as exc:
        raise InputError("input_read_failed") from exc


def no_symlink(path: Path) -> bool:
    path = path.absolute()
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        if current.is_symlink():
            return False
    return True


def one_csv(root: Path, pattern: re.Pattern, label: str) -> Path:
    found = []
    for base, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = [name for name in dirs if not (Path(base) / name).is_symlink()]
        found.extend(Path(base) / name for name in files if pattern.fullmatch(name))
    if len(found) != 1 or not no_symlink(found[0]):
        raise InputError(f"{label}_mapping_unavailable")
    return found[0]


def table_path(root: Path, table: str, region: str) -> Path:
    name = re.escape(table[3:].lower())
    return one_csv(root, re.compile(rf"tn_{name}_.+_{SUFFIX[region]}\.csv", re.I), "input_table")


def codebook_file(path: Path, region: str) -> Path:
    if not no_symlink(path):
        raise InputError("codebook_path_invalid")
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise InputError("codebook_path_invalid") from exc
    roots = [Path(*resolved.parts[:i + 1]) for i, part in enumerate(resolved.parts)
             if part == f"2023-travel-log-{region}"]
    if len(roots) != 1:
        raise InputError("codebook_region_invalid")
    if resolved.is_dir():
        if resolved.name.upper() != "TL_CSV":
            raise InputError("codebook_role_invalid")
        role_root = resolved
        candidates = []
        for base, dirs, files in os.walk(resolved, followlinks=False):
            dirs[:] = [name for name in dirs if not (Path(base) / name).is_symlink()]
            candidates.extend(Path(base) / name for name in files if CODEBOOK_PATTERN.fullmatch(name))
    else:
        if (not CODEBOOK_PATTERN.fullmatch(resolved.name)
                or resolved.parent.name.upper() != "TL_CSV"):
            raise InputError("codebook_role_invalid")
        role_root = resolved.parent
        candidates = [resolved]
    if len(candidates) != 1 or not no_symlink(candidates[0]):
        raise InputError("codebook_table_mapping_unavailable")
    return candidates[0]


def codebook(file: Path) -> dict[str, set[str]]:
    groups = {group: set() for group in GROUPS}
    for row in read_rows(file, {"CD_A", "CD_B"}):
        group, value = row["CD_A"], row["CD_B"]
        if group in groups and value is not None and value.strip():
            groups[group].add(value)
    return groups


def parse_inputs(args):
    inputs, books = {}, {}
    for item in args.input:
        left, sep, path = item.partition("=")
        region, colon, role = left.partition(":")
        key = (region, role.upper())
        if not sep or not colon or region not in SUFFIX or key[1] not in {"TL", "VL"} or key in inputs:
            raise InputError("input_argument_invalid")
        inputs[key] = Path(path).expanduser()
    for item in args.codebook:
        region, sep, path = item.partition("=")
        if not sep or region not in SUFFIX or region in books:
            raise InputError("codebook_argument_invalid")
        books[region] = Path(path).expanduser()
    expected = {(region, role) for region in SUFFIX for role in ("TL", "VL")}
    if inputs.keys() != expected or books.keys() != SUFFIX.keys():
        raise InputError("required_inputs_missing")
    for (region, role), path in inputs.items():
        if not no_symlink(path):
            raise InputError("input_path_invalid")
        try:
            resolved = path.resolve(strict=True)
        except OSError as exc:
            raise InputError("input_region_path_invalid") from exc
        if (f"2023-travel-log-{region}" not in resolved.parts or not resolved.is_dir()
                or resolved.name.upper() != f"{role}_CSV"):
            raise InputError("input_role_directory_invalid")
    for region, path in books.items():
        if not no_symlink(path):
            raise InputError("codebook_path_invalid")
        try:
            resolved = path.resolve(strict=True)
        except OSError as exc:
            raise InputError("codebook_region_path_invalid") from exc
        if f"2023-travel-log-{region}" not in resolved.parts:
            raise InputError("codebook_region_path_invalid")
    return inputs, books


def run(inputs, books, output: Path) -> None:
    output = prepare_output(output)
    codebook_paths = {region: codebook_file(path, region) for region, path in books.items()}
    group_values = {region: codebook(path) for region, path in codebook_paths.items()}
    domain_rows, field_rows = [], []
    for region in books:
        groups = group_values[region]
        domain_ok = {}
        for group in sorted(GROUPS):
            expected = set().union(*(allowed(spec[1]) for fields in MAPPING.values()
                                     for spec in fields.values() if spec[0] == group))
            actual = groups[group]
            missing, extra = expected - actual, actual - expected
            valid = bool(actual) and not missing and not extra
            domain_ok[group] = valid
            domain_rows.append({"region": region, "group": group, "expected_bucket": bucket(len(expected)),
                                "codebook_bucket": bucket(len(actual)), "missing_bucket": bucket(len(missing)),
                                "extra_bucket": bucket(len(extra)), "status": "valid" if valid else "unresolved"})
        for (which_region, role), root in inputs.items():
            if which_region != region:
                continue
            for table, fields in MAPPING.items():
                path = table_path(root, table, region)
                wanted = set(fields)
                stats = {field: {"observed": 0, "blank": 0, "outside": 0, "group_miss": 0} for field in wanted}
                for row in read_rows(path, wanted):
                    for field, (group, ranges) in fields.items():
                        value, count = row[field], stats[field]
                        if value is None or not value.strip():
                            count["blank"] += 1
                        else:
                            count["observed"] += 1
                            count["outside"] += value not in allowed(ranges)
                            if field in GROUP_FIELDS:
                                count["group_miss"] += value not in groups[group]
                for field, (group, _) in fields.items():
                    count = stats[field]
                    summary = summarize_counts(
                        field,
                        (count["observed"], count["blank"], count["outside"], count["group_miss"]),
                        domain_ok[group],
                    )
                    field_rows.append({"region": region, "split": role, "table": table, **summary})

    specs = (("codebook_domains.csv", domain_rows), ("field_observations.csv", field_rows))
    with tempfile.TemporaryDirectory(dir=output.parent, prefix=".code-domain-") as temp:
        tempdir = Path(temp)
        for filename, rows in specs:
            with (tempdir / filename).open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
                writer.writeheader()
                writer.writerows(rows)
        os.replace(tempdir, output)


def prepare_output(output: Path) -> Path:
    output = output.expanduser()
    if not no_symlink(output):
        raise InputError("output_path_invalid")
    try:
        resolved = output.resolve(strict=False)
        base = RESULTS.resolve(strict=True)
        resolved.relative_to(base)
        resolved.parent.resolve(strict=True).relative_to(base)
    except (OSError, ValueError) as exc:
        raise InputError("output_path_invalid") from exc
    if resolved.exists() or not resolved.parent.is_dir():
        raise InputError("output_must_be_new")
    if subprocess.run(["git", "check-ignore", "-q", "--no-index", str(resolved)],
                      cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
        raise InputError("output_not_ignored")
    return resolved


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", action="append", required=True, metavar="REGION:TL|VL=DIR")
    parser.add_argument("--codebook", action="append", required=True, metavar="REGION=TC_CODEB_CSV_OR_TL_DIR")
    parser.add_argument("--output", required=True, metavar="NEW_IGNORED_DIR")
    parser.add_argument("--confirm-approved", action="store_true")
    parser.add_argument("--confirm-terms", action="store_true")
    args = parser.parse_args(argv)
    try:
        if not args.confirm_approved or not args.confirm_terms:
            raise InputError("confirmation_required")
        output = prepare_output(Path(args.output))
        inputs, books = parse_inputs(args)
        run(inputs, books, output)
    except InputError as exc:
        print(f"validation_status: {exc}", file=sys.stderr)
        return 2
    except OSError:
        print("validation_status: blocked_io_error", file=sys.stderr)
        return 2
    print("validation_status: completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
