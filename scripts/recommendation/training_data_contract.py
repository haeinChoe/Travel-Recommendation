"""Training data composition, cohort eligibility, and Feature/Label contract (Issue #71).

This module formalizes the training data contract for 2023 AI Hub Domestic Travel Log
recommendation experiments and unseen TourAPI serving compatibility:

1. Independence from TourAPI Identifier Matching:
   Training observation eligibility MUST NOT depend on TourAPI catalog match status
   (`MATCHED`, `AMBIGUOUS`, `UNMATCHED`, `identity_source_missing`).
2. Identifier Key vs Model Feature Boundary:
   `TRAVELER_ID`, `TRAVEL_ID`, `VISIT_AREA_ID`, `POI_ID`, and `contentid` are strictly
   in-memory join, deduplication, grouping, and split-validation keys — never model features.
3. 3-Level Observation Grain:
   - `visit_event_grain`: `(region, TRAVEL_ID, VISIT_AREA_ID)`
   - `trip_poi_grain`: `(region, TRAVEL_ID, POI_ID)` (deduplicated binary `observed_positive = 1`)
   - `trip_request_grain`: `(region, TRAVELER_ID, TRAVEL_ID)` (split integrity unit)
4. 2-Tier Cohort Separation:
   - Structural validity (`missing_or_unmapped_trip`, `missing_or_ambiguous_traveler`,
     `missing_poi_id`, `invalid_value_or_date`)
   - Tourism domain separation (`tourism_core_cohort` vs `non_tourism_cohort` by `VISIT_AREA_TYPE_CD`)
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Iterable, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.recommendation.experiment_design_audit import (
    CATALOG_MATCH_STATUS_FILTERS,
    POST_EVENT_VISIT_FIELDS,
    RAW_IDENTIFIER_KEYS,
)
from scripts.recommendation.sgg_crosswalk import SggCrosswalk

RESULTS_ROOT = REPO_ROOT / "results" / "experiments" / "training-data-contract"
REGIONS: tuple[str, ...] = ("capital", "west", "east", "jeju-islands")
SPLITS: tuple[str, ...] = ("TL", "VL")

REGION_ENV_PREFIX: dict[str, str] = {
    "capital": "CAPITAL",
    "west": "WEST",
    "east": "EAST",
    "jeju-islands": "JEJU",
}

# 3-Level Observation Grain Definitions
OBSERVATION_GRAINS: dict[str, tuple[str, ...]] = {
    "visit_event_grain": ("region", "TRAVEL_ID", "VISIT_AREA_ID"),
    "trip_poi_grain": ("region", "TRAVEL_ID", "POI_ID"),
    "trip_request_grain": ("region", "TRAVELER_ID", "TRAVEL_ID"),
}

# Primary Context Feature Groups
STYLE_FEATURES: tuple[str, ...] = tuple(f"TRAVEL_STYL_{i}" for i in range(1, 9))
MOTIVE_FEATURES: tuple[str, ...] = tuple(f"TRAVEL_MOTIVE_{i}" for i in range(1, 4))
DESTINATION_FEATURES: tuple[str, ...] = ("region", "TRAVEL_STATUS_DESTINATION")
COMPANION_FEATURES: tuple[str, ...] = ("TRAVEL_STATUS_ACCOMPANY", "TRAVEL_COMPANIONS_NUM")
TEMPORAL_FEATURES: tuple[str, ...] = ("month", "elapsed_days")

PRIMARY_CONTEXT_FEATURE_GROUPS: dict[str, tuple[str, ...]] = {
    "STYLE": STYLE_FEATURES,
    "MOTIVE": MOTIVE_FEATURES,
    "DESTINATION": DESTINATION_FEATURES,
    "COMPANION": COMPANION_FEATURES,
    "TEMPORAL": TEMPORAL_FEATURES,
}

PRIMARY_CONTEXT_FEATURES: tuple[str, ...] = (
    *STYLE_FEATURES,
    *MOTIVE_FEATURES,
    *DESTINATION_FEATURES,
    *COMPANION_FEATURES,
    *TEMPORAL_FEATURES,
)

SENSITIVITY_ONLY_CONTEXT_FEATURES: tuple[str, ...] = ("companion_relation_codes",)

BASIC_ITEM_FEATURES: tuple[str, ...] = ("region", "VISIT_AREA_TYPE_CD", "SGG_CD")
RICHER_ITEM_MASTER_FEATURES: tuple[str, ...] = (
    "SGG_CD",
    "ASORT_LCLASDC",
    "ASORT_MLSFCDC",
    "ASORT_SDASDC",
)
TRAIN_DERIVED_ITEM_FEATURES: tuple[str, ...] = ("tl_popularity", "popularity_band")

AUXILIARY_POST_VISIT_LABELS: tuple[str, ...] = (
    "DGSTFN",
    "REVISIT_INTENTION",
    "RCMDTN_INTENTION",
)

DEMOGRAPHIC_EXCLUDED_FEATURES: frozenset[str] = frozenset({
    "GENDER",
    "AGE_GRP",
    "INCOME",
    "HOUSE_INCOME",
    "EDU_NM",
    "EDU_FNSH_SE",
    "MARR_STTS",
    "JOB_NM",
    "JOB_ETC",
    "RESIDENCE_SGG_CODE",
})

UNRESOLVED_OR_RAW_EXCLUDED_FEATURES: frozenset[str] = frozenset({
    "TRAVEL_MISSION",
    "TRAVEL_MISSION_CHECK",
    "season",
    "TRAVEL_START_YMD",
    "TRAVEL_END_YMD",
    "VISIT_AREA_NM",
    "POI_NM",
    "ROAD_NM_ADDR",
    "LOTNO_ADDR",
    "X_COORD",
    "Y_COORD",
    "IMG_CAPTION",
    "PHOTO_FILE_ID",
    "LODGING_TYPE_CD",
})

# Documented Code Domains
STYLE_DOMAIN: frozenset[str] = frozenset(str(i) for i in range(1, 8))
MOTIVE_DOMAIN: frozenset[str] = frozenset(str(i) for i in range(1, 11))
COMPANION_REL_DOMAIN: frozenset[str] = frozenset(str(i) for i in range(1, 12))
FEEDBACK_DOMAIN: frozenset[str] = frozenset(str(i) for i in range(1, 6))

# Tourism Core vs Non-Tourism Visit Area Type Cohorts (TN_VISIT_AREA_INFO.VISIT_AREA_TYPE_CD, TC_CODEB cd_a='VIS')
TOURISM_CORE_VISIT_AREA_TYPES: frozenset[str] = frozenset({
    "1",   # 자연관광지
    "2",   # 역사/유적/종교 시설(문화재, 박물관, 촬영지, 절 등)
    "3",   # 문화 시설(공연장, 영화관, 전시관 등)
    "5",   # 레저/스포츠 관련 시설(스키, 카트, 수상레저)
    "6",   # 테마시설(놀이공원, 워터파크)
    "7",   # 산책로, 둘레길 등
    "8",   # 지역 축제/행사
    "12",  # 기타 (TC_CODEB cd_a='VIS' 원문 명칭 '기타'; 순수 관광/비관광 경계에서 주의 필요)
    "13",  # 체험 활동 관광지
})

NON_TOURISM_VISIT_AREA_TYPES: frozenset[str] = frozenset({
    "4",   # 상업지구(거리, 시장, 쇼핑시설)
    "9",   # 역, 터미널, 고속도로 휴게소
    "10",  # 상점
    "11",  # 식당/카페
    "21",  # 집
    "22",  # 친구/친지집
    "23",  # 사무실
    "24",  # 숙소
})

VISIT_AREA_TYPE_DOMAIN: frozenset[str] = (
    TOURISM_CORE_VISIT_AREA_TYPES | NON_TOURISM_VISIT_AREA_TYPES
)

# Exact official cd_b -> cd_nm mapping from 4-region TC_CODEB (cd_a == 'VIS')
VISIT_AREA_TYPE_LABELS: dict[str, str] = {
    "1": "자연관광지",
    "2": "역사/유적/종교 시설(문화재, 박물관, 촬영지, 절 등)",
    "3": "문화 시설(공연장, 영화관, 전시관 등)",
    "4": "상업지구(거리, 시장, 쇼핑시설)",
    "5": "레저/스포츠 관련 시설(스키, 카트, 수상레저)",
    "6": "테마시설(놀이공원, 워터파크)",
    "7": "산책로, 둘레길 등",
    "8": "지역 축제/행사",
    "9": "역, 터미널, 고속도로 휴게소",
    "10": "상점",
    "11": "식당/카페",
    "12": "기타",
    "13": "체험 활동 관광지",
    "21": "집",
    "22": "친구/친지집",
    "23": "사무실",
    "24": "숙소",
}

FIELD_CODE_DOMAINS: dict[str, frozenset[str]] = {
    **{field_name: STYLE_DOMAIN for field_name in STYLE_FEATURES},
    **{field_name: MOTIVE_DOMAIN for field_name in MOTIVE_FEATURES},
    "REL_CD": COMPANION_REL_DOMAIN,
    "VISIT_AREA_TYPE_CD": VISIT_AREA_TYPE_DOMAIN,
    **{field_name: FEEDBACK_DOMAIN for field_name in AUXILIARY_POST_VISIT_LABELS},
}


@dataclass(frozen=True)
class TemporalFeatures:
    month: str | None
    elapsed_days: int | None
    is_valid: bool
    invalid_reason: str | None = None


@dataclass(frozen=True)
class ObservationEligibility:
    region: str
    structurally_valid_visit_event: bool
    structurally_valid_trip_poi: bool
    domain_cohort: str  # "tourism_core", "non_tourism", or "excluded_structural"
    exclusion_reasons: tuple[str, ...]
    observed_positive: int  # 1 if structurally_valid_visit_event else 0
    is_tourism_core_positive: bool


@dataclass(frozen=True)
class TripPoiPositive:
    region: str
    traveler_id: str
    travel_id: str
    poi_id: str
    observed_positive: int
    repeat_visit_count: int
    has_tourism_core_visit: bool
    visit_area_types: tuple[str, ...]
    sgg_codes: tuple[str, ...]


def _clean_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text != "" else None


def validate_code_domain(field_name: str, raw_value: object) -> str | None:
    """Validate a categorical code against its documented AI Hub domain.

    Returns the cleaned string when valid, or `None` when missing or out of domain
    (never imputing an arbitrary replacement value).
    """
    cleaned = _clean_str(raw_value)
    if cleaned is None:
        return None
    allowed = FIELD_CODE_DOMAINS.get(field_name)
    if allowed is not None and cleaned not in allowed:
        return None
    return cleaned


def validate_companions_num(raw_value: object) -> int | None:
    """Validate TRAVEL_COMPANIONS_NUM as an integer >= 0."""
    cleaned = _clean_str(raw_value)
    if cleaned is None:
        return None
    try:
        parsed = int(cleaned)
    except ValueError:
        try:
            float_val = float(cleaned)
            if not float_val.is_integer():
                return None
            parsed = int(float_val)
        except ValueError:
            return None
    return parsed if parsed >= 0 else None


def derive_temporal_features(
    start_ymd: str | None,
    end_ymd: str | None,
) -> TemporalFeatures:
    """Derive privacy-safe `month` and `elapsed_days` from raw start/end YMD strings.

    Raw dates are never returned or stored. Inverted dates (`end < start`) or
    unparseable strings return `None` without arbitrary imputation.
    """
    start_clean = _clean_str(start_ymd)
    end_clean = _clean_str(end_ymd)
    if start_clean is None or end_clean is None:
        return TemporalFeatures(
            month=None,
            elapsed_days=None,
            is_valid=False,
            invalid_reason="missing_start_or_end_date",
        )
    try:
        start_dt = date.fromisoformat(start_clean)
        end_dt = date.fromisoformat(end_clean)
    except ValueError:
        return TemporalFeatures(
            month=None,
            elapsed_days=None,
            is_valid=False,
            invalid_reason="unparseable_date",
        )

    month_str = f"{start_dt.month:02d}"
    delta_days = (end_dt - start_dt).days
    if delta_days < 0:
        return TemporalFeatures(
            month=month_str,
            elapsed_days=None,
            is_valid=False,
            invalid_reason="inverted_date_range",
        )
    return TemporalFeatures(
        month=month_str,
        elapsed_days=delta_days,
        is_valid=True,
        invalid_reason=None,
    )


def derive_companion_relation_codes(
    companion_rows: Iterable[Mapping[str, object]],
) -> tuple[str, ...] | None:
    """Derive sorted unique tuple of valid `REL_CD` values for recorded-only sensitivity."""
    codes: set[str] = set()
    for row in companion_rows:
        valid_rel = validate_code_domain("REL_CD", row.get("REL_CD"))
        if valid_rel is not None:
            codes.add(valid_rel)
    if not codes:
        return None
    return tuple(sorted(codes, key=lambda x: int(x)))


def resolve_sgg_code_parity(
    sgg_cd: str | None,
    sgg_crosswalk: SggCrosswalk | None = None,
) -> tuple[str, str] | None:
    """Check whether an AI Hub `SGG_CD` maps to a TourAPI `(lDongRegnCd, lDongSignguCd)` pair.

    Returns `(tour_regn, tour_signgu)` when compatible, or `None` when missing/unmapped.
    """
    cleaned = _clean_str(sgg_cd)
    if cleaned is None or len(cleaned) < 5 or not cleaned[:5].isdigit():
        return None
    code_5 = cleaned[:5]
    if sgg_crosswalk is not None and code_5 in sgg_crosswalk.aihub_to_tour:
        return sgg_crosswalk.aihub_to_tour[code_5]
    c1, c2 = code_5[:2], code_5[2:5]
    cw = sgg_crosswalk if sgg_crosswalk is not None else SggCrosswalk()
    return cw._resolve_tour_pair(code_5, c1, c2)


def validate_feature_contract(
    feature_names: Iterable[str],
    *,
    filter_by_catalog_match_status: bool = False,
    catalog_match_status_filter: str | None = None,
) -> tuple[str, ...]:
    """Validate that a candidate feature list and cohort filter obey the Issue #71 contract."""
    violations: list[str] = []
    feature_set = set(feature_names)

    if feature_set & RAW_IDENTIFIER_KEYS:
        violations.append("raw_identifiers_are_join_keys_not_model_features")
    if feature_set & POST_EVENT_VISIT_FIELDS:
        violations.append("post_event_feedback_is_unavailable_at_request_time")
    if feature_set & DEMOGRAPHIC_EXCLUDED_FEATURES:
        violations.append("demographics_excluded_from_default_model_features")
    if feature_set & UNRESOLVED_OR_RAW_EXCLUDED_FEATURES:
        violations.append("raw_or_unresolved_fields_excluded_from_model_features")
    if (
        filter_by_catalog_match_status
        or (catalog_match_status_filter in CATALOG_MATCH_STATUS_FILTERS)
    ):
        violations.append("training_eligibility_must_not_depend_on_catalog_match_status")

    return tuple(violations)


def check_split_trip_leakage(
    tl_trip_ids: set[str],
    vl_trip_ids: set[str],
) -> int:
    """Return the count of overlapping `TRAVEL_ID`s between TL and VL."""
    return len(tl_trip_ids & vl_trip_ids)


def validate_vis_codebook_rows(
    rows: Iterable[Mapping[str, object]],
) -> dict[str, object]:
    """Validate `TC_CODEB` rows for `cd_a == 'VIS'` against `VISIT_AREA_TYPE_LABELS` and cohort sets.

    Ensures:
    1. Every `cd_a == 'VIS'` entry in `TC_CODEB` matches `VISIT_AREA_TYPE_LABELS[cd_b]`.
    2. The union of `TOURISM_CORE_VISIT_AREA_TYPES` and `NON_TOURISM_VISIT_AREA_TYPES`
       is disjoint and exactly covers all 17 `VIS` codes (`1..13, 21..24`).
    """
    observed_vis: dict[str, str] = {}
    duplicate_codes: list[str] = []

    for row in rows:
        norm = {
            str(k).strip().upper(): (str(v).strip() if v is not None else "")
            for k, v in row.items()
            if k is not None
        }
        if norm.get("CD_A") != "VIS":
            continue
        cd_b = norm.get("CD_B", "")
        cd_nm = norm.get("CD_NM", "")
        if not cd_b:
            continue
        if cd_b in observed_vis and observed_vis[cd_b] != cd_nm:
            duplicate_codes.append(cd_b)
        observed_vis[cd_b] = cd_nm

    expected_keys = set(VISIT_AREA_TYPE_LABELS.keys())
    observed_keys = set(observed_vis.keys())
    missing_codes = sorted(expected_keys - observed_keys)
    unexpected_codes = sorted(observed_keys - expected_keys)
    label_mismatches = sorted(
        code
        for code in (expected_keys & observed_keys)
        if observed_vis[code] != VISIT_AREA_TYPE_LABELS[code]
    )
    cohort_overlap = sorted(TOURISM_CORE_VISIT_AREA_TYPES & NON_TOURISM_VISIT_AREA_TYPES)
    unmapped_in_cohorts = sorted(
        observed_keys - (TOURISM_CORE_VISIT_AREA_TYPES | NON_TOURISM_VISIT_AREA_TYPES)
    )

    verified = (
        len(observed_vis) == len(VISIT_AREA_TYPE_LABELS)
        and not duplicate_codes
        and not missing_codes
        and not unexpected_codes
        and not label_mismatches
        and not cohort_overlap
        and not unmapped_in_cohorts
    )
    return {
        "vis_codebook_verified": verified,
        "verified_code_count": len(observed_vis),
        "missing_codes": missing_codes,
        "unexpected_codes": unexpected_codes,
        "label_mismatches": label_mismatches,
        "duplicate_conflicting_codes": duplicate_codes,
        "cohort_overlap_codes": cohort_overlap,
        "unmapped_cohort_codes": unmapped_in_cohorts,
    }


def evaluate_visit_observation(
    *,
    region: str,
    travel_id: str | None,
    visit_area_id: str | None,
    poi_id: str | None,
    visit_area_type_cd: str | None,
    trip_exists_unique: bool,
    traveler_exists_unique: bool,
    catalog_match_status: str | None = None,
) -> ObservationEligibility:
    """Classify a single visit row's structural validity and tourism cohort eligibility.

    Crucially, `catalog_match_status` (`MATCHED`, `AMBIGUOUS`, `UNMATCHED`,
    `identity_source_missing`) is ignored for eligibility so that training cohorts
    never depend on TourAPI identifier matching.
    """
    _ = catalog_match_status  # Explicitly unused: eligibility is match-status independent.

    reasons: list[str] = []
    clean_trip = _clean_str(travel_id)
    clean_visit_id = _clean_str(visit_area_id)
    clean_poi = _clean_str(poi_id)
    valid_type = validate_code_domain("VISIT_AREA_TYPE_CD", visit_area_type_cd)

    if clean_trip is None or not trip_exists_unique:
        reasons.append("missing_or_unmapped_trip")
    elif not traveler_exists_unique:
        reasons.append("missing_or_ambiguous_traveler")

    if clean_visit_id is None:
        reasons.append("missing_visit_area_id")

    structurally_valid_visit_event = len(reasons) == 0

    if clean_poi is None:
        reasons.append("missing_poi_id")

    structurally_valid_trip_poi = structurally_valid_visit_event and (clean_poi is not None)

    if not structurally_valid_visit_event:
        domain_cohort = "excluded_structural"
        is_tourism_core = False
    elif valid_type in TOURISM_CORE_VISIT_AREA_TYPES:
        domain_cohort = "tourism_core"
        is_tourism_core = True
    else:
        domain_cohort = "non_tourism"
        is_tourism_core = False
        if _clean_str(visit_area_type_cd) is None or valid_type is None:
            reasons.append("missing_or_invalid_visit_area_type")
        else:
            reasons.append("non_tourism_visit_area_type")

    return ObservationEligibility(
        region=region,
        structurally_valid_visit_event=structurally_valid_visit_event,
        structurally_valid_trip_poi=structurally_valid_trip_poi,
        domain_cohort=domain_cohort,
        exclusion_reasons=tuple(reasons),
        observed_positive=1 if structurally_valid_visit_event else 0,
        is_tourism_core_positive=structurally_valid_trip_poi and is_tourism_core,
    )


def build_trip_poi_positives(
    visit_rows: Iterable[Mapping[str, object]],
    *,
    region: str,
    trip_to_traveler: Mapping[str, str | None],
    valid_traveler_ids: set[str] | None = None,
) -> tuple[list[TripPoiPositive], dict[str, int]]:
    """Deduplicate visit events to `(region, TRAVEL_ID, POI_ID)` binary positives.

    Preserves repeat-visit counts as a diagnostic while assigning binary
    `observed_positive = 1` per distinct `(region, TRAVEL_ID, POI_ID)`.
    """
    grouped_counts: Counter[tuple[str, str, str]] = Counter()
    grouped_traveler: dict[tuple[str, str, str], str] = {}
    grouped_types: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    grouped_sggs: dict[tuple[str, str, str], set[str]] = defaultdict(set)

    total_rows = 0
    valid_visit_events = 0
    missing_poi_rows = 0
    unmapped_trip_rows = 0
    ambiguous_traveler_rows = 0

    for row in visit_rows:
        total_rows += 1
        trip_id = _clean_str(row.get("TRAVEL_ID"))
        visit_id = _clean_str(row.get("VISIT_AREA_ID"))
        poi_id = _clean_str(row.get("POI_ID"))
        v_type = validate_code_domain("VISIT_AREA_TYPE_CD", row.get("VISIT_AREA_TYPE_CD"))
        sgg_cd = _clean_str(row.get("SGG_CD"))

        if trip_id is None or trip_id not in trip_to_traveler:
            unmapped_trip_rows += 1
            continue
        traveler_id = trip_to_traveler[trip_id]
        if traveler_id is None or (
            valid_traveler_ids is not None and traveler_id not in valid_traveler_ids
        ):
            ambiguous_traveler_rows += 1
            continue
        if visit_id is None:
            continue

        valid_visit_events += 1
        if poi_id is None:
            missing_poi_rows += 1
            continue

        key = (region, trip_id, poi_id)
        grouped_counts[key] += 1
        grouped_traveler[key] = traveler_id
        if v_type is not None:
            grouped_types[key].add(v_type)
        if sgg_cd is not None:
            grouped_sggs[key].add(sgg_cd)

    positives: list[TripPoiPositive] = []
    repeat_pairs = 0
    repeated_extra_events = 0
    tourism_core_pairs = 0

    for key in sorted(grouped_counts.keys()):
        reg, tr_id, p_id = key
        cnt = grouped_counts[key]
        if cnt > 1:
            repeat_pairs += 1
            repeated_extra_events += cnt - 1
        types_sorted = tuple(sorted(grouped_types[key]))
        has_core = any(t in TOURISM_CORE_VISIT_AREA_TYPES for t in types_sorted)
        if has_core:
            tourism_core_pairs += 1
        positives.append(
            TripPoiPositive(
                region=reg,
                traveler_id=grouped_traveler[key],
                travel_id=tr_id,
                poi_id=p_id,
                observed_positive=1,
                repeat_visit_count=cnt,
                has_tourism_core_visit=has_core,
                visit_area_types=types_sorted,
                sgg_codes=tuple(sorted(grouped_sggs[key])),
            )
        )

    diagnostics = {
        "total_visit_rows": total_rows,
        "valid_visit_event_rows": valid_visit_events,
        "missing_poi_visit_rows": missing_poi_rows,
        "unmapped_trip_visit_rows": unmapped_trip_rows,
        "ambiguous_traveler_visit_rows": ambiguous_traveler_rows,
        "distinct_trip_poi_positives": len(positives),
        "tourism_core_trip_poi_positives": tourism_core_pairs,
        "non_tourism_only_trip_poi_positives": len(positives) - tourism_core_pairs,
        "within_trip_repeat_poi_pairs": repeat_pairs,
        "within_trip_repeat_extra_events": repeated_extra_events,
    }
    return positives, diagnostics


def _find_csv_case_insensitive(folder: Path, keyword: str) -> list[Path]:
    kw_lower = keyword.casefold()
    matches = [
        p
        for p in folder.glob("*.csv")
        if kw_lower in p.name.casefold() and not p.is_symlink()
    ]
    return sorted(matches)


def _load_master_poi_summary(
    other_dir: Path,
) -> tuple[set[str], set[str], dict[str, str], int, int]:
    """Load unique POI_IDs, rich-attribute POI_IDs, and master SGG_CDs from TN_POI_MASTER."""
    candidates = [
        other_dir / "메타데이터" / "tn_poi_master_POIMaster_all.csv",
        other_dir / "tn_poi_master_POIMaster_all.csv",
    ]
    target: Path | None = next((p for p in candidates if p.exists()), None)
    if target is None:
        found = sorted(other_dir.glob("**/*poi_master*.csv")) + sorted(
            other_dir.glob("**/*POI*Master*.csv")
        )
        if not found:
            raise FileNotFoundError("TN_POI_MASTER CSV not found in bound OTHER root")
        target = found[0]

    counts: Counter[str] = Counter()
    master_sgg_by_id: dict[str, str] = {}
    rich_complete_ids: set[str] = set()
    total_rows = 0

    with target.open("r", encoding="utf-8-sig", errors="replace") as stream:
        reader = csv.reader(stream)
        header = [h.strip() for h in next(reader)]
        idx_id = header.index("POI_ID")
        idx_sgg = header.index("SGG_CD") if "SGG_CD" in header else -1
        idx_l = header.index("ASORT_LCLASDC") if "ASORT_LCLASDC" in header else -1
        idx_m = header.index("ASORT_MLSFCDC") if "ASORT_MLSFCDC" in header else -1
        idx_s = header.index("ASORT_SDASDC") if "ASORT_SDASDC" in header else -1

        for row in reader:
            total_rows += 1
            if len(row) <= idx_id:
                continue
            pid = row[idx_id].strip()
            if not pid:
                continue
            counts[pid] += 1
            if idx_sgg >= 0 and len(row) > idx_sgg:
                sgg_val = row[idx_sgg].strip()
                if sgg_val:
                    master_sgg_by_id[pid] = sgg_val
            if (
                idx_sgg >= 0
                and idx_l >= 0
                and idx_m >= 0
                and idx_s >= 0
                and len(row) > max(idx_sgg, idx_l, idx_m, idx_s)
            ):
                if (
                    row[idx_sgg].strip()
                    and row[idx_l].strip()
                    and row[idx_m].strip()
                    and row[idx_s].strip()
                ):
                    rich_complete_ids.add(pid)

    unique_ids = {pid for pid, c in counts.items() if c == 1}
    duplicate_ids = sum(1 for c in counts.values() if c > 1)
    unique_master_sgg = {pid: sgg for pid, sgg in master_sgg_by_id.items() if pid in unique_ids}
    return unique_ids, (rich_complete_ids & unique_ids), unique_master_sgg, total_rows, duplicate_ids


def _load_sgg_crosswalk_from_env() -> SggCrosswalk:
    sgg_paths: list[Path] = []
    for region in REGIONS:
        prefix = REGION_ENV_PREFIX[region]
        for split in SPLITS:
            env_val = os.environ.get(f"{prefix}_{split}")
            if env_val:
                folder = Path(env_val).resolve()
                for f in _find_csv_case_insensitive(folder, "tc_sgg"):
                    if f not in sgg_paths:
                        sgg_paths.append(f)
    cw = SggCrosswalk()
    if sgg_paths:
        cw.load_from_csvs(sgg_paths)
    return cw


def make_master_cache_key(file_path: Path) -> tuple[str, int, int]:
    """Generate a collision-resistant cache key for TN_POI_MASTER file.

    Includes resolved path, file size in bytes, and nanosecond modification time.
    """
    resolved = file_path.resolve()
    stat = resolved.stat()
    return (str(resolved), stat.st_size, stat.st_mtime_ns)


def audit_training_data_contract(
    *,
    output_dir: Path = RESULTS_ROOT,
    run_id: str | None = None,
) -> dict[str, object]:
    """Run the 4-region TL/VL cohort & feature/label contract audit.

    Reads approved raw inputs read-only, keeps raw IDs in memory only, and returns
    exact non-identifying aggregate metrics.
    """
    t0 = time.time()
    sgg_crosswalk = _load_sgg_crosswalk_from_env()

    # Load shared TN_POI_MASTER once if all regions point to the same file or per region
    master_cache_by_mtime: dict[tuple[str, int, int], tuple[set[str], set[str], dict[str, str], int, int]] = {}

    split_metrics: dict[str, dict[str, object]] = {}
    tl_trips_by_region: dict[str, set[str]] = {}
    vl_trips_by_region: dict[str, set[str]] = {}
    tl_all_pois_by_region: dict[str, set[str]] = defaultdict(set)
    tl_core_pois_by_region: dict[str, set[str]] = defaultdict(set)
    vl_all_positives_by_region: dict[str, list[TripPoiPositive]] = defaultdict(list)

    # Aggregate counters across all 4 regions × 2 splits
    agg_totals: Counter[str] = Counter()
    agg_tl_totals: Counter[str] = Counter()
    agg_vl_totals: Counter[str] = Counter()
    agg_type_counts: Counter[str] = Counter()
    agg_tl_type_counts: Counter[str] = Counter()
    agg_vl_type_counts: Counter[str] = Counter()

    for region in REGIONS:
        prefix = REGION_ENV_PREFIX[region]
        other_val = os.environ.get(f"{prefix}_OTHER") or os.environ.get("CAPITAL_OTHER")
        if not other_val:
            raise FileNotFoundError(f"Missing {prefix}_OTHER environment variable")
        other_path = Path(other_val).resolve()

        # Check cache key by stat of master file
        candidates = [
            other_path / "메타데이터" / "tn_poi_master_POIMaster_all.csv",
            other_path / "tn_poi_master_POIMaster_all.csv",
        ]
        master_file = next((p for p in candidates if p.exists()), None)
        if master_file is None:
            found = sorted(other_path.glob("**/*poi_master*.csv")) + sorted(
                other_path.glob("**/*POI*Master*.csv")
            )
            if not found:
                raise FileNotFoundError("TN_POI_MASTER file not found")
            master_file = found[0]
        stat_key = make_master_cache_key(master_file)
        if stat_key not in master_cache_by_mtime:
            master_cache_by_mtime[stat_key] = _load_master_poi_summary(other_path)
        master_unique_ids, master_rich_ids, master_sgg_by_id, master_rows, master_dup_keys = (
            master_cache_by_mtime[stat_key]
        )

        for split in SPLITS:
            split_env = os.environ.get(f"{prefix}_{split}")
            if not split_env:
                raise FileNotFoundError(f"Missing {prefix}_{split} environment variable")
            split_dir = Path(split_env).resolve()

            travel_files = _find_csv_case_insensitive(split_dir, "tn_travel_")
            if not travel_files:
                travel_files = [
                    p
                    for p in _find_csv_case_insensitive(split_dir, "tn_travel")
                    if "traveller" not in p.name.casefold()
                ]
            master_files = _find_csv_case_insensitive(split_dir, "tn_traveller_master")
            companion_files = _find_csv_case_insensitive(split_dir, "tn_companion_info")
            visit_files = _find_csv_case_insensitive(split_dir, "tn_visit_area_info")
            codeb_files = _find_csv_case_insensitive(split_dir, "codeb")

            if not (travel_files and master_files and visit_files and codeb_files):
                raise FileNotFoundError(f"Required tables missing in {region}:{split}")

            # 0. Verify TC_CODEB (cd_a == 'VIS') against official contract labels
            with codeb_files[0].open("r", encoding="utf-8-sig", errors="replace") as f:
                vis_check = validate_vis_codebook_rows(csv.DictReader(f))
            if not vis_check["vis_codebook_verified"]:
                raise ValueError(
                    f"TC_CODEB VIS verification failed for {region}:{split}: {vis_check}"
                )

            # 1. Read TN_TRAVELLER_MASTER
            traveler_rows_by_id: dict[str, list[dict[str, str]]] = defaultdict(list)
            with master_files[0].open("r", encoding="utf-8-sig", errors="replace") as f:
                for row in csv.DictReader(f):
                    tid = _clean_str(row.get("TRAVELER_ID"))
                    if tid is not None:
                        traveler_rows_by_id[tid].append(row)

            unique_travelers: dict[str, dict[str, str]] = {
                tid: rows[0] for tid, rows in traveler_rows_by_id.items() if len(rows) == 1
            }

            # 2. Read TN_TRAVEL
            trip_rows_by_id: dict[str, list[dict[str, str]]] = defaultdict(list)
            with travel_files[0].open("r", encoding="utf-8-sig", errors="replace") as f:
                for row in csv.DictReader(f):
                    tr_id = _clean_str(row.get("TRAVEL_ID"))
                    if tr_id is not None:
                        trip_rows_by_id[tr_id].append(row)

            unique_trips: dict[str, dict[str, str]] = {
                tr_id: rows[0] for tr_id, rows in trip_rows_by_id.items() if len(rows) == 1
            }
            trip_to_traveler: dict[str, str | None] = {}
            for tr_id, row in unique_trips.items():
                owner = _clean_str(row.get("TRAVELER_ID"))
                trip_to_traveler[tr_id] = owner if (owner in unique_travelers) else None

            if split == "TL":
                tl_trips_by_region[region] = set(unique_trips.keys())
            else:
                vl_trips_by_region[region] = set(unique_trips.keys())

            # 3. Read TN_COMPANION_INFO
            companion_by_trip: dict[str, list[dict[str, str]]] = defaultdict(list)
            if companion_files:
                with companion_files[0].open("r", encoding="utf-8-sig", errors="replace") as f:
                    for row in csv.DictReader(f):
                        tr_id = _clean_str(row.get("TRAVEL_ID"))
                        if tr_id is not None:
                            companion_by_trip[tr_id].append(row)

            # Evaluate trip-level context feature completeness (on unique valid trips)
            valid_trip_ids = [
                tr_id for tr_id, owner in trip_to_traveler.items() if owner is not None
            ]
            trip_context_complete: set[str] = set()
            style_complete_trips = 0
            motive_complete_trips = 0
            dest_complete_trips = 0
            comp_complete_trips = 0
            temporal_complete_trips = 0
            inverted_date_trips = 0
            companion_rel_recorded_trips = 0

            for tr_id in valid_trip_ids:
                tr_row = unique_trips[tr_id]
                owner_id = trip_to_traveler[tr_id]
                assert owner_id is not None
                m_row = unique_travelers[owner_id]

                styles_ok = all(
                    validate_code_domain(col, m_row.get(col)) is not None
                    for col in STYLE_FEATURES
                )
                motives_ok = all(
                    validate_code_domain(col, m_row.get(col)) is not None
                    for col in MOTIVE_FEATURES
                )
                dest_ok = _clean_str(m_row.get("TRAVEL_STATUS_DESTINATION")) is not None
                comp_ok = (
                    _clean_str(m_row.get("TRAVEL_STATUS_ACCOMPANY")) is not None
                    and validate_companions_num(m_row.get("TRAVEL_COMPANIONS_NUM")) is not None
                )
                temp = derive_temporal_features(
                    tr_row.get("TRAVEL_START_YMD"),
                    tr_row.get("TRAVEL_END_YMD"),
                )
                if temp.invalid_reason == "inverted_date_range":
                    inverted_date_trips += 1

                if styles_ok:
                    style_complete_trips += 1
                if motives_ok:
                    motive_complete_trips += 1
                if dest_ok:
                    dest_complete_trips += 1
                if comp_ok:
                    comp_complete_trips += 1
                if temp.is_valid:
                    temporal_complete_trips += 1

                if styles_ok and motives_ok and dest_ok and comp_ok and temp.is_valid:
                    trip_context_complete.add(tr_id)

                rel_codes = derive_companion_relation_codes(companion_by_trip.get(tr_id, ()))
                if rel_codes is not None:
                    companion_rel_recorded_trips += 1

            # 4. Read TN_VISIT_AREA_INFO
            visit_rows_raw: list[dict[str, str]] = []
            with visit_files[0].open("r", encoding="utf-8-sig", errors="replace") as f:
                for row in csv.DictReader(f):
                    visit_rows_raw.append(row)

            positives, grain_diag = build_trip_poi_positives(
                visit_rows_raw,
                region=region,
                trip_to_traveler=trip_to_traveler,
                valid_traveler_ids=set(unique_travelers.keys()),
            )

            # Visit-event level cohort & feedback breakdown
            visit_event_tourism_core = 0
            visit_event_non_tourism = 0
            visit_event_with_poi_tourism_core = 0
            visit_event_with_poi_non_tourism = 0
            visit_event_sgg_valid = 0
            visit_event_sgg_parity = 0
            feedback_valid_counts: Counter[str] = Counter()
            feedback_all_three_valid = 0
            type_counter_visit_event: Counter[str] = Counter()

            for row in visit_rows_raw:
                tr_id = _clean_str(row.get("TRAVEL_ID"))
                v_id = _clean_str(row.get("VISIT_AREA_ID"))
                p_id = _clean_str(row.get("POI_ID"))
                v_type_raw = _clean_str(row.get("VISIT_AREA_TYPE_CD"))
                sgg_raw = _clean_str(row.get("SGG_CD"))

                trip_ok = tr_id is not None and tr_id in unique_trips
                traveler_ok = trip_ok and (trip_to_traveler.get(tr_id) is not None)  # type: ignore[arg-type]

                elig = evaluate_visit_observation(
                    region=region,
                    travel_id=tr_id,
                    visit_area_id=v_id,
                    poi_id=p_id,
                    visit_area_type_cd=v_type_raw,
                    trip_exists_unique=trip_ok,
                    traveler_exists_unique=traveler_ok,
                )
                if not elig.structurally_valid_visit_event:
                    continue

                v_type_valid = validate_code_domain("VISIT_AREA_TYPE_CD", v_type_raw) or "invalid_or_missing"
                type_counter_visit_event[v_type_valid] += 1
                agg_type_counts[v_type_valid] += 1
                if split == "TL":
                    agg_tl_type_counts[v_type_valid] += 1
                else:
                    agg_vl_type_counts[v_type_valid] += 1

                if elig.domain_cohort == "tourism_core":
                    visit_event_tourism_core += 1
                    if elig.structurally_valid_trip_poi:
                        visit_event_with_poi_tourism_core += 1
                else:
                    visit_event_non_tourism += 1
                    if elig.structurally_valid_trip_poi:
                        visit_event_with_poi_non_tourism += 1

                if sgg_raw is not None:
                    visit_event_sgg_valid += 1
                    if resolve_sgg_code_parity(sgg_raw, sgg_crosswalk) is not None:
                        visit_event_sgg_parity += 1

                fb_ok_all = True
                for fb_col in AUXILIARY_POST_VISIT_LABELS:
                    if validate_code_domain(fb_col, row.get(fb_col)) is not None:
                        feedback_valid_counts[fb_col] += 1
                    else:
                        fb_ok_all = False
                if fb_ok_all:
                    feedback_all_three_valid += 1

            # Trip-POI level metrics (97,640 universe across all 8 splits)
            trip_poi_all = len(positives)
            trip_poi_core = sum(1 for p in positives if p.has_tourism_core_visit)
            trip_poi_non_tourism = trip_poi_all - trip_poi_core

            trip_poi_context_complete_all = sum(
                1 for p in positives if p.travel_id in trip_context_complete
            )
            trip_poi_context_complete_core = sum(
                1
                for p in positives
                if p.has_tourism_core_visit and p.travel_id in trip_context_complete
            )

            trip_poi_sgg_parity_all = sum(
                1
                for p in positives
                if any(
                    resolve_sgg_code_parity(code, sgg_crosswalk) is not None
                    for code in (
                        *p.sgg_codes,
                        *([master_sgg_by_id[p.poi_id]] if p.poi_id in master_sgg_by_id else []),
                    )
                )
            )
            trip_poi_sgg_parity_core = sum(
                1
                for p in positives
                if p.has_tourism_core_visit
                and any(
                    resolve_sgg_code_parity(code, sgg_crosswalk) is not None
                    for code in (
                        *p.sgg_codes,
                        *([master_sgg_by_id[p.poi_id]] if p.poi_id in master_sgg_by_id else []),
                    )
                )
            )

            trip_poi_master_joined_all = sum(
                1 for p in positives if p.poi_id in master_unique_ids
            )
            trip_poi_master_joined_core = sum(
                1
                for p in positives
                if p.has_tourism_core_visit and p.poi_id in master_unique_ids
            )
            trip_poi_master_rich_all = sum(
                1 for p in positives if p.poi_id in master_rich_ids
            )
            trip_poi_master_rich_core = sum(
                1
                for p in positives
                if p.has_tourism_core_visit and p.poi_id in master_rich_ids
            )

            trips_with_any_poi = len({p.travel_id for p in positives})
            trips_with_core_poi = len({p.travel_id for p in positives if p.has_tourism_core_visit})
            distinct_pois_all = len({p.poi_id for p in positives})
            distinct_pois_core = len({p.poi_id for p in positives if p.has_tourism_core_visit})

            if split == "TL":
                tl_all_pois_by_region[region] = {p.poi_id for p in positives}
                tl_core_pois_by_region[region] = {
                    p.poi_id for p in positives if p.has_tourism_core_visit
                }
            else:
                vl_all_positives_by_region[region] = positives

            cell_key = f"{region}:{split}"
            cell_summary = {
                "region": region,
                "split": split,
                "trips_total": len(unique_trips),
                "trips_valid_owner": len(valid_trip_ids),
                "trips_with_any_poi_visit": trips_with_any_poi,
                "trips_with_tourism_core_visit": trips_with_core_poi,
                "trips_primary_context_complete": len(trip_context_complete),
                "trips_primary_context_complete_rate": round(
                    len(trip_context_complete) / len(valid_trip_ids), 6
                )
                if valid_trip_ids
                else 0.0,
                "trips_style_complete": style_complete_trips,
                "trips_motive_complete": motive_complete_trips,
                "trips_destination_complete": dest_complete_trips,
                "trips_companion_complete": comp_complete_trips,
                "trips_temporal_complete": temporal_complete_trips,
                "trips_inverted_dates": inverted_date_trips,
                "trips_companion_relation_recorded": companion_rel_recorded_trips,
                "visit_rows_total": grain_diag["total_visit_rows"],
                "visit_events_valid": grain_diag["valid_visit_event_rows"],
                "visit_rows_missing_poi_id": grain_diag["missing_poi_visit_rows"],
                "visit_rows_unmapped_trip": grain_diag["unmapped_trip_visit_rows"],
                "visit_rows_ambiguous_traveler": grain_diag["ambiguous_traveler_visit_rows"],
                "visit_events_tourism_core": visit_event_tourism_core,
                "visit_events_non_tourism": visit_event_non_tourism,
                "visit_events_with_poi_tourism_core": visit_event_with_poi_tourism_core,
                "visit_events_with_poi_non_tourism": visit_event_with_poi_non_tourism,
                "visit_events_sgg_nonblank": visit_event_sgg_valid,
                "visit_events_sgg_crosswalk_valid": visit_event_sgg_parity,
                "visit_events_dgstfn_valid": feedback_valid_counts["DGSTFN"],
                "visit_events_revisit_intention_valid": feedback_valid_counts["REVISIT_INTENTION"],
                "visit_events_rcmdtn_intention_valid": feedback_valid_counts["RCMDTN_INTENTION"],
                "visit_events_all_three_feedback_valid": feedback_all_three_valid,
                "trip_poi_positives_all": trip_poi_all,
                "trip_poi_positives_tourism_core": trip_poi_core,
                "trip_poi_positives_non_tourism_only": trip_poi_non_tourism,
                "trip_poi_within_trip_repeat_pairs": grain_diag["within_trip_repeat_poi_pairs"],
                "trip_poi_within_trip_repeat_extra_events": grain_diag[
                    "within_trip_repeat_extra_events"
                ],
                "trip_poi_primary_context_complete_all": trip_poi_context_complete_all,
                "trip_poi_primary_context_complete_tourism_core": trip_poi_context_complete_core,
                "trip_poi_sgg_crosswalk_valid_all": trip_poi_sgg_parity_all,
                "trip_poi_sgg_crosswalk_valid_tourism_core": trip_poi_sgg_parity_core,
                "trip_poi_master_unique_join_all": trip_poi_master_joined_all,
                "trip_poi_master_unique_join_tourism_core": trip_poi_master_joined_core,
                "trip_poi_master_rich_complete_all": trip_poi_master_rich_all,
                "trip_poi_master_rich_complete_tourism_core": trip_poi_master_rich_core,
                "distinct_pois_all": distinct_pois_all,
                "distinct_pois_tourism_core": distinct_pois_core,
                "master_total_rows": master_rows,
                "master_duplicate_poi_keys": master_dup_keys,
                "vis_codebook_verified": bool(vis_check["vis_codebook_verified"]),
                "vis_codebook_verified_code_count": int(vis_check["verified_code_count"]),  # type: ignore[arg-type]
                "vis_codebook_mismatch_count": len(vis_check["label_mismatches"]),  # type: ignore[arg-type]
            }
            split_metrics[cell_key] = cell_summary

            target_counter = agg_tl_totals if split == "TL" else agg_vl_totals
            for metric_name, val in cell_summary.items():
                if (
                    isinstance(val, int)
                    and not isinstance(val, bool)
                    and not metric_name.startswith("master_")
                    and not metric_name.startswith("vis_codebook_")
                ):
                    agg_totals[metric_name] += val
                    target_counter[metric_name] += val

    # Compute TL/VL split overlap & VL cold-start diagnostics per region
    leakage_and_cold_start: dict[str, dict[str, object]] = {}
    total_vl_seen_in_tl_all = 0
    total_vl_seen_in_tl_core = 0

    for region in REGIONS:
        tl_trips = tl_trips_by_region.get(region, set())
        vl_trips = vl_trips_by_region.get(region, set())
        overlap_trips = check_split_trip_leakage(tl_trips, vl_trips)

        tl_pois_all = tl_all_pois_by_region[region]
        tl_pois_core = tl_core_pois_by_region[region]
        vl_pos = vl_all_positives_by_region[region]

        vl_all_cnt = len(vl_pos)
        vl_seen_all = sum(1 for p in vl_pos if p.poi_id in tl_pois_all)
        vl_core_pos = [p for p in vl_pos if p.has_tourism_core_visit]
        vl_core_cnt = len(vl_core_pos)
        vl_seen_core = sum(1 for p in vl_core_pos if p.poi_id in tl_pois_core)

        total_vl_seen_in_tl_all += vl_seen_all
        total_vl_seen_in_tl_core += vl_seen_core

        leakage_and_cold_start[region] = {
            "tl_vl_trip_id_overlap": overlap_trips,
            "vl_trip_poi_positives_all": vl_all_cnt,
            "vl_positives_seen_in_tl_all": vl_seen_all,
            "vl_positives_cold_start_all": vl_all_cnt - vl_seen_all,
            "vl_cold_start_rate_all": round((vl_all_cnt - vl_seen_all) / vl_all_cnt, 6)
            if vl_all_cnt
            else 0.0,
            "vl_trip_poi_positives_tourism_core": vl_core_cnt,
            "vl_positives_seen_in_tl_tourism_core": vl_seen_core,
            "vl_positives_cold_start_tourism_core": vl_core_cnt - vl_seen_core,
            "vl_cold_start_rate_tourism_core": round(
                (vl_core_cnt - vl_seen_core) / vl_core_cnt, 6
            )
            if vl_core_cnt
            else 0.0,
        }

    visit_type_breakdown: list[dict[str, object]] = []
    total_valid_visits = agg_totals["visit_events_valid"]
    for code in sorted(
        agg_type_counts.keys(),
        key=lambda c: int(c) if c.isdigit() else 999,
    ):
        cnt = agg_type_counts[code]
        tl_cnt = agg_tl_type_counts[code]
        vl_cnt = agg_vl_type_counts[code]
        cohort_name = (
            "tourism_core"
            if code in TOURISM_CORE_VISIT_AREA_TYPES
            else "non_tourism"
        )
        visit_type_breakdown.append({
            "visit_area_type_cd": code,
            "label": VISIT_AREA_TYPE_LABELS.get(code, "기타/미상"),
            "domain_cohort": cohort_name,
            "tl_visit_events": tl_cnt,
            "vl_visit_events": vl_cnt,
            "total_visit_events": cnt,
            "share_of_valid_visit_events": round(cnt / total_valid_visits, 6)
            if total_valid_visits
            else 0.0,
        })

    resolved_run_id = run_id or f"issue71-training-contract-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    script_sha256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

    payload: dict[str, object] = {
        "run_id": resolved_run_id,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "elapsed_seconds": round(time.time() - t0, 3),
        "script_sha256": script_sha256,
        "contract_version": "issue-71-v1",
        "tourapi_match_status_independent": True,
        "vis_codebook_verification": {
            "vis_codebook_verified": all(
                bool(m.get("vis_codebook_verified")) for m in split_metrics.values()
            ),
            "splits_verified": len(split_metrics),
            "verified_code_count": len(VISIT_AREA_TYPE_LABELS),
            "cross_region_mismatches": sum(
                int(m.get("vis_codebook_mismatch_count", 0)) for m in split_metrics.values()  # type: ignore[arg-type]
            ),
            "official_cd_b_to_cd_nm": dict(VISIT_AREA_TYPE_LABELS),
        },
        "observation_grains": {k: list(v) for k, v in OBSERVATION_GRAINS.items()},
        "aggregate_totals": {
            "all_splits": dict(agg_totals),
            "tl_only": dict(agg_tl_totals),
            "vl_only": dict(agg_vl_totals),
            "vl_positives_seen_in_tl_all": total_vl_seen_in_tl_all,
            "vl_positives_cold_start_all": agg_vl_totals["trip_poi_positives_all"]
            - total_vl_seen_in_tl_all,
            "vl_positives_seen_in_tl_tourism_core": total_vl_seen_in_tl_core,
            "vl_positives_cold_start_tourism_core": agg_vl_totals[
                "trip_poi_positives_tourism_core"
            ]
            - total_vl_seen_in_tl_core,
        },
        "by_region_split": split_metrics,
        "leakage_and_cold_start_by_region": leakage_and_cold_start,
        "visit_area_type_breakdown": visit_type_breakdown,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "training_data_contract_audit.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    csv_path = output_dir / "cohort_funnel_by_region_split.csv"
    if split_metrics:
        fieldnames = list(next(iter(split_metrics.values())).keys())
        with csv_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row_dict in split_metrics.values():
                writer.writerow(row_dict)

    return payload


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audit 2023 AI Hub travel-log training data cohorts and Feature/Label contract (Issue #71)."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=RESULTS_ROOT,
        help="Git-ignored output directory for privacy-safe aggregate artifacts.",
    )
    parser.add_argument(
        "--run-id",
        type=str,
        default=None,
        help="Optional explicit run identifier.",
    )
    args = parser.parse_args(argv)

    payload = audit_training_data_contract(output_dir=args.output_dir, run_id=args.run_id)
    agg = payload["aggregate_totals"]  # type: ignore[index]
    all_s = agg["all_splits"]  # type: ignore[index]
    print(
        f"Training data contract audit completed: "
        f"trips={all_s['trips_valid_owner']:,}, "
        f"visit_events={all_s['visit_events_valid']:,}, "
        f"trip_poi_positives={all_s['trip_poi_positives_all']:,}, "
        f"tourism_core_trip_poi_positives={all_s['trip_poi_positives_tourism_core']:,}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
