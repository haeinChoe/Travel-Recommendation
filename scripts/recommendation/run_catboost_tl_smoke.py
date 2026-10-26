"""Run a bounded, TL-only Issue #82 CatBoost smoke experiment.

Role-bound inputs are supplied through RAW_ROOT and {CAPITAL,WEST,EAST,JEJU}
_{TL,OTHER}. Only each TL's travel/traveler/visit and TC_SGG tables are read;
from each OTHER role, only TN_POI_MASTER is opened and only its static columns
are parsed. Paths, identifiers, and row-level values stay in process memory.

Examples (values must already be bound in the authorized local environment):
  python3 scripts/recommendation/run_catboost_tl_smoke.py --region capital --mode probe
  python3 scripts/recommendation/run_catboost_tl_smoke.py --region capital --mode profile
  python3 scripts/recommendation/run_catboost_tl_smoke.py --region capital --mode full

The probe uses a limited train/evaluation cohort and 20 iterations for hardware
feasibility only. Profile mode uses all inner-train data and the fixed
YetiRank/uniform/1x/1000-iteration configuration but scores only eight
inner-validation queries for throughput projection. Full mode evaluates every
eligible TL inner-validation query and writes the privacy-safe aggregate result.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import resource
import signal
import subprocess
import sys
import threading
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable, Mapping

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.recommendation.canonical_admin_location import (  # noqa: E402
    build_admin_address_lookup,
    build_admin_lookup,
    resolve_master_admin_location_indexed,
)
from scripts.recommendation.catboost_ranking_experiment import (  # noqa: E402
    CandidateInventory,
    ExperimentConfig,
    PreparedItemCatalog,
    SamplingStrategy,
    fit_catboost,
    materialize_inner_train_item_features,
    sample_unobserved,
    score_inner_validation_queries,
)
from scripts.recommendation.training_data_contract import (  # noqa: E402
    build_trip_poi_positives,
)
from scripts.recommendation.training_dataset import (  # noqa: E402
    _context,
    _find_csv_case_insensitive,
    _one,
    _clean_str,
    SOURCE_TO_CANONICAL_COLUMNS,
    STYLE_FEATURES,
    MOTIVE_FEATURES,
)
from scripts.recommendation.evaluate_popularity import (  # noqa: E402
    approved_capital_filekey_root,
)
from scripts.recommendation.poi_catalog_policy import load_poi_catalog_policy  # noqa: E402
from scripts.recommendation.tl_traveler_split import (  # noqa: E402
    deterministic_traveler_group_split,
    valid_unique_trip_owner_rows,
)

REGIONS = ("capital", "west", "east", "jeju-islands")
ENV_PREFIX = {"capital": "CAPITAL", "west": "WEST", "east": "EAST", "jeju-islands": "JEJU"}
MASTER_COLUMNS = (
    "POI_ID", "SGG_CD", "ASORT_LCLASDC", "ASORT_MLSFCDC", "ASORT_SDASDC",
    "ROAD_NM_ADDR", "LOTNO_ADDR",
)
TRAVEL_COLUMNS = ("TRAVEL_ID", "TRAVELER_ID", "TRAVEL_START_YMD", "TRAVEL_END_YMD")
TRAVELER_COLUMNS = (
    "TRAVELER_ID", *STYLE_FEATURES, *MOTIVE_FEATURES,
    "TRAVEL_STATUS_DESTINATION", "TRAVEL_STATUS_ACCOMPANY", "TRAVEL_COMPANIONS_NUM",
)
VISIT_COLUMNS = (
    "TRAVEL_ID", "VISIT_AREA_ID", "POI_ID", "VISIT_AREA_TYPE_CD", "SGG_CD",
)
SGG_COLUMNS = ("SGG_CD", "SGG_CD1", "SGG_CD2", "SIDO_NM", "SGG_NM")
FEATURE_GROUPS = (
    "Q4_TEMPORAL", "I2_ADMINISTRATIVE_LOCATION", "I3_POPULARITY", "I4_HISTORICAL_POI",
)
SPLIT_SEED = 20261025
ITERATIONS = 1000
PROBE_ITERATIONS = 20
PROBE_TRAIN_TRIPS = 32
PROBE_VALIDATION_QUERIES = 8
PREDICTION_BATCH_ROWS = 262_144
VALIDATION_PROGRESS_QUERIES = 10
SOFT_RSS_LIMIT_BYTES = 16 * 1024**3
MIN_AVAILABLE_BYTES = 8 * 1024**3
MASTER_PROGRESS_ROWS = 25_000
TELEMETRY: list[dict[str, object]] = []
RESOLVED_ADMIN_LOCATION_STATUSES = frozenset({
    "resolved_single_source", "resolved_multi_source",
})


class SafeFailure(RuntimeError):
    """An error whose message is safe for terminal output."""


def _emit(stage: str, started: float, *, stage_seconds: float | None = None, **counts: object) -> None:
    rss = _rss_bytes()
    available = _available_bytes()
    if rss >= SOFT_RSS_LIMIT_BYTES or available < MIN_AVAILABLE_BYTES:
        raise SafeFailure("memory_guard")
    record: dict[str, object] = {
        "stage": stage,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "rss_mib": round(rss / 1024**2),
        "peak_rss_mib": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024),
        "host_available_mib": round(available / 1024**2),
    }
    if stage_seconds is not None:
        record["stage_seconds"] = round(stage_seconds, 3)
    record.update(counts)
    TELEMETRY.append(record)
    print(json.dumps(record, separators=(",", ":"), sort_keys=True), flush=True)


def _start_memory_watchdog(*, timeout_seconds: float | None = None) -> None:
    started = time.monotonic()
    def monitor() -> None:
        while True:
            rss = _rss_bytes()
            available = _available_bytes()
            expired = timeout_seconds is not None and time.monotonic() - started >= timeout_seconds
            if rss >= SOFT_RSS_LIMIT_BYTES or available < MIN_AVAILABLE_BYTES or expired:
                print(json.dumps({
                    "stage": "time_watchdog" if expired else "memory_watchdog",
                    "status": "stopping",
                    "rss_mib": round(rss / 1024**2),
                    "host_available_mib": round(available / 1024**2),
                }, separators=(",", ":")), flush=True)
                os.kill(os.getpid(), signal.SIGTERM)
            time.sleep(2)
    threading.Thread(target=monitor, name="issue82-memory-watchdog", daemon=True).start()


def _rss_bytes() -> int:
    try:
        with open("/proc/self/statm", encoding="ascii") as stream:
            resident_pages = int(stream.read().split()[1])
        return resident_pages * os.sysconf("SC_PAGE_SIZE")
    except (OSError, ValueError, IndexError):
        return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024)


def _available_bytes() -> int:
    try:
        with open("/proc/meminfo", encoding="ascii") as stream:
            for line in stream:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return 0


def _bound_inputs(region: str) -> tuple[Path, Path, Path]:
    prefix = ENV_PREFIX[region]
    raw_root = Path(os.environ["RAW_ROOT"]).resolve(strict=True)
    tl_source = Path(os.environ[f"{prefix}_TL"])
    other_source = Path(os.environ[f"{prefix}_OTHER"])
    tl = tl_source.resolve(strict=True)
    other = other_source.resolve(strict=True)
    for original, resolved in ((tl_source, tl), (other_source, other)):
        if not resolved.is_dir() or _has_symlink_component(original):
            raise SafeFailure("role_binding")
        try:
            resolved.relative_to(raw_root)
        except ValueError as exc:
            raise SafeFailure("role_binding") from exc
    if region == "capital":
        # Capital's user-bound export exception is defined by the 2023 source
        # dataset and exact Other filekey in the repository's EDA provenance.
        if not approved_capital_filekey_root("capital", "TL", tl):
            raise SafeFailure("capital_tl_provenance")
        if other.name != "filekey-539782" or not any(
            part == "2023-travel-log-capital" for part in other.parts
        ):
            raise SafeFailure("capital_other_provenance")
    else:
        if tl.name.casefold() != "tl_csv" or other.name.casefold() != "other":
            raise SafeFailure("role_layout")
    return raw_root, tl, other


def _has_symlink_component(path: Path) -> bool:
    current = Path(path.anchor) if path.is_absolute() else Path.cwd()
    for part in path.parts[1:] if path.is_absolute() else path.parts:
        current /= part
        if current.is_symlink():
            return True
    return False


def _find_master_path(other: Path) -> Path:
    matches: list[Path] = []
    for current, directories, names in os.walk(other, followlinks=False):
        base = Path(current)
        depth = len(base.relative_to(other).parts)
        directories[:] = [
            name for name in directories
            if not name.startswith(".") and not (base / name).is_symlink() and depth < 4
        ]
        for name in names:
            folded = name.casefold()
            if name.lower().endswith(".csv") and ("poi_master" in folded or "poimaster" in folded):
                candidate = base / name
                if not candidate.is_symlink():
                    matches.append(candidate)
    if len(matches) != 1:
        raise SafeFailure("master_table_count")
    return matches[0]


def _normalize_admin_codebook_rows(rows: Iterable[Mapping[str, str]]) -> list[dict[str, str]]:
    """Normalize only 5-digit or zero-padded 10-digit TC_SGG rows.

    Nonzero 10-digit subdistrict rows are not truncated into SGG evidence.
    The canonical lookup still verifies component composition and names.
    """
    normalized: list[dict[str, str]] = []
    for row in rows:
        code = (row.get("SGG_CD") or "").strip()
        part1 = (row.get("SGG_CD1") or "").strip()
        part2 = (row.get("SGG_CD2") or "").strip()
        if len(code) == 10 and code[5:] == "00000":
            code = code[:5]
        elif len(code) != 5:
            continue
        if code != part1 + part2:
            continue
        normalized.append({**row, "SGG_CD": code})
    return normalized


def _table(folder: Path, token: str, fallback: str | None = None) -> Path:
    found = _find_csv_case_insensitive(folder, token)
    if fallback and not found:
        found = [p for p in _find_csv_case_insensitive(folder, fallback)
                 if "traveller" not in p.name.casefold()]
    if len(found) != 1:
        raise SafeFailure("tl_table_count")
    return found[0]


def iter_projected_csv(path: Path, required: Iterable[str], selected: Iterable[str]):
    """Stream selected columns while preserving strict source row-width checks."""
    selected_set = set(selected)
    required_set = set(required)
    with path.open("r", encoding="utf-8-sig", errors="strict", newline="") as stream:
        reader = csv.reader(stream)
        try:
            header = [value.strip() for value in next(reader)]
        except StopIteration as exc:
            raise SafeFailure("csv_header") from exc
        if not header or any(not value for value in header) or len(set(header)) != len(header):
            raise SafeFailure("csv_header")
        index = {name: position for position, name in enumerate(header)}
        if not required_set.issubset(index):
            raise SafeFailure("csv_schema")
        chosen = [(name, index[name]) for name in selected_set if name in index]
        for values in reader:
            if len(values) != len(header):
                raise SafeFailure("csv_row_width")
            yield {name: values[position] for name, position in chosen}


def iter_projected_values(path: Path, required: Iterable[str], selected: Iterable[str]):
    """Stream projected columns as tuples to avoid one dict allocation per row."""
    selected_names = tuple(selected)
    required_set = set(required)
    with path.open("r", encoding="utf-8-sig", errors="strict", newline="") as stream:
        reader = csv.reader(stream)
        try:
            header = [value.strip() for value in next(reader)]
        except StopIteration as exc:
            raise SafeFailure("csv_header") from exc
        if not header or any(not value for value in header) or len(set(header)) != len(header):
            raise SafeFailure("csv_header")
        index = {name: position for position, name in enumerate(header)}
        if not required_set.issubset(index):
            raise SafeFailure("csv_schema")
        positions = tuple(index[name] for name in selected_names)
        for values in reader:
            if len(values) != len(header):
                raise SafeFailure("csv_row_width")
            yield tuple(values[position] for position in positions)


def read_projected_csv(path: Path, required: Iterable[str], selected: Iterable[str]) -> list[dict[str, str]]:
    """Load a small TL source table using only its model-relevant columns."""
    return list(iter_projected_csv(path, required, selected))


def _load_master(
    path: Path,
    admin_lookup: Mapping[str, object],
    total_start: float,
    *,
    source_package_region: str,
) -> tuple[dict[str, dict[str, object]], set[str], int, int]:
    required = ("POI_ID", "SGG_CD", "ASORT_LCLASDC", "ASORT_MLSFCDC", "ASORT_SDASDC", "ROAD_NM_ADDR", "LOTNO_ADDR")
    duplicate_ids: set[str] = set()
    unique: dict[str, dict[str, object]] = {}
    master_start = time.monotonic()
    last_emit = master_start
    seen_rows = 0
    blank_id_rows = 0
    address_lookup = build_admin_address_lookup(admin_lookup)
    address_result_cache: dict[str, tuple[str, ...]] = {}
    for values in iter_projected_values(path, required, required):
        seen_rows += 1
        item = _clean_str(values[0])
        if not item:
            blank_id_rows += 1
        else:
            if item in duplicate_ids:
                pass
            elif item in unique:
                # Preserve the catalog contract: every repeated POI_ID is
                # excluded, regardless of which source row appeared first.
                del unique[item]
                duplicate_ids.add(item)
            else:
                code = _clean_str(values[1])
                road = _clean_str(values[5])
                lot = _clean_str(values[6])
                location_status, sido_code, sgg_code = resolve_master_admin_location_indexed(
                    lookup=admin_lookup,
                    address_lookup=address_lookup,
                    sgg_code=code,
                    addresses=(road, lot),
                    address_result_cache=address_result_cache,
                )
                unique[item] = {
                    "item_id": item,
                    "source_package_region": source_package_region,
                    "source_category_l1_code": _clean_str(values[2]),
                    "source_category_l2_code": _clean_str(values[3]),
                    "source_category_l3_code": _clean_str(values[4]),
                    "canonical_admin_sido_code": sido_code,
                    "canonical_admin_sgg_code": sgg_code,
                    "canonical_admin_location_status": location_status,
                }
        if seen_rows % MASTER_PROGRESS_ROWS == 0 or time.monotonic()-last_emit >= 10:
            _emit("master_csv_read", total_start, stage_seconds=time.monotonic()-master_start,
                  source_rows=seen_rows, unique_ids=len(unique) + len(duplicate_ids),
                  blank_id_rows=blank_id_rows)
            _emit("master_location", total_start, stage_seconds=time.monotonic()-master_start,
                  nonduplicate_unique_ids=len(unique), total_unique_ids=len(unique) + len(duplicate_ids),
                  duplicate_id_groups=len(duplicate_ids))
            last_emit = time.monotonic()
    return unique, duplicate_ids, seen_rows, blank_id_rows


def _resolved_canonical_sido_code(row: Mapping[str, object]) -> str:
    status = _clean_str(row.get("canonical_admin_location_status"))
    code = _clean_str(row.get("canonical_admin_sido_code"))
    if status not in RESOLVED_ADMIN_LOCATION_STATUSES:
        return ""
    return code


def _pre_filter_candidate_aggregates(
    master: Mapping[str, Mapping[str, object]],
    duplicate_ids: set[str],
    validation_truth: Mapping[str, set[str]],
    *,
    source_package_region: str,
    policy,
    source_rows: int,
    blank_id_rows: int,
) -> dict[str, object]:
    """Summarize geography and validation coverage before candidate filtering."""
    codes = policy.product_region_to_ldong_regn_cd.get(source_package_region)
    if not codes:
        raise SafeFailure("product_region_policy")
    counts_by_code = {code: 0 for code in sorted(codes)}
    unresolved_ids = 0
    resolved_outside_region_ids = 0
    for row in master.values():
        code = _resolved_canonical_sido_code(row)
        if not code:
            unresolved_ids += 1
        elif code in counts_by_code:
            counts_by_code[code] += 1
        else:
            resolved_outside_region_ids += 1

    positive_pairs = 0
    candidate_pairs = 0
    missing_pairs = 0
    unresolved_positive_pairs = 0
    other_region_positive_pairs = 0
    duplicate_positive_pairs = 0
    covered_queries = 0
    for trip_id, positive_ids in validation_truth.items():
        query_covered = False
        for item_id in positive_ids:
            positive_pairs += 1
            row = master.get(item_id)
            if row is None:
                if item_id in duplicate_ids:
                    duplicate_positive_pairs += 1
                else:
                    missing_pairs += 1
                continue
            code = _resolved_canonical_sido_code(row)
            if not code:
                unresolved_positive_pairs += 1
            elif code in counts_by_code:
                candidate_pairs += 1
                query_covered = True
            else:
                other_region_positive_pairs += 1
        covered_queries += int(query_covered)

    geography_denominator = len(master)
    return {
        "source_package_region": source_package_region,
        "candidate_region_policy_version": policy.version,
        "master_source_rows": source_rows,
        "master_blank_id_rows": blank_id_rows,
        "master_total_unique_ids": len(master) + len(duplicate_ids),
        "master_duplicate_id_groups": len(duplicate_ids),
        "master_unique_ids_after_duplicate_policy": geography_denominator,
        "canonical_candidate_ids_by_admin_sido_code": counts_by_code,
        "master_resolved_outside_requested_region_ids": resolved_outside_region_ids,
        "master_geography_unresolved_ids": unresolved_ids,
        "master_geography_resolution_denominator_ids": geography_denominator,
        "master_geography_unresolved_rate": round(
            unresolved_ids / geography_denominator, 6
        ) if geography_denominator else 0.0,
        "validation_positive_queries": len(validation_truth),
        "validation_positive_pairs": positive_pairs,
        "validation_candidate_covered_queries": covered_queries,
        "validation_candidate_covered_pairs": candidate_pairs,
        "validation_candidate_pair_coverage_rate": round(
            candidate_pairs / positive_pairs, 6
        ) if positive_pairs else 0.0,
        "validation_master_missing_positive_pairs": missing_pairs,
        "validation_master_duplicate_key_positive_pairs": duplicate_positive_pairs,
        "validation_master_present_geography_unresolved_positive_pairs": unresolved_positive_pairs,
        "validation_master_present_other_region_positive_pairs": other_region_positive_pairs,
    }


def _filter_master_to_product_region(
    master: dict[str, dict[str, object]],
    *,
    source_package_region: str,
    policy,
) -> dict[str, dict[str, object]]:
    """Drain full master rows into the resolved, policy-mapped candidate scope."""
    codes = policy.product_region_to_ldong_regn_cd.get(source_package_region)
    if not codes:
        raise SafeFailure("product_region_policy")
    candidates: dict[str, dict[str, object]] = {}
    # Move references rather than copying the full 7M-row map into a second map.
    while master:
        item_id, row = master.popitem()
        if row.get("source_package_region") != source_package_region:
            raise SafeFailure("source_region_provenance")
        code = _resolved_canonical_sido_code(row)
        if code in codes:
            row["product_region"] = source_package_region
            # `region` is the prepared candidate/request scope enforced by the
            # ranking contract; source provenance remains separately recorded.
            row["region"] = source_package_region
            candidates[item_id] = row
    if not candidates:
        raise SafeFailure("empty_geographic_inventory")
    return candidates


def _context_rows(travel_rows: list[dict[str, str]], traveler_rows: list[dict[str, str]], region: str, run_id: str):
    valid = valid_unique_trip_owner_rows(travel_rows, traveler_rows)
    owners = {str(row["TRAVEL_ID"]): str(row["TRAVELER_ID"]) for row in valid}
    unique_trips: dict[str, dict[str, str]] = {}
    counts = Counter(_clean_str(row.get("TRAVEL_ID")) for row in travel_rows)
    for row in travel_rows:
        trip = _clean_str(row.get("TRAVEL_ID"))
        if trip and counts[trip] == 1 and trip in owners:
            unique_trips[trip] = row
    traveler_counts = Counter(_clean_str(row.get("TRAVELER_ID")) for row in traveler_rows)
    unique_travelers = {
        _clean_str(row.get("TRAVELER_ID")): row for row in traveler_rows
        if _clean_str(row.get("TRAVELER_ID")) and traveler_counts[_clean_str(row.get("TRAVELER_ID"))] == 1
    }
    query_by_trip = {
        trip: _context(unique_trips[trip], unique_travelers[owner], "TL", region, run_id)
        for trip, owner in owners.items() if trip in unique_trips and owner in unique_travelers
    }
    if set(query_by_trip) != set(owners):
        raise SafeFailure("trip_context_cohort")
    return owners, query_by_trip


def _make_frame(queries, positives, materialization, catalog, *, limit: int | None):
    import pandas as pd
    item_rows = {str(row["item_id"]): row for row in materialization.item_features}
    inventory = catalog.inventory
    inventory_item_ids = set(inventory.items)
    by_trip: dict[str, set[str]] = defaultdict(set)
    for positive in positives:
        if positive.observed_positive:
            by_trip[positive.travel_id].add(positive.poi_id)
    rows: list[dict[str, object]] = []
    groups = 0
    for trip in sorted(by_trip):
        if limit is not None and groups >= limit:
            break
        positive_ids = tuple(sorted(by_trip[trip] & inventory_item_ids))
        if not positive_ids:
            continue
        negatives = sample_unobserved(
            inventory, positive_ids, ratio=1, seed=SPLIT_SEED,
            strategy=SamplingStrategy.UNIFORM,
        )
        if not negatives:
            continue
        context = queries[trip]
        for item_id, label in [*((item, 1) for item in positive_ids), *((item, 0) for item in negatives)]:
            item = item_rows[item_id]
            row = {column: item.get(column) for column in (
                "canonical_admin_sido_code", "canonical_admin_sgg_code",
                "canonical_admin_location_status", "train_positive_interaction_count",
                "train_observed_visit_type_codes",
            )}
            row.update({column: context.get(column) for column in (
                "start_month", "elapsed_days", "region",
            )})
            row.update({"item_id": item_id, "trip_id": trip, "group_id": trip, "label": label})
            rows.append(row)
        groups += 1
    if not rows:
        raise SafeFailure("empty_training_frame")
    return pd.DataFrame(rows), groups


def run(region: str, mode: str) -> dict[str, object]:
    TELEMETRY.clear()
    total_start = time.monotonic()
    if _available_bytes() < MIN_AVAILABLE_BYTES:
        raise SafeFailure("memory_gate")
    raw_root, tl_root, other_root = _bound_inputs(region)
    if not raw_root.is_dir():
        raise SafeFailure("raw_root")
    # Resolve expected tables only inside the already-bound roots. Other is
    # read solely for the static master, never visits or feedback.
    travel_path = _table(tl_root, "tn_travel_", "tn_travel")
    traveler_path = _table(tl_root, "tn_traveller_master")
    visit_path = _table(tl_root, "tn_visit_area_info")
    sgg_path = _table(tl_root, "tc_sgg")
    master_path = _find_master_path(other_root)
    _emit("role_preflight", total_start, tables_validated=5, roles="TL+static_OTHER")

    phase = time.monotonic()
    sgg_rows = read_projected_csv(sgg_path, SGG_COLUMNS, SGG_COLUMNS)
    admin_lookup = build_admin_lookup(_normalize_admin_codebook_rows(sgg_rows))
    if not admin_lookup:
        raise SafeFailure("admin_codebook")
    policy = load_poi_catalog_policy()
    master, duplicate_master_ids, master_source_rows, master_blank_id_rows = _load_master(
        master_path, admin_lookup, total_start, source_package_region=region,
    )
    if not master:
        raise SafeFailure("empty_master")
    _emit("static_catalog", total_start, stage_seconds=time.monotonic()-phase,
          master_unique_ids=len(master) + len(duplicate_master_ids),
          nonduplicate_master_ids=len(master), duplicate_id_groups=len(duplicate_master_ids),
          admin_codes=len(admin_lookup), policy_version=policy.version)

    phase = time.monotonic()
    traveler_rows = read_projected_csv(traveler_path, TRAVELER_COLUMNS, TRAVELER_COLUMNS)
    travel_rows = read_projected_csv(travel_path, TRAVEL_COLUMNS, TRAVEL_COLUMNS)
    visit_rows = read_projected_csv(visit_path, VISIT_COLUMNS, VISIT_COLUMNS)
    owners, query_context = _context_rows(travel_rows, traveler_rows, region, "issue82-inner-tl")
    valid_events = [
        {**row, "source_split": "TL"}
        for row in visit_rows
        if _clean_str(row.get("TRAVEL_ID")) in owners and _clean_str(row.get("VISIT_AREA_ID"))
    ]
    positives, positive_diagnostics = build_trip_poi_positives(
        valid_events, region=region, trip_to_traveler=owners,
        valid_traveler_ids=set(owners.values()),
    )
    eligible_positives = [positive for positive in positives if positive.has_tourism_core_visit]
    positive_rows = [
        {"TRAVEL_ID": item.travel_id, "POI_ID": item.poi_id,
         "observed_positive": 1, "source_split": "TL"}
        for item in eligible_positives
    ]
    _emit("tl_source_load", total_start, stage_seconds=time.monotonic()-phase,
          trip_count=len(owners), traveler_rows=len(traveler_rows),
          valid_visit_events=len(valid_events), positive_pairs=len(positives))

    validation_partition = deterministic_traveler_group_split(
        owners, seed=SPLIT_SEED, validation_fraction=0.2,
    )
    validation_truth: dict[str, set[str]] = defaultdict(set)
    for positive in eligible_positives:
        if validation_partition.get(positive.travel_id) == "inner-validation":
            validation_truth[positive.travel_id].add(positive.poi_id)
    pre_filter_aggregates = _pre_filter_candidate_aggregates(
        master, duplicate_master_ids, validation_truth,
        source_package_region=region, policy=policy,
        source_rows=master_source_rows, blank_id_rows=master_blank_id_rows,
    )
    _emit("candidate_scope_pre_filter", total_start, **pre_filter_aggregates)
    phase = time.monotonic()
    master = _filter_master_to_product_region(
        master, source_package_region=region, policy=policy,
    )
    _emit("geographic_candidate_inventory", total_start,
          stage_seconds=time.monotonic()-phase, product_region=region,
          candidate_items=len(master), policy_version=policy.version)

    phase = time.monotonic()
    materialization = materialize_inner_train_item_features(
        trip_owner=owners, item_features=master.values(),
        positive_interactions=positive_rows, visit_events=valid_events,
        split_seed=SPLIT_SEED,
    )
    if dict(materialization.partition_by_trip) != validation_partition:
        raise SafeFailure("inner_split_mismatch")
    catalog_config = ExperimentConfig(
        feature_groups=FEATURE_GROUPS,
        sampling_strategy=SamplingStrategy.UNIFORM,
        negative_ratio=1,
        objective="YetiRank",
        seed=SPLIT_SEED,
        iterations=PROBE_ITERATIONS if mode == "probe" else ITERATIONS,
        k_values=(5, 10, 20),
    )
    catalog = PreparedItemCatalog.from_materialization(materialization, catalog_config, region=region)
    inner_train = sum(v == "inner-train" for v in materialization.partition_by_trip.values())
    inner_validation = sum(v == "inner-validation" for v in materialization.partition_by_trip.values())
    _emit("inner_split_features", total_start, stage_seconds=time.monotonic()-phase,
          inner_train_trips=inner_train, inner_validation_trips=inner_validation,
          candidate_items=len(catalog.inventory.items), derived_i3_i4="inner-train_only")

    phase = time.monotonic()
    train_limit = PROBE_TRAIN_TRIPS if mode == "probe" else None
    train_frame, train_groups = _make_frame(
        query_context,
        [p for p in eligible_positives if materialization.partition_by_trip.get(p.travel_id)=="inner-train"],
        materialization, catalog, limit=train_limit,
    )
    _emit("uniform_sampling", total_start, stage_seconds=time.monotonic()-phase,
          train_rows=len(train_frame), train_queries=train_groups, negative_ratio=1)

    # Validation ground truth remains all positives, including positives
    # missing from master, geographically unresolved, or outside ProductRegion.
    ordered_validation = sorted(validation_truth)
    if mode in {"probe", "profile"}:
        ordered_validation = ordered_validation[:PROBE_VALIDATION_QUERIES]
    if not ordered_validation:
        raise SafeFailure("empty_validation")
    phase = time.monotonic()
    model = fit_catboost(
        train_frame, label_column="label", group_column="group_id",
        config=catalog_config,
        train_derived_source_scope="inner-train",
        inner_train_materialization=materialization,
    )
    _emit("catboost_fit", total_start, stage_seconds=time.monotonic()-phase,
          iterations=catalog_config.iterations, train_rows=len(train_frame),
          train_queries=train_groups)

    phase = time.monotonic()
    validation_progress_interval = max(
        1, min(VALIDATION_PROGRESS_QUERIES, len(ordered_validation) // 10)
    )
    def ground_truth():
        for index, trip in enumerate(ordered_validation, start=1):
            yield trip, validation_truth[trip]
            if index % validation_progress_interval == 0 or index == len(ordered_validation):
                _emit("validation_progress", total_start, queries_completed=index,
                      queries_total=len(ordered_validation), candidate_items=len(catalog.inventory.items))
    result = score_inner_validation_queries(
        model, catalog, ground_truth(), query_features=query_context,
        config=catalog_config, max_rows_per_batch=PREDICTION_BATCH_ROWS,
    )
    _emit("evaluation", total_start, stage_seconds=time.monotonic()-phase,
          query_count=result.query_count, candidate_count=result.candidate_count,
          scored_rows=result.scored_rows, max_prediction_rows=result.max_batch_rows)
    telemetry_by_stage = {str(record["stage"]): record for record in TELEMETRY}
    return {
        "region": region,
        "mode": mode,
        "objective": "YetiRank",
        "sampling": "uniform",
        "negative_ratio": 1,
        "seed": SPLIT_SEED,
        "iterations": catalog_config.iterations,
        "feature_groups": list(FEATURE_GROUPS),
        "train_rows": len(train_frame),
        "train_queries": train_groups,
        "validation_queries": result.query_count,
        "candidate_items": result.candidate_count,
        "scored_rows": result.scored_rows,
        "prediction_frame_row_cap": PREDICTION_BATCH_ROWS,
        "fit_seconds": telemetry_by_stage["catboost_fit"]["stage_seconds"],
        "scoring_seconds": telemetry_by_stage["evaluation"]["stage_seconds"],
        "peak_rss_mib": max(int(record["peak_rss_mib"]) for record in TELEMETRY),
        "metrics": dict(result.metrics),
        "total_seconds": round(time.monotonic()-total_start, 3),
        "positive_diagnostics": {
            "distinct_trip_poi_positives": positive_diagnostics["distinct_trip_poi_positives"],
            "tourism_core_trip_poi_positives": positive_diagnostics["tourism_core_trip_poi_positives"],
        },
        "candidate_scope_aggregates": pre_filter_aggregates,
        "scope_note": (
            "source-package provenance is distinct from ProductRegion; candidate inventory "
            "contains only resolved canonical SIDO codes in the versioned ProductRegion policy"
        ),
        "telemetry": list(TELEMETRY),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--region", choices=REGIONS, required=True)
    parser.add_argument("--mode", choices=("probe", "profile", "full"), required=True)
    parser.add_argument(
        "--time-limit-seconds", type=int, default=120,
        help="Probe watchdog limit; use a bounded increase for actual throughput profiling.",
    )
    args = parser.parse_args()
    if args.time_limit_seconds <= 0:
        parser.error("--time-limit-seconds must be positive")
    try:
        _start_memory_watchdog(
            timeout_seconds=args.time_limit_seconds if args.mode in {"probe", "profile"} else None
        )
        result = run(args.region, args.mode)
        if args.mode == "full":
            output = REPO_ROOT / "results" / "experiments" / "catboost-ranking" / "issue82-inner-tl-smoke-20261026"
            # Fail closed unless the local policy already excludes this path.
            ignored = subprocess.run(
                ["git", "-C", str(REPO_ROOT), "check-ignore", "-q", str(output)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            ).returncode == 0
            if not ignored:
                raise SafeFailure("results_not_gitignored")
            output.mkdir(parents=True, exist_ok=True)
            target = output / f"{args.region}.json"
            temporary = target.with_suffix(".json.tmp")
            temporary.write_text(json.dumps(result, separators=(",", ":"), sort_keys=True), encoding="utf-8")
            temporary.replace(target)
        print(json.dumps({"result": result}, separators=(",", ":"), sort_keys=True), flush=True)
        return 0
    except SafeFailure as exc:
        print(json.dumps({"status": "stopped", "reason": str(exc)}, separators=(",", ":")), flush=True)
        return 2
    except Exception as exc:
        # Suppress messages because parser/library exceptions can contain paths,
        # row values, or raw IDs. The type is sufficient for safe triage.
        print(json.dumps({"status": "failed", "error_class": type(exc).__name__}, separators=(",", ":")), flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
