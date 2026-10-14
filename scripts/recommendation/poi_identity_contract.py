"""Conservative, deterministic POI identity and request eligibility primitives.

Only synthetic records are used by this module's tests. Real catalog inputs need
their own approved, versioned acquisition path before these functions are used.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Literal

MatchStatus = Literal["MATCHED", "AMBIGUOUS", "UNMATCHED"]
EligibilityStatus = Literal["ELIGIBLE", "INELIGIBLE", "UNRESOLVED"]


def normalize_exact(value: str | None) -> str:
    """Normalize Unicode and whitespace without inventing spelling equivalence."""
    return " ".join(unicodedata.normalize("NFKC", value or "").casefold().split())


@dataclass(frozen=True)
class SourcePoi:
    region: str
    poi_id: str
    name: str | None
    road_address: str | None


@dataclass(frozen=True)
class CatalogPoi:
    content_id: str
    title: str | None
    road_address: str | None
    area_code: str | None
    district_code: str | None
    content_type: str | None
    listing_state: Literal["listed", "not_displayed", "unknown"]


@dataclass(frozen=True)
class MatchResult:
    status: MatchStatus
    canonical_id: str | None
    method: str
    candidate_count: int
    validation_status: Literal["unreviewed", "requires_review"]
    confidence: float | None = None  # Calibrated only after an authorized review set.
    snapshot_version: str | None = None


def match_source_poi(source: SourcePoi, catalog: list[CatalogPoi],
                     *, source_conflicted: bool = False,
                     snapshot_version: str | None = None) -> MatchResult:
    """Promote only a unique exact name plus road address pair to MATCHED.

    A name-only match is ambiguous. Coordinates, fuzzy names, administrative
    codes, and category are deliberately withheld until their semantics and
    error thresholds have been validated. The result is an unreviewed rule
    outcome, not a measured precision estimate.
    """
    name = normalize_exact(source.name)
    address = normalize_exact(source.road_address)
    def result(status: MatchStatus, canonical_id: str | None, method: str,
               candidate_count: int, validation_status: Literal["unreviewed", "requires_review"]) -> MatchResult:
        return MatchResult(status, canonical_id, method, candidate_count,
                           validation_status, None, snapshot_version)
    if source_conflicted:
        return result("AMBIGUOUS", None, "conflicting_source_metadata", 0, "requires_review")
    if not source.region or not source.poi_id.strip() or not name:
        return result("UNMATCHED", None, "insufficient_source_identity", 0, "requires_review")
    named = [item for item in catalog if normalize_exact(item.title) == name]
    if not named:
        return result("UNMATCHED", None, "no_exact_name", 0, "requires_review")
    if not address:
        return result("AMBIGUOUS", None, "name_without_address", len(named), "requires_review")
    exact = [item for item in named if normalize_exact(item.road_address) == address]
    if not exact:
        return result("AMBIGUOUS", None, "name_address_conflict", len(named), "requires_review")
    ids = {item.content_id.strip() for item in exact if item.content_id.strip()}
    if len(ids) != 1 or len(exact) != 1:
        return result("AMBIGUOUS", None, "duplicate_exact_pair", len(exact), "requires_review")
    canonical = next(iter(ids))
    if sum(item.content_id.strip() == canonical for item in catalog) != 1:
        return result("AMBIGUOUS", None, "conflicting_canonical_id", len(exact), "requires_review")
    return result("MATCHED", canonical, "unique_exact_name_address", 1, "unreviewed")


@dataclass(frozen=True)
class RequestContext:
    region_code: str | None
    district_code: str | None = None
    explicitly_selected_district: bool = False
    explicitly_selected_category: str | None = None


@dataclass(frozen=True)
class SnapshotValidation:
    provider_use_authorized: bool
    complete: bool
    schema_validated: bool
    current_for_request: bool
    listing_state_provenance_validated: bool


def candidate_eligibility(
    request: RequestContext,
    item: CatalogPoi,
    supported_types: frozenset[str],
    *,
    snapshot: SnapshotValidation | None = None,
    region_crosswalk_validated: bool,
    district_crosswalk_validated: bool = False,
    category_crosswalk_validated: bool = False,
) -> EligibilityStatus:
    """Apply known hard constraints, returning UNRESOLVED for missing contracts."""
    if snapshot is None or not all((snapshot.provider_use_authorized, snapshot.complete,
                                    snapshot.schema_validated, snapshot.current_for_request,
                                    snapshot.listing_state_provenance_validated)):
        return "UNRESOLVED"
    if item.listing_state == "not_displayed":
        return "INELIGIBLE"
    if not request.region_code or not region_crosswalk_validated or not supported_types:
        return "UNRESOLVED"
    if item.listing_state != "listed" or not item.area_code or not item.content_type:
        return "UNRESOLVED"
    if item.content_type not in supported_types or item.area_code != request.region_code:
        return "INELIGIBLE"
    if request.explicitly_selected_district:
        if not request.district_code or not district_crosswalk_validated or not item.district_code:
            return "UNRESOLVED"
        if item.district_code != request.district_code:
            return "INELIGIBLE"
    if request.explicitly_selected_category and not category_crosswalk_validated:
        return "UNRESOLVED"
    # A selected category still needs a versioned category value/crosswalk in
    # the catalog. This minimal contract does not define such a field yet.
    if request.explicitly_selected_category:
        return "UNRESOLVED"
    return "ELIGIBLE"
