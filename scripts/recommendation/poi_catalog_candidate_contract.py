"""Deterministic, conservative POI identity and candidate eligibility rules.

This module never calls TourAPI. Callers must provide an authorized, versioned
catalog snapshot and explicit product policy. Raw item identifiers are inputs
to in-memory joins and must not be emitted to public artifacts.
"""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Mapping


@dataclass(frozen=True)
class PoiRecord:
    item_id: str
    name: str = ""
    district_code: str = ""
    address: str = ""
    latitude: str = ""
    longitude: str = ""
    category: str = ""
    content_type_id: str = ""
    region_codes: frozenset[str] = frozenset()
    district_codes: frozenset[str] = frozenset()
    catalog_status: str = "unknown"  # active | inactive | unknown


@dataclass(frozen=True)
class MatchResult:
    source_item_id: str
    status: str  # MATCHED | AMBIGUOUS | UNMATCHED
    canonical_item_id: str | None
    method: str | None
    candidate_count: int


def normalize_text(value: str | None) -> str:
    """Normalize Unicode and whitespace only; retain punctuation conservatively."""
    if not value:
        return ""
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def normalize_code(value: str | None) -> str:
    return "".join(unicodedata.normalize("NFKC", value or "").split()).casefold()


def _coord(value: str) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _distance_meters(left: PoiRecord, right: PoiRecord) -> float | None:
    lat1, lon1 = _coord(left.latitude), _coord(left.longitude)
    lat2, lon2 = _coord(right.latitude), _coord(right.longitude)
    if None in (lat1, lon1, lat2, lon2):
        return None
    if not (-90 <= lat1 <= 90 and -90 <= lat2 <= 90 and -180 <= lon1 <= 180 and -180 <= lon2 <= 180):
        return None
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi, dlambda = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 6_371_000 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def match_source_item(
    source: PoiRecord,
    catalog: list[PoiRecord],
    *,
    fuzzy_threshold: float | None = None,
    distance_threshold_m: float | None = None,
    source_category_to_content_types: Mapping[str, frozenset[str]] | None = None,
) -> MatchResult:
    """Resolve a source item only when all available exact signals agree.

    Fuzzy-name and distance thresholds are disabled unless explicitly supplied.
    Such near matches are diagnostic candidates only and produce AMBIGUOUS.
    Category is a consistency check only when a reviewed crosswalk is supplied;
    it never creates an identity match by itself.
    """
    if not source.item_id.strip():
        return MatchResult(source.item_id, "UNMATCHED", None, None, 0)
    if not 0 <= (fuzzy_threshold if fuzzy_threshold is not None else 0) <= 1:
        raise ValueError("fuzzy threshold must be between 0 and 1")
    if distance_threshold_m is not None and (
        not math.isfinite(distance_threshold_m) or distance_threshold_m < 0
    ):
        raise ValueError("distance threshold must be finite and nonnegative")

    source_name = normalize_text(source.name)
    source_district = normalize_code(source.district_code)
    source_address = normalize_text(source.address)
    source_lat, source_lon = _coord(source.latitude), _coord(source.longitude)
    evidence: dict[str, set[str]] = {
        "name_address": set(), "name_district": set(), "normalized_name": set(),
        "exact_coordinate": set(),
    }
    exact_signal_conflicts: set[str] = set()
    near_candidates: set[str] = set()
    category_types = None
    if source_category_to_content_types is not None:
        category_types = source_category_to_content_types.get(normalize_code(source.category))

    seen_catalog_ids: set[str] = set()
    for item in catalog:
        if not item.item_id.strip():
            continue
        if item.item_id in seen_catalog_ids:
            raise ValueError("catalog canonical IDs must be unique within a snapshot")
        seen_catalog_ids.add(item.item_id)
        name = normalize_text(item.name)
        district = normalize_code(item.district_code)
        address = normalize_text(item.address)
        if source_name and name and source_name == name:
            evidence["normalized_name"].add(item.item_id)
            near_candidates.add(item.item_id)
            if source_district and district and source_district == district:
                evidence["name_district"].add(item.item_id)
            if source_address and address and source_address == address:
                evidence["name_address"].add(item.item_id)
                if source_district and district and source_district != district:
                    exact_signal_conflicts.add(item.item_id)
            if (
                source_district and district and source_district == district
                and source_address and address and source_address != address
            ):
                exact_signal_conflicts.add(item.item_id)
        lat, lon = _coord(item.latitude), _coord(item.longitude)
        if source_lat is not None and source_lon is not None and lat == source_lat and lon == source_lon:
            evidence["exact_coordinate"].add(item.item_id)
            near_candidates.add(item.item_id)

        if source_name and name and fuzzy_threshold is not None:
            if SequenceMatcher(None, source_name, name, autojunk=False).ratio() >= fuzzy_threshold:
                near_candidates.add(item.item_id)
        if distance_threshold_m is not None:
            distance = _distance_meters(source, item)
            if distance is not None and distance <= distance_threshold_m:
                near_candidates.add(item.item_id)

    # A bare name or coordinate can identify multiple physical places. Keep
    # those signals useful for candidate discovery, but require an exact name
    # plus an administrative area/address before assigning identity.
    method_order = ("name_address", "name_district")
    strongest_method = next((method for method in method_order if evidence[method]), None)
    exact_candidates = evidence[strongest_method] if strongest_method else set()
    if exact_signal_conflicts & exact_candidates:
        conflict_count = len(set().union(*evidence.values()) | exact_signal_conflicts)
        return MatchResult(source.item_id, "AMBIGUOUS", None, "conflicting_exact_signals", conflict_count)
    if len(exact_candidates) > 1:
        return MatchResult(source.item_id, "AMBIGUOUS", None, strongest_method, len(exact_candidates))
    if len(exact_candidates) == 1:
        canonical_id = next(iter(exact_candidates))
        if any(candidates and canonical_id not in candidates for candidates in evidence.values()):
            conflict_count = len(set().union(*evidence.values()) | exact_signal_conflicts)
            return MatchResult(source.item_id, "AMBIGUOUS", None, "conflicting_exact_signals", conflict_count)
        item = next(item for item in catalog if item.item_id == canonical_id)
        if category_types is not None and item.content_type_id and item.content_type_id not in category_types:
            return MatchResult(source.item_id, "AMBIGUOUS", None, "category_type_conflict", 1)
        return MatchResult(source.item_id, "MATCHED", canonical_id, strongest_method, 1)
    if near_candidates:
        return MatchResult(source.item_id, "AMBIGUOUS", None, "fuzzy_or_distance_candidate", len(near_candidates))
    return MatchResult(source.item_id, "UNMATCHED", None, None, 0)


def audit_experiment_design(design: Mapping[str, object]) -> tuple[str, ...]:
    """Return deterministic blockers for common recommendation-contract errors.

    Inputs are deliberately plain values so the gate can be used in docs/tests
    without opening travel-log rows. It diagnoses a design; it does not score
    model quality.
    """
    findings: list[str] = []
    if design.get("claim") == "ranking_quality" and design.get("task") == "post_visit_satisfaction_classification":
        findings.append("post_visit_classification_is_not_ranking_evidence")
    if design.get("unvisited_label") == 0 and not design.get("negative_sampling_protocol"):
        findings.append("unvisited_items_are_unknown_without_exposure_or_sampling_protocol")
    if design.get("task") == "ranking" and set(design.get("metrics", ())) <= {"accuracy"}:
        findings.append("ranking_requires_ranking_metrics")
    if set(design.get("features", ())) & {"DGSTFN", "REVISIT_INTENTION", "RCMDTN_INTENTION"}:
        findings.append("post_event_feedback_is_unavailable_at_request_time")
    if design.get("claims_incremental_feature_value") and design.get("cohorts_comparable") is False:
        findings.append("feature_ablation_cohorts_are_not_comparable")
    return tuple(findings)


def eligibility_reason(
    item: PoiRecord,
    *,
    request_region: str,
    region_admin_codes: Mapping[str, frozenset[str]],
    supported_content_types: frozenset[str],
    request_district_code: str | None = None,
) -> str:
    """Return a stable fail-closed eligibility reason for one catalog record."""
    region_codes = region_admin_codes.get(normalize_code(request_region))
    if not region_codes:
        return "request_region_unmapped"
    if item.catalog_status == "inactive":
        return "catalog_inactive"
    if item.catalog_status != "active":
        return "catalog_status_unknown"
    if not item.content_type_id or item.content_type_id not in supported_content_types:
        return "unsupported_content_type"
    if not item.region_codes or not item.region_codes.intersection(region_codes):
        return "outside_request_region"
    if request_district_code is not None:
        district = normalize_code(request_district_code)
        if not district:
            return "request_district_invalid"
        if not item.district_codes or district not in {normalize_code(c) for c in item.district_codes}:
            return "outside_request_district"
    return "eligible"


def count_bucket(count: int) -> str:
    if count <= 0:
        return "0"
    if count < 10:
        return "<10"
    return "10+"


def _rate_band(numerator: int, denominator: int) -> str:
    if denominator < 10 or 0 < numerator < 10:
        return "privacy_limited"
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


def match_summary(results: list[MatchResult]) -> dict[str, str]:
    """Return privacy-bucketed status totals without identifiers or row values."""
    return {status: count_bucket(sum(result.status == status for result in results))
            for status in ("MATCHED", "AMBIGUOUS", "UNMATCHED")}


def diagnose_catalog(
    source_items: list[PoiRecord],
    catalog: list[PoiRecord],
    *,
    request_region: str,
    region_admin_codes: Mapping[str, frozenset[str]],
    supported_content_types: frozenset[str],
    request_district_code: str | None = None,
    source_category_to_content_types: Mapping[str, frozenset[str]] | None = None,
) -> dict[str, object]:
    """Produce deterministic, identifier-free diagnostics for a fixed snapshot."""
    matches = [match_source_item(
        source,
        catalog,
        source_category_to_content_types=source_category_to_content_types,
    ) for source in source_items]
    eligibility = [eligibility_reason(
        item,
        request_region=request_region,
        region_admin_codes=region_admin_codes,
        supported_content_types=supported_content_types,
        request_district_code=request_district_code,
    ) for item in catalog]
    method_counts = {
        method: count_bucket(sum(result.method == method for result in matches))
        for method in ("name_address", "name_district", "conflicting_exact_signals",
                       "category_type_conflict", "fuzzy_or_distance_candidate", "unmatched")
    }
    return {
        "source_item_count": count_bucket(len(source_items)),
        "catalog_item_count": count_bucket(len(catalog)),
        "identity": match_summary(matches),
        "match_method_counts": method_counts | {
            "unmatched": count_bucket(sum(result.status == "UNMATCHED" for result in matches)),
        },
        "eligibility_reason_counts": {
            reason: count_bucket(eligibility.count(reason))
            for reason in sorted(set(eligibility))
        },
        "eligible_catalog_items": count_bucket(sum(reason == "eligible" for reason in eligibility)),
        "identity_validation": "diagnostic_only_until_source_and_catalog_semantics_are_verified",
    }


def positive_coverage(positive_item_ids: set[str], eligible_item_ids: set[str]) -> dict[str, str]:
    """Summarize observed-positive coverage; absence remains unlabeled."""
    denominator = len(positive_item_ids)
    inside = len(positive_item_ids & eligible_item_ids)
    outside = denominator - inside
    if denominator < 10 or 0 < inside < 10 or 0 < outside < 10:
        return {"matched_positive": "privacy_limited", "outside_positive": "privacy_limited"}
    return {
        "matched_positive": _rate_band(inside, denominator),
        "outside_positive": _rate_band(outside, denominator),
    }
