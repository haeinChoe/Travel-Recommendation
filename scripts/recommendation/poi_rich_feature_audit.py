"""TL-only POI rich-feature materialization and aggregate-only audit for Issue #95.

The CLI reads only the explicitly bound capital TL and static OTHER roles. It does not
read official VL or visit feedback. Static address columns are read in memory only to
resolve canonical administrative location; addresses, coordinates, and raw item/trip IDs
are not serialized to the aggregate JSON or stdout.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass, field
from datetime import UTC, datetime
from fractions import Fraction
from pathlib import Path
from typing import Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.recommendation.catboost_ranking_experiment import (  # noqa: E402
    ExperimentConfig,
    normalize_feature_value,
)
from scripts.recommendation.canonical_admin_location import build_admin_lookup  # noqa: E402
from scripts.recommendation.poi_catalog_policy import load_poi_catalog_policy  # noqa: E402
from scripts.recommendation.run_catboost_tl_smoke import (  # noqa: E402
    FEATURE_GROUPS as BASELINE_FEATURE_GROUPS,
    SGG_COLUMNS,
    TRAVELER_COLUMNS,
    TRAVEL_COLUMNS,
    VISIT_COLUMNS,
    _available_bytes,
    _bound_inputs,
    _clean_str,
    _filter_master_to_product_region,
    _find_master_path,
    _load_master,
    _normalize_admin_codebook_rows,
    _table,
    read_projected_csv,
    _context_rows,
)
from scripts.recommendation.tl_traveler_split import (  # noqa: E402
    deterministic_traveler_group_split,
    recompute_inner_train_positive_interaction_count,
    recompute_inner_train_visit_type_codes,
    validate_no_traveler_overlap,
)
from scripts.recommendation.training_data_contract import (  # noqa: E402
    NON_TOURISM_VISIT_AREA_TYPES,
    TripPoiPositive,
    build_trip_poi_positives,
)

SPLIT_SEED = 20261025
VALIDATION_FRACTION = 0.2
BASELINE_GROUPS = (
    "Q4_TEMPORAL",
    "I2_ADMINISTRATIVE_LOCATION",
    "I3_POPULARITY",
    "I4_HISTORICAL_POI",
)
BASELINE_ITEM_COLUMNS = (
    "canonical_admin_sido_code",
    "canonical_admin_sgg_code",
    "canonical_admin_location_status",
    "train_positive_interaction_count",
    "train_observed_visit_type_codes",
)
STATIC_CATEGORY_COLUMNS = (
    "source_category_l1_code",
    "source_category_l2_code",
    "source_category_l3_code",
)
PROFILE_FIELDS = (
    "start_month",
    "companion_status",
    *(f"travel_motive_{index}" for index in range(1, 4)),
    *(f"travel_style_{index}" for index in range(1, 9)),
)
COHORTS = ("all_valid_observed", "tourism_core")
SUPPORT_BUCKETS = ("0", "1", "2-4", "5-9", "10+")
HISTORICAL_CANDIDATE_COUNT = 3_052_797
HISTORICAL_BASELINE_TUPLE_COUNT = 729
DEFAULT_OUTPUT_DIR = REPO_ROOT / "results" / "experiments" / "poi-rich-feature-v1"
MIN_AVAILABLE_BYTES = 8 * 1024**3

SERVICE_FEATURE_CONTRACT: tuple[dict[str, object], ...] = (
    {
        "group": "static_administrative_location",
        "fields": [
            "canonical_admin_sido_code",
            "canonical_admin_sgg_code",
            "canonical_admin_location_status",
        ],
        "availability_class": "day_0_static",
        "source_role": "static OTHER / TN_POI_MASTER plus documented TC_SGG codebook",
        "serving_parity": "Retain the existing location contract; this audit does not establish new TourAPI parity.",
    },
    {
        "group": "static_poi_classification",
        "fields": [
            *STATIC_CATEGORY_COLUMNS,
            *(f"{column}_missing" for column in STATIC_CATEGORY_COLUMNS),
        ],
        "availability_class": "day_0_static",
        "source_role": "static OTHER / TN_POI_MASTER.ASORT_*",
        "serving_parity": "Unverified; no AI Hub-to-TourAPI category crosswalk is assumed or introduced.",
    },
    {
        "group": "historical_observed_visit_support",
        "fields": [
            "all_valid_observed_trip_poi_support",
            "all_valid_observed_traveler_support",
            "tourism_core_trip_poi_support",
            "tourism_core_traveler_support",
        ],
        "availability_class": "service_log_derivable_if_confirmed_visits_are_collected",
        "source_role": "inner-train TL unique trip-POI pairs",
        "serving_parity": "Conditional on recording confirmed visits; click and save events are not visits.",
    },
    {
        "group": "historical_visitor_context_distribution",
        "fields": list(PROFILE_FIELDS),
        "availability_class": "service_log_derivable_if_context_and_confirmed_visits_are_collected",
        "source_role": "inner-train TL trip context joined once per unique trip-POI pair",
        "serving_parity": "Conditional; identical meaning, collection time, and field coding must be established.",
    },
    {
        "group": "historical_visit_event_type",
        "fields": ["train_observed_visit_type_codes"],
        "availability_class": "offline_only_or_deferred",
        "source_role": "inner-train TL TN_VISIT_AREA_INFO.VISIT_AREA_TYPE_CD",
        "serving_parity": "An event classification, never static POI classification or TourAPI content type.",
    },
)


@dataclass
class FieldDistribution:
    valid_trip_pair_support: int = 0
    traveler_ids: set[str] = field(default_factory=set)
    value_counts: Counter[str] = field(default_factory=Counter)


@dataclass
class ItemHistory:
    distinct_trip_poi_support: int = 0
    traveler_ids: set[str] = field(default_factory=set)
    fields: dict[str, FieldDistribution] = field(default_factory=dict)


class _SafeArgumentParser(argparse.ArgumentParser):
    """Suppress caller-supplied values from CLI parse errors."""

    def error(self, message: str) -> None:
        del message
        self._print_message("Invalid command-line arguments; details are suppressed.\n", sys.stderr)
        raise SystemExit(2)


def _support_bucket(value: int) -> str:
    if value < 0:
        raise ValueError("Support counts must be non-negative")
    if value == 0:
        return "0"
    if value == 1:
        return "1"
    if value <= 4:
        return "2-4"
    if value <= 9:
        return "5-9"
    return "10+"


def _event_pair_classification(pair: TripPoiPositive) -> str:
    if pair.has_tourism_core_visit:
        return "tourism_core"
    if any(code in NON_TOURISM_VISIT_AREA_TYPES for code in pair.visit_area_types):
        return "known_non_tourism_only"
    return "actual_visit_type_unresolved"


def _add_context_pair(
    accumulator: ItemHistory,
    *,
    traveler_id: str,
    context: Mapping[str, object],
) -> None:
    accumulator.distinct_trip_poi_support += 1
    accumulator.traveler_ids.add(traveler_id)
    for field_name in PROFILE_FIELDS:
        value = _clean_str(context.get(field_name))
        if value is None:
            continue
        profile = accumulator.fields.setdefault(field_name, FieldDistribution())
        profile.valid_trip_pair_support += 1
        profile.traveler_ids.add(traveler_id)
        profile.value_counts[value] += 1


def _build_inner_train_histories(
    *,
    positives: Sequence[TripPoiPositive],
    partition_by_trip: Mapping[str, str],
    trip_owner: Mapping[str, str],
    context_by_trip: Mapping[str, Mapping[str, object]],
    candidate_ids: set[str],
) -> tuple[dict[str, dict[str, ItemHistory]], dict[str, object]]:
    histories: dict[str, dict[str, ItemHistory]] = {
        cohort: defaultdict(ItemHistory) for cohort in COHORTS
    }
    all_pair_types: Counter[str] = Counter()
    candidate_pair_types: Counter[str] = Counter()
    outside_candidate_pair_types: Counter[str] = Counter()

    for pair in positives:
        partition = partition_by_trip.get(pair.travel_id)
        if partition not in {"inner-train", "inner-validation"}:
            raise ValueError("Observed trip-POI pair has no validated inner partition")
        if partition != "inner-train":
            continue

        classification = _event_pair_classification(pair)
        all_pair_types[classification] += 1
        if pair.poi_id not in candidate_ids:
            outside_candidate_pair_types[classification] += 1
            continue

        candidate_pair_types[classification] += 1
        traveler_id = trip_owner.get(pair.travel_id)
        context = context_by_trip.get(pair.travel_id)
        if not traveler_id or context is None:
            raise ValueError("Inner-train positive lacks a validated trip context")

        _add_context_pair(
            histories["all_valid_observed"][pair.poi_id],
            traveler_id=traveler_id,
            context=context,
        )
        if pair.has_tourism_core_visit:
            _add_context_pair(
                histories["tourism_core"][pair.poi_id],
                traveler_id=traveler_id,
                context=context,
            )

    expected_pair_types = {
        "tourism_core",
        "known_non_tourism_only",
        "actual_visit_type_unresolved",
    }
    for counts in (all_pair_types, candidate_pair_types, outside_candidate_pair_types):
        if set(counts) - expected_pair_types:
            raise ValueError("Unexpected visit-cohort classification")
    if sum(candidate_pair_types.values()) + sum(outside_candidate_pair_types.values()) != sum(
        all_pair_types.values()
    ):
        raise ValueError("Candidate and outside-candidate visit pairs do not reconcile")
    if candidate_pair_types["tourism_core"] != sum(
        history.distinct_trip_poi_support
        for history in histories["tourism_core"].values()
    ):
        raise ValueError("Tourism-core pair support does not reconcile")

    summary = {
        "inner_train_all_valid_observed_trip_poi_pairs": sum(all_pair_types.values()),
        "inner_train_candidate_trip_poi_pairs": sum(candidate_pair_types.values()),
        "inner_train_outside_candidate_trip_poi_pairs": sum(outside_candidate_pair_types.values()),
        "visit_pair_type_counts_inner_train_all_valid": {
            key: all_pair_types[key] for key in sorted(expected_pair_types)
        },
        "visit_pair_type_counts_inner_train_in_candidate_universe": {
            key: candidate_pair_types[key] for key in sorted(expected_pair_types)
        },
        "visit_pair_type_counts_inner_train_outside_candidate_universe": {
            key: outside_candidate_pair_types[key] for key in sorted(expected_pair_types)
        },
        "cohort_semantics": {
            "all_valid_observed": (
                "Distinct structurally valid TL inner-train trip-POI pairs, regardless of "
                "tourism-core event classification. These are observed visits, not preference labels."
            ),
            "tourism_core": (
                "A subset of all-valid pairs with at least one valid tourism-core "
                "VISIT_AREA_TYPE_CD event."
            ),
            "known_non_tourism_only": (
                "A distinct observed trip-POI pair with valid non-tourism event type(s) "
                "and no tourism-core type; it is not unobserved."
            ),
            "actual_visit_type_unresolved": (
                "A structurally valid observed trip-POI pair with no valid event type code; "
                "it remains observed, not unobserved."
            ),
        },
    }
    return histories, summary


def _profile_share(profile: FieldDistribution | None) -> dict[str, float] | None:
    if profile is None or profile.valid_trip_pair_support == 0:
        return None
    if sum(profile.value_counts.values()) != profile.valid_trip_pair_support:
        raise ValueError("Profile values do not reconcile with the field-specific denominator")
    if len(profile.traveler_ids) > profile.valid_trip_pair_support:
        raise ValueError("Distinct traveler support exceeds trip-POI support")
    denominator = profile.valid_trip_pair_support
    return {
        value: count / denominator
        for value, count in sorted(profile.value_counts.items())
    }


def build_poi_rich_feature_row(
    *,
    item_id: str,
    static_item: Mapping[str, object],
    all_valid_history: ItemHistory | None,
    tourism_core_history: ItemHistory | None,
    baseline_i3: int,
    baseline_i4: Sequence[str],
) -> dict[str, object]:
    """Build one in-memory item row; the raw item key must never be serialized."""

    row: dict[str, object] = {
        "item_id": item_id,
        "canonical_admin_sido_code": static_item.get("canonical_admin_sido_code"),
        "canonical_admin_sgg_code": static_item.get("canonical_admin_sgg_code"),
        "canonical_admin_location_status": static_item.get("canonical_admin_location_status"),
        "source_category_l1_code": static_item.get("source_category_l1_code"),
        "source_category_l2_code": static_item.get("source_category_l2_code"),
        "source_category_l3_code": static_item.get("source_category_l3_code"),
        "train_positive_interaction_count": baseline_i3,
        "train_observed_visit_type_codes": tuple(baseline_i4),
    }
    for column in STATIC_CATEGORY_COLUMNS:
        row[f"{column}_missing"] = static_item.get(column) is None

    for cohort, history in (
        ("all_valid_observed", all_valid_history),
        ("tourism_core", tourism_core_history),
    ):
        pair_support = history.distinct_trip_poi_support if history else 0
        traveler_support = len(history.traveler_ids) if history else 0
        if traveler_support > pair_support:
            raise ValueError("Distinct traveler support exceeds trip-POI support")
        row[f"{cohort}_trip_poi_support"] = pair_support
        row[f"{cohort}_traveler_support"] = traveler_support
        row[f"{cohort}_has_observed_visit"] = pair_support > 0
        support_by_field: dict[str, dict[str, int]] = {}
        shares_by_field: dict[str, dict[str, float] | None] = {}
        for field_name in PROFILE_FIELDS:
            profile = history.fields.get(field_name) if history else None
            valid_trip_pair_support = profile.valid_trip_pair_support if profile else 0
            valid_traveler_support = len(profile.traveler_ids) if profile else 0
            if valid_traveler_support > valid_trip_pair_support:
                raise ValueError("Field traveler support exceeds valid-response support")
            support_by_field[field_name] = {
                "valid_trip_poi_support": valid_trip_pair_support,
                "valid_traveler_support": valid_traveler_support,
            }
            shares_by_field[field_name] = _profile_share(profile)
        row[f"{cohort}_profile_support"] = support_by_field
        row[f"{cohort}_profile_shares"] = shares_by_field
    return row


def _baseline_signature(
    row: Mapping[str, object],
    config: ExperimentConfig,
) -> tuple[object, ...]:
    return tuple(
        normalize_feature_value(
            column,
            row.get(column, () if column == "train_observed_visit_type_codes" else None),
            config,
        )
        for column in BASELINE_ITEM_COLUMNS
    )


def _static_category_signature(row: Mapping[str, object]) -> tuple[object, ...]:
    values = tuple(
        normalize_feature_value(column, row.get(column), config)
        for column, config in (
            (STATIC_CATEGORY_COLUMNS[0], _STATIC_NORMALIZATION_CONFIG),
            (STATIC_CATEGORY_COLUMNS[1], _STATIC_NORMALIZATION_CONFIG),
            (STATIC_CATEGORY_COLUMNS[2], _STATIC_NORMALIZATION_CONFIG),
        )
    )
    missing_flags = tuple(bool(row.get(f"{column}_missing")) for column in STATIC_CATEGORY_COLUMNS)
    return (*values, *missing_flags)


def _history_signature(
    history: ItemHistory | None,
    *,
    cohort: str,
) -> tuple[object, ...]:
    pair_support = history.distinct_trip_poi_support if history else 0
    traveler_support = len(history.traveler_ids) if history else 0
    signature: list[object] = [pair_support, traveler_support]
    for field_name in PROFILE_FIELDS:
        profile = history.fields.get(field_name) if history else None
        if profile is None or profile.valid_trip_pair_support == 0:
            if profile is not None and profile.value_counts:
                raise ValueError("Missing profile denominator has observed values")
            signature.append((0, 0, None))
            continue
        denominator = profile.valid_trip_pair_support
        if sum(profile.value_counts.values()) != denominator:
            raise ValueError("Profile distribution denominator mismatch")
        shares = tuple(
            (value, Fraction(count, denominator))
            for value, count in sorted(profile.value_counts.items())
        )
        signature.append((denominator, len(profile.traveler_ids), shares))
    return (cohort, *signature)


def _tuple_metrics(counter: Counter[tuple[object, ...]], candidate_count: int) -> dict[str, object]:
    duplicate_candidates = sum(count for count in counter.values() if count > 1)
    return {
        "candidate_count": candidate_count,
        "unique_item_feature_tuple_count": len(counter),
        "duplicate_tuple_candidate_count": duplicate_candidates,
        "duplicate_tuple_candidate_rate": (
            round(duplicate_candidates / candidate_count, 8) if candidate_count else 0.0
        ),
        "largest_tie_group_size": max(counter.values(), default=0),
    }


def _code_revision() -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "--short", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = result.stdout.strip()
    return value if re.fullmatch(r"[0-9a-f]{7,40}", value) else None


def _write_aggregate(path: Path, payload: Mapping[str, object]) -> None:
    try:
        relative = path.resolve(strict=False).relative_to(REPO_ROOT.resolve(strict=True))
    except (OSError, ValueError) as error:
        raise ValueError("Output must stay inside the repository") from error
    check = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "check-ignore", "-q", str(relative)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if check.returncode != 0:
        raise ValueError("Aggregate output location is not Git-ignored")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                         encoding="utf-8")
    temporary.replace(path)


def _run_audit(*, run_id: str, terms_confirmed: bool) -> dict[str, object]:
    if not terms_confirmed:
        raise ValueError("Applicable terms and handling conditions must be rechecked before row access")
    if _available_bytes() < MIN_AVAILABLE_BYTES:
        raise ValueError("Insufficient available memory for the candidate inventory")

    total_start = time.monotonic()
    _, tl_root, other_root = _bound_inputs("capital")
    travel_path = _table(tl_root, "tn_travel_", "tn_travel")
    traveler_path = _table(tl_root, "tn_traveller_master")
    visit_path = _table(tl_root, "tn_visit_area_info")
    sgg_path = _table(tl_root, "tc_sgg")
    master_path = _find_master_path(other_root)

    sgg_rows = read_projected_csv(sgg_path, SGG_COLUMNS, SGG_COLUMNS)
    admin_lookup = build_admin_lookup(_normalize_admin_codebook_rows(sgg_rows))
    if not admin_lookup:
        raise ValueError("Administrative codebook is unavailable")
    policy = load_poi_catalog_policy()
    master, duplicate_master_ids, master_source_rows, blank_id_rows = _load_master(
        master_path,
        admin_lookup,
        total_start,
        source_package_region="capital",
    )
    if not master:
        raise ValueError("Static POI master is empty")
    candidate_items = _filter_master_to_product_region(
        master,
        source_package_region="capital",
        policy=policy,
    )
    candidate_ids = set(candidate_items)

    traveler_rows = read_projected_csv(
        traveler_path, TRAVELER_COLUMNS, TRAVELER_COLUMNS
    )
    travel_rows = read_projected_csv(travel_path, TRAVEL_COLUMNS, TRAVEL_COLUMNS)
    visit_rows = read_projected_csv(visit_path, VISIT_COLUMNS, VISIT_COLUMNS)
    trip_owner, context_by_trip = _context_rows(
        travel_rows,
        traveler_rows,
        "capital",
        "issue95-poi-rich-feature-v1",
    )
    partition_by_trip = deterministic_traveler_group_split(
        trip_owner,
        seed=SPLIT_SEED,
        validation_fraction=VALIDATION_FRACTION,
    )
    overlap_count = validate_no_traveler_overlap(trip_owner, partition_by_trip)
    if set(context_by_trip) != set(trip_owner):
        raise ValueError("Trip context and split trip sets do not match")

    valid_events = [
        {**row, "source_split": "TL"}
        for row in visit_rows
        if _clean_str(row.get("TRAVEL_ID")) in trip_owner
        and _clean_str(row.get("VISIT_AREA_ID"))
    ]
    positives, _ = build_trip_poi_positives(
        valid_events,
        region="capital",
        trip_to_traveler=trip_owner,
        valid_traveler_ids=set(trip_owner.values()),
    )
    inner_train_valid_events = [
        row for row in valid_events
        if partition_by_trip.get(_clean_str(row.get("TRAVEL_ID")) or "") == "inner-train"
    ]
    inner_train_events = [
        row for row in inner_train_valid_events
        if _clean_str(row.get("POI_ID")) in candidate_ids
    ]
    baseline_positive_rows = [
        {
            "TRAVEL_ID": pair.travel_id,
            "POI_ID": pair.poi_id,
            "observed_positive": 1,
            "source_split": "TL",
        }
        for pair in positives
        if pair.has_tourism_core_visit
        and pair.poi_id in candidate_ids
        and partition_by_trip.get(pair.travel_id) == "inner-train"
    ]
    i3 = recompute_inner_train_positive_interaction_count(
        baseline_positive_rows,
        partition_by_trip,
    )
    i4 = recompute_inner_train_visit_type_codes(
        inner_train_events,
        partition_by_trip,
    )
    histories, visit_summary = _build_inner_train_histories(
        positives=positives,
        partition_by_trip=partition_by_trip,
        trip_owner=trip_owner,
        context_by_trip=context_by_trip,
        candidate_ids=candidate_ids,
    )

    if set(candidate_items) != candidate_ids:
        raise ValueError("Candidate inventory changed during audit construction")
    if sum(1 for row in baseline_positive_rows) != sum(
        1 for pair in positives
        if pair.has_tourism_core_visit
        and pair.poi_id in candidate_ids
        and partition_by_trip.get(pair.travel_id) == "inner-train"
    ):
        raise ValueError("Baseline positive set does not reconcile")

    baseline_config = ExperimentConfig(
        feature_groups=BASELINE_GROUPS,
        seed=SPLIT_SEED,
        popularity_transform="raw",
    )
    if tuple(BASELINE_FEATURE_GROUPS) != BASELINE_GROUPS:
        raise ValueError("Corrected baseline groups changed; refresh the comparison contract")

    support_pair_bins = {cohort: Counter() for cohort in COHORTS}
    support_traveler_bins = {cohort: Counter() for cohort in COHORTS}
    profile_field_bins: dict[str, dict[str, dict[str, Counter[str]]]] = {
        cohort: {
            field_name: {"valid_trip_poi_support": Counter(), "valid_traveler_support": Counter()}
            for field_name in PROFILE_FIELDS
        }
        for cohort in COHORTS
    }
    tuple_counters: dict[str, Counter[tuple[object, ...]]] = {
        "baseline_I2_I3_I4": Counter(),
        "plus_static_source_category": Counter(),
        "plus_all_valid_visitor_context": Counter(),
        "plus_tourism_core_visitor_context": Counter(),
    }
    non_default_counts: Counter[str] = Counter()
    active_candidate_ids = (
        set(histories["all_valid_observed"]) | set(histories["tourism_core"])
    )
    static_codes = {column: 0 for column in STATIC_CATEGORY_COLUMNS}
    all_three_static_count = 0
    any_static_category_count = 0
    canonical_sgg_count = 0
    canonical_sido_count = 0
    core_event_codes_by_item: dict[str, Sequence[str]] = i4
    candidate_count = len(candidate_items)

    for item_id, static_item in candidate_items.items():
        if not item_id or item_id not in candidate_ids:
            raise ValueError("Candidate item identity is missing")
        baseline_i3 = i3.get(item_id, 0)
        baseline_i4 = tuple(core_event_codes_by_item.get(item_id, ()))
        all_history = histories["all_valid_observed"].get(item_id)
        core_history = histories["tourism_core"].get(item_id)

        if item_id in active_candidate_ids:
            row = build_poi_rich_feature_row(
                item_id=item_id,
                static_item=static_item,
                all_valid_history=all_history,
                tourism_core_history=core_history,
                baseline_i3=baseline_i3,
                baseline_i4=baseline_i4,
            )
            baseline = _baseline_signature(row, baseline_config)
            category = _static_category_signature(row)
            all_signature = _history_signature(all_history, cohort="all_valid_observed")
            core_signature = _history_signature(core_history, cohort="tourism_core")
            all_pair_support = int(row["all_valid_observed_trip_poi_support"])
            all_traveler_support = int(row["all_valid_observed_traveler_support"])
            core_pair_support = int(row["tourism_core_trip_poi_support"])
            core_traveler_support = int(row["tourism_core_traveler_support"])
        else:
            # Cold items retain static item values, have support 0, and carry null shares.
            cold_row = {
                **static_item,
                **{f"{column}_missing": static_item.get(column) is None
                   for column in STATIC_CATEGORY_COLUMNS},
                "train_positive_interaction_count": baseline_i3,
                "train_observed_visit_type_codes": baseline_i4,
            }
            baseline = _baseline_signature(cold_row, baseline_config)
            category = _static_category_signature(cold_row)
            all_signature = _history_signature(None, cohort="all_valid_observed")
            core_signature = _history_signature(None, cohort="tourism_core")
            all_pair_support = all_traveler_support = 0
            core_pair_support = core_traveler_support = 0

        static_values = tuple(static_item.get(column) for column in STATIC_CATEGORY_COLUMNS)
        for column, value in zip(STATIC_CATEGORY_COLUMNS, static_values, strict=True):
            if value is not None:
                static_codes[column] += 1
        if all(value is not None for value in static_values):
            all_three_static_count += 1
        if any(value is not None for value in static_values):
            any_static_category_count += 1
        canonical_sido_count += static_item.get("canonical_admin_sido_code") is not None
        canonical_sgg_count += static_item.get("canonical_admin_sgg_code") is not None

        tuple_counters["baseline_I2_I3_I4"][baseline] += 1
        tuple_counters["plus_static_source_category"][(*baseline, *category)] += 1
        tuple_counters["plus_all_valid_visitor_context"][
            (*baseline, *category, *all_signature)
        ] += 1
        tuple_counters["plus_tourism_core_visitor_context"][
            (*baseline, *category, *core_signature)
        ] += 1

        non_default_counts["baseline_I2_I3_I4"] += (
            baseline_i3 > 0 or bool(baseline_i4)
        )
        non_default_counts["plus_static_source_category"] += any(
            value is not None for value in static_values
        )
        non_default_counts["plus_all_valid_visitor_context"] += all_pair_support > 0
        non_default_counts["plus_tourism_core_visitor_context"] += core_pair_support > 0

        for cohort, pair_support, traveler_support, history in (
            ("all_valid_observed", all_pair_support, all_traveler_support, all_history),
            ("tourism_core", core_pair_support, core_traveler_support, core_history),
        ):
            support_pair_bins[cohort][_support_bucket(pair_support)] += 1
            support_traveler_bins[cohort][_support_bucket(traveler_support)] += 1
            for field_name in PROFILE_FIELDS:
                profile = history.fields.get(field_name) if history else None
                valid_pairs = profile.valid_trip_pair_support if profile else 0
                valid_travelers = len(profile.traveler_ids) if profile else 0
                profile_field_bins[cohort][field_name]["valid_trip_poi_support"][
                    _support_bucket(valid_pairs)
                ] += 1
                profile_field_bins[cohort][field_name]["valid_traveler_support"][
                    _support_bucket(valid_travelers)
                ] += 1

    if any(sum(counter.values()) != candidate_count for counter in tuple_counters.values()):
        raise ValueError("Feature tuple counts do not share one unchanged candidate universe")
    for cohort in COHORTS:
        if sum(support_pair_bins[cohort].values()) != candidate_count:
            raise ValueError("Trip-POI support distribution does not cover all candidates")
        if sum(support_traveler_bins[cohort].values()) != candidate_count:
            raise ValueError("Traveler support distribution does not cover all candidates")
        for field_name in PROFILE_FIELDS:
            for support_kind in ("valid_trip_poi_support", "valid_traveler_support"):
                if sum(profile_field_bins[cohort][field_name][support_kind].values()) != candidate_count:
                    raise ValueError("Profile support distribution does not cover all candidates")

    feature_comparison = [
        {
            "stage": stage,
            **_tuple_metrics(counter, candidate_count),
            "candidate_items_with_non_default_stage_features": non_default_counts[stage],
            "non_default_stage_feature_candidate_rate": (
                round(non_default_counts[stage] / candidate_count, 8) if candidate_count else 0.0
            ),
        }
        for stage, counter in tuple_counters.items()
    ]
    profile_availability: dict[str, object] = {}
    for cohort in COHORTS:
        fields: dict[str, object] = {}
        for field_name in PROFILE_FIELDS:
            pair_bins = profile_field_bins[cohort][field_name]["valid_trip_poi_support"]
            traveler_bins = profile_field_bins[cohort][field_name]["valid_traveler_support"]
            valid_items = candidate_count - pair_bins["0"]
            fields[field_name] = {
                "items_with_valid_response_count": valid_items,
                "items_with_valid_response_rate": (
                    round(valid_items / candidate_count, 8) if candidate_count else 0.0
                ),
                "valid_trip_poi_support_bins": {
                    bucket: pair_bins[bucket] for bucket in SUPPORT_BUCKETS
                },
                "valid_traveler_support_bins": {
                    bucket: traveler_bins[bucket] for bucket in SUPPORT_BUCKETS
                },
                "share_denominator": "valid response count for this field on distinct inner-train trip-POI pairs",
                "zero_denominator_share": None,
            }
        profile_availability[cohort] = fields

    support_summary: dict[str, object] = {}
    for cohort in COHORTS:
        pairs = support_pair_bins[cohort]
        travelers = support_traveler_bins[cohort]
        history_items = candidate_count - pairs["0"]
        support_summary[cohort] = {
            "distinct_inner_train_trip_poi_support_bins": {
                bucket: pairs[bucket] for bucket in SUPPORT_BUCKETS
            },
            "distinct_inner_train_traveler_support_bins": {
                bucket: travelers[bucket] for bucket in SUPPORT_BUCKETS
            },
            "candidate_items_with_observed_support_count": history_items,
            "candidate_items_with_observed_support_rate": (
                round(history_items / candidate_count, 8) if candidate_count else 0.0
            ),
            "zero_support_means": "no observed pair in this cohort; it does not mean a negative or dislike",
        }

    comparison = {
        "candidate_universe": "unchanged corrected #82 capital ProductRegion candidate definition",
        "candidate_policy_version": policy.version,
        "candidate_policy_sha256": policy.policy_sha256,
        "historical_candidate_count_reference": HISTORICAL_CANDIDATE_COUNT,
        "current_candidate_count": candidate_count,
        "candidate_count_matches_historical_reference": candidate_count == HISTORICAL_CANDIDATE_COUNT,
        "baseline_feature_groups": list(BASELINE_GROUPS),
        "baseline_item_tuple_columns": list(BASELINE_ITEM_COLUMNS),
        "Q4_TEMPORAL": "query-side only; excluded from item tuple uniqueness",
        "split_seed": SPLIT_SEED,
        "validation_fraction": VALIDATION_FRACTION,
        "historical_729_tuple_count_reference": HISTORICAL_BASELINE_TUPLE_COUNT,
        "current_baseline_tuple_count": len(tuple_counters["baseline_I2_I3_I4"]),
        "baseline_tuple_count_matches_historical_reference": (
            len(tuple_counters["baseline_I2_I3_I4"]) == HISTORICAL_BASELINE_TUPLE_COUNT
        ),
        "historical_execution_run_id_or_commit_linkage": "not available in checked-in source; this run records the reproducible recipe and current result",
        "comparison_rule": (
            "All stages use the same current candidate IDs, same static I2, and same "
            "20261025/20% traveler-group split. A match to 729 is a recipe-level "
            "reconstruction, not proof of the original execution identity."
        ),
        "feature_tuple_comparison": feature_comparison,
    }

    traveler_train_count = len({
        trip_owner[trip] for trip, part in partition_by_trip.items() if part == "inner-train"
    })
    traveler_validation_count = len({
        trip_owner[trip] for trip, part in partition_by_trip.items() if part == "inner-validation"
    })
    if traveler_train_count + traveler_validation_count != len(set(trip_owner.values())):
        raise ValueError("Inner split traveler counts do not reconcile")

    return {
        "schema_version": "poi-rich-feature-audit-v1",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "run_id": run_id,
        "code_revision": _code_revision(),
        "audit_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "source_scope": {
            "dataset": "AI Hub Domestic Travel Log 2023",
            "region": "capital",
            "roles_read": ["CAPITAL_TL", "CAPITAL_OTHER"],
            "outer_VL_access": "not read",
            "visit_fields_selected": list(VISIT_COLUMNS),
            "feedback_fields_selected": [],
            "static_fields_selected": list(STATIC_CATEGORY_COLUMNS),
        },
        "terms_and_privacy": {
            "terms_recheck_required_before_row_access": True,
            "terms_recheck_confirmed_by_cli_operator": terms_confirmed,
            "raw_rows_or_raw_identifiers_in_output": False,
            "exact_local_paths_or_environment_values_in_output": False,
            "post_visit_feedback_read": False,
        },
        "candidate_inventory": {
            "source": "unique TN_POI_MASTER items with resolved canonical SIDO in the unchanged capital ProductRegion mapping",
            "count": candidate_count,
            "duplicate_master_id_groups_excluded_by_existing_contract": len(duplicate_master_ids),
            "blank_master_id_rows_excluded_by_existing_contract": blank_id_rows,
            "source_master_row_count": master_source_rows,
            "candidate_universe_policy_change": False,
        },
        "split": {
            "method": "deterministic traveler-group split from existing Issue #80 helper",
            "seed": SPLIT_SEED,
            "validation_fraction": VALIDATION_FRACTION,
            "inner_train_trip_count": sum(value == "inner-train" for value in partition_by_trip.values()),
            "inner_validation_trip_count": sum(value == "inner-validation" for value in partition_by_trip.values()),
            "inner_train_traveler_count": traveler_train_count,
            "inner_validation_traveler_count": traveler_validation_count,
            "traveler_overlap_count": overlap_count,
            "inner_validation_rows_or_feedback_used_for_features": False,
        },
        "static_feature_availability": {
            "candidate_count": candidate_count,
            "canonical_admin_sido_nonmissing_count": canonical_sido_count,
            "canonical_admin_sgg_nonmissing_count": canonical_sgg_count,
            "source_category_nonmissing_count_by_level": dict(static_codes),
            "all_three_source_categories_nonmissing_count": all_three_static_count,
            "any_source_category_nonmissing_count": any_static_category_count,
            "source_classification_is_static_other": True,
            "VISIT_AREA_TYPE_CD_is_static_classification": False,
        },
        "inner_train_observed_visit_summary": {
            **visit_summary,
            "structurally_valid_inner_train_visit_event_rows": len(inner_train_valid_events),
            "inner_train_visit_event_rows_without_poi_id": sum(
                _clean_str(row.get("POI_ID")) is None for row in inner_train_valid_events
            ),
            "inner_train_visit_event_rows_linked_to_candidate_universe": len(inner_train_events),
            "tourism_core_trip_poi_pairs_in_candidate_universe": (
                visit_summary["visit_pair_type_counts_inner_train_in_candidate_universe"]["tourism_core"]
            ),
            "non_tourism_actual_visit_pairs_are_unobserved": False,
            "observed_visit_pair_is_a_preference_label": False,
            "label_zero_or_negative_sample_created": False,
        },
        "support_by_cohort": support_summary,
        "visitor_context_profile_availability": profile_availability,
        "feature_contract": {
            "service_reproducibility_groups": list(SERVICE_FEATURE_CONTRACT),
            "cohort_choice_or_feature_adoption_made": False,
            "profile_fields": list(PROFILE_FIELDS),
            "profile_unit": "one row per unique inner-train trip-POI pair",
            "profile_missing_policy": "field denominator excludes missing responses; zero denominator yields null share",
            "static_category_source": "TN_POI_MASTER.ASORT_LCLASDC / ASORT_MLSFCDC / ASORT_SDASDC",
            "event_type_source": "TN_VISIT_AREA_INFO.VISIT_AREA_TYPE_CD, historical event only",
            "post_visit_feedback": "excluded; no feedback fields are selected or read",
            "cold_item_policy": {
                "static_fields_retained": True,
                "all_history_support_counts": 0,
                "tourism_core_support_counts": 0,
                "profile_shares": None,
                "negative_label_or_dislike_implied": False,
            },
        },
        "baseline_comparison": comparison,
        "privacy": {
            "raw_ids_written": False,
            "raw_rows_written": False,
            "per_item_features_written": False,
            "aggregate_only_output": True,
            "row_level_identifiers_serialized": False,
            "small_cell_suppression_applied": False,
            "stdout_summary_only": True,
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = _SafeArgumentParser(
        description="Build inner-train-only POI features and emit aggregate-only audit results"
    )
    parser.add_argument(
        "--run-id",
        required=True,
        help="Stable non-sensitive run identifier (letters, digits, dot, underscore, hyphen)",
    )
    parser.add_argument(
        "--terms-confirmed",
        action="store_true",
        help="Confirm applicable terms and handling conditions were rechecked before opening rows",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", args.run_id):
        parser.error("Invalid --run-id; details are suppressed")
    if not args.terms_confirmed:
        parser.error("Recheck applicable terms and handling conditions before row access")
    try:
        # Imported source loaders emit progress JSON; keep aggregate details out of stdout.
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            payload = _run_audit(run_id=args.run_id, terms_confirmed=args.terms_confirmed)
            output_path = DEFAULT_OUTPUT_DIR / f"{args.run_id}.json"
            _write_aggregate(output_path, payload)
    except Exception:
        print(
            json.dumps({"status": "stopped"}, sort_keys=True),
            file=sys.stderr,
            flush=True,
        )
        return 2
    print(json.dumps({"status": "complete"}, sort_keys=True), flush=True)
    return 0


# Shared configuration objects keep the existing feature normalizer authoritative.
_STATIC_NORMALIZATION_CONFIG = ExperimentConfig(
    feature_groups=("I1_CATEGORY",),
    category_depth=3,
    seed=SPLIT_SEED,
    popularity_transform="raw",
)


if __name__ == "__main__":
    raise SystemExit(main())
