"""Diagnose capital SbL photo-ID mismatches without emitting identifier values."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

from inspect_capital_json import collect_json_files, prepare_paths
from extract_capital_sbl_json import (
    MAX_ARCHIVE_MEMBERS,
    ExtractionBlocked,
    preflight_zip_directory,
    safe_member_path,
)
from interpret_capital_codebook import read_header
from validate_capital_codebook import has_symlink_component, prepare_paths as prepare_provenance_paths

K = 10
PHOTO_TABLE_PATTERN = re.compile(r"^TN_TOUR_PHOTO_.+_E\.csv$", re.IGNORECASE)
MAX_ARCHIVE_ROLE_CANDIDATES = 100
MAX_ARCHIVE_ROLE_BYTES = 8 << 30
HASH_CHUNK_BYTES = 1 << 20


def bucket(value: int) -> str:
    if value == 0:
        return "0"
    return "<10" if value < K else "10+"


def table_candidates(root: Path) -> list[Path]:
    matches: list[Path] = []
    for current, directories, filenames in os.walk(root, followlinks=False):
        base = Path(current)
        directories[:] = [name for name in directories if not (base / name).is_symlink()]
        for filename in filenames:
            path = base / filename
            if not path.is_symlink() and PHOTO_TABLE_PATTERN.fullmatch(filename):
                matches.append(path)
    return matches


def csv_headers(root: Path, selected_table: Path) -> tuple[bool, bool]:
    """Return whether another CSV header declares PHOTO_FILE_ID and scan status."""
    found = False
    try:
        for current, directories, filenames in os.walk(root, followlinks=False):
            base = Path(current)
            directories[:] = [name for name in directories if not (base / name).is_symlink()]
            for filename in filenames:
                path = base / filename
                if path.suffix.casefold() != ".csv" or path.is_symlink():
                    continue
                if path == selected_table:
                    continue
                parsed = read_header(path)
                if parsed is None:
                    return found, False
                found = found or "PHOTO_FILE_ID" in parsed[0]
    except OSError:
        return found, False
    return found, True


def scan_table(path: Path) -> tuple[Counter[str], int, int, int, int, int, int]:
    parsed = read_header(path)
    if parsed is None:
        raise ValueError
    header, encoding = parsed
    try:
        key_index = header.index("PHOTO_FILE_ID")
    except ValueError as exc:
        raise ValueError from exc

    row_count = short_rows = empty_rows = whitespace_rows = 0
    keys: Counter[str] = Counter()
    with path.open("r", encoding=encoding, newline="") as stream:
        reader = csv.reader(stream)
        next(reader, None)
        for row in reader:
            row_count += 1
            if key_index >= len(row):
                short_rows += 1
                continue
            value = row[key_index]
            if value == "":
                empty_rows += 1
            elif value.isspace():
                whitespace_rows += 1
            else:
                keys[value] += 1
    duplicate_groups = sum(count > 1 for count in keys.values())
    duplicate_excess_rows = sum(count - 1 for count in keys.values() if count > 1)
    return keys, row_count, short_rows, empty_rows, whitespace_rows, duplicate_groups, duplicate_excess_rows


def scan_json(files: list[Path]) -> tuple[Counter[str], int, int, int, int, int]:
    occurrences: Counter[str] = Counter()
    missing = empty = whitespace = nonstring = 0
    for path in files:
        with path.open("r", encoding="utf-8-sig") as stream:
            document = json.load(stream)
        if not isinstance(document, dict):
            missing += 1
            continue
        images = document.get("images")
        if not isinstance(images, dict) or "PHOTO_FILE_ID" not in images:
            missing += 1
            continue
        value = images["PHOTO_FILE_ID"]
        if value is None:
            missing += 1
        elif not isinstance(value, str):
            nonstring += 1
        elif value == "":
            empty += 1
        elif value.isspace():
            whitespace += 1
        else:
            occurrences[value] += 1
    return occurrences, missing, empty, whitespace, nonstring, len(occurrences)


def sha256_stream(stream) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    while chunk := stream.read(HASH_CHUNK_BYTES):
        digest.update(chunk)
        size += len(chunk)
    return digest.hexdigest(), size


def has_token(text: str, token: str) -> bool:
    # Treat embedded alphanumeric strings as part of a larger marker. Separators
    # such as underscores, dots, and hyphens remain valid token boundaries.
    boundary = r"[A-Za-z0-9]"
    return re.search(
        rf"(?<!{boundary}){re.escape(token)}(?!{boundary})", text, flags=re.IGNORECASE
    ) is not None


def archive_provenance(
    table_path: Path,
    archive_path: Path,
    raw_root: Path,
    approved_filekey: str,
) -> dict[str, tuple[int | None, str]]:
    """Hash only role/category-marked CSV members in one explicitly selected archive."""
    result: dict[str, tuple[int | None, str]] = {}
    try:
        if any(has_symlink_component(path) for path in (table_path, archive_path, raw_root)):
            raise ValueError
        archive_path = archive_path.resolve(strict=True)
        raw_root = raw_root.resolve(strict=True)
        archive_path.relative_to(raw_root)
        if not archive_path.is_file() or not zipfile.is_zipfile(archive_path):
            raise ValueError
        archive_category_marked = (
            any(part.casefold() == "tl_csv" for part in archive_path.parts)
            or archive_path.stem.casefold() == "tl_csv"
        )

        with table_path.open("rb") as table_stream:
            local_digest, local_size = sha256_stream(table_stream)
        expected_entries, _ = preflight_zip_directory(archive_path)
        candidates: list[zipfile.ZipInfo] = []
        with zipfile.ZipFile(archive_path, "r") as archive:
            infos = archive.infolist()
            if len(infos) != expected_entries or not infos or len(infos) > MAX_ARCHIVE_MEMBERS:
                raise ValueError
            for info in infos:
                member_path = safe_member_path(info.filename)
                mode = (info.external_attr >> 16) & 0xFFFF
                if info.is_dir() or (mode and stat.S_ISLNK(mode)):
                    continue
                if (
                    PHOTO_TABLE_PATTERN.fullmatch(member_path.name)
                    and (
                        archive_category_marked
                        or any(part.casefold() == "tl_csv" for part in member_path.parts[:-1])
                    )
                ):
                    if info.flag_bits & 1 or info.file_size < 0:
                        raise ValueError
                    candidates.append(info)
            total_declared = sum(info.file_size for info in candidates)
            if (
                len(candidates) > MAX_ARCHIVE_ROLE_CANDIDATES
                or total_declared > MAX_ARCHIVE_ROLE_BYTES
            ):
                raise ValueError

            matches = 0
            category_marked_members = 0
            approved_markers = 0
            version_markers = 0
            archive_key_marker = has_token(archive_path.name, approved_filekey)
            archive_version_marker = has_token(archive_path.name, "1.2")
            for info in candidates:
                member_path = safe_member_path(info.filename)
                if archive_category_marked or any(
                    part.casefold() == "tl_csv" for part in member_path.parts[:-1]
                ):
                    category_marked_members += 1
                if archive_key_marker or has_token(info.filename, approved_filekey):
                    approved_markers += 1
                if archive_version_marker or has_token(info.filename, "1.2"):
                    version_markers += 1
                digest = hashlib.sha256()
                actual_size = 0
                with archive.open(info, "r") as stream:
                    while chunk := stream.read(HASH_CHUNK_BYTES):
                        digest.update(chunk)
                        actual_size += len(chunk)
                        if actual_size > info.file_size:
                            raise ValueError
                if actual_size != info.file_size:
                    raise ValueError
                if actual_size == local_size and digest.hexdigest() == local_digest:
                    matches += 1
        result["tl_csv_role_member_candidates"] = (len(candidates), "k10_bucket")
        result["category_marked_role_members"] = (category_marked_members, "k10_bucket")
        result["content_hash_matches"] = (matches, "k10_bucket")
        result["unique_content_hash_match"] = (
            None,
            "yes_unique" if matches == 1 else "no_unique_match",
        )
        result["approved_filekey_metadata_markers"] = (approved_markers, "k10_bucket")
        result["version_1_2_metadata_markers"] = (version_markers, "k10_bucket")
        result["archive_scan"] = (None, "completed")
    except (OSError, ValueError, zipfile.BadZipFile, zipfile.LargeZipFile, ExtractionBlocked):
        result["archive_scan"] = (None, "blocked_or_incomplete")
    return result


def normalized_maps(keys: Counter[str], values: set[str], transform):
    table_rows: dict[str, int] = defaultdict(int)
    table_variants: dict[str, set[str]] = defaultdict(set)
    for raw, count in keys.items():
        norm = transform(raw)
        if norm:
            table_rows[norm] += count
            table_variants[norm].add(raw)
    json_variants: dict[str, set[str]] = defaultdict(set)
    for raw in values:
        norm = transform(raw)
        if norm:
            json_variants[norm].add(raw)
    return table_rows, table_variants, json_variants


def collision_keys(groups: dict[str, set[str]]) -> int:
    return sum(len(variants) > 1 for variants in groups.values())


def new_casefold_collisions(raw_values: set[str]) -> int:
    variants: dict[str, set[str]] = defaultdict(set)
    for raw in raw_values:
        trimmed = raw.strip()
        if trimmed:
            variants[trimmed.casefold()].add(trimmed)
    return collision_keys(variants)


def append(rows: list[dict[str, str]], scope: str, metric: str, value: int | None,
           status: str = "k10_bucket") -> None:
    rows.append({
        "scope": scope,
        "metric": metric,
        "bucket": bucket(value) if value is not None else "not_applicable",
        "status": status,
    })


def save(path: Path, rows: list[dict[str, str]]) -> bool:
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", newline="", dir=path.parent,
            prefix=".photo-id-diagnosis-", delete=False,
        ) as stream:
            temporary = stream.name
            writer = csv.DictWriter(
                stream, fieldnames=("scope", "metric", "bucket", "status"),
                lineterminator="\n",
            )
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


def diagnose(input_root: Path, json_root: Path, raw_root: Path,
             archive_path: Path, approved_filekey: str) -> list[dict[str, str]]:
    files = collect_json_files(json_root)
    candidates = table_candidates(input_root)
    if files is None or len(candidates) != 1:
        raise ValueError
    table_keys, table_rows, short_rows, empty_rows, whitespace_rows, duplicate_groups, duplicate_excess = scan_table(candidates[0])
    occurrences, json_missing, json_empty, json_whitespace, json_nonstring, unique_json_count = scan_json(files)
    json_ids = set(occurrences)
    table_ids = set(table_keys)
    exact_matches = json_ids & table_ids
    exact_unmatched = json_ids - table_ids

    trim_table_rows, trim_table_variants, trim_json_variants = normalized_maps(
        table_keys, json_ids, str.strip
    )
    trim_candidates = {
        value for value in exact_unmatched
        if value.strip() and value.strip() in trim_table_rows
    }
    after_trim = exact_unmatched - trim_candidates

    cf_transform = lambda value: value.strip().casefold()
    cf_table_rows, cf_table_variants, cf_json_variants = normalized_maps(
        table_keys, json_ids, cf_transform
    )
    casefold_candidates = {
        value for value in after_trim
        if cf_transform(value) and cf_transform(value) in cf_table_rows
    }
    remaining = after_trim - casefold_candidates

    trim_candidate_occurrences = sum(occurrences[value] for value in trim_candidates)
    casefold_candidate_occurrences = sum(occurrences[value] for value in casefold_candidates)
    remaining_occurrences = sum(occurrences[value] for value in remaining)
    exact_unmatched_occurrences = sum(occurrences[value] for value in exact_unmatched)

    trim_ambiguous_candidates = sum(
        value.strip() in trim_table_rows
        and trim_table_rows[value.strip()] > 1
        for value in trim_candidates
    )
    casefold_ambiguous_candidates = sum(
        cf_transform(value) in cf_table_rows
        and cf_table_rows[cf_transform(value)] > 1
        for value in casefold_candidates
    )
    trim_candidate_groups: dict[str, set[str]] = defaultdict(set)
    for value in trim_candidates:
        trim_candidate_groups[value.strip()].add(value)
    trim_json_collision_ids = sum(
        len(ids)
        for key, ids in trim_candidate_groups.items()
        if len(trim_json_variants.get(key, ())) > 1
    )
    cf_candidate_groups: dict[str, set[str]] = defaultdict(set)
    for value in casefold_candidates:
        cf_candidate_groups[cf_transform(value)].add(value)
    cf_json_collision_ids = sum(
        len(ids)
        for key, ids in cf_candidate_groups.items()
        if len(cf_json_variants.get(key, ())) > 1
    )
    exact_duplicate_matches = sum(table_keys[value] > 1 for value in exact_matches)

    other_photo_header, headers_complete = csv_headers(input_root, candidates[0])
    rows: list[dict[str, str]] = []
    provenance = archive_provenance(candidates[0], archive_path, raw_root, approved_filekey)
    append(rows, "table", "capital_role_file_coverage", None, "unique_capital_E_suffix_match_complete_scan")
    append(rows, "table", "package_category", None,
           "TL_csv_path_component" if any(part.casefold() == "tl_csv" for part in candidates[0].parts)
           else "category_component_not_verified")
    for metric, (value, status) in provenance.items():
        append(rows, "provenance", metric, value, status)
    append(rows, "table", "table_version", None, "not_independently_encoded_or_verified")
    append(rows, "table", "full_row_scan", None, "complete")
    append(rows, "table", "row_cohort", table_rows)
    append(rows, "table", "short_row_missing_key_column", short_rows)
    append(rows, "table", "empty_key_cell", empty_rows, "CSV_text_empty_cell")
    append(rows, "table", "whitespace_only_key_cell", whitespace_rows)
    append(rows, "table", "nonblank_key_rows", sum(table_keys.values()))
    append(rows, "table", "exact_duplicate_key_groups", duplicate_groups)
    append(rows, "table", "exact_duplicate_excess_rows", duplicate_excess)
    append(rows, "table", "exact_matched_json_unique_ids_with_duplicate_table_key", exact_duplicate_matches)
    append(rows, "json", "document_cohort", len(files))
    append(rows, "json", "id_missing_or_null", json_missing)
    append(rows, "json", "id_empty_cell", json_empty)
    append(rows, "json", "id_whitespace_only", json_whitespace)
    append(rows, "json", "id_nonstring", json_nonstring)
    append(rows, "json", "id_nonblank_occurrences", sum(occurrences.values()))
    append(rows, "json", "id_unique_values", unique_json_count)
    append(rows, "json", "exact_matched_unique_ids", len(exact_matches))
    append(rows, "json", "exact_unmatched_unique_ids", len(exact_unmatched), "initial_unmatched_cohort")
    append(rows, "json", "exact_unmatched_occurrences", exact_unmatched_occurrences, "initial_unmatched_cohort")
    append(rows, "trim_only_candidate", "unique_ids", len(trim_candidates), "candidate_only_not_joined")
    append(rows, "trim_only_candidate", "occurrences", trim_candidate_occurrences, "candidate_only_not_joined")
    append(rows, "casefold_after_trim_candidate", "unique_ids", len(casefold_candidates), "candidate_only_not_joined")
    append(rows, "casefold_after_trim_candidate", "occurrences", casefold_candidate_occurrences, "candidate_only_not_joined")
    append(rows, "unmatched_after_casefold", "unique_ids", len(remaining), "cause_unresolved")
    append(rows, "unmatched_after_casefold", "occurrences", remaining_occurrences, "cause_unresolved")
    append(rows, "exact", "matched_unique_ids_with_duplicate_table_key", exact_duplicate_matches)
    append(rows, "trim", "table_normalization_collision_keys", collision_keys(trim_table_variants))
    append(rows, "trim", "json_normalization_collision_keys", collision_keys(trim_json_variants))
    append(rows, "trim", "candidate_ids_with_multiple_table_rows", trim_ambiguous_candidates)
    append(rows, "trim", "candidate_ids_in_json_normalization_collision", trim_json_collision_ids)
    append(rows, "casefold_after_trim", "new_table_casefold_collision_keys", new_casefold_collisions(set(table_keys)))
    append(rows, "casefold_after_trim", "new_json_casefold_collision_keys", new_casefold_collisions(json_ids))
    append(rows, "casefold_after_trim", "candidate_ids_with_multiple_table_rows", casefold_ambiguous_candidates)
    append(rows, "casefold_after_trim", "candidate_ids_in_json_normalization_collision", cf_json_collision_ids)
    append(rows, "documentation", "filename_path_transform", None, "not_tested_no_documented_mapping_rule")
    append(rows, "documentation", "photo_id_table_scope", None, "HWP_declares_TN_TOUR_PHOTO_and_SbL_images")
    append(rows, "documentation", "other_region_or_collection_scope", None, "not_scanned_outside_approved_capital_inputs")
    append(rows, "documentation", "CSV_null_semantics", None, "no_typed_null_or_sentinel_rule_verified")
    append(rows, "input_inventory", "other_capital_csv_photo_id_header", None,
           "scan_incomplete" if not headers_complete else "present" if other_photo_header else "none_found")
    append(rows, "input_inventory", "version_provenance", None,
           "official_listing_version_does_not_verify_local_table_file_version")
    append(rows, "interpretation", "normalization_join", None, "not_performed_candidates_only")
    return rows


def diagnose_archive_only(input_root: Path, raw_root: Path, archive_path: Path,
                          approved_filekey: str) -> list[dict[str, str]]:
    candidates = table_candidates(input_root)
    if len(candidates) != 1:
        raise ValueError
    rows: list[dict[str, str]] = []
    for metric, (value, status) in archive_provenance(
        candidates[0], archive_path, raw_root, approved_filekey
    ).items():
        append(rows, "provenance", metric, value, status)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnose capital SbL photo-ID linkage without emitting values.")
    parser.add_argument("--raw-root", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--json-root")
    parser.add_argument("--archive", required=True,
                        help="Explicit approved capital TL_csv candidate archive inside raw root")
    parser.add_argument("--approved-filekey", required=True,
                        help="Approved TL_csv filekey used only for an in-memory metadata marker check")
    parser.add_argument("--output", required=True)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--provenance-only", action="store_true",
                        help="Hash the unique capital photo table against role/category members only")
    args = parser.parse_args()
    raw_root = Path(args.raw_root).expanduser()
    archive_path = Path(args.archive).expanduser()
    if has_symlink_component(raw_root) or has_symlink_component(archive_path):
        print("status: blocked_archive_path", file=sys.stderr)
        return 2
    if args.provenance_only:
        paths = prepare_provenance_paths(args.raw_root, args.input, args.output, args.overwrite)
        if paths is None:
            print("status: blocked_path_or_output", file=sys.stderr)
            return 2
        input_root, output = paths
        json_root = None
    else:
        if not args.json_root:
            parser.error("--json-root is required unless --provenance-only is selected")
        paths = prepare_paths(args.raw_root, args.input, args.json_root, args.output, args.overwrite)
        if paths is None:
            print("status: blocked_path_or_output", file=sys.stderr)
            return 2
        input_root, json_root, output = paths
    try:
        rows = (
            diagnose_archive_only(input_root, raw_root, archive_path, args.approved_filekey)
            if args.provenance_only
            else diagnose(input_root, json_root, raw_root, archive_path, args.approved_filekey)
        )
    except (OSError, UnicodeError, csv.Error, json.JSONDecodeError, ValueError, MemoryError):
        print("status: blocked_scan", file=sys.stderr)
        return 2
    if not save(output, rows):
        print("status: artifact_write_failed", file=sys.stderr)
        return 2
    print("status: completed")
    print("counts: k10_buckets_only")
    print("normalization: diagnostic_candidates_only_no_join")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
