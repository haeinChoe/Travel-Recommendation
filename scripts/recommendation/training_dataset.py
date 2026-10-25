"""Issue #73 deterministic standard training dataset transformation.

Raw identifiers are kept in memory only. The three Parquet files contain run-scoped
surrogate keys and explicitly separated metadata and model-feature columns.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.recommendation.training_data_contract import (
    MOTIVE_FEATURES,
    NON_TOURISM_VISIT_AREA_TYPES,
    REGION_ENV_PREFIX,
    REGIONS,
    SPLITS,
    STYLE_FEATURES,
    TEMPORAL_FEATURES,
    TOURISM_CORE_VISIT_AREA_TYPES,
    VISIT_AREA_TYPE_LABELS,
    _clean_str,
    _find_csv_case_insensitive,
    resolve_sgg_code_parity,
    build_trip_poi_positives,
    derive_temporal_features,
    validate_code_domain,
    validate_companions_num,
    validate_vis_codebook_rows,
)
from scripts.recommendation.training_data_contract import (
    COMPANION_FEATURES,
)
from scripts.recommendation.sgg_crosswalk import SggCrosswalk
from scripts.recommendation.canonical_admin_location import (
    build_admin_lookup,
    compare_visit_location,
    normalize_aihub_sgg_code,
    resolve_canonical_admin_location,
)

DEFAULT_OUTPUT = REPO_ROOT / "data" / "processed" / "training-dataset"
MODEL_FEATURE_ALLOWLIST = frozenset(
    {*(f"travel_style_{i}" for i in range(1, 9)),
     *(f"travel_motive_{i}" for i in range(1, 4)), "region", "travel_status_destination",
     "companion_status", "companion_count", "start_month", "elapsed_days",
     "train_observed_visit_type_codes", "canonical_admin_sido_code",
     "canonical_admin_sgg_code", "canonical_admin_location_status", "source_category_l1_code",
     "source_category_l2_code", "source_category_l3_code", "train_positive_interaction_count"}
)
SOURCE_TO_CANONICAL_COLUMNS = {
    **{f"TRAVEL_STYL_{i}": f"travel_style_{i}" for i in range(1, 9)},
    **{f"TRAVEL_MOTIVE_{i}": f"travel_motive_{i}" for i in range(1, 4)},
    "TRAVEL_STATUS_DESTINATION": "travel_status_destination",
    "TRAVEL_STATUS_ACCOMPANY": "companion_status",
    "TRAVEL_COMPANIONS_NUM": "companion_count",
    "TN_TRAVEL.TRAVEL_START_YMD:month": "start_month",
    "TN_TRAVEL.TRAVEL_START_YMD+TRAVEL_END_YMD": "elapsed_days",
    "VISIT_AREA_TYPE_CD": "train_observed_visit_type_codes",
    "SGG_CD": "visit_sgg_code_evidence",
    "ASORT_LCLASDC": "source_category_l1_code",
    "ASORT_MLSFCDC": "source_category_l2_code",
    "ASORT_SDASDC": "source_category_l3_code",
    "train_trip_item_positive_count": "train_positive_interaction_count",
    "interaction_split_set": "observed_in_splits",
}
FORBIDDEN_FEATURE_NAMES = frozenset({
    "trip_key", "item_key", "split", "observed_in_splits",
    "observed_positive", "repeat_visit_count", "TRAVELER_ID", "TRAVEL_ID",
    "VISIT_AREA_ID", "POI_ID", "contentid", "TRAVEL_START_YMD",
    "TRAVEL_END_YMD", "ROAD_NM_ADDR", "LOTNO_ADDR", "X_COORD", "Y_COORD",
    "latitude", "longitude", "h3", "distance", "TN_GPS_COORD",
    "visit_type_conflict", "repeat_visit_count", "source_split",
})


def surrogate_key(run_id: str, kind: str, region: str, raw_id: str) -> str:
    """Stable opaque key; the raw value is only ever hashed in memory."""
    payload = "\0".join((run_id, kind, region, raw_id)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:32]


def strict_sgg(raw: object, valid_codes: set[str]) -> str | None:
    value = _clean_str(raw)
    return value if value in valid_codes else None


def _read_dicts(path: Path, required: Iterable[str] = ()) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", errors="strict", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or any(not name.strip() for name in reader.fieldnames):
            raise ValueError("Malformed CSV header")
        reader.fieldnames = [name.strip() for name in reader.fieldnames]
        if len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise ValueError("Duplicate CSV column")
        if set(required) - set(reader.fieldnames):
            raise ValueError("Required columns missing from source CSV")
        parsed = []
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ValueError("Malformed CSV row width")
            parsed.append({str(k).strip(): v for k, v in row.items() if k is not None})
        return parsed


def _one(files: list[Path], table: str) -> Path:
    if len(files) != 1:
        raise ValueError(f"Expected exactly one {table} CSV; found {len(files)}")
    return files[0]


def _source_files(folder: Path) -> dict[str, Path]:
    travel = _find_csv_case_insensitive(folder, "tn_travel_")
    if not travel:
        travel = [p for p in _find_csv_case_insensitive(folder, "tn_travel")
                  if "traveller" not in p.name.casefold()]
    return {
        "travel": _one(travel, "TN_TRAVEL"),
        "traveller": _one(_find_csv_case_insensitive(folder, "tn_traveller_master"), "TN_TRAVELLER_MASTER"),
        "visit": _one(_find_csv_case_insensitive(folder, "tn_visit_area_info"), "TN_VISIT_AREA_INFO"),
        "codeb": _one(_find_csv_case_insensitive(folder, "codeb"), "TC_CODEB"),
        "companion": _find_csv_case_insensitive(folder, "tn_companion_info"),
    }


def _master_path(other: Path) -> Path:
    candidates = [other / "메타데이터" / "tn_poi_master_POIMaster_all.csv",
                  other / "tn_poi_master_POIMaster_all.csv"]
    target = next((p for p in candidates if p.is_file()), None)
    if target is None:
        found = sorted(other.glob("**/*poi_master*.csv")) + sorted(other.glob("**/*POI*Master*.csv"))
        if len(found) != 1:
            raise ValueError("TN_POI_MASTER must resolve to one CSV")
        target = found[0]
    return target


def _master_rows(path: Path, admin_lookup: Mapping[str, object]) -> tuple[dict[str, dict[str, str]], Counter[str]]:
    counts: Counter[str] = Counter()
    first: dict[str, dict[str, str]] = {}
    for row in _read_dicts(path, ("POI_ID", "SGG_CD", "ASORT_LCLASDC", "ASORT_MLSFCDC", "ASORT_SDASDC")):
        pid = _clean_str(row.get("POI_ID"))
        if not pid:
            continue
        counts[pid] += 1
        first.setdefault(pid, row)
    unique = {}
    for pid, row in first.items():
        if counts[pid] == 1:
            unique[pid] = {
                "SGG_CD": normalize_aihub_sgg_code(row.get("SGG_CD"), admin_lookup),
                "_raw_sgg": _clean_str(row.get("SGG_CD")),
                **{c: _clean_str(row.get(c)) for c in ("ASORT_LCLASDC", "ASORT_MLSFCDC", "ASORT_SDASDC")},
                "ROAD_NM_ADDR": _clean_str(row.get("ROAD_NM_ADDR")),
                "LOTNO_ADDR": _clean_str(row.get("LOTNO_ADDR")),
                "X_COORD": _clean_str(row.get("X_COORD")),
                "Y_COORD": _clean_str(row.get("Y_COORD")),
            }
    return unique, counts


def _context(travel: Mapping[str, str], traveler: Mapping[str, str], split: str,
             region: str, run_id: str) -> dict[str, object]:
    start, end = _clean_str(travel.get("TRAVEL_START_YMD")), _clean_str(travel.get("TRAVEL_END_YMD"))
    temporal = derive_temporal_features(start, end)
    tid = _clean_str(travel.get("TRAVEL_ID"))
    if tid is None:
        raise ValueError("Missing TRAVEL_ID in unique trip row")
    result: dict[str, object] = {
        "trip_key": surrogate_key(run_id, "trip", region, tid),
        "region": region, "split": {"TL": "train", "VL": "validation"}[split],
        "start_month": temporal.month, "elapsed_days": temporal.elapsed_days,
        "travel_status_destination": _clean_str(traveler.get("TRAVEL_STATUS_DESTINATION")),
        "companion_status": _clean_str(traveler.get("TRAVEL_STATUS_ACCOMPANY")),
        "companion_count": validate_companions_num(traveler.get("TRAVEL_COMPANIONS_NUM")),
    }
    for col in STYLE_FEATURES + MOTIVE_FEATURES:
        result[SOURCE_TO_CANONICAL_COLUMNS[col]] = validate_code_domain(col, traveler.get(col))
    return result


def resolve_item_sgg(visit_codes: set[str], master_sgg: str | None) -> tuple[str, str | None]:
    """Apply the shared visit/Master conflict policy for audit and item features."""
    if len(visit_codes) > 1:
        return "value_conflicts", None
    if visit_codes:
        visit_sgg = next(iter(visit_codes))
        if master_sgg and master_sgg != visit_sgg:
            return "value_conflicts", None
        return "direct", visit_sgg
    if master_sgg:
        return "master_filled", master_sgg
    return "unavailable", None


def _sgg_outcome(current_visit_sgg: str | None, current_raw_sgg: str | None,
                 cohort_visit_codes: set[str], poi_id: str | None,
                 master_rows: Mapping[str, Mapping[str, str]],
                 master_counts: Counter[str], valid_sgg: set[str]) -> tuple[str, str | None, str, str]:
    join_state = ("poi_id_missing" if not poi_id else
                  "unique" if poi_id in master_rows else
                  "ambiguous" if master_counts[poi_id] > 1 else "missing")
    master = master_rows.get(poi_id or "")
    master_value = master.get("SGG_CD") if master else None
    # Master SGG-state is kept separate from the POI join-state.
    if master:
        master_state = "valid" if master_value else ("invalid_unregistered" if master.get("_raw_sgg") else "missing")
    elif join_state == "ambiguous":
        master_state = "unavailable_ambiguous_join"
    else:
        master_state = "unavailable_no_unique_master"
    valid_master = master_value if master_value in valid_sgg else None
    resolution, resolved_sgg = resolve_item_sgg(cohort_visit_codes, valid_master)
    if resolution == "value_conflicts":
        return "value_conflicts", None, join_state, master_state
    if resolution == "direct":
        if current_visit_sgg:
            return "direct", resolved_sgg, join_state, master_state
        return "poi_aggregate_filled", resolved_sgg, join_state, master_state
    if resolution == "master_filled":
        return "master_filled", resolved_sgg, join_state, master_state
    visit_state = "invalid_unregistered" if current_raw_sgg else "missing"
    if visit_state == "invalid_unregistered" or master_state == "invalid_unregistered":
        outcome = "invalid_unregistered"
    elif not poi_id or join_state in {"missing", "ambiguous"}:
        outcome = "poi_join_missing_or_ambiguous"
    elif master_state == "missing" and visit_state == "missing":
        outcome = "both_missing"
    elif master_state == "missing":
        outcome = "master_missing"
    else:
        outcome = "master_missing"
    return outcome, None, join_state, master_state


def validate_feature_allowlist(columns: Iterable[str]) -> None:
    illegal = set(columns) - MODEL_FEATURE_ALLOWLIST
    forbidden = set(columns) & FORBIDDEN_FEATURE_NAMES
    if illegal or forbidden:
        raise ValueError("Model feature allowlist violation")


def validate_dataset_keys(context_rows: list[dict[str, object]], item_rows: list[dict[str, object]],
                          interaction_rows: list[dict[str, object]]) -> None:
    trip_metadata: dict[str, tuple[str, str]] = {}
    trip_keys = [str(r.get("trip_key", "")) for r in context_rows]
    item_keys = [str(r.get("item_key", "")) for r in item_rows]
    if not all(trip_keys) or len(set(trip_keys)) != len(trip_keys):
        raise ValueError("Trip surrogate key integrity failed")
    if not all(item_keys) or len(set(item_keys)) != len(item_keys):
        raise ValueError("Item surrogate key integrity failed")
    interaction_keys = [(str(r.get("trip_key", "")), str(r.get("item_key", "")))
                        for r in interaction_rows]
    if len(set(interaction_keys)) != len(interaction_keys):
        raise ValueError("Duplicate trip-item interaction")
    for row in context_rows:
        trip_metadata[str(row["trip_key"])] = (str(row["region"]), str(row["split"]))
    item_metadata = {str(row["item_key"]): str(row["region"]) for row in item_rows}
    for row in interaction_rows:
        trip_key, item_key = str(row.get("trip_key", "")), str(row.get("item_key", ""))
        if trip_key not in trip_metadata or item_key not in item_metadata:
            raise ValueError("Interaction foreign key integrity failed")
        if (trip_metadata[trip_key] != (str(row.get("region")), str(row.get("split")))
                or item_metadata[item_key] != row.get("region")):
            raise ValueError("Trip split leakage")
        if row.get("observed_positive") != 1 or int(row.get("repeat_visit_count", 0)) < 1:
            raise ValueError("Interaction label or diagnostic invalid")
    for row in context_rows:
        if not row.get("region") or row.get("split") not in {"train", "validation"}:
            raise ValueError("Required trip_context metadata missing")
    for row in item_rows:
        observed_splits = row.get("observed_in_splits")
        if (not row.get("region") or not isinstance(observed_splits, list)
                or not set(observed_splits) <= {"train", "validation"}):
            raise ValueError("Required item_features metadata missing")
        if not isinstance(row.get("train_observed_visit_type_codes"), list) or row.get("train_positive_interaction_count") is None:
            raise ValueError("Required item_features values missing")


def validate_sgg_reconciliation(outcomes: Mapping[str, int], denominator: int) -> None:
    if sum(outcomes.values()) != denominator:
        raise ValueError("SGG outcome denominator mismatch")


class _SafeArgumentParser(argparse.ArgumentParser):
    """Keep argparse diagnostics from reflecting caller-supplied argument text."""

    def error(self, message: str) -> None:
        self._print_message("Invalid command-line arguments; details are suppressed.\n", sys.stderr)
        raise SystemExit(2)


def _parquet(connection: "duckdb.DuckDBPyConnection", path: Path, rows: list[dict[str, object]], schema: str) -> None:
    # Explicit DDL keeps the Parquet physical types and nullability stable for empty data too.
    connection.execute(f"CREATE TEMP TABLE frame AS {schema}")
    if rows:
        names = list(rows[0])
        columns = ",".join('"' + n + '"' for n in names)
        marks = ",".join("?" for _ in names)
        connection.executemany(f"INSERT INTO frame ({columns}) VALUES ({marks})", [tuple(r[n] for n in names) for r in rows])
    connection.execute(f"COPY frame TO '{str(path).replace("'", "''")}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    connection.execute("DROP TABLE frame")


def transform(inputs: Mapping[tuple[str, str], Path], masters: Mapping[str, Path],
              output_dir: Path, run_id: str) -> dict[str, object]:
    """Transform all eight role-bound input splits into three Parquet datasets."""
    if set(inputs) != {(r, s) for r in REGIONS for s in SPLITS}:
        raise ValueError("Exactly all 8 region/split inputs are required")
    contexts: dict[tuple[str, str], dict[str, object]] = {}
    interaction_rows: list[dict[str, object]] = []
    item_build: dict[tuple[str, str], dict[str, object]] = {}
    audit = {"by_region_split_cohort": {}, "visit_type_reconciliation": {},
             "canonical_location": {}}
    codebook_digest: set[str] = set()
    sgg_crosswalk = SggCrosswalk()
    trip_ids_by_region_split: dict[tuple[str, str], set[str]] = {}

    for region in REGIONS:
        # Master is scoped by region and must never be sourced from VL visit values.
        master_path = masters[region]
        for split in SPLITS:
            src = _source_files(inputs[(region, split)])
            codebook = _read_dicts(src["codeb"], ("cd_a", "cd_b", "cd_nm"))
            vis_check = validate_vis_codebook_rows(codebook)
            if not vis_check["vis_codebook_verified"]:
                raise ValueError(f"TC_CODEB VIS mismatch in {region}:{split}")
            codebook_digest.add(hashlib.sha256(json.dumps(vis_check, sort_keys=True).encode()).hexdigest())
            tc_sgg_files = _find_csv_case_insensitive(inputs[(region, split)], "tc_sgg")
            if tc_sgg_files:
                sgg_crosswalk.load_from_csvs(tc_sgg_files)
            sgg_codes: set[str] = set()
            for p in tc_sgg_files:
                sgg_rows = _read_dicts(p, ("SGG_CD",))
                for row in sgg_rows:
                    code = _clean_str(row.get("SGG_CD"))
                    if code: sgg_codes.add(code)
            if not sgg_codes:
                raise ValueError(f"TC_SGG missing in {region}:{split}")
            sgg_rows = [row for p in tc_sgg_files
                        for row in _read_dicts(p, ("SGG_CD", "SGG_CD1", "SGG_CD2", "SIDO_NM", "SGG_NM"))]
            admin_lookup = build_admin_lookup(sgg_rows)
            if not admin_lookup:
                raise ValueError(f"TC_SGG has no usable administrative names in {region}:{split}")
            master_rows, master_counts = _master_rows(master_path, admin_lookup)
            if split == "TL":
                location_counts: Counter[str] = Counter()
                for pid, master in master_rows.items():
                    location = resolve_canonical_admin_location(
                        lookup=admin_lookup,
                        master_sgg_codes=(master.get("_raw_sgg"),),
                        master_addresses=(master.get("ROAD_NM_ADDR"), master.get("LOTNO_ADDR")),
                    )
                    item_key = surrogate_key(run_id, "item", region, pid)
                    build = item_build.setdefault((region, item_key), {
                        "item_key": item_key, "region": region, "split_presence": set(),
                        "VISIT_AREA_TYPE_CODES": set(), "tl_popularity": 0,
                    })
                    build.update({
                        "ASORT_LCLASDC": master.get("ASORT_LCLASDC"),
                        "ASORT_MLSFCDC": master.get("ASORT_MLSFCDC"),
                        "ASORT_SDASDC": master.get("ASORT_SDASDC"),
                        "canonical_admin_sido_code": location.sido_code,
                        "canonical_admin_sgg_code": location.sgg_code,
                        "canonical_admin_sido_name": location.sido_name,
                        "canonical_admin_sgg_name": location.sgg_name,
                        "canonical_admin_location_status": location.status,
                        "canonical_admin_provenance": list(location.provenance),
                        "canonical_admin_conflict_sources": list(location.conflict_sources),
                        "coordinate_validation_status": location.coordinate_status,
                    })
                    location_counts[location.status] += 1
                audit["canonical_location"][region] = {
                    "master_inventory_denominator": len(master_rows),
                    "static_resolution_status_counts": dict(sorted(location_counts.items())),
                    "coordinate_validation": "unverified_source_crs_and_axis_order; not used",
                    "visit_evidence_policy": "diagnostic_only; never fills model feature",
                }

            traveler_rows = _read_dicts(src["traveller"], ("TRAVELER_ID", *STYLE_FEATURES, *MOTIVE_FEATURES,
                "TRAVEL_STATUS_DESTINATION", "TRAVEL_STATUS_ACCOMPANY", "TRAVEL_COMPANIONS_NUM"))
            travelers: dict[str, list[dict[str, str]]] = defaultdict(list)
            for row in traveler_rows:
                key = _clean_str(row.get("TRAVELER_ID"))
                if key: travelers[key].append(row)
            unique_travelers = {k: v[0] for k, v in travelers.items() if len(v) == 1}
            raw_trip_rows = _read_dicts(src["travel"], ("TRAVEL_ID", "TRAVELER_ID", "TRAVEL_START_YMD", "TRAVEL_END_YMD"))
            trip_rows: dict[str, list[dict[str, str]]] = defaultdict(list)
            for row in raw_trip_rows:
                key = _clean_str(row.get("TRAVEL_ID"))
                if key: trip_rows[key].append(row)
            unique_trips = {k: v[0] for k, v in trip_rows.items() if len(v) == 1}
            trip_ids_by_region_split[(region, split)] = set(unique_trips)
            if split == "VL" and trip_ids_by_region_split[(region, "TL")] & set(unique_trips):
                raise ValueError(f"TL/VL trip overlap in {region}")
            trip_owner: dict[str, str | None] = {}
            for tid, row in unique_trips.items():
                owner = _clean_str(row.get("TRAVELER_ID"))
                trip_owner[tid] = owner if owner in unique_travelers else None
            if any(owner is None for owner in trip_owner.values()):
                # Match #71 structural rules: malformed trip ownership is excluded, not fabricated.
                trip_owner = {k: v for k, v in trip_owner.items() if v is not None}
            for tid, owner in trip_owner.items():
                assert owner is not None
                contexts[(region, tid)] = _context(unique_trips[tid], unique_travelers[owner], split, region, run_id)

            visits = _read_dicts(src["visit"], ("TRAVEL_ID", "VISIT_AREA_ID", "POI_ID", "VISIT_AREA_TYPE_CD", "SGG_CD",
                "ROAD_NM_ADDR", "LOTNO_ADDR", "X_COORD", "Y_COORD"))
            valid_events: list[dict[str, str]] = []
            trip_visit_rows = []
            for row in visits:
                tid = _clean_str(row.get("TRAVEL_ID"))
                if tid in trip_owner and _clean_str(row.get("VISIT_AREA_ID")):
                    valid_events.append(row)
                    trip_visit_rows.append(row)
            positives, diag = build_trip_poi_positives(trip_visit_rows, region=region,
                trip_to_traveler=trip_owner, valid_traveler_ids=set(unique_travelers))

            if split == "TL":
                visit_location_counts: Counter[str] = Counter()
                for event in valid_events:
                    poi_id = _clean_str(event.get("POI_ID"))
                    if not poi_id:
                        visit_location_counts["visit_only_unconfirmed"] += 1
                        continue
                    item_key = surrogate_key(run_id, "item", region, poi_id)
                    static = item_build.get((region, item_key), {})
                    visit_location_counts[compare_visit_location(
                        canonical_sgg_code=static.get("canonical_admin_sgg_code"),
                        visit_sgg_codes=(event.get("SGG_CD"),),
                        visit_addresses=(event.get("ROAD_NM_ADDR"), event.get("LOTNO_ADDR")),
                        lookup=admin_lookup,
                    )] += 1
                audit["canonical_location"][region]["train_visit_corroboration"] = {
                    "denominator": len(valid_events),
                    "status_counts": dict(sorted(visit_location_counts.items())),
                    "used_to_populate_features": False,
                }

            visit_type_counts: Counter[str] = Counter({name: 0 for name in (
                "tourism_core", "non_tourism", "missing_visit_type", "unsupported_visit_type")})
            for row in valid_events:
                raw_type = _clean_str(row.get("VISIT_AREA_TYPE_CD"))
                valid_type = validate_code_domain("VISIT_AREA_TYPE_CD", raw_type)
                if raw_type is None:
                    reason = "missing_visit_type"
                elif valid_type is None:
                    reason = "unsupported_visit_type"
                elif valid_type in TOURISM_CORE_VISIT_AREA_TYPES:
                    reason = "tourism_core"
                elif valid_type in NON_TOURISM_VISIT_AREA_TYPES:
                    reason = "non_tourism"
                else:
                    reason = "unsupported_visit_type"
                visit_type_counts[reason] += 1
            validate_sgg_reconciliation(visit_type_counts, len(valid_events))
            audit["visit_type_reconciliation"][f"{region}:{split}"] = {
                "all_valid_visits_denominator": len(valid_events),
                "visit_type_classification_counts": dict(sorted(visit_type_counts.items())),
            }

            by_pair: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
            for row in trip_visit_rows:
                tid, pid = _clean_str(row.get("TRAVEL_ID")), _clean_str(row.get("POI_ID"))
                if tid and pid: by_pair[(tid, pid)].append(row)
            for positive in positives:
                if not positive.has_tourism_core_visit:
                    continue
                trip_key = surrogate_key(run_id, "trip", region, positive.travel_id)
                item_key = surrogate_key(run_id, "item", region, positive.poi_id)
                evs = by_pair[(positive.travel_id, positive.poi_id)]
                core_events = [e for e in evs if (validate_code_domain("VISIT_AREA_TYPE_CD", e.get("VISIT_AREA_TYPE_CD")) in TOURISM_CORE_VISIT_AREA_TYPES)]
                # Only TL rows can populate item-derived values. VL can only link to an existing key.
                if split == "TL":
                    build = item_build.setdefault((region, item_key), {
                        "item_key": item_key, "region": region, "split_presence": set(),
                        "VISIT_AREA_TYPE_CODES": set(),
                        "ASORT_LCLASDC": None, "ASORT_MLSFCDC": None, "ASORT_SDASDC": None,
                        "tl_popularity": 0,
                        "canonical_admin_sido_code": None, "canonical_admin_sgg_code": None,
                        "canonical_admin_sido_name": None, "canonical_admin_sgg_name": None,
                        "canonical_admin_location_status": "unavailable",
                        "canonical_admin_provenance": [], "canonical_admin_conflict_sources": [],
                        "coordinate_validation_status": "unverified_not_used",
                    })
                    build["VISIT_AREA_TYPE_CODES"].update(
                        validate_code_domain("VISIT_AREA_TYPE_CD", e.get("VISIT_AREA_TYPE_CD"))
                        for e in evs if validate_code_domain("VISIT_AREA_TYPE_CD", e.get("VISIT_AREA_TYPE_CD"))
                    )
                    master = master_rows.get(positive.poi_id)
                    if master:
                        for col in ("ASORT_LCLASDC", "ASORT_MLSFCDC", "ASORT_SDASDC"):
                            build[col] = master.get(col)
                    if positive.has_tourism_core_visit:
                        build["tl_popularity"] += 1
                    build["split_presence"].add("train")
                elif (region, item_key) in item_build:
                    item_build[(region, item_key)]["split_presence"].add({"TL": "train", "VL": "validation"}[split])
                interaction_rows.append({
                    "trip_key": trip_key, "item_key": item_key, "region": region, "split": {"TL": "train", "VL": "validation"}[split],
                    "observed_positive": 1, "repeat_visit_count": positive.repeat_visit_count,
                })

            # Visit-level SGG audit: only aggregate states and boolean location clues leave memory.
            for cohort in ("all_valid_visits", "tourism_core", "non_tourism"):
                rows = valid_events if cohort == "all_valid_visits" else [r for r in valid_events if
                    ((validate_code_domain("VISIT_AREA_TYPE_CD", r.get("VISIT_AREA_TYPE_CD"))
                      in (TOURISM_CORE_VISIT_AREA_TYPES if cohort == "tourism_core"
                          else NON_TOURISM_VISIT_AREA_TYPES)))]
                result_counts: Counter[str] = Counter({name: 0 for name in (
                    "direct", "poi_aggregate_filled", "master_filled", "invalid_unregistered",
                    "poi_join_missing_or_ambiguous", "master_missing", "both_missing", "value_conflicts")})
                visit_states: Counter[str] = Counter({name: 0 for name in ("valid", "invalid_unregistered", "missing")})
                join_states: Counter[str] = Counter({name: 0 for name in ("unique", "missing", "ambiguous", "poi_id_missing")})
                master_states: Counter[str] = Counter({name: 0 for name in (
                    "valid", "invalid_unregistered", "missing", "unavailable_ambiguous_join",
                    "unavailable_no_unique_master")})
                legacy_coverage = strict_coverage = 0
                unavailable_clues: Counter[str] = Counter({name: 0 for name in (
                    "ROAD_NM_ADDR_present", "LOTNO_ADDR_present", "XY_pair_present")})
                unavailable_poi_presence: Counter[str] = Counter({"present": 0, "missing": 0})
                unavailable_master_join_states: Counter[str] = Counter({
                    "unique": 0, "missing": 0, "ambiguous": 0, "not_applicable": 0})
                poi_aggregate_event_states: Counter[str] = Counter({name: 0 for name in (
                    "unique_valid_value", "multiple_valid_values", "no_valid_value", "not_applicable")})
                poi_aggregate_distinct_states: Counter[str] = Counter({name: 0 for name in (
                    "unique_valid_value", "multiple_valid_values", "no_valid_value")})
                unavailable_rows = 0
                by_poi_sgg: dict[str, set[str]] = defaultdict(set)
                for event in rows:
                    event_poi = _clean_str(event.get("POI_ID"))
                    if event_poi:
                        by_poi_sgg[event_poi]
                        event_raw = _clean_str(event.get("SGG_CD"))
                        event_valid = strict_sgg(event_raw, sgg_codes)
                        if event_valid:
                            by_poi_sgg[event_poi].add(event_valid)
                for poi_id, codes in by_poi_sgg.items():
                    aggregate_state = ("multiple_valid_values" if len(codes) > 1 else
                                       "unique_valid_value" if codes else "no_valid_value")
                    poi_aggregate_distinct_states[aggregate_state] += 1
                for row in rows:
                    raw_sgg = _clean_str(row.get("SGG_CD"))
                    pid = _clean_str(row.get("POI_ID"))
                    valid_visit = strict_sgg(raw_sgg, sgg_codes)
                    cohort_codes = by_poi_sgg.get(pid or "", {valid_visit} if valid_visit else set())
                    outcome, resolved_sgg, jstate, mstate = _sgg_outcome(
                        valid_visit, raw_sgg, cohort_codes, pid,
                        master_rows, master_counts, sgg_codes)
                    vstate = "valid" if valid_visit else ("invalid_unregistered" if raw_sgg else "missing")
                    visit_states[vstate] += 1; join_states[jstate] += 1; master_states[mstate] += 1
                    result_counts[outcome] += 1
                    aggregate_state = ("not_applicable" if not pid else
                        "multiple_valid_values" if len(cohort_codes) > 1 else
                        "unique_valid_value" if cohort_codes else "no_valid_value")
                    poi_aggregate_event_states[aggregate_state] += 1
                    if resolved_sgg in sgg_codes: strict_coverage += 1
                    if resolved_sgg and resolve_sgg_code_parity(resolved_sgg, sgg_crosswalk) is not None:
                        legacy_coverage += 1
                    if outcome not in {"direct", "poi_aggregate_filled", "master_filled"}:
                        unavailable_rows += 1
                        unavailable_poi_presence["present" if pid else "missing"] += 1
                        if not pid:
                            unavailable_master_join_states["not_applicable"] += 1
                        elif pid in master_rows:
                            unavailable_master_join_states["unique"] += 1
                        elif master_counts[pid] > 1:
                            unavailable_master_join_states["ambiguous"] += 1
                        else:
                            unavailable_master_join_states["missing"] += 1
                        unavailable_clues["ROAD_NM_ADDR_present"] += bool(_clean_str(row.get("ROAD_NM_ADDR")))
                        unavailable_clues["LOTNO_ADDR_present"] += bool(_clean_str(row.get("LOTNO_ADDR")))
                        unavailable_clues["XY_pair_present"] += bool(_clean_str(row.get("X_COORD")) and _clean_str(row.get("Y_COORD")))
                key = f"{region}:{split}:{cohort}"
                validate_sgg_reconciliation(visit_states, len(rows))
                validate_sgg_reconciliation(join_states, len(rows))
                validate_sgg_reconciliation(master_states, len(rows))
                validate_sgg_reconciliation(result_counts, len(rows))
                validate_sgg_reconciliation(poi_aggregate_event_states, len(rows))
                validate_sgg_reconciliation(poi_aggregate_distinct_states, len(by_poi_sgg))
                validate_sgg_reconciliation(unavailable_poi_presence, unavailable_rows)
                validate_sgg_reconciliation(unavailable_master_join_states, unavailable_rows)
                if any(count > unavailable_rows for count in unavailable_clues.values()):
                    raise ValueError("SGG unavailable location-presence count exceeds denominator")
                audit["by_region_split_cohort"][key] = {
                    "denominator": len(rows), "visit_state_counts": dict(sorted(visit_states.items())),
                    "master_join_state_counts": dict(sorted(join_states.items())),
                    "master_sgg_state_counts": dict(sorted(master_states.items())),
                    "resolved_outcome_counts": dict(sorted(result_counts.items())),
                    "current_visit_strict_valid_count": visit_states["valid"],
                    "poi_aggregate_event_state_counts": dict(sorted(poi_aggregate_event_states.items())),
                    "poi_aggregate_distinct_state_counts": dict(sorted(poi_aggregate_distinct_states.items())),
                    "distinct_poi_denominator": len(by_poi_sgg),
                    "legacy_crosswalk_compatible_count": legacy_coverage,
                    "strict_tc_sgg_coverage_count": strict_coverage,
                    "sgg_unavailable_observation_count": unavailable_rows,
                    "sgg_unavailable_poi_presence_counts": dict(sorted(unavailable_poi_presence.items())),
                    "sgg_unavailable_master_join_state_counts": dict(sorted(unavailable_master_join_states.items())),
                    "sgg_unavailable_location_presence_counts": dict(unavailable_clues),
                }

    # Ensure every interaction has one item row; VL-only items get null TL-derived fields.
    for row in interaction_rows:
        key = (row["region"], row["item_key"])
        if key not in item_build:
            item_build[key] = {"item_key": row["item_key"], "region": row["region"],
                "split_presence": set(), "VISIT_AREA_TYPE_CODES": set(),
                "ASORT_LCLASDC": None, "ASORT_MLSFCDC": None, "ASORT_SDASDC": None,
                "tl_popularity": 0, "canonical_admin_sido_code": None,
                "canonical_admin_sgg_code": None, "canonical_admin_sido_name": None,
                "canonical_admin_sgg_name": None, "canonical_admin_location_status": "unavailable",
                "canonical_admin_provenance": [], "canonical_admin_conflict_sources": [],
                "coordinate_validation_status": "unverified_not_used"}
        item_build[key]["split_presence"].add(row["split"])
    item_rows = []
    for key in sorted(item_build):
        item = item_build[key]
        item_rows.append({
            "item_key": item["item_key"], "region": item["region"],
            "observed_in_splits": sorted(item["split_presence"]),
            "train_observed_visit_type_codes": sorted(item["VISIT_AREA_TYPE_CODES"], key=lambda x: int(x)),
            "canonical_admin_sido_code": item["canonical_admin_sido_code"],
            "canonical_admin_sgg_code": item["canonical_admin_sgg_code"],
            "canonical_admin_sido_name": item["canonical_admin_sido_name"],
            "canonical_admin_sgg_name": item["canonical_admin_sgg_name"],
            "canonical_admin_location_status": item["canonical_admin_location_status"],
            "canonical_admin_provenance": sorted(set(item["canonical_admin_provenance"])),
            "canonical_admin_conflict_sources": sorted(set(item["canonical_admin_conflict_sources"])),
            "coordinate_validation_status": item["coordinate_validation_status"],
            "source_category_l1_code": item["ASORT_LCLASDC"],
            "source_category_l2_code": item["ASORT_MLSFCDC"],
            "source_category_l3_code": item["ASORT_SDASDC"],
            "train_positive_interaction_count": item["tl_popularity"],
        })
    context_rows = [contexts[k] for k in sorted(contexts)]
    interaction_rows.sort(key=lambda r: (r["region"], r["split"], r["trip_key"], r["item_key"]))
    item_rows.sort(key=lambda r: (r["region"], r["item_key"]))
    validate_dataset_keys(context_rows, item_rows, interaction_rows)
    context_features = set(MODEL_FEATURE_ALLOWLIST) - {"train_observed_visit_type_codes", "canonical_admin_sido_code", "canonical_admin_sgg_code", "canonical_admin_location_status", "source_category_l1_code", "source_category_l2_code", "source_category_l3_code", "train_positive_interaction_count"}
    item_features = {"region", "train_observed_visit_type_codes", "canonical_admin_sido_code", "canonical_admin_sgg_code", "canonical_admin_location_status", "source_category_l1_code", "source_category_l2_code", "source_category_l3_code", "train_positive_interaction_count"}
    validate_feature_allowlist(context_features | item_features)
    output_dir.mkdir(parents=True, exist_ok=True)
    import duckdb

    con = duckdb.connect()
    try:
        _parquet(con, output_dir / "trip_context.parquet", context_rows,
            "SELECT CAST(NULL AS VARCHAR) trip_key, CAST(NULL AS VARCHAR) region, CAST(NULL AS VARCHAR) split, "
            + ", ".join([*(f"CAST(NULL AS VARCHAR) travel_style_{i}" for i in range(1,9)),
                *(f"CAST(NULL AS VARCHAR) travel_motive_{i}" for i in range(1,4)),
                "CAST(NULL AS VARCHAR) travel_status_destination", "CAST(NULL AS VARCHAR) companion_status",
                "CAST(NULL AS INTEGER) companion_count", 'CAST(NULL AS VARCHAR) AS "start_month"', "CAST(NULL AS INTEGER) elapsed_days"])
            + " WHERE FALSE")
        _parquet(con, output_dir / "item_features.parquet", item_rows,
            "SELECT CAST(NULL AS VARCHAR) item_key, CAST(NULL AS VARCHAR) region, CAST(NULL AS VARCHAR[]) observed_in_splits, "
            "CAST(NULL AS VARCHAR[]) train_observed_visit_type_codes, "
            "CAST(NULL AS VARCHAR) canonical_admin_sido_code, CAST(NULL AS VARCHAR) canonical_admin_sgg_code, "
            "CAST(NULL AS VARCHAR) canonical_admin_sido_name, CAST(NULL AS VARCHAR) canonical_admin_sgg_name, "
            "CAST(NULL AS VARCHAR) canonical_admin_location_status, "
            "CAST(NULL AS VARCHAR[]) canonical_admin_provenance, CAST(NULL AS VARCHAR[]) canonical_admin_conflict_sources, "
            "CAST(NULL AS VARCHAR) coordinate_validation_status, "
            "CAST(NULL AS VARCHAR) source_category_l1_code, CAST(NULL AS VARCHAR) source_category_l2_code, "
            "CAST(NULL AS VARCHAR) source_category_l3_code, CAST(NULL AS BIGINT) train_positive_interaction_count WHERE FALSE")
        _parquet(con, output_dir / "trip_item_interaction.parquet", interaction_rows,
            "SELECT CAST(NULL AS VARCHAR) trip_key, CAST(NULL AS VARCHAR) item_key, CAST(NULL AS VARCHAR) region, "
            "CAST(NULL AS VARCHAR) split, CAST(NULL AS INTEGER) observed_positive, "
            "CAST(NULL AS BIGINT) repeat_visit_count WHERE FALSE")
    finally:
        con.close()
    payload = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "dataset_type": "travel-recommendation-training", "schema_version": "2.0", "contract_version": "2.0", "outputs": {"trip_context": len(context_rows),
            "item_features": len(item_rows), "trip_item_interaction": len(interaction_rows)},
        "feature_allowlist": sorted(MODEL_FEATURE_ALLOWLIST), "codebook_splits_verified": 8,
        "codebook_digest_count": len(codebook_digest), "sgg_audit": audit,
        "privacy": {"raw_ids_persisted": False, "raw_values_in_audit": False,
                    "raw_paths_in_manifest": False},
    }
    (output_dir / "manifest.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def _resolve_env_inputs() -> tuple[dict[tuple[str, str], Path], dict[str, Path]]:
    inputs = {}
    for region in REGIONS:
        prefix = REGION_ENV_PREFIX[region]
        for split in SPLITS:
            value = os.environ.get(f"{prefix}_{split}")
            if not value: raise ValueError(f"Missing required input binding {prefix}_{split}")
            inputs[(region, split)] = Path(value)
    masters = {}
    for region in REGIONS:
        prefix = REGION_ENV_PREFIX[region]
        value = os.environ.get(f"{prefix}_OTHER")
        if not value: raise ValueError(f"Missing required master binding {prefix}_OTHER")
        masters[region] = _master_path(Path(value))
    return inputs, masters


def main(argv: Sequence[str] | None = None) -> int:
    parser = _SafeArgumentParser(description="Build Issue #73 standard training Parquet datasets")
    parser.add_argument("--run-id", required=True, help="Stable non-sensitive run identifier")
    parser.add_argument("--output-dir", type=Path, default=None,
                        help="Git-ignored output directory; default is data/processed/training-dataset/<run-id>")
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", args.run_id):
        parser.error("Invalid --run-id; details are suppressed.")
    try:
        inputs, masters = _resolve_env_inputs()
        output = args.output_dir or (DEFAULT_OUTPUT / args.run_id)
        result = transform(inputs, masters, output, args.run_id)
    except Exception:
        # CSV/library errors can echo raw rows or source/output paths; keep CLI failures safe.
        print("Training dataset transformation failed; diagnostic details are suppressed for privacy.", file=sys.stderr)
        return 2
    print("Training dataset transformation completed: " + json.dumps(result["outputs"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
