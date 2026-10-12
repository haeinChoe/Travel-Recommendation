"""Run the Issue #45 context/POI feasibility experiment.

The executable is intentionally limited to observed visit associations and
separate post-visit feedback prediction. A visit-only file has no valid
negative examples, so this script never invents unobserved visits as negatives.
Raw identifiers are kept in memory only for joins and popularity aggregation.
"""

from __future__ import annotations

import argparse
import codecs
import csv
import hashlib
import json
import math
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable

import evaluate_popularity as shared

REPO_ROOT = shared.REPO_ROOT
RESULTS_ROOT = REPO_ROOT / "results" / "experiments" / "context-poi-signal"
REGIONS = shared.REGIONS
ROLES = ("TL", "VL")
FEEDBACK_FIELDS = ("DGSTFN", "REVISIT_INTENTION", "RCMDTN_INTENTION")
TABLES = shared.TABLES
K = 10
ARTIFACTS = (
    "associations.csv",
    "context_poi_distributions.csv",
    "column_availability.csv",
    "feedback_distributions.csv",
    "feedback_cross_distributions.csv",
    "feedback_context_poi_distributions.csv",
    "feedback_associations.csv",
    "feedback_ablations.csv",
    "run_metadata.json",
)
MISSING = "<missing>"
REQUIRED_COLUMNS = {
    "TN_TRAVEL": {"TRAVEL_ID"},
    "TN_VISIT_AREA_INFO": {"TRAVEL_ID"},
}
OPTIONAL_COLUMNS = {
    "TN_TRAVEL": {"TRAVEL_MISSION", "TRAVEL_START_YMD"},
    "TN_VISIT_AREA_INFO": {
        "POI_ID",
        "SGG_CD",
        "VISIT_AREA_TYPE_CD",
        *FEEDBACK_FIELDS,
    },
}
DEFAULT_SYNTHETIC_COLUMNS = frozenset(
    column for columns in OPTIONAL_COLUMNS.values() for column in columns
)


@dataclass
class Source:
    region: str
    role: str
    root: Path
    travel_files: tuple[Path, ...]
    visit_files: tuple[Path, ...]
    availability: dict[str, dict[str, str]] | None = None


@dataclass(frozen=True)
class Visit:
    region: str
    role: str
    context: tuple[str, ...]
    poi_features: tuple[str, ...]
    popularity: str
    feedback: dict[str, str | None]
    available_columns: frozenset[str] = DEFAULT_SYNTHETIC_COLUMNS


class SafeInputError(ValueError):
    """An input contract failure with a path- and identifier-free message."""


def _table_role(path: Path) -> str | None:
    stem = path.stem.upper()
    return next(
        (kind for name, kind in TABLES.items() if stem == name or stem.startswith(name + "_")),
        None,
    )


def resolve_sources(
    specs: list[tuple[str, str, Path]],
    raw_root: Path,
    allow_approved_capital_filekey_folders: bool = False,
) -> list[Source]:
    if shared.has_symlink_component(raw_root):
        raise ValueError("raw root contains a symlink")
    root = Path(os.path.abspath(raw_root)).resolve()
    resolved: set[Path] = set()
    sources: list[Source] = []
    seen: set[tuple[str, str]] = set()
    for region, role, requested in specs:
        key = (region, role)
        if key in seen:
            raise ValueError("duplicate region/source-role input")
        seen.add(key)
        if shared.has_symlink_component(requested):
            raise ValueError("input path contains a symlink")
        path = Path(os.path.abspath(requested)).resolve()
        if not path.is_dir() or not shared.within(path, root):
            raise ValueError("TL/VL inputs must be existing folders below --raw-root")
        role_folder = path.name == f"{role}_csv"
        approved_capital_folder = (
            allow_approved_capital_filekey_folders
            and shared.approved_capital_filekey_root(region, role, path)
        )
        if not (role_folder or approved_capital_folder):
            raise ValueError("input folder does not match the TL/VL role-folder contract")
        if path in resolved:
            raise ValueError("different source roles cannot use the same folder")
        resolved.add(path)
        files = shared.csv_files(path)
        travel = tuple(item for item in files if _table_role(item) == "travel")
        visits = tuple(item for item in files if _table_role(item) == "visits")
        if not travel or not visits:
            raise ValueError("each source role must include TN_TRAVEL and TN_VISIT_AREA_INFO CSVs")
        sources.append(Source(region, role, path, travel, visits))
    expected = {(region, role) for region in REGIONS for role in ROLES}
    if seen != expected:
        raise ValueError("exactly one TL and one VL source is required for every region")
    return sorted(sources, key=lambda source: (source.region, source.role))


def _encoding(path: Path) -> str:
    with path.open("rb") as stream:
        prefix = stream.read(4)
    if prefix.startswith(codecs.BOM_UTF8):
        return "utf-8-sig"
    if prefix.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return "utf-16"
    return "utf-8"


def _read_rows(files: Iterable[Path], selected: set[str]) -> Iterable[dict[str, str | None]]:
    for path in files:
        try:
            with path.open("r", encoding=_encoding(path), newline="") as stream:
                reader = csv.DictReader(stream)
                if reader.fieldnames is None:
                    raise ValueError("CSV header missing")
                headers: dict[str, str] = {}
                for name in reader.fieldnames:
                    if name is None:
                        continue
                    key = name.strip().casefold()
                    if key in headers:
                        raise ValueError("duplicate CSV header")
                    headers[key] = name
                for row in reader:
                    yield {
                        requested: row.get(headers[requested.casefold()])
                        if requested.casefold() in headers
                        else None
                        for requested in selected
                    }
        except (OSError, UnicodeError, csv.Error) as exc:
            raise ValueError("CSV input could not be read safely") from exc


def _headers(path: Path) -> set[str]:
    try:
        with path.open("r", encoding=_encoding(path), newline="") as stream:
            reader = csv.reader(stream)
            row = next(reader, None)
            if row is None:
                raise SafeInputError("required table header is missing")
            normalized = [name.strip().casefold() for name in row]
            if len(normalized) != len(set(normalized)):
                raise SafeInputError("table has duplicate column headers")
            return set(normalized)
    except SafeInputError:
        raise
    except (OSError, UnicodeError, csv.Error) as exc:
        raise SafeInputError("table header could not be read safely") from exc


def validate_headers(sources: list[Source]) -> list[dict[str, str]]:
    """Validate mandatory headers before reading data rows; summarize optional fields."""
    statuses: list[dict[str, str]] = []
    for source in sources:
        source_availability: dict[str, dict[str, str]] = {}
        for table_name, files in (
            ("TN_TRAVEL", source.travel_files),
            ("TN_VISIT_AREA_INFO", source.visit_files),
        ):
            if not files:
                raise SafeInputError("required source table is missing")
            header_sets = [_headers(path) for path in files]
            required = REQUIRED_COLUMNS[table_name]
            required_normalized = {column.casefold() for column in required}
            if any(not required_normalized.issubset(headers) for headers in header_sets):
                raise SafeInputError("required ID or join column header is missing")
            optional = OPTIONAL_COLUMNS.get(table_name, set())
            for column in sorted(required | optional):
                present = [column.casefold() in headers for headers in header_sets]
                if column in required:
                    status = "required_available"
                elif all(present):
                    status = "available"
                elif any(present):
                    status = "partial"
                else:
                    status = "missing"
                source_availability.setdefault(table_name, {})[column] = status
                if column in optional:
                    statuses.append({
                        "region": source.region,
                        "source_role": source.role,
                        "table": table_name,
                        "column": column,
                        "status": status,
                    })
        source.availability = source_availability
    return statuses


def _read_trip_ids(source: Source) -> set[str]:
    return {
        trip_id
        for row in _read_rows(source.travel_files, {"TRAVEL_ID"})
        if (trip_id := _cell(row, "TRAVEL_ID")) is not None
    }


def _privacy_count_bucket(value: int) -> str:
    return "<10" if value < K else "10+"


def validate_trip_overlap(sources: list[Source]) -> None:
    by_key = {(source.region, source.role): source for source in sources}
    for region in REGIONS:
        overlap = _read_trip_ids(by_key[(region, "TL")]) & _read_trip_ids(
            by_key[(region, "VL")]
        )
        if overlap:
            raise SafeInputError(
                "TL/VL TRAVEL_ID overlap in region "
                f"{region}; privacy-safe count bucket={_privacy_count_bucket(len(overlap))}"
            )


def validate_join_quality(sources: list[Source]) -> None:
    """Fail before analysis if trip context cannot be joined unambiguously to visits."""
    for source in sources:
        available = (source.availability or {}).get("TN_TRAVEL", {})
        context_columns = [
            column for column in ("TRAVEL_MISSION", "TRAVEL_START_YMD")
            if available.get(column) == "available"
        ]
        contexts: dict[str, tuple[str | None, ...]] = {}
        ambiguous: set[str] = set()
        missing_trip_ids = 0
        missing_trip_contexts: set[str] = set()
        for row in _read_rows(source.travel_files, {"TRAVEL_ID", *context_columns}):
            trip_id = _cell(row, "TRAVEL_ID")
            if trip_id is None:
                missing_trip_ids += 1
                continue
            values = tuple(_cell(row, column) for column in context_columns)
            if any(value is None for value in values):
                missing_trip_contexts.add(trip_id)
            if trip_id in ambiguous:
                continue
            previous = contexts.get(trip_id)
            if previous is not None and previous != values:
                contexts.pop(trip_id, None)
                ambiguous.add(trip_id)
            else:
                contexts[trip_id] = values
        unjoinable_visits = 0
        for row in _read_rows(source.visit_files, {"TRAVEL_ID"}):
            trip_id = _cell(row, "TRAVEL_ID")
            if trip_id is None or trip_id not in contexts or trip_id in ambiguous:
                unjoinable_visits += 1
        if missing_trip_ids or missing_trip_contexts or ambiguous or unjoinable_visits:
            raise SafeInputError(
                f"trip/visit join quality failed for region {source.region} {source.role}; "
                f"missing_trip_ids={_privacy_count_bucket(missing_trip_ids)}; "
                f"missing_trip_contexts={_privacy_count_bucket(len(missing_trip_contexts))}; "
                f"ambiguous_trip_contexts={_privacy_count_bucket(len(ambiguous))}; "
                f"unjoinable_visits={_privacy_count_bucket(unjoinable_visits)}"
            )


def _cell(row: dict[str, str | None], name: str) -> str | None:
    value = row.get(name)
    return value.strip() if value is not None and value.strip() else None


def _context_value(value: str | None) -> str:
    return value if value is not None else MISSING


def _month(value: str | None) -> str:
    if value is None:
        return MISSING
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return "<invalid_date>"
    return f"month_{parsed.month:02d}"


def _popularity_bucket(count: int) -> str:
    if count <= 0:
        return "0"
    if count <= 1:
        return "1"
    if count <= 4:
        return "2-4"
    if count <= 9:
        return "5-9"
    if count <= 49:
        return "10-49"
    return "50+"


def collect_events(sources: list[Source]) -> dict[tuple[str, str], list[Visit]]:
    """Load only documented candidate fields; IDs are memory-only join keys."""
    if any(source.availability is None for source in sources):
        validate_headers(sources)
    validate_trip_overlap(sources)
    validate_join_quality(sources)
    travel_cols = {"TRAVEL_ID", "TRAVEL_MISSION", "TRAVEL_START_YMD"}
    visit_cols = {
        "TRAVEL_ID", "POI_ID", "VISIT_AREA_TYPE_CD", "SGG_CD",
        *FEEDBACK_FIELDS,
    }
    trips: dict[tuple[str, str], dict[str, tuple[str, str]]] = {}
    tl_counts: Counter[tuple[str, str]] = Counter()
    tl_trip_counts: Counter[tuple[str, str, str]] = Counter()
    for source in sources:
        key = (source.region, source.role)
        trip_context: dict[str, tuple[str, str]] = {}
        ambiguous_trips: set[str] = set()
        for row in _read_rows(source.travel_files, travel_cols):
            trip_id = _cell(row, "TRAVEL_ID")
            if trip_id is None:
                continue
            # Keep only unambiguous trip-context mappings. No ID is a feature.
            value = (
                _context_value(_cell(row, "TRAVEL_MISSION")),
                _month(_cell(row, "TRAVEL_START_YMD")),
            )
            if trip_id in ambiguous_trips:
                continue
            if trip_id in trip_context and trip_context[trip_id] != value:
                trip_context.pop(trip_id, None)
                ambiguous_trips.add(trip_id)
                continue
            trip_context[trip_id] = value
        trips[key] = trip_context
        # First pass derives split-local popularity counts. Re-reading visits
        # avoids retaining raw visit rows after the count is computed.
        for row in _read_rows(source.visit_files, visit_cols):
            poi_id = _cell(row, "POI_ID")
            trip_id = _cell(row, "TRAVEL_ID")
            if source.role == "TL" and poi_id is not None:
                tl_counts[(source.region, poi_id)] += 1
                if trip_id is not None:
                    tl_trip_counts[(source.region, trip_id, poi_id)] += 1

    events: dict[tuple[str, str], list[Visit]] = {}
    for source in sources:
        key = (source.region, source.role)
        visits: list[Visit] = []
        for row in _read_rows(source.visit_files, visit_cols):
            trip_id = _cell(row, "TRAVEL_ID")
            trip_context = trips[key].get(trip_id or "")
            if trip_context is None:
                continue
            poi_id = _cell(row, "POI_ID")
            pop_count = tl_counts.get((source.region, poi_id), 0) if poi_id else 0
            if source.role == "TL" and poi_id is not None and trip_id is not None:
                # Popularity is a training-source feature; exclude this trip's
                # visits so its own observed event cannot create its feature.
                pop_count = max(0, pop_count - tl_trip_counts[(source.region, trip_id, poi_id)])
            popularity = _popularity_bucket(pop_count) if poi_id is not None else MISSING
            visits.append(
                Visit(
                    source.region,
                    source.role,
                    trip_context,
                    (
                        source.region,
                        _context_value(_cell(row, "SGG_CD")),
                        _context_value(_cell(row, "VISIT_AREA_TYPE_CD")),
                    ),
                    popularity,
                    {field: _cell(row, field) for field in FEEDBACK_FIELDS},
                    frozenset(
                        column
                        for table_status in (source.availability or {}).values()
                        for column, status in table_status.items()
                        if status == "available"
                    ),
                )
            )
        events[key] = visits
    return events


def _regularized_gamma_q(a: float, x: float) -> float:
    """Regularized upper incomplete gamma, for chi-square survival p-values."""
    if a <= 0 or x < 0:
        raise ValueError("invalid gamma arguments")
    if x == 0:
        return 1.0
    log_factor = -x + a * math.log(x) - math.lgamma(a)
    if x < a + 1:
        term = total = 1.0 / a
        ap = a
        for _ in range(10000):
            ap += 1
            term *= x / ap
            total += term
            if abs(term) <= abs(total) * 1e-14:
                break
        p = total * math.exp(log_factor)
        return min(1.0, max(0.0, 1.0 - p))
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
        if abs(delta - 1.0) <= 1e-14:
            break
    return min(1.0, max(0.0, math.exp(log_factor) * h))


def chi_square_effect(rows: list[tuple[str, str]]) -> dict[str, float | int | str]:
    table: dict[str, Counter[str]] = defaultdict(Counter)
    cols: Counter[str] = Counter()
    for left, right in rows:
        table[left][right] += 1
        cols[right] += 1
    n = len(rows)
    row_totals = {key: sum(counts.values()) for key, counts in table.items()}
    r, c = len(row_totals), len(cols)
    if n < K or r < 2 or c < 2:
        return {
            "status": "insufficient_support",
            "n": n,
            "cramers_v": math.nan,
            "p_value": math.nan,
        }
    if any(0 < count < K for counts in table.values() for count in counts.values()):
        return {"status": "suppressed_k10", "n": n, "cramers_v": math.nan, "p_value": math.nan}
    statistic = 0.0
    min_expected = math.inf
    for left, row_total in row_totals.items():
        for right, col_total in cols.items():
            expected = row_total * col_total / n
            min_expected = min(min_expected, expected)
            observed = table[left][right]
            if expected:
                statistic += (observed - expected) ** 2 / expected
    if min_expected < 5:
        return {
            "status": "sparse_expected_cells",
            "n": n,
            "cramers_v": math.nan,
            "p_value": math.nan,
        }
    df = (r - 1) * (c - 1)
    p_value = _regularized_gamma_q(df / 2.0, statistic / 2.0)
    v = math.sqrt(statistic / (n * min(r - 1, c - 1)))
    return {"status": "observed", "n": n, "cramers_v": v, "p_value": p_value}


def association_rows(events: dict[tuple[str, str], list[Visit]]) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    scopes = [(region, role, visits) for (region, role), visits in sorted(events.items())]
    for role in ROLES:
        pooled = [
            visit
            for (_region, source_role), rows in events.items()
            if source_role == role
            for visit in rows
        ]
        scopes.append(("all-regions", role, pooled))
    for region, role, visits in scopes:
        for context_index, context_name in enumerate(("TRAVEL_MISSION", "TRAVEL_START_MONTH")):
            for poi_index, poi_name in ((0, "region"), (1, "SGG_CD"), (2, "VISIT_AREA_TYPE_CD")):
                bands = [
                    "all",
                    *sorted({visit.popularity for visit in visits if visit.popularity != MISSING}),
                ]
                for band in bands:
                    cohort = (
                        visits
                        if band == "all"
                        else [visit for visit in visits if visit.popularity == band]
                    )
                    unavailable = not _feature_available(cohort, context_name) or not (
                        _feature_available(cohort, poi_name)
                    )
                    result = ({
                        "status": "unavailable_missing_column",
                        "n": len(cohort),
                        "cramers_v": math.nan,
                        "p_value": math.nan,
                    } if unavailable else chi_square_effect(
                        [
                            (visit.context[context_index], visit.poi_features[poi_index])
                            for visit in cohort
                        ]
                    ))
                    output.append(
                        {
                            "region": region,
                            "source_role": role,
                            "context_feature": context_name,
                            "poi_feature": poi_name,
                            "popularity_band": band,
                            "status": result["status"],
                            "support": _support_bucket(int(result["n"])),
                            "cramers_v": _number(result["cramers_v"]),
                            "p_value_descriptive": _number(result["p_value"]),
                        }
                    )
    return output


def context_poi_distributions(
    events: dict[tuple[str, str], list[Visit]],
) -> list[dict[str, object]]:
    """Write only k-safe contingency supports with opaque category labels."""
    output: list[dict[str, object]] = []
    scopes = [(region, role, visits) for (region, role), visits in sorted(events.items())]
    for role in ROLES:
        pooled = [
            visit
            for (_region, source_role), rows in events.items()
            if source_role == role
            for visit in rows
        ]
        scopes.append(("all-regions", role, pooled))
    for region, role, visits in scopes:
        for context_index, context_name in enumerate(("TRAVEL_MISSION", "TRAVEL_START_MONTH")):
            for poi_index, poi_name in ((0, "region"), (1, "SGG_CD"), (2, "VISIT_AREA_TYPE_CD")):
                context_labels = {
                    value: f"context_{index + 1}"
                    for index, value in enumerate(
                        sorted({visit.context[context_index] for visit in visits})
                    )
                }
                poi_labels = {
                    value: f"poi_{index + 1}"
                    for index, value in enumerate(
                        sorted({visit.poi_features[poi_index] for visit in visits})
                    )
                }
                for band in [
                    "all",
                    *sorted({visit.popularity for visit in visits if visit.popularity != MISSING}),
                ]:
                    cohort = (
                        visits
                        if band == "all"
                        else [visit for visit in visits if visit.popularity == band]
                    )
                    counts = Counter(
                        (visit.context[context_index], visit.poi_features[poi_index])
                        for visit in cohort
                    )
                    if (
                        not _feature_available(cohort, context_name)
                        or not _feature_available(cohort, poi_name)
                    ):
                        output.append({
                            "region": region, "source_role": role,
                            "context_feature": context_name, "poi_feature": poi_name,
                            "popularity_band": band, "context_category": "",
                            "poi_category": "", "support": "",
                            "status": "unavailable_missing_column",
                        })
                        continue
                    small = any(0 < count < K for count in counts.values())
                    if small or not counts:
                        output.append(
                            {
                                "region": region,
                                "source_role": role,
                                "context_feature": context_name,
                                "poi_feature": poi_name,
                                "popularity_band": band,
                                "context_category": "",
                                "poi_category": "",
                                "support": _support_bucket(sum(counts.values())),
                                "status": "suppressed_k10" if small else "insufficient_support",
                            }
                        )
                        continue
                    for (context_value, poi_value), count in sorted(counts.items()):
                        output.append(
                            {
                                "region": region,
                                "source_role": role,
                                "context_feature": context_name,
                                "poi_feature": poi_name,
                                "popularity_band": band,
                                "context_category": context_labels[context_value],
                                "poi_category": poi_labels[poi_value],
                                "support": _support_bucket(count),
                                "status": "observed",
                            }
                        )
    return output


def feedback_diagnostics(
    events: dict[tuple[str, str], list[Visit]],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    distributions: list[dict[str, object]] = []
    associations: list[dict[str, object]] = []
    scopes = [(region, role, visits) for (region, role), visits in sorted(events.items())]
    for role in ROLES:
        pooled = [
            visit
            for (_region, source_role), rows in events.items()
            if source_role == role
            for visit in rows
        ]
        scopes.append(("all-regions", role, pooled))
    for region, role, visits in scopes:
        for outcome in FEEDBACK_FIELDS:
            outcome_available = all(
                outcome in visit.available_columns for visit in visits
            )
            if not outcome_available:
                distributions.append({
                    "region": region, "source_role": role, "outcome": outcome,
                    "category": "", "support": "", "status": "unavailable_missing_column",
                })
                for feature_name, _get_feature in (
                    ("TRAVEL_MISSION", lambda visit: visit.context[0]),
                    ("TRAVEL_START_MONTH", lambda visit: visit.context[1]),
                    ("region", lambda visit: visit.poi_features[0]),
                    ("SGG_CD", lambda visit: visit.poi_features[1]),
                    ("VISIT_AREA_TYPE_CD", lambda visit: visit.poi_features[2]),
                ):
                    associations.append({
                        "region": region, "source_role": role, "outcome": outcome,
                        "feature": feature_name, "popularity_band": "all",
                        "status": "unavailable_missing_column", "support": "",
                        "cramers_v": "", "p_value_descriptive": "",
                    })
                continue
            values = [visit.feedback[outcome] for visit in visits]
            categories = Counter(
                "<missing>"
                if value is None
                else (
                    f"code_{value}"
                    if value in {"1", "2", "3", "4", "5"}
                    else "<outside_1_to_5>"
                )
                for value in values
            )
            small_support = sum(count for count in categories.values() if count < K)
            for category, count in sorted(categories.items()):
                if count < K:
                    continue
                distributions.append(
                    {
                        "region": region,
                        "source_role": role,
                        "outcome": outcome,
                        "category": category,
                        "support": _support_bucket(count),
                        "status": "observed",
                    }
                )
            if small_support:
                distributions.append(
                    {
                        "region": region,
                        "source_role": role,
                        "outcome": outcome,
                        "category": "<suppressed>",
                        "support": _support_bucket(small_support),
                        "status": "suppressed_k10",
                    }
                )
            valid = [
                visit
                for visit in visits
                if visit.feedback[outcome] in {"1", "2", "3", "4", "5"}
            ]
            features = (
                ("TRAVEL_MISSION", lambda visit: visit.context[0]),
                ("TRAVEL_START_MONTH", lambda visit: visit.context[1]),
                ("region", lambda visit: visit.poi_features[0]),
                ("SGG_CD", lambda visit: visit.poi_features[1]),
                ("VISIT_AREA_TYPE_CD", lambda visit: visit.poi_features[2]),
            )
            for feature_name, get_feature in features:
                bands = [
                    "all",
                    *sorted({visit.popularity for visit in valid if visit.popularity != MISSING}),
                ]
                for band in bands:
                    cohort = (
                        valid
                        if band == "all"
                        else [visit for visit in valid if visit.popularity == band]
                    )
                    if not _feature_available(cohort, feature_name):
                        associations.append({
                            "region": region, "source_role": role, "outcome": outcome,
                            "feature": feature_name, "popularity_band": band,
                            "status": "unavailable_missing_column", "support": "",
                            "cramers_v": "", "p_value_descriptive": "",
                        })
                        continue
                    result = chi_square_effect(
                        [
                            (get_feature(visit), str(visit.feedback[outcome]))
                            for visit in cohort
                        ]
                    )
                    associations.append(
                        {
                            "region": region,
                            "source_role": role,
                            "outcome": outcome,
                            "feature": feature_name,
                            "popularity_band": band,
                            "status": result["status"],
                            "support": _support_bucket(int(result["n"])),
                            "cramers_v": _number(result["cramers_v"]),
                            "p_value_descriptive": _number(result["p_value"]),
                        }
                    )
    return distributions, associations


def feedback_cross_distributions(
    events: dict[tuple[str, str], list[Visit]],
) -> list[dict[str, object]]:
    """Summarize feedback categories by each context/POI feature with k suppression."""
    output: list[dict[str, object]] = []
    scopes = [(region, role, visits) for (region, role), visits in sorted(events.items())]
    for role in ROLES:
        pooled = [
            visit
            for (_region, source_role), rows in events.items()
            if source_role == role
            for visit in rows
        ]
        scopes.append(("all-regions", role, pooled))
    features = (
        ("TRAVEL_MISSION", lambda visit: visit.context[0]),
        ("TRAVEL_START_MONTH", lambda visit: visit.context[1]),
        ("region", lambda visit: visit.poi_features[0]),
        ("SGG_CD", lambda visit: visit.poi_features[1]),
        ("VISIT_AREA_TYPE_CD", lambda visit: visit.poi_features[2]),
    )
    for region, role, visits in scopes:
        for outcome in FEEDBACK_FIELDS:
            if any(outcome not in visit.available_columns for visit in visits):
                output.append({
                    "region": region, "source_role": role, "outcome": outcome,
                    "feature": "all", "popularity_band": "all",
                    "feature_category": "", "outcome_category": "", "support": "",
                    "status": "unavailable_missing_column",
                })
                continue
            outcome_labels = {
                category: f"outcome_{index + 1}"
                for index, category in enumerate(
                    sorted(
                        {
                            _feedback_category(visit.feedback[outcome])
                            for visit in visits
                        }
                    )
                )
            }
            for feature_name, get_feature in features:
                feature_labels = {
                    category: f"feature_{index + 1}"
                    for index, category in enumerate(
                        sorted({get_feature(visit) for visit in visits})
                    )
                }
                for band in [
                    "all",
                    *sorted({visit.popularity for visit in visits if visit.popularity != MISSING}),
                ]:
                    cohort = (
                        visits
                        if band == "all"
                        else [visit for visit in visits if visit.popularity == band]
                    )
                    if not _feature_available(cohort, feature_name):
                        output.append({
                            "region": region, "source_role": role, "outcome": outcome,
                            "feature": feature_name, "popularity_band": band,
                            "feature_category": "", "outcome_category": "",
                            "support": "", "status": "unavailable_missing_column",
                        })
                        continue
                    counts = Counter(
                        (get_feature(visit), _feedback_category(visit.feedback[outcome]))
                        for visit in cohort
                    )
                    small = any(0 < count < K for count in counts.values())
                    if small or not counts:
                        output.append(
                            {
                                "region": region,
                                "source_role": role,
                                "outcome": outcome,
                                "feature": feature_name,
                                "popularity_band": band,
                                "feature_category": "",
                                "outcome_category": "",
                                "support": _support_bucket(sum(counts.values())),
                                "status": "suppressed_k10" if small else "insufficient_support",
                            }
                        )
                        continue
                    for (feature_value, outcome_value), count in sorted(counts.items()):
                        output.append(
                            {
                                "region": region,
                                "source_role": role,
                                "outcome": outcome,
                                "feature": feature_name,
                                "popularity_band": band,
                                "feature_category": feature_labels[feature_value],
                                "outcome_category": outcome_labels[outcome_value],
                                "support": _support_bucket(count),
                                "status": "observed",
                            }
                        )
    return output


def feedback_context_poi_distributions(
    events: dict[tuple[str, str], list[Visit]],
) -> list[dict[str, object]]:
    """Summarize joint context × POI × feedback cells with whole-table k suppression."""
    output: list[dict[str, object]] = []
    scopes = [(region, role, visits) for (region, role), visits in sorted(events.items())]
    for role in ROLES:
        pooled = [
            visit
            for (_region, source_role), rows in events.items()
            if source_role == role
            for visit in rows
        ]
        scopes.append(("all-regions", role, pooled))
    contexts = (
        ("TRAVEL_MISSION", 0),
        ("TRAVEL_START_MONTH", 1),
    )
    pois = (
        ("region", 0),
        ("SGG_CD", 1),
        ("VISIT_AREA_TYPE_CD", 2),
    )
    for region, role, visits in scopes:
        for outcome in FEEDBACK_FIELDS:
            for context_name, context_index in contexts:
                for poi_name, poi_index in pois:
                    base = {
                        "region": region,
                        "source_role": role,
                        "outcome": outcome,
                        "context_feature": context_name,
                        "poi_feature": poi_name,
                    }
                    if (
                        not all(outcome in visit.available_columns for visit in visits)
                        or not _feature_available(visits, context_name)
                        or not _feature_available(visits, poi_name)
                    ):
                        output.append({
                            **base,
                            "context_category": "",
                            "poi_category": "",
                            "outcome_category": "",
                            "support": "",
                            "status": "unavailable_missing_column",
                        })
                        continue
                    counts = Counter(
                        (
                            visit.context[context_index],
                            visit.poi_features[poi_index],
                            _feedback_category(visit.feedback[outcome]),
                        )
                        for visit in visits
                    )
                    if not counts:
                        output.append({
                            **base,
                            "context_category": "",
                            "poi_category": "",
                            "outcome_category": "",
                            "support": "0",
                            "status": "insufficient_support",
                        })
                        continue
                    if any(count < K for count in counts.values()):
                        output.append({
                            **base,
                            "context_category": "",
                            "poi_category": "",
                            "outcome_category": "",
                            "support": _support_bucket(sum(counts.values())),
                            "status": "suppressed_k10",
                        })
                        continue
                    context_labels = {
                        value: f"context_{index + 1}"
                        for index, value in enumerate(sorted({cell[0] for cell in counts}))
                    }
                    poi_labels = {
                        value: f"poi_{index + 1}"
                        for index, value in enumerate(sorted({cell[1] for cell in counts}))
                    }
                    outcome_labels = {
                        value: f"outcome_{index + 1}"
                        for index, value in enumerate(sorted({cell[2] for cell in counts}))
                    }
                    for (context_value, poi_value, outcome_value), count in sorted(counts.items()):
                        output.append({
                            **base,
                            "context_category": context_labels[context_value],
                            "poi_category": poi_labels[poi_value],
                            "outcome_category": outcome_labels[outcome_value],
                            "support": _support_bucket(count),
                            "status": "observed",
                        })
    return output


def _feedback_category(value: str | None) -> str:
    if value is None:
        return "<missing>"
    if value in {"1", "2", "3", "4", "5"}:
        return f"code_{value}"
    return "<outside_1_to_5>"


def _support_bucket(value: int) -> str:
    return "0" if value == 0 else ("<10" if value < K else "10+")


def _number(value: object) -> str:
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return f"{float(value):.6g}"
    return ""


def _feature_available(visits: list[Visit], feature_name: str) -> bool:
    column = {
        "TRAVEL_MISSION": "TRAVEL_MISSION",
        "TRAVEL_START_MONTH": "TRAVEL_START_YMD",
        "SGG_CD": "SGG_CD",
        "VISIT_AREA_TYPE_CD": "VISIT_AREA_TYPE_CD",
    }.get(feature_name)
    return column is None or all(column in visit.available_columns for visit in visits)


def _features(event: Visit, ablation: str) -> tuple[str, ...]:
    if ablation == "popularity_only":
        return (event.popularity,)
    if ablation == "context_only":
        return event.context
    if ablation == "poi_only":
        return event.poi_features
    if ablation == "context_plus_poi":
        return (*event.context, *event.poi_features)
    raise ValueError("unknown ablation")


NBModel = tuple[
    list[str],
    dict[str, int],
    list[dict[str, Counter[str]]],
    list[set[str]],
]


def _fit_nb(rows: list[tuple[tuple[str, ...], str]]) -> NBModel:
    classes = sorted({label for _, label in rows})
    class_counts: Counter[str] = Counter(label for _, label in rows)
    feature_counts: list[dict[str, Counter[str]]] = [
        defaultdict(Counter) for _ in range(len(rows[0][0]))
    ]
    vocabularies: list[set[str]] = [set() for _ in feature_counts]
    for features, label in rows:
        for index, value in enumerate(features):
            feature_counts[index][label][value] += 1
            vocabularies[index].add(value)
    return classes, class_counts, feature_counts, vocabularies


def _predict_log_probs(
    features: tuple[str, ...],
    fitted: NBModel,
) -> dict[str, float]:
    classes, class_counts, feature_counts, vocabularies = fitted
    total = sum(class_counts.values())
    logits: dict[str, float] = {}
    for label in classes:
        score = math.log((class_counts[label] + 1) / (total + len(classes)))
        for index, value in enumerate(features):
            counts = feature_counts[index][label]
            vocab_size = len(vocabularies[index]) + 1
            score += math.log((counts.get(value, 0) + 1) / (class_counts[label] + vocab_size))
        logits[label] = score
    maximum = max(logits.values())
    normalizer = maximum + math.log(sum(math.exp(value - maximum) for value in logits.values()))
    return {label: score - normalizer for label, score in logits.items()}


def ablation_rows(events: dict[tuple[str, str], list[Visit]]) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    ablations = ("popularity_only", "context_only", "poi_only", "context_plus_poi")
    scopes = [
        (region, events.get((region, "TL"), []), events.get((region, "VL"), []))
        for region in REGIONS
    ]
    scopes.append((
        "all-regions",
        [event for (region, role), values in events.items() if role == "TL" for event in values],
        [event for (region, role), values in events.items() if role == "VL" for event in values],
    ))
    for region, tl, vl in scopes:
        for outcome in FEEDBACK_FIELDS:
            train = [
                (event, event.feedback[outcome])
                for event in tl
                if event.feedback[outcome] in {"1", "2", "3", "4", "5"}
            ]
            valid = [
                (event, event.feedback[outcome])
                for event in vl
                if event.feedback[outcome] in {"1", "2", "3", "4", "5"}
            ]
            for ablation in ablations:
                result: dict[str, object] = {
                    "region": region,
                    "outcome": outcome,
                    "ablation": ablation,
                    "status": "insufficient_support",
                    "train_support": _support_bucket(len(train)),
                    "validation_support": _support_bucket(len(valid)),
                    "mean_log_loss": "",
                }
                if any(outcome not in event.available_columns for event in (*tl, *vl)):
                    result["status"] = "unavailable_missing_column"
                    output.append(result)
                    continue
                train_classes = Counter(label for _, label in train)
                valid_classes = Counter(label for _, label in valid)
                needed = {
                    "popularity_only": {"POI_ID"},
                    "context_only": {"TRAVEL_MISSION", "TRAVEL_START_YMD"},
                    "poi_only": {"SGG_CD", "VISIT_AREA_TYPE_CD"},
                    "context_plus_poi": {
                        "TRAVEL_MISSION", "TRAVEL_START_YMD", "SGG_CD",
                        "VISIT_AREA_TYPE_CD",
                    },
                }[ablation]
                if any(
                    not needed.issubset(event.available_columns)
                    for event, _ in (*train, *valid)
                ):
                    result["status"] = "unavailable_missing_column"
                    output.append(result)
                    continue
                small_class = any(
                    0 < count < K
                    for count in (*train_classes.values(), *valid_classes.values())
                )
                unseen_validation_class = bool(set(valid_classes) - set(train_classes))
                if unseen_validation_class:
                    result["status"] = "suppressed_unseen_validation_class"
                elif len(train) >= K and len(valid) >= K and small_class:
                    result["status"] = "suppressed_k10"
                elif len(train) >= K and len(valid) >= K and len(train_classes) >= 2:
                    fitted = _fit_nb(
                        [(_features(event, ablation), str(label)) for event, label in train]
                    )
                    loss = 0.0
                    for event, label in valid:
                        log_probs = _predict_log_probs(_features(event, ablation), fitted)
                        loss -= log_probs[str(label)]
                    result["status"] = "observed"
                    result["mean_log_loss"] = _number(loss / len(valid))
                output.append(result)
    return output


def _write_csv(path: Path, rows: list[dict[str, object]], fields: tuple[str, ...]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _validate_output(output: Path, overwrite: bool) -> list[Path]:
    resolved = output.resolve()
    if (
        output.is_symlink()
        or not shared.within(resolved, RESULTS_ROOT.resolve())
        or resolved == RESULTS_ROOT.resolve()
    ):
        raise ValueError("output must be below ignored results/experiments/context-poi-signal")
    if shared.has_symlink_component(output):
        raise ValueError("output path contains a symlink")
    targets = [output / name for name in ARTIFACTS]
    if output.exists() and not overwrite:
        raise ValueError("output folder already exists; choose a new run id or explicit overwrite")
    if any(path.is_symlink() for path in targets) or (
        not overwrite and any(path.exists() for path in targets)
    ):
        raise ValueError("output already exists; choose a new run id or explicit overwrite")
    return targets


def _write_outputs(
    output: Path,
    associations: list[dict[str, object]],
    distributions: list[dict[str, object]],
    feedback_distributions: list[dict[str, object]],
    feedback_cross: list[dict[str, object]],
    feedback_context_poi: list[dict[str, object]],
    feedback_associations: list[dict[str, object]],
    ablations: list[dict[str, object]],
    column_availability: list[dict[str, str]],
    metadata: dict[str, object],
    overwrite: bool,
) -> None:
    targets = _validate_output(output, overwrite)
    output.mkdir(parents=True, exist_ok=True)
    _write_csv(
        targets[0],
        associations,
        (
            "region", "source_role", "context_feature", "poi_feature",
            "popularity_band", "status", "support", "cramers_v", "p_value_descriptive",
        ),
    )
    _write_csv(
        targets[1],
        distributions,
        (
            "region", "source_role", "context_feature", "poi_feature",
            "popularity_band", "context_category", "poi_category", "support", "status",
        ),
    )
    _write_csv(
        targets[2],
        column_availability,
        ("region", "source_role", "table", "column", "status"),
    )
    _write_csv(
        targets[3],
        feedback_distributions,
        ("region", "source_role", "outcome", "category", "support", "status"),
    )
    _write_csv(
        targets[4],
        feedback_cross,
        (
            "region", "source_role", "outcome", "feature", "popularity_band",
            "feature_category", "outcome_category", "support", "status",
        ),
    )
    _write_csv(
        targets[5],
        feedback_context_poi,
        (
            "region", "source_role", "outcome", "context_feature", "poi_feature",
            "context_category", "poi_category", "outcome_category", "support", "status",
        ),
    )
    _write_csv(
        targets[6],
        feedback_associations,
        (
            "region", "source_role", "outcome", "feature", "popularity_band",
            "status", "support", "cramers_v", "p_value_descriptive",
        ),
    )
    _write_csv(
        targets[7],
        ablations,
        (
            "region", "outcome", "ablation", "status", "train_support",
            "validation_support", "mean_log_loss",
        ),
    )
    targets[8].write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-root", type=Path, default=shared.RAW_ROOT)
    parser.add_argument(
        "--input", action="append", type=shared.parse_input_spec, required=True,
        metavar="REGION:TL|VL=PATH",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--confirm-approved", action="store_true")
    parser.add_argument("--confirm-terms", action="store_true")
    parser.add_argument("--confirm-user-shell-preflight", action="store_true")
    parser.add_argument("--confirm-poi-candidate", action="store_true")
    parser.add_argument("--allow-approved-capital-filekey-folders", action="store_true")
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", args.run_id):
        parser.error("run-id contains unsupported characters")
    if not (
        args.confirm_approved
        and args.confirm_terms
        and args.confirm_user_shell_preflight
        and args.confirm_poi_candidate
    ):
        parser.error(
            "approval, terms, original-shell preflight, and provisional POI-candidate "
            "confirmations are required"
        )
    try:
        started = datetime.now(UTC).isoformat()
        _validate_output(args.output, args.overwrite)
        sources = resolve_sources(
            args.input,
            args.raw_root,
            args.allow_approved_capital_filekey_folders,
        )
        column_availability = validate_headers(sources)
        events = collect_events(sources)
        associations = association_rows(events)
        distributions = context_poi_distributions(events)
        feedback_distributions, feedback_associations = feedback_diagnostics(events)
        feedback_cross = feedback_cross_distributions(events)
        feedback_context_poi = feedback_context_poi_distributions(events)
        ablations = ablation_rows(events)
        code_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        revision, working_tree_dirty = _revision_state()
        metadata = {
            "dataset": "AI Hub Domestic Travel Log 2023",
            "dataset_version": "2023",
            "regions": list(REGIONS),
            "source_roles": {"TL": "train_development", "VL": "external_replication"},
            "split_policy": "supplied_role_folders_only_no_merge_no_random_resplit",
            "seed": None,
            "run_id": args.run_id,
            "code_revision": revision,
            "code_worktree_dirty": working_tree_dirty,
            "script_sha256": code_sha,
            "started_utc": started,
            "finished_utc": datetime.now(UTC).isoformat(),
            "outcomes": list(FEEDBACK_FIELDS),
            "statistical_test": "descriptive_row_chi_square_with_cramers_v_and_k10_cell_suppression",
            "p_value_interpretation": (
                "descriptive_uncalibrated_due_to_trip_clustered_visits; "
                "excluded_from_issue_41_go"
            ),
            "issue_41_go_uses_p_values": False,
            "capital_role_mapping_inputs_recorded": False,
            "predictive_model": "categorical_naive_bayes",
            "feature_sets": ["popularity_only", "context_only", "poi_only", "context_plus_poi"],
            "popularity_bands": ["0", "1", "2-4", "5-9", "10-49", "50+"],
            "raw_ids_as_features": False,
            "raw_input_paths_recorded": False,
            "actual_visit_classifier": "not_fit_no_valid_negative_or_exposure_definition",
            "privacy_suppression_k": K,
        }
        _write_outputs(
            args.output,
            associations,
            distributions,
            feedback_distributions,
            feedback_cross,
            feedback_context_poi,
            feedback_associations,
            ablations,
            column_availability,
            metadata,
            args.overwrite,
        )
        print("context-POI feasibility outputs written under ignored results path")
        return 0
    except (OSError, ValueError, csv.Error) as exc:
        if isinstance(exc, SafeInputError):
            print(f"experiment failed safely: {exc}", file=sys.stderr)
        else:
            print(f"experiment failed safely: {type(exc).__name__}", file=sys.stderr)
        return 1


def _revision_state() -> tuple[str | None, bool | None]:
    import subprocess

    try:
        revision_result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, check=True,
            capture_output=True, text=True, timeout=5,
        )
        status_result = subprocess.run(
            ["git", "status", "--porcelain"], cwd=REPO_ROOT, check=True,
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None, None
    revision = revision_result.stdout.strip()
    return (
        revision if re.fullmatch(r"[0-9a-f]{40}", revision) else None,
        bool(status_result.stdout.strip()),
    )


if __name__ == "__main__":
    raise SystemExit(main())
