"""Conservative, deterministic POI identity and request eligibility primitives.

Only synthetic records are used by this module's tests. Real catalog inputs need
their own approved, versioned acquisition path before these functions are used.
"""

from __future__ import annotations

import unicodedata
from difflib import SequenceMatcher
from dataclasses import dataclass
from typing import Literal

MatchStatus = Literal["MATCHED", "AMBIGUOUS", "UNMATCHED"]
PipelineStatus = Literal["MATCHED", "REVIEW", "AMBIGUOUS", "UNMATCHED"]
EligibilityStatus = Literal["ELIGIBLE", "INELIGIBLE", "UNRESOLVED"]


def normalize_exact(value: str | None) -> str:
    """Normalize Unicode and whitespace without inventing spelling equivalence."""
    return " ".join(unicodedata.normalize("NFKC", value or "").casefold().split())


def normalize_punctuation_candidate(value: str | None) -> str:
    """Build a lossy candidate key; callers must retain collisions for review."""
    normalized = unicodedata.normalize("NFKC", value or "").casefold()
    return " ".join("".join(" " if unicodedata.category(char).startswith("P") else char
                            for char in normalized).split())


def _char_ngrams(value: str, n: int = 3) -> set[str]:
    if len(value) < n:
        return {value} if value else set()
    return {value[index:index + n] for index in range(len(value) - n + 1)}


def _similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, left, right, autojunk=False).ratio()


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


@dataclass(frozen=True)
class CandidateEvidence:
    item: CatalogPoi
    rule: str
    name_similarity: float
    address_similarity: float
    source_name: str | None = None
    source_address: str | None = None


@dataclass(frozen=True)
class CandidateGenerationResult:
    status: PipelineStatus
    stage: Literal["stage1_exact", "stage2_normalized", "stage3_fuzzy", "none"]
    method: str
    candidates: tuple[CandidateEvidence, ...]
    candidate_count: int
    blocking_rule: str
    strict_result: MatchResult
    source_variant_candidate_counts: tuple[tuple[str | None, str | None, int], ...] = ()


class CatalogCandidateIndex:
    """Collision-preserving candidate index; it never makes a fuzzy match."""

    def __init__(self, catalog: list[CatalogPoi], *, snapshot_version: str | None = None,
                 fuzzy_display_limit: int = 5) -> None:
        self.catalog = catalog
        self.snapshot_version = snapshot_version
        self.fuzzy_display_limit = max(1, fuzzy_display_limit)
        self.by_exact_name: dict[str, list[CatalogPoi]] = {}
        self.by_punctuation_name: dict[str, list[CatalogPoi]] = {}
        self.by_punctuation_address: dict[str, list[CatalogPoi]] = {}
        self.by_ngram: dict[str, list[CatalogPoi]] = {}
        self.by_content_id: dict[str, CatalogPoi] = {item.content_id: item for item in catalog}
        for item in catalog:
            exact = normalize_exact(item.title)
            punctuation = normalize_punctuation_candidate(item.title)
            if exact:
                self.by_exact_name.setdefault(exact, []).append(item)
            if punctuation:
                self.by_punctuation_name.setdefault(punctuation, []).append(item)
                for gram in _char_ngrams(punctuation):
                    self.by_ngram.setdefault(gram, []).append(item)
            address_key = normalize_punctuation_candidate(item.road_address)
            if address_key:
                self.by_punctuation_address.setdefault(address_key, []).append(item)

    def collision_counts(self) -> dict[str, int]:
        return {
            "exact_name_keys_with_multiple_catalog_items": sum(
                len(items) > 1 for items in self.by_exact_name.values()),
            "punctuation_name_keys_with_multiple_catalog_items": sum(
                len(items) > 1 for items in self.by_punctuation_name.values()),
        }

    @staticmethod
    def _evidence(source: SourcePoi, item: CatalogPoi, rule: str) -> CandidateEvidence:
        source_name = normalize_exact(source.name)
        catalog_name = normalize_exact(item.title)
        source_address = normalize_exact(source.road_address)
        catalog_address = normalize_exact(item.road_address)
        return CandidateEvidence(
            item=item,
            rule=rule,
            name_similarity=_similarity(source_name, catalog_name),
            address_similarity=_similarity(source_address, catalog_address),
            source_name=source.name,
            source_address=source.road_address,
        )

    def generate(self, source: SourcePoi, *, source_conflicted: bool = False,
                 retain_all_candidates: bool = False
                 ) -> CandidateGenerationResult:
        strict = match_source_poi(source, self.by_exact_name.get(normalize_exact(source.name), []),
                                  source_conflicted=source_conflicted,
                                  snapshot_version=self.snapshot_version)
        if strict.status == "MATCHED" and strict.canonical_id:
            item = self.by_content_id[strict.canonical_id]
            evidence = self._evidence(source, item, strict.method)
            return CandidateGenerationResult(
                "MATCHED", "stage1_exact", strict.method, (evidence,), 1,
                "unique_normalized_name_and_address_string", strict,
            )
        if source_conflicted:
            return CandidateGenerationResult("AMBIGUOUS", "none", strict.method,
                                             (), 0, "conflicting_source_metadata", strict)
        name = normalize_exact(source.name)
        exact_candidates = self.by_exact_name.get(name, [])
        punctuation_key = normalize_punctuation_candidate(source.name)
        punctuation_candidates = self.by_punctuation_name.get(punctuation_key, [])
        normalized: dict[str, tuple[CatalogPoi, str]] = {}
        for item in exact_candidates:
            normalized[item.content_id] = (item, "exact_name_address_string_variant")
        for item in punctuation_candidates:
            normalized.setdefault(item.content_id, (item, "punctuation_name_variant"))
        address_key = normalize_punctuation_candidate(source.road_address)
        address_candidates = self.by_punctuation_address.get(address_key, []) if address_key else []
        for item in address_candidates:
            normalized.setdefault(item.content_id, (item, "punctuation_address_variant"))
        if normalized:
            evidence = tuple(self._evidence(source, item, rule)
                             for item, rule in normalized.values())
            evidence = tuple(sorted(evidence, key=lambda value: (
                value.address_similarity, value.name_similarity, value.item.content_id
            ), reverse=True))
            status: PipelineStatus = "REVIEW" if len(evidence) == 1 else "AMBIGUOUS"
            rules = {value.rule for value in evidence}
            method = next(iter(rules)) if len(rules) == 1 else "normalized_multi_rule_candidates"
            blocking = "exact_or_punctuation_name_or_address_key"
            return CandidateGenerationResult(status, "stage2_normalized", method,
                                             (evidence if retain_all_candidates else
                                              evidence[:self.fuzzy_display_limit]), len(evidence),
                                             blocking, strict)
        if not name:
            return CandidateGenerationResult("UNMATCHED", "none", "missing_source_name",
                                             (), 0, "no_source_name", strict)

        punctuation = punctuation_key
        grams = _char_ngrams(punctuation)
        candidates: dict[str, CatalogPoi] = {}
        for gram in grams:
            for item in self.by_ngram.get(gram, ()):
                candidates[item.content_id] = item
        if not candidates:
            return CandidateGenerationResult("UNMATCHED", "none", "no_candidate_block_hit",
                                             (), 0, "no_shared_character_trigram", strict)
        evidence = [self._evidence(source, item, "fuzzy_character_trigram_block")
                    for item in candidates.values()]
        evidence.sort(key=lambda value: (
            value.name_similarity, value.address_similarity, value.item.content_id
        ), reverse=True)
        displayed = tuple(evidence[:self.fuzzy_display_limit])
        # Even a unique top score is review-only. Similarity is never an auto-match.
        return CandidateGenerationResult(
            "AMBIGUOUS" if len(candidates) > 1 else "REVIEW",
            "stage3_fuzzy", "fuzzy_character_trigram_block",
            tuple(evidence) if retain_all_candidates else displayed,
            len(candidates), "any_shared_character_trigram_no_area_filter", strict,
        )


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
