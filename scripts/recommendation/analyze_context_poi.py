"""Analyze context × POI feasibility without exposing source-level records.

The program keeps identifiers and raw category values in memory only. It reads
only named fields from approved TL/VL roles and writes aggregate audit,
association, predictive, and metadata artifacts below ignored results/.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Iterable, Sequence

import evaluate_popularity as shared

REPO_ROOT = shared.REPO_ROOT
RESULTS_ROOT = REPO_ROOT / "results" / "experiments" / "context-poi-signal"
REGIONS = shared.REGIONS
MIN_CELL = 10
TARGETS = ("DGSTFN", "REVISIT_INTENTION", "RCMDTN_INTENTION")
MASTER_CONTEXT = (
    *(f"TRAVEL_STYL_{index}" for index in range(1, 9)),
    *(f"TRAVEL_MOTIVE_{index}" for index in range(1, 4)),
    "TRAVEL_STATUS_DESTINATION",
    "TRAVEL_STATUS_ACCOMPANY",
    "TRAVEL_COMPANIONS_NUM",
)
TRIP_CONTEXT = (
    "TRAVEL_MISSION",
    "TRAVEL_START_YMD",
    "TRAVEL_END_YMD",
)
DEMOGRAPHICS = ("GENDER", "AGE_GRP")
VISIT_POI = (
    "POI_ID",
    "VISIT_AREA_TYPE_CD",
    "SGG_CD",
    *TARGETS,
)
MASTER_POI = (
    "POI_ID",
    "SGG_CD",
    "ASORT_LCLASDC",
    "ASORT_MLSFCDC",
    "ASORT_SDASDC",
)
COMPANION_FIELDS = ("REL_CD", "COMPANION_GENDER", "COMPANION_AGE_GRP", "COMPANION_SITUATION")
ALL_FEATURE_FIELDS = (*MASTER_CONTEXT, *TRIP_CONTEXT, *DEMOGRAPHICS, *VISIT_POI, *MASTER_POI,
                      *COMPANION_FIELDS)
ARTIFACTS = ("availability_audit.csv", "associations.csv", "predictive_ablation.csv", "run_metadata.json")


@dataclass(frozen=True)
class InputSpec:
    region: str
    role: str
    root: Path


@dataclass(frozen=True)
class PoiSpec:
    region: str
    root: Path


@dataclass
class LoadedSplit:
    spec: InputSpec
    trip_rows: dict[str, dict[str, str | None]]
    master_rows: dict[str, dict[str, str | None]]
    companion_rows: dict[str, list[dict[str, str | None]]]
    observations: list[dict[str, object]]
    audit: list[dict[str, object]]
    poi_ids: set[str] = field(default_factory=set)
    trip_ids: set[str] = field(default_factory=set)
    traveler_ids: set[str] = field(default_factory=set)


def _table_role(path: Path) -> str | None:
    stem = path.stem.upper()
    for table in (
        "TN_TRAVEL", "TN_TRAVELLER_MASTER", "TN_COMPANION_INFO",
        "TN_VISIT_AREA_INFO", "TN_POI_MASTER",
    ):
        if stem == table or stem.startswith(table + "_"):
            return table
    return None


def parse_poi_spec(value: str) -> tuple[str, Path]:
    region, sep, raw_path = value.partition("=")
    if not sep or region not in REGIONS or not raw_path:
        raise argparse.ArgumentTypeError("POI master 형식은 region=PATH 입니다.")
    return region, Path(raw_path)


def count_bucket(value: int) -> str:
    if value == 0:
        return "0"
    return "<10" if value < MIN_CELL else "10+"


def rate_band(numerator: int, denominator: int) -> str:
    if denominator < MIN_CELL or 0 < numerator < MIN_CELL:
        return "<10/suppressed"
    if numerator == 0:
        return "0-<10%"
    ratio = numerator / denominator
    if ratio < 0.10:
        return "0-<10%"
    if ratio < 0.25:
        return "10-<25%"
    if ratio < 0.50:
        return "25-<50%"
    if ratio < 0.75:
        return "50-<75%"
    if ratio < 0.90:
        return "75-<90%"
    return "90-100%"


def _blank(value: str | None) -> bool:
    return value is None or value.strip() == ""


def _value(row: dict[str, str | None], field_name: str) -> str | None:
    value = row.get(field_name.casefold())
    return None if _blank(value) else value


def _read_rows(files: Sequence[Path], required: set[str], selected: set[str]):
    return shared._rows(files, required, selected)


def _files_by_table(root: Path) -> dict[str, list[Path]]:
    result: dict[str, list[Path]] = defaultdict(list)
    for path in shared.csv_files(root):
        role = _table_role(path)
        if role:
            result[role].append(path)
    return result


def _read_table(files: Sequence[Path], required: set[str], selected: set[str]):
    return list(_read_rows(files, required, selected))


def _date(value: str | None) -> date | None:
    if _blank(value):
        return None
    try:
        return date.fromisoformat(value)  # type: ignore[arg-type]
    except ValueError:
        return None


def _feature_audit(scope: str, table: str, field_name: str,
                   values: Iterable[str | None], status: str = "observed") -> dict[str, object]:
    total = nonmissing = 0
    distinct: set[str] = set()
    frequencies: Counter[str] = Counter()
    for value in values:
        total += 1
        if not _blank(value):
            nonmissing += 1
            distinct.add(value)  # exact source string; no trim/case normalization
            frequencies[value] += 1
    return {
        "scope": scope,
        "table": table,
        "field": field_name,
        "rows": count_bucket(total),
        "nonmissing": count_bucket(nonmissing),
        "missing_rate": rate_band(total - nonmissing, total) if total else "unavailable",
        "cardinality": count_bucket(len(distinct)),
        "categories_below_k": count_bucket(sum(0 < count < MIN_CELL for count in frequencies.values())),
        "categories_at_least_k": count_bucket(sum(count >= MIN_CELL for count in frequencies.values())),
        "largest_category_share": rate_band(max(frequencies.values(), default=0), nonmissing) if nonmissing else "unavailable",
        "status": status if total else "insufficient-support",
    }


def _feedback_audit(scope: str, target: str,
                    values: Iterable[str | None]) -> dict[str, object]:
    observed = list(values)
    result = _feature_audit(scope, "TN_VISIT_AREA_INFO", target, observed)
    allowed_codes = {"1", "2", "3", "4", "5"}
    outside = [value for value in observed if not _blank(value) and value not in allowed_codes]
    distinct_outside = set(outside)
    result.update({
        "outside_documented_range": count_bucket(len(outside)),
        "outside_range_cardinality": count_bucket(len(distinct_outside)),
        "status": "documented_1_to_5_opaque_codes",
    })
    return result


def _trip_lookup(rows: Sequence[dict[str, str | None]]) -> tuple[dict[str, dict[str, str | None]], dict[str, object]]:
    groups: dict[str, list[dict[str, str | None]]] = defaultdict(list)
    for row in rows:
        trip_id = _value(row, "TRAVEL_ID")
        if trip_id is not None:
            groups[trip_id].append(row)
    unique = {key: values[0] for key, values in groups.items() if len(values) == 1}
    audit = {
        "candidate_keys": count_bucket(len(groups)),
        "unique_keys": count_bucket(len(unique)),
        "duplicate_keys": count_bucket(sum(1 for values in groups.values() if len(values) > 1)),
    }
    return unique, audit


def _poi_lookup(rows: Sequence[dict[str, str | None]]) -> tuple[dict[str, dict[str, str | None]], dict[str, object]]:
    groups: dict[str, list[dict[str, str | None]]] = defaultdict(list)
    for row in rows:
        poi = _value(row, "POI_ID")
        if poi is not None:
            groups[poi].append(row)
    unique = {key: values[0] for key, values in groups.items() if len(values) == 1}
    duplicate = sum(1 for values in groups.values() if len(values) > 1)
    multi_sgg = sum(
        1 for values in groups.values()
        if len({v for row in values if (v := _value(row, "SGG_CD")) is not None}) > 1
    )
    return unique, {
        "master_rows": count_bucket(len(rows)),
        "nonblank_candidate_keys": count_bucket(len(groups)),
        "unique_candidate_keys": count_bucket(len(unique)),
        "duplicate_candidate_keys": count_bucket(duplicate),
        "keys_with_multiple_sgg_values": count_bucket(multi_sgg),
    }


def _load_split(spec: InputSpec, poi_root: Path | None) -> LoadedSplit:
    tables = _files_by_table(spec.root)
    if not tables["TN_TRAVEL"] or not tables["TN_VISIT_AREA_INFO"]:
        raise ValueError("required travel or visit table is missing")
    travel_fields = {"TRAVEL_ID", "TRAVELER_ID", *TRIP_CONTEXT}
    master_fields = {"TRAVELER_ID", *MASTER_CONTEXT, *DEMOGRAPHICS}
    visit_fields = {"TRAVEL_ID", *VISIT_POI}
    companion_fields = {"TRAVEL_ID", *COMPANION_FIELDS}
    travel_rows = _read_table(tables["TN_TRAVEL"], {"TRAVEL_ID", "TRAVELER_ID"}, travel_fields)
    master_rows_raw = _read_table(tables["TN_TRAVELLER_MASTER"], {"TRAVELER_ID"}, master_fields) if tables["TN_TRAVELLER_MASTER"] else []
    companion_rows_raw = _read_table(tables["TN_COMPANION_INFO"], {"TRAVEL_ID"}, companion_fields) if tables["TN_COMPANION_INFO"] else []
    visit_rows = _read_table(tables["TN_VISIT_AREA_INFO"], {"TRAVEL_ID"}, visit_fields)
    scope = f"{spec.region}:{spec.role}"

    trips, trip_key_audit = _trip_lookup(travel_rows)
    owners_by_traveler: dict[str, list[dict[str, str | None]]] = defaultdict(list)
    for row in master_rows_raw:
        traveler_id = _value(row, "TRAVELER_ID")
        if traveler_id is not None:
            owners_by_traveler[traveler_id].append(row)
    masters = {key: values[0] for key, values in owners_by_traveler.items() if len(values) == 1}
    companions: dict[str, list[dict[str, str | None]]] = defaultdict(list)
    for row in companion_rows_raw:
        trip_id = _value(row, "TRAVEL_ID")
        if trip_id is not None:
            companions[trip_id].append(row)

    poi_by_id: dict[str, dict[str, str | None]] = {}
    poi_field_audit: list[dict[str, object]] = []
    poi_audit: dict[str, object] = {
        "master_rows": "unavailable", "nonblank_candidate_keys": "unavailable",
        "unique_candidate_keys": "unavailable", "duplicate_candidate_keys": "unavailable",
        "keys_with_multiple_sgg_values": "unavailable",
    }
    if poi_root is not None:
        poi_files = shared.csv_files(poi_root) if poi_root.is_dir() else [poi_root]
        poi_files = [p for p in poi_files if _table_role(p) == "TN_POI_MASTER"]
        if poi_files:
            master_poi_rows = _read_table(poi_files, {"POI_ID"}, set(MASTER_POI))
            poi_by_id, poi_audit = _poi_lookup(master_poi_rows)
            poi_field_audit = [
                _feature_audit(scope, "TN_POI_MASTER", field_name,
                               (_value(row, field_name) for row in master_poi_rows))
                for field_name in MASTER_POI
            ]

    observations: list[dict[str, object]] = []
    visit_master_matches = 0
    visit_trip_matches = 0
    poi_matches = 0
    poi_candidate_rows = sum(_value(row, "POI_ID") is not None for row in visit_rows)
    poi_metadata_coverage: Counter[str] = Counter()
    visit_poi_frequency: Counter[str] = Counter()
    for visit in visit_rows:
        poi_id = _value(visit, "POI_ID")
        if poi_id is not None and poi_id in poi_by_id:
            poi_matches += 1
            for field_name in ("SGG_CD", "ASORT_LCLASDC", "ASORT_MLSFCDC", "ASORT_SDASDC"):
                if _value(poi_by_id[poi_id], field_name) is not None:
                    poi_metadata_coverage[field_name] += 1
    for visit in visit_rows:
        poi_candidate = _value(visit, "POI_ID")
        if poi_candidate is not None:
            visit_poi_frequency[poi_candidate] += 1
    for visit in visit_rows:
        trip_id = _value(visit, "TRAVEL_ID")
        trip = trips.get(trip_id) if trip_id is not None else None
        if trip is None:
            continue
        visit_trip_matches += 1
        traveler_id = _value(trip, "TRAVELER_ID")
        traveler = masters.get(traveler_id) if traveler_id is not None else None
        if traveler is not None:
            visit_master_matches += 1
        poi_id = _value(visit, "POI_ID")
        poi_record = poi_by_id.get(poi_id) if poi_id is not None else None
        row: dict[str, object] = {
            "region": spec.region,
            "role": spec.role,
            "trip_id": trip_id,
            "traveler_id": traveler_id,
            "poi_id": poi_id,
            "visit_area_type": _value(visit, "VISIT_AREA_TYPE_CD"),
            "visit_sgg": _value(visit, "SGG_CD"),
            "master_sgg": _value(poi_record or {}, "SGG_CD"),
            "poi_l1": _value(poi_record or {}, "ASORT_LCLASDC"),
            "poi_l2": _value(poi_record or {}, "ASORT_MLSFCDC"),
            "poi_l3": _value(poi_record or {}, "ASORT_SDASDC"),
            "feedback": {target: _value(visit, target) for target in TARGETS},
            "popularity_band": None,
            "elapsed_days": None,
            "month": None,
            "context": {},
            "demographics": {},
            "companion_relations": (),
        }
        for name in MASTER_CONTEXT:
            row["context"][name] = _value(traveler or {}, name)  # type: ignore[index]
        for name in DEMOGRAPHICS:
            row["demographics"][name] = _value(traveler or {}, name)  # type: ignore[index]
        for name in TRIP_CONTEXT:
            row["context"][name] = _value(trip, name)  # type: ignore[index]
        start = _date(_value(trip, "TRAVEL_START_YMD"))
        end = _date(_value(trip, "TRAVEL_END_YMD"))
        if start is not None:
            row["month"] = f"{start.month:02d}"
        if start is not None and end is not None and end >= start:
            row["elapsed_days"] = (end - start).days
        comp = companions.get(trip_id or "", [])
        row["companion_relations"] = tuple(sorted({v for c in comp if (v := _value(c, "REL_CD")) is not None}))
        observations.append(row)
    if spec.role == "TL":
        counts = Counter(
            row["poi_id"] for row in observations
            if row["poi_id"] is not None
        )
        for row in observations:
            count = counts.get(row["poi_id"], 0)
            row["popularity_band"] = (
                "1" if count == 1 else "2-4" if count <= 4 else "5-9" if count <= 9 else "10+"
            ) if count else None

    audit: list[dict[str, object]] = []
    for table, fields, rows in (
        ("TN_TRAVEL", (*TRIP_CONTEXT,), travel_rows),
        ("TN_TRAVELLER_MASTER", (*MASTER_CONTEXT, *DEMOGRAPHICS), master_rows_raw),
        ("TN_VISIT_AREA_INFO", tuple(field for field in VISIT_POI if field not in TARGETS), visit_rows),
        ("TN_COMPANION_INFO", (*COMPANION_FIELDS,), companion_rows_raw),
    ):
        for field_name in fields:
            audit.append(_feature_audit(
                scope, table, field_name, (_value(row, field_name) for row in rows),
                "unresolved_semantics" if field_name in {"TRAVEL_MISSION", "TRAVEL_MISSION_CHECK"} else "observed",
            ))
    audit.extend([
        {"scope": scope, "table": "TN_TRAVEL", "field": "TRAVEL_ID candidate relationship", **trip_key_audit,
         "status": "audited_candidate_only"},
        {"scope": scope, "table": "TN_TRAVELLER_MASTER", "field": "TRAVELER_ID candidate join",
         "rows": count_bucket(len(master_rows_raw)),
         "nonmissing": count_bucket(sum(_value(row, "TRAVELER_ID") is not None for row in master_rows_raw)),
         "missing_rate": rate_band(sum(_value(row, "TRAVELER_ID") is None for row in master_rows_raw), len(master_rows_raw)),
         "cardinality": count_bucket(len(masters)),
         "duplicate_keys": count_bucket(sum(len(rows) > 1 for rows in owners_by_traveler.values())),
         "status": "audited_candidate_only"},
        {"scope": scope, "table": "TN_TRAVEL → TN_TRAVELLER_MASTER", "field": "visit rows with unique candidate owner",
         "rows": count_bucket(len(visit_rows)), "nonmissing": count_bucket(visit_master_matches),
         "missing_rate": rate_band(len(visit_rows) - visit_master_matches, len(visit_rows)),
         "cardinality": "not_applicable", "status": "audited_candidate_only"},
        {"scope": scope, "table": "TN_VISIT_AREA_INFO → TN_POI_MASTER", "field": "POI_ID exact candidate join",
         **poi_audit, "visit_rows": count_bucket(len(visit_rows)),
         "visit_candidate_keys": count_bucket(len(visit_poi_frequency)),
         "visit_keys_with_multiple_rows": count_bucket(sum(count > 1 for count in visit_poi_frequency.values())),
         "visit_nonblank_poi_rows": count_bucket(poi_candidate_rows),
         "matched_visit_rows": count_bucket(poi_matches),
         "coverage": rate_band(poi_matches, poi_candidate_rows), "status": "audited_candidate_only" if poi_by_id else "unavailable_master"},
        {"scope": scope, "table": "TN_VISIT_AREA_INFO → TN_TRAVEL", "field": "TRAVEL_ID candidate join",
         "rows": count_bucket(len(visit_rows)), "nonmissing": count_bucket(visit_trip_matches),
         "missing_rate": rate_band(len(visit_rows) - visit_trip_matches, len(visit_rows)),
         "status": "audited_candidate_only"},
        {"scope": scope, "table": "TN_COMPANION_INFO → TN_TRAVEL", "field": "TRAVEL_ID one-to-many candidate join",
         "rows": count_bucket(len(companion_rows_raw)), "nonmissing": count_bucket(len(companions)),
         "missing_rate": "not_applicable", "cardinality": "one-to-many candidate",
         "status": "audited_candidate_only" if companion_rows_raw else "unavailable_table"},
        {"scope": scope, "table": "TN_VISIT_AREA_INFO", "field": "VISIT_AREA_TYPE_CD",
         "rows": count_bucket(len(visit_rows)), "nonmissing": count_bucket(sum(_value(v, "VISIT_AREA_TYPE_CD") is not None for v in visit_rows)),
         "status": "candidate_poi_representation"},
        {"scope": scope, "table": "derived from TN_TRAVEL", "field": "month from TRAVEL_START_YMD",
         **_feature_audit(scope, "derived", "month", (
             f"{parsed.month:02d}" for value in (_value(row, "TRAVEL_START_YMD") for row in travel_rows)
             if (parsed := _date(value)) is not None
         ))},
        {"scope": scope, "table": "derived from TN_TRAVEL", "field": "elapsed calendar days",
         **_feature_audit(scope, "derived", "elapsed calendar days", (
             str((end - start).days) if start is not None and end is not None and end >= start else None
             for row in travel_rows
             for start, end in [(_date(_value(row, "TRAVEL_START_YMD")), _date(_value(row, "TRAVEL_END_YMD")))]
         ))},
        {"scope": scope, "table": "TN_TRAVEL", "field": "season mapping",
         "status": "unresolved_no_documented_mapping"},
        {"scope": scope, "table": "TN_VISIT_AREA_INFO", "field": "feedback targets",
         "status": "kept_separate_post_event_targets"},
    ])
    audit.extend(
        _feedback_audit(scope, target, (_value(row, target) for row in visit_rows))
        for target in TARGETS
    )
    audit.extend(poi_field_audit)
    for field_name in ("SGG_CD", "ASORT_LCLASDC", "ASORT_MLSFCDC", "ASORT_SDASDC"):
        audit.append({
            "scope": scope, "table": "TN_VISIT_AREA_INFO → TN_POI_MASTER",
            "field": f"matched visit coverage for {field_name}",
            "rows": count_bucket(poi_candidate_rows),
            "nonmissing": count_bucket(poi_metadata_coverage[field_name]),
            "missing_rate": rate_band(poi_candidate_rows - poi_metadata_coverage[field_name], poi_candidate_rows),
            "status": "candidate_metadata_coverage" if poi_by_id else "unavailable_master",
        })
    return LoadedSplit(
        spec, trips, masters, companions, observations, audit,
        {poi_id for row in visit_rows if (poi_id := _value(row, "POI_ID")) is not None},
        {trip_id for row in travel_rows if (trip_id := _value(row, "TRAVEL_ID")) is not None},
        {traveler_id for row in travel_rows if (traveler_id := _value(row, "TRAVELER_ID")) is not None},
    )


def _chi_square(table: dict[tuple[object, object], int], rows: int,
                left_levels: int, right_levels: int) -> tuple[float | None, float | None, float | None]:
    if rows == 0 or left_levels < 2 or right_levels < 2:
        return None, None, None
    left_counts: Counter[object] = Counter()
    right_counts: Counter[object] = Counter()
    for (left, right), count in table.items():
        left_counts[left] += count
        right_counts[right] += count
    chi = 0.0
    for left in left_counts:
        for right in right_counts:
            observed = table.get((left, right), 0)
            expected = left_counts[left] * right_counts[right] / rows
            if expected:
                chi += (observed - expected) ** 2 / expected
    dof = (left_levels - 1) * (right_levels - 1)
    # Regularized upper incomplete gamma Q(dof/2, chi/2), stdlib only.
    p_value = _gamma_q(dof / 2, chi / 2)
    cramers_v = math.sqrt(chi / (rows * min(left_levels - 1, right_levels - 1)))
    return chi, p_value, cramers_v


def _gamma_q(a: float, x: float) -> float:
    if x <= 0:
        return 1.0
    if x < a + 1.0:
        term = total = 1.0 / a
        ap = a
        for _ in range(10000):
            ap += 1.0
            term *= x / ap
            total += term
            if abs(term) <= abs(total) * 1e-14:
                break
        p = total * math.exp(-x + a * math.log(x) - math.lgamma(a))
        return max(0.0, min(1.0, 1.0 - p))
    b = x + 1.0 - a
    c = 1.0 / 1e-300
    d = 1.0 / b
    h = d
    for i in range(1, 10000):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        if abs(d) < 1e-300:
            d = 1e-300
        c = b + an / c
        if abs(c) < 1e-300:
            c = 1e-300
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-14:
            break
    return max(0.0, min(1.0, math.exp(-x + a * math.log(x) - math.lgamma(a)) * h))


def _association(scope: str, grain: str, kind: str, feature: str, target: str,
                 pairs: Iterable[tuple[object, object]],
                 trip_id_exclusions: str = "") -> dict[str, object]:
    table: Counter[tuple[object, object]] = Counter()
    for left, right in pairs:
        if left is None or right is None:
            continue
        table[(left, right)] += 1
    n = sum(table.values())
    left_levels = len({pair[0] for pair in table})
    right_levels = len({pair[1] for pair in table})
    if n == 0 or left_levels < 2 or right_levels < 2:
        status = "insufficient-support"
        chi = p = v = None
    elif n < MIN_CELL:
        status = "privacy-limited"
        chi = p = v = None
    else:
        status = "observed"
        chi, p, v = _chi_square(table, n, left_levels, right_levels)
    return {
        "scope": scope, "grain": grain, "analysis": kind, "feature": feature,
        "target": target, "support": count_bucket(n),
        "feature_cardinality": count_bucket(left_levels),
        "target_cardinality": count_bucket(right_levels),
        "cramers_v": "" if v is None else f"{v:.6f}",
        "chi_square_p": "" if p is None else f"{p:.6g}",
        "missing_trip_id_exclusions": trip_id_exclusions,
        "status": status,
    }


def _distinct_trip_pairs(rows: Sequence[dict[str, object]], left_fn, right_fn):
    seen: set[tuple[object, ...]] = set()
    missing_trip_id = 0
    for row in rows:
        trip = (row.get("region"), row.get("role"), row.get("trip_id"))
        left = left_fn(row)
        right = right_fn(row)
        if left is None or right is None:
            continue
        if trip[2] is None:
            missing_trip_id += 1
        elif trip[0] is not None and trip[1] is not None:
            seen.add((*trip, left, right))
    return [(values[-2], values[-1]) for values in seen], count_bucket(missing_trip_id)


def _naive_bayes_fit(rows: Sequence[dict[str, object]], features: Sequence[str], target: str):
    class_counts: Counter[str] = Counter()
    category_counts: dict[str, dict[str, Counter[str]]] = {
        feature: defaultdict(Counter) for feature in features
    }
    observed = 0
    for row in rows:
        y = row["feedback"].get(target)  # type: ignore[union-attr]
        values = [row.get(feature) for feature in features]
        if y is None or any(value is None for value in values):
            continue
        y = str(y)
        class_counts[y] += 1
        observed += 1
        for feature, value in zip(features, values):
            category_counts[feature][y][str(value)] += 1
    vocab = {feature: {value for by_class in category_counts[feature].values() for value in by_class}
             for feature in features}
    return class_counts, category_counts, vocab, observed


def _naive_bayes_predict(row: dict[str, object], features: Sequence[str], model):
    class_counts, category_counts, vocab, observed = model
    if observed == 0:
        return None
    n_classes = len(class_counts)
    best_label = None
    best_score = -math.inf
    for label, class_count in class_counts.items():
        score = math.log(class_count / observed)
        for feature in features:
            value = str(row[feature])
            counts = category_counts[feature][label]
            denominator = class_count + len(vocab[feature]) + 1
            score += math.log((counts.get(value, 0) + 1) / denominator)
        if score > best_score:
            best_label, best_score = label, score
    return best_label


def _feature_sets(row: dict[str, object]) -> dict[str, dict[str, object]]:
    context = dict(row["context"])
    # Explicit unresolved field names never become predictors.
    context.pop("TRAVEL_MISSION", None)
    context.pop("TRAVEL_MISSION_CHECK", None)
    # The raw recorded dates are not predictors; only Issue-listed derived
    # month and elapsed calendar-day values are eligible exploratory features.
    context.pop("TRAVEL_START_YMD", None)
    context.pop("TRAVEL_END_YMD", None)
    context_features: dict[str, object] = {key: value for key, value in context.items()}
    context_features["month"] = row.get("month")
    context_features["elapsed_days"] = row.get("elapsed_days")
    context_features["region"] = row.get("region")
    companion_values = row.get("companion_relations")
    context_features["companion_relation_codes"] = (
        "|".join(companion_values) if companion_values else None
    )
    base_poi = {key: row.get(key) for key in ("region", "visit_area_type", "visit_sgg")}
    rich_poi = {key: row.get(key) for key in ("master_sgg", "poi_l1", "poi_l2", "poi_l3")}
    full = {**context_features, **base_poi, **rich_poi}
    return {
        "popularity_only": {"region": row.get("region"), "popularity_band": row.get("popularity_band")},
        "poi_only": {**base_poi, **rich_poi},
        "context_only": context_features,
        "context_plus_poi": {**context_features, **base_poi},
        "context_plus_richer_poi": full,
    }


def _predictive_rows(region: str, target: str, train: Sequence[dict[str, object]],
                     validation: Sequence[dict[str, object]]) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    ablations = ("popularity_only", "poi_only", "context_only", "context_plus_poi", "context_plus_richer_poi")
    train_sets = [(row, _feature_sets(row)) for row in train]
    val_sets = [(row, _feature_sets(row)) for row in validation]
    for ablation in ablations:
        feature_names = sorted({name for _, feature_sets in train_sets
                                for name in feature_sets[ablation]})
        train_usable = [
            (row, feature_sets[ablation]) for row, feature_sets in train_sets
            if row["feedback"].get(target) is not None  # type: ignore[union-attr]
            and feature_names
            and all(feature_sets[ablation].get(name) is not None for name in feature_names)
        ]
        val_usable = [
            (row, feature_sets[ablation]) for row, feature_sets in val_sets
            if row["feedback"].get(target) is not None  # type: ignore[union-attr]
            and feature_names
            and all(feature_sets[ablation].get(name) is not None for name in feature_names)
        ]
        if not feature_names:
            output.append({"scope": region, "target": target, "ablation": ablation,
                           "train_support": count_bucket(0), "validation_support": count_bucket(0),
                           "accuracy": "", "majority_accuracy": "", "delta_vs_majority": "",
                           "status": "insufficient-support"})
            continue
        train_for_model = [dict(row, **feat) for row, feat in train_usable]
        model = _naive_bayes_fit(train_for_model, feature_names, target)
        eval_pairs = []
        train_events = model[3]
        for row, features in val_usable:
            prediction = _naive_bayes_predict(features, feature_names, model)
            label = row["feedback"].get(target)  # type: ignore[union-attr]
            if prediction is not None and label is not None:
                eval_pairs.append((str(label), prediction))
        val_n = len(eval_pairs)
        majority = max(model[0].values(), default=0) / train_events if train_events else 0.0
        accuracy = sum(actual == pred for actual, pred in eval_pairs) / val_n if val_n else 0.0
        status = (
            "insufficient-support" if train_events == 0 or val_n == 0
            else "privacy-limited" if train_events < MIN_CELL or val_n < MIN_CELL
            else "observed"
        )
        output.append({
            "scope": region, "target": target, "ablation": ablation,
            "train_support": count_bucket(train_events), "validation_support": count_bucket(val_n),
            "accuracy": f"{accuracy:.6f}" if status == "observed" else "suppressed",
            "majority_accuracy": f"{majority:.6f}" if status == "observed" else "suppressed",
            "delta_vs_majority": f"{accuracy - majority:.6f}" if status == "observed" else "suppressed",
            "status": status,
        })
    return output


def _join_specs(raw_root: Path, args) -> tuple[list[InputSpec], dict[str, Path]]:
    if shared.has_symlink_component(args.raw_root) or shared.has_symlink_component(RESULTS_ROOT.absolute()):
        raise ValueError("raw/output path contains a symlink")
    root = Path(os.path.abspath(raw_root)).resolve()
    specs: list[InputSpec] = []
    seen_roles: set[tuple[str, str]] = set()
    seen_roots: set[Path] = set()
    for region, role, requested in args.input:
        if shared.has_symlink_component(requested):
            raise ValueError("input path contains a symlink")
        path = Path(os.path.abspath(requested)).resolve()
        if not path.is_dir() or not shared.within(path, root):
            raise ValueError("input must be an existing role folder under --raw-root")
        valid_layout = path.name == f"{role}_csv" or shared.approved_capital_filekey_root(region, role, path)
        if not valid_layout or (region, role) in seen_roles or path in seen_roots:
            raise ValueError("input roles must be unique, distinct, and role-labeled")
        seen_roles.add((region, role))
        seen_roots.add(path)
        specs.append(InputSpec(region, role, path))
    regions = {region for region, _ in seen_roles}
    if not regions or seen_roles != {(region, role) for region in regions for role in ("TL", "VL")}:
        raise ValueError("each selected region requires exactly one TL and one VL role")
    poi_roots: dict[str, Path] = {}
    for region, requested in args.poi_master:
        if region not in regions or region in poi_roots or shared.has_symlink_component(requested):
            raise ValueError("POI master inputs must be unique for selected regions")
        path = Path(os.path.abspath(requested)).resolve()
        if not shared.within(path, root) or not (path.is_dir() or path.is_file()):
            raise ValueError("POI master input must exist under --raw-root")
        poi_roots[region] = path
    if set(poi_roots) != regions:
        raise ValueError("one POI master input is required for each selected region")
    return specs, poi_roots


def _write_artifacts(output: Path, audit_rows, association_rows, predictive_rows, metadata,
                     overwrite: bool) -> None:
    resolved = output.resolve()
    if output.is_symlink() or shared.has_symlink_component(output.absolute()) or not shared.within(resolved, RESULTS_ROOT.resolve()) or resolved == RESULTS_ROOT.resolve():
        raise ValueError("output must be under results/experiments/context-poi-signal/<run-id>")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", output.name):
        raise ValueError("invalid run-id")
    output.mkdir(parents=True, exist_ok=True)
    targets = [output / name for name in ARTIFACTS]
    if any(path.is_symlink() or (path.exists() and not path.is_file()) for path in targets):
        raise ValueError("unsafe output file")
    if not overwrite and any(path.exists() for path in targets):
        raise ValueError("run already exists; use another run-id")
    stage = output / ".stage"
    if stage.exists() or stage.is_symlink():
        raise ValueError("staging path already exists")
    stage.mkdir(mode=0o700)
    tables = (
        (audit_rows, ("scope", "table", "field", "rows", "nonmissing", "missing_rate", "cardinality", "categories_below_k", "categories_at_least_k", "largest_category_share", "outside_documented_range", "outside_range_cardinality", "candidate_keys", "unique_keys", "duplicate_keys", "master_rows", "nonblank_candidate_keys", "unique_candidate_keys", "duplicate_candidate_keys", "keys_with_multiple_sgg_values", "visit_rows", "visit_candidate_keys", "visit_keys_with_multiple_rows", "visit_nonblank_poi_rows", "matched_visit_rows", "coverage", "status")),
        (association_rows, ("scope", "grain", "analysis", "feature", "target", "support", "feature_cardinality", "target_cardinality", "cramers_v", "chi_square_p", "missing_trip_id_exclusions", "status")),
        (predictive_rows, ("scope", "target", "ablation", "train_support", "validation_support", "accuracy", "majority_accuracy", "delta_vs_majority", "status")),
    )
    try:
        for name, (rows, fields) in zip(ARTIFACTS, tables):
            with (stage / name).open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(rows)
        (stage / ARTIFACTS[-1]).write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        for name in ARTIFACTS:
            os.replace(stage / name, output / name)
    finally:
        for child in stage.iterdir():
            child.unlink()
        stage.rmdir()


def _analyze(specs: Sequence[InputSpec], poi_roots: dict[str, Path], run_id: str):
    started = datetime.now(UTC)
    splits = {(spec.region, spec.role): _load_split(spec, poi_roots.get(spec.region)) for spec in specs}
    regions = sorted({spec.region for spec in specs})
    overlap_by_region = {
        region: splits[(region, "TL")].trip_ids & splits[(region, "VL")].trip_ids
        for region in regions
    }
    if any(overlap_by_region.values()):
        raise ValueError("TL/VL trip overlap detected")
    same_region_overlap = {}
    for region in regions:
        tl = splits[(region, "TL")]
        vl = splits[(region, "VL")]
        traveler_overlap = tl.traveler_ids & vl.traveler_ids
        item_overlap = tl.poi_ids & vl.poi_ids
        same_region_overlap[region] = {
            "traveler_overlap_count": count_bucket(len(traveler_overlap)),
            "traveler_overlap_rate": rate_band(len(traveler_overlap), len(vl.traveler_ids)),
            "candidate_item_overlap_count": count_bucket(len(item_overlap)),
            "candidate_item_overlap_rate": rate_band(len(item_overlap), len(vl.poi_ids)),
            "vl_item_cold_start_rate": rate_band(len(vl.poi_ids - tl.poi_ids), len(vl.poi_ids)),
        }
    tl_rows = [row for region in regions for row in splits[(region, "TL")].observations]
    vl_rows = [row for region in regions for row in splits[(region, "VL")].observations]
    # Popularity is fit from TL only and then attached to both roles. VL counts
    # never update the predictor.
    for region in regions:
        counts = Counter(
            row["poi_id"] for row in splits[(region, "TL")].observations
            if row.get("poi_id") is not None
        )
        for role in ("TL", "VL"):
            for row in splits[(region, role)].observations:
                count = counts.get(row.get("poi_id"), 0)
                row["popularity_band"] = (
                    "1" if count == 1 else "2-4" if count <= 4 else "5-9" if count <= 9 else "10+"
                ) if count else None

    # Region collisions are counted in memory only; IDs are never serialized.
    id_regions: dict[str, set[str]] = defaultdict(set)
    for region in regions:
        for role in ("TL", "VL"):
            for poi in splits[(region, role)].poi_ids:
                id_regions[poi].add(region)
    collision_count = sum(len(values) > 1 for values in id_regions.values())
    audit_rows = [row for spec in specs for row in splits[(spec.region, spec.role)].audit]
    for scope, selected in [(region, [v for v in id_regions.values() if region in v]) for region in regions]:
        audit_rows.append({"scope": scope, "table": "cross-region audit", "field": "POI_ID candidate shared across regions",
                           "rows": "", "nonmissing": count_bucket(sum(len(v) > 1 for v in selected)),
                           "status": "candidate_collision_only"})
    audit_rows.append({"scope": "aggregate", "table": "cross-region audit", "field": "POI_ID candidate shared across regions",
                       "nonmissing": count_bucket(collision_count), "status": "candidate_collision_only"})

    associations: list[dict[str, object]] = []
    context_getters = {
        **{name: (lambda row, field=name: row["context"].get(field)) for name in MASTER_CONTEXT},
        "month_from_TRAVEL_START_YMD": lambda row: row.get("month"),
        "elapsed_calendar_days": lambda row: row.get("elapsed_days"),
        "companion_relation_codes": lambda row: "|".join(row.get("companion_relations", ())) or None,
    }
    demographic_getters = {
        name: (lambda row, field=name: row["demographics"].get(field)) for name in DEMOGRAPHICS
    }
    poi_getters = {
        "VISIT_AREA_TYPE_CD": lambda row: row.get("visit_area_type"),
        "visit_SGG_CD": lambda row: row.get("visit_sgg"),
        "POI_master_ASORT_LCLASDC": lambda row: row.get("poi_l1"),
        "POI_master_ASORT_MLSFCDC": lambda row: row.get("poi_l2"),
        "POI_master_ASORT_SDASDC": lambda row: row.get("poi_l3"),
        "POI_master_SGG_CD": lambda row: row.get("master_sgg"),
    }
    analysis_scopes = [
        (region, {role: splits[(region, role)].observations for role in ("TL", "VL")})
        for region in regions
    ]
    analysis_scopes.append((
        "aggregate",
        {role: [row for region in regions for row in splits[(region, role)].observations]
         for role in ("TL", "VL")},
    ))
    for scope_name, role_rows in analysis_scopes:
        for role, rows in role_rows.items():
            scope = f"{scope_name}:{role}"
            pair_features = {**context_getters, **poi_getters}
            for feature, getter in pair_features.items():
                for poi_feature, poi_getter in poi_getters.items():
                    if feature == poi_feature:
                        continue
                    association = _association(scope, "visit-row", "context_to_poi", feature,
                                               poi_feature, ((getter(r), poi_getter(r)) for r in rows))
                    associations.append(association)
                    trip_pairs, missing_trip_id_exclusions = _distinct_trip_pairs(rows, getter, poi_getter)
                    associations.append(_association(scope, "distinct-trip-pair", "context_to_poi",
                                                     feature, poi_feature, trip_pairs,
                                                     missing_trip_id_exclusions))
            for feature, getter in {**context_getters, **poi_getters}.items():
                for target in TARGETS:
                    associations.append(_association(
                        scope, "visit-row", "feature_to_feedback", feature, target,
                        ((getter(r), r["feedback"].get(target)) for r in rows),  # type: ignore[union-attr]
                    ))
            for feature, getter in demographic_getters.items():
                for poi_feature, poi_getter in poi_getters.items():
                    associations.append(_association(
                        scope, "visit-row", "demographic_to_poi_separate", feature, poi_feature,
                        ((getter(r), poi_getter(r)) for r in rows),
                    ))
                for target in TARGETS:
                    associations.append(_association(
                        scope, "visit-row", "demographic_to_feedback_separate", feature, target,
                        ((getter(r), r["feedback"].get(target)) for r in rows),  # type: ignore[union-attr]
                    ))
            # The joint tuple is descriptive predictive association, not causal interaction.
            for context_name, context_getter in context_getters.items():
                for poi_name, poi_getter in poi_getters.items():
                    joint = lambda row, cg=context_getter, pg=poi_getter: (
                        (cg(row), pg(row)) if cg(row) is not None and pg(row) is not None else None
                    )
                    for target in TARGETS:
                        associations.append(_association(
                            scope, "visit-row", "joint_context_poi_to_feedback",
                            f"{context_name} × {poi_name}", target,
                            ((joint(r), r["feedback"].get(target)) for r in rows),  # type: ignore[union-attr]
                        ))
            # Dominant-signal comparisons are kept as separate descriptors.
            region_getter = lambda row: row.get("region")
            popularity_getter = lambda row: row.get("popularity_band")
            for signal, getter in (
                ("region", region_getter),
                ("TL_POI_popularity_band", popularity_getter),
                ("POI_master_ASORT_LCLASDC", lambda row: row.get("poi_l1")),
                ("VISIT_AREA_TYPE_CD", lambda row: row.get("visit_area_type")),
            ):
                for target in TARGETS:
                    associations.append(_association(
                        scope, "visit-row", "dominant_signal_to_feedback", signal, target,
                        ((getter(r), r["feedback"].get(target)) for r in rows),  # type: ignore[union-attr]
                    ))

    predictive: list[dict[str, object]] = []
    for region in regions:
        train = splits[(region, "TL")].observations
        validation = splits[(region, "VL")].observations
        # The Issue defines TL discovery and VL replication; no randomized row split is introduced.
        for target in TARGETS:
            predictive.extend(_predictive_rows(region, target, train, validation))
    # Aggregate scope uses the same region-scoped keys and only adds summary rows.
    for target in TARGETS:
        predictive.extend(_predictive_rows("aggregate", target, tl_rows, vl_rows))

    script_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    metadata = {
        "dataset": {"name": "AI Hub Domestic Travel Log", "version": "2023"},
        "input_roles": [{"region": region, "role": role} for region in regions for role in ("TL", "VL")],
        "code_revision": shared._git_revision(),
        "code_worktree_dirty": shared._git_dirty(),
        "script_sha256": script_hash,
        "run_id": run_id,
        "started_utc": started.isoformat(timespec="seconds"),
        "finished_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "protocol": {
            "discovery": "TL", "replication": "VL", "random_resplit": False,
            "trip_id_overlap_check": {
                "status": "passed", "count_policy": "0/<10/10+",
                "per_region": {region: count_bucket(len(values)) for region, values in overlap_by_region.items()},
            },
            "tl_vl_overlap_diagnostics": {
                "count_policy": "0/<10/10+",
                "rate_policy": "coarse bands; small numerators and denominators suppressed",
                "per_region": same_region_overlap,
            },
            "primary_association": "Cramer's V and chi-square; exact source strings treated as opaque categories",
            "feedback_targets": list(TARGETS), "feedback_targets_are_separate": True,
            "demographics": "analyzed separately; excluded from the primary context feature ablations",
            "poi_join": "exact region-scoped POI_ID candidate; join quality audited; no canonical identity claim",
            "missing_feature_values": "reported; no imputation; associations use observed pairs; each predictive ablation uses its own complete-observed feature and target rows",
            "popularity_feature": "TL observed region-scoped POI_ID visit-count bands; ID not used as a predictor",
            "predictive_model": "categorical naive Bayes; Laplace alpha=1; no tuning; feedback codes treated nominally",
            "seed": None,
            "ranking": "not evaluated; unvisited candidates are not negatives",
            "grain": "visit-row plus deduplicated trip-feature-pair association; feedback has no invented trip aggregation",
            "season": "not derived; season cut points unresolved",
            "duration": "elapsed calendar-day difference (end minus start); no inclusive-day interpretation",
        },
        "privacy": {
            "raw_paths_written": False, "raw_identifiers_written": False,
            "raw_category_values_written": False, "coordinates_or_free_text_written": False,
            "row_level_outputs": False, "minimum_cell_size": MIN_CELL,
            "counts": "0/<10/10+ buckets", "rates": "coarse bands; small numerators suppressed",
            "small_support_effects": "not emitted below k=10; status distinguishes privacy-limited from insufficient-support",
        },
        "policy": {"source_data_immutable": True, "external_transfer": False,
                    "test_metrics": "not generated"},
    }
    return audit_rows, associations, predictive, metadata


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run privacy-safe context × POI feasibility analysis on approved TL/VL inputs.")
    parser.add_argument("--raw-root", type=Path, default=shared.RAW_ROOT)
    parser.add_argument("--input", action="append", required=True, type=shared.parse_input_spec, metavar="REGION:TL|VL=PATH")
    parser.add_argument("--poi-master", action="append", default=[], type=parse_poi_spec, metavar="REGION=PATH")
    parser.add_argument("--run-id", default=datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"))
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--allow-approved-capital-filekey-folders", action="store_true")
    parser.add_argument("--confirm-approved", action="store_true")
    parser.add_argument("--confirm-terms", action="store_true")
    parser.add_argument("--confirm-poi-candidate", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not (args.confirm_approved and args.confirm_terms and args.confirm_poi_candidate):
        print("[중단] 승인, 이용 조건, POI_ID 후보 확인 옵션이 필요합니다.", file=sys.stderr)
        return 2
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", args.run_id):
        print("[중단] run-id 형식을 확인하세요.", file=sys.stderr)
        return 2
    try:
        specs, poi_roots = _join_specs(args.raw_root, args)
        audit, associations, predictive, metadata = _analyze(specs, poi_roots, args.run_id)
        output = RESULTS_ROOT / args.run_id
        _write_artifacts(output, audit, associations, predictive, metadata, args.overwrite)
    except (OSError, UnicodeError, csv.Error, ValueError) as exc:
        print(f"[중단] context × POI 분석 실패: {type(exc).__name__}", file=sys.stderr)
        return 2
    print(f"완료: results/experiments/context-poi-signal/{args.run_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
