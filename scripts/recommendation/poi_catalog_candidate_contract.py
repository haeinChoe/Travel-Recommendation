"""Deterministic POI identity and candidate eligibility rules.

This module never calls TourAPI. Callers must provide an authorized, versioned
catalog snapshot and explicit product policy. Raw item identifiers are inputs
to in-memory joins and must not be emitted to public artifacts.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Mapping


@dataclass(frozen=True)
class SourcePoi:
    """Historical observation; its ``region`` is the observed source region."""

    source_item_id: str
    region: str
    name: str = ""
    district_code: str = ""
    address: str = ""
    category: str = ""
    request_id: str = ""


@dataclass(frozen=True)
class CatalogPoi:
    """Serving catalog item with provider-scoped canonical identity."""

    content_id: str
    title: str = ""
    district_code: str = ""
    address: str = ""
    content_type_id: str = ""
    region_codes: frozenset[str] = frozenset()
    district_codes: frozenset[str] = frozenset()
    classification_codes: tuple[str, ...] = ()
    modified_time: str = ""


@dataclass(frozen=True)
class CandidateRequest:
    """Request-time region context, supplied independently for product coverage."""

    request_id: str
    region: str
    district_code: str | None = None


@dataclass(frozen=True)
class HistoricalRequestProxy:
    """Historical feasibility proxy derived from observed source regions."""

    request_id: str
    region: str


@dataclass(frozen=True)
class CatalogSnapshot:
    snapshot_version: str
    records: tuple[CatalogPoi, ...]
    provider: str = "tourapi-korservice2"
    manual_version: str = "4.4"
    retrieved_at: str = ""
    request_config_hash: str = ""
    policy_version: str = "poi-catalog-candidate-v1"


def derive_proxy_requests_from_observations(observations: list[SourcePoi]) -> list[HistoricalRequestProxy]:
    """Build historical feasibility proxies; never use these as product requests.

    ``SourcePoi.region`` is the historical observation's region. The returned
    ``HistoricalRequestProxy.region`` is only a proxy copied from those observations,
    not request-time product context.
    """
    regions_by_request: dict[str, str] = {}
    for observation in observations:
        request_id = observation.request_id
        region = normalize_code(observation.region)
        if not request_id.strip() or not region:
            raise ValueError("observations require nonblank request IDs and regions")
        previous = regions_by_request.setdefault(request_id, region)
        if previous != region:
            raise ValueError("all observations for a request must share one region")
    return [HistoricalRequestProxy(request_id=request_id, region=region)
            for request_id, region in sorted(regions_by_request.items())]


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


def _normalize_code_map(mapping: Mapping[str, frozenset[str]]) -> dict[str, frozenset[str]]:
    normalized: dict[str, frozenset[str]] = {}
    for key, values in mapping.items():
        normalized_key = normalize_code(key)
        normalized_values = frozenset(filter(None, (normalize_code(value) for value in values)))
        if not normalized_key:
            continue
        if normalized_key in normalized and normalized[normalized_key] != normalized_values:
            raise ValueError("policy keys collide after normalization")
        normalized[normalized_key] = normalized_values
    return normalized


def match_source_item(
    source: SourcePoi,
    catalog: list[CatalogPoi],
    *,
    source_region_to_admin_codes: Mapping[str, frozenset[str]],
    fuzzy_threshold: float | None = None,
    source_category_to_content_types: Mapping[str, frozenset[str]] | None = None,
) -> MatchResult:
    """Resolve a source item only when all available exact signals agree.

    Fuzzy-name thresholds are disabled unless explicitly supplied. Such near
    matches are diagnostic candidates only and produce AMBIGUOUS. Coordinates
    are intentionally absent because their CRS and encoding are unverified.
    Category is a consistency check only when a reviewed crosswalk is supplied;
    it never creates an identity match by itself. Identity matching also requires
    an explicit reviewed source-region-to-catalog-admin-code mapping.
    """
    if not source.source_item_id.strip():
        return MatchResult(source.source_item_id, "UNMATCHED", None, None, 0)
    if not 0 <= (fuzzy_threshold if fuzzy_threshold is not None else 0) <= 1:
        raise ValueError("fuzzy threshold must be between 0 and 1")
    reviewed_region_codes = _normalize_code_map(source_region_to_admin_codes).get(normalize_code(source.region))
    if not reviewed_region_codes:
        return MatchResult(source.source_item_id, "UNMATCHED", None, "region_unmapped", 0)

    source_name = normalize_text(source.name)
    source_district = normalize_code(source.district_code)
    source_address = normalize_text(source.address)
    evidence: dict[str, set[str]] = {
        "name_address": set(), "name_district": set(), "normalized_name": set(),
    }
    exact_signal_conflicts: set[str] = set()
    near_candidates: set[str] = set()
    category_types = None
    if source_category_to_content_types is not None:
        category_types = _normalize_code_map(source_category_to_content_types).get(normalize_code(source.category))

    seen_catalog_ids: set[str] = set()
    for item in catalog:
        if not item.content_id.strip():
            continue
        if item.content_id in seen_catalog_ids:
            raise ValueError("catalog canonical IDs must be unique within a snapshot")
        seen_catalog_ids.add(item.content_id)
        item_region_codes = {normalize_code(code) for code in item.region_codes if normalize_code(code)}
        if not item_region_codes or not reviewed_region_codes.intersection(item_region_codes):
            continue
        name = normalize_text(item.title)
        districts = {normalize_code(code) for code in item.district_codes if normalize_code(code)}
        if item.district_code:
            districts.add(normalize_code(item.district_code))
        address = normalize_text(item.address)
        if source_name and name and source_name == name:
            evidence["normalized_name"].add(item.content_id)
            near_candidates.add(item.content_id)
            if source_district and source_district in districts:
                evidence["name_district"].add(item.content_id)
            if source_address and address and source_address == address:
                evidence["name_address"].add(item.content_id)
                if source_district and districts and source_district not in districts:
                    exact_signal_conflicts.add(item.content_id)
            if (
                source_district and source_district in districts
                and source_address and address and source_address != address
            ):
                exact_signal_conflicts.add(item.content_id)

        if source_name and name and fuzzy_threshold is not None:
            if SequenceMatcher(None, source_name, name, autojunk=False).ratio() >= fuzzy_threshold:
                near_candidates.add(item.content_id)

    # A bare name can identify multiple physical places. Keep
    # those signals useful for candidate discovery, but require an exact name
    # plus an administrative area/address before assigning identity.
    method_order = ("name_address", "name_district")
    strongest_method = next((method for method in method_order if evidence[method]), None)
    exact_candidates = evidence[strongest_method] if strongest_method else set()
    if exact_signal_conflicts & exact_candidates:
        conflict_count = len(set().union(*evidence.values()) | exact_signal_conflicts)
        return MatchResult(source.source_item_id, "AMBIGUOUS", None, "conflicting_exact_signals", conflict_count)
    if len(exact_candidates) > 1:
        return MatchResult(source.source_item_id, "AMBIGUOUS", None, strongest_method, len(exact_candidates))
    if len(exact_candidates) == 1:
        canonical_id = next(iter(exact_candidates))
        if any(candidates and canonical_id not in candidates for candidates in evidence.values()):
            conflict_count = len(set().union(*evidence.values()) | exact_signal_conflicts)
            return MatchResult(source.source_item_id, "AMBIGUOUS", None, "conflicting_exact_signals", conflict_count)
        item = next(item for item in catalog if item.content_id == canonical_id)
        if category_types is not None and item.content_type_id and normalize_code(item.content_type_id) not in category_types:
            return MatchResult(source.source_item_id, "AMBIGUOUS", None, "category_type_conflict", 1)
        return MatchResult(source.source_item_id, "MATCHED", canonical_id, strongest_method, 1)
    if near_candidates:
        return MatchResult(source.source_item_id, "AMBIGUOUS", None, "fuzzy_name_candidate", len(near_candidates))
    return MatchResult(source.source_item_id, "UNMATCHED", None, None, 0)


def eligibility_reason(
    item: CatalogPoi,
    *,
    request_region: str,
    region_admin_codes: Mapping[str, frozenset[str]],
    supported_content_types: frozenset[str],
    request_district_code: str | None = None,
) -> str:
    """Return v1 eligibility; snapshot membership is established by the caller."""
    region_codes = _normalize_code_map(region_admin_codes).get(normalize_code(request_region))
    if not region_codes:
        return "request_region_unmapped"
    supported_types = {normalize_code(value) for value in supported_content_types if normalize_code(value)}
    if not item.content_type_id or normalize_code(item.content_type_id) not in supported_types:
        return "unsupported_content_type"
    item_regions = {normalize_code(code) for code in item.region_codes if normalize_code(code)}
    if not item_regions or not item_regions.intersection(region_codes):
        return "outside_request_region"
    if request_district_code is not None:
        district = normalize_code(request_district_code)
        if not district:
            return "request_district_invalid"
        item_districts = {normalize_code(code) for code in item.district_codes if normalize_code(code)}
        if item.district_code:
            item_districts.add(normalize_code(item.district_code))
        if not item_districts or district not in item_districts:
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
    source_items: list[SourcePoi],
    catalog: list[CatalogPoi],
    *,
    source_region_to_admin_codes: Mapping[str, frozenset[str]],
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
        source_region_to_admin_codes=source_region_to_admin_codes,
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
                       "category_type_conflict", "fuzzy_name_candidate", "region_unmapped", "unmatched")
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


def _candidate_size_bucket(size: int) -> str:
    if size == 0:
        return "0"
    if size == 1:
        return "1"
    if size < 10:
        return "2-9"
    if size < 50:
        return "10-49"
    if size < 500:
        return "50-499"
    return "500+"


def diagnose_candidate_coverage(
    requests: list[CandidateRequest],
    observed_positives: list[SourcePoi],
    snapshot: CatalogSnapshot,
    *,
    region_admin_codes: Mapping[str, frozenset[str]],
    supported_content_types: frozenset[str],
    source_category_to_content_types: Mapping[str, frozenset[str]] | None = None,
) -> dict[str, object]:
    """Build request-level candidates and privacy-safe coverage aggregates.

    Request IDs and item IDs are used only for in-memory grouping. This is a
    hypothetical product-eligibility diagnostic; it does not measure historical
    exposure. Positives with unresolved identity are reported separately.
    """
    if any(not isinstance(request, CandidateRequest) for request in requests):
        raise TypeError("product coverage requires independently supplied CandidateRequest contexts")
    if not snapshot.snapshot_version.strip():
        raise ValueError("catalog snapshot version is required")
    snapshot_ids = [item.content_id for item in snapshot.records]
    if any(not item_id.strip() for item_id in snapshot_ids) or len(set(snapshot_ids)) != len(snapshot_ids):
        raise ValueError("snapshot provider content IDs must be nonblank and unique")
    request_by_id = {request.request_id: request for request in requests}
    if len(request_by_id) != len(requests) or any(not key.strip() for key in request_by_id):
        raise ValueError("request IDs must be nonblank and unique")

    positives_by_request: dict[str, list[SourcePoi]] = {key: [] for key in request_by_id}
    seen_positives: dict[tuple[str, str], SourcePoi] = {}
    for source in observed_positives:
        if source.request_id not in request_by_id:
            raise ValueError("every observed positive must reference a known request")
        identity = (source.request_id, source.source_item_id)
        previous = seen_positives.get(identity)
        if previous is not None:
            if previous != source:
                raise ValueError("duplicate source identity has conflicting observation fields")
            continue
        positives_by_request[source.request_id].append(source)
        seen_positives[identity] = source

    candidate_sizes: list[int] = []
    request_positive_total = 0
    identity_counts = {status: 0 for status in ("MATCHED", "AMBIGUOUS", "UNMATCHED")}
    resolved_positive_count = 0
    covered_positive_count = 0
    outside_candidate_positive_count = 0

    for request in requests:
        eligible = [
            item for item in snapshot.records
            if eligibility_reason(
                item,
                request_region=request.region,
                region_admin_codes=region_admin_codes,
                supported_content_types=supported_content_types,
                request_district_code=request.district_code,
            ) == "eligible"
        ]
        eligible_ids = {item.content_id for item in eligible}
        candidate_sizes.append(len(eligible_ids))
        for source in positives_by_request[request.request_id]:
            request_positive_total += 1
            result = match_source_item(
                source,
                list(snapshot.records),
                source_region_to_admin_codes=region_admin_codes,
                source_category_to_content_types=source_category_to_content_types,
            )
            identity_counts[result.status] += 1
            if result.status == "MATCHED" and result.canonical_item_id is not None:
                resolved_positive_count += 1
                if result.canonical_item_id in eligible_ids:
                    covered_positive_count += 1
                else:
                    outside_candidate_positive_count += 1

    size_buckets = ("0", "1", "2-9", "10-49", "50-499", "500+")
    size_distribution = {
        bucket: count_bucket(sum(_candidate_size_bucket(size) == bucket for size in candidate_sizes))
        for bucket in size_buckets
    }
    nonempty_requests = sum(size > 0 for size in candidate_sizes)
    return {
        "snapshot_version": snapshot.snapshot_version,
        "request_count": count_bucket(len(requests)),
        "nonempty_candidate_request_rate": _rate_band(nonempty_requests, len(requests)),
        "candidate_size_distribution": size_distribution,
        "observed_positive_count": count_bucket(request_positive_total),
        "identity_status": {status: count_bucket(count) for status, count in identity_counts.items()},
        "resolved_positive_count": count_bucket(resolved_positive_count),
        "positive_candidate_coverage": _rate_band(covered_positive_count, resolved_positive_count),
        "outside_candidate_positive_share": _rate_band(
            outside_candidate_positive_count, resolved_positive_count
        ),
        "unresolved_identity_excluded_from_candidate_coverage": True,
        "interpretation": "hypothetical_product_eligibility_not_historical_exposure",
    }
