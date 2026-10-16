"""Conservative, deterministic POI identity and request eligibility primitives.

Only synthetic records are used by this module's tests. Real catalog inputs need
their own approved, versioned acquisition path before these functions are used.
"""

from __future__ import annotations

import unicodedata
from array import array
from collections import Counter
from difflib import SequenceMatcher
from dataclasses import dataclass
from functools import lru_cache
from heapq import heappush, heappushpop
from typing import Callable, Literal

MatchStatus = Literal["MATCHED", "AMBIGUOUS", "UNMATCHED"]
PipelineStatus = Literal["MATCHED", "REVIEW", "AMBIGUOUS", "UNMATCHED"]
EligibilityStatus = Literal["ELIGIBLE", "INELIGIBLE", "UNRESOLVED"]
RegionMappingStatus = Literal["MAPPED", "UNMAPPED", "UNSUPPORTED"]
_CANDIDATE_BLOCKS = (
    "exact_name", "punctuation_name", "spacing_name", "catalog_addr1_key",
    "lot_address_key", "spacing_catalog_addr1_key", "spacing_lot_address_key",
    "name_token", "name_prefix_2", "address_piece", "validated_admin_component",
    "character_trigram",
)
_CANDIDATE_BLOCK_BITS = {name: 1 << position for position, name in enumerate(_CANDIDATE_BLOCKS)}


def normalize_exact(value: str | None) -> str:
    """Normalize Unicode and whitespace without inventing spelling equivalence."""
    return " ".join(unicodedata.normalize("NFKC", value or "").casefold().split())


def normalize_punctuation_candidate(value: str | None) -> str:
    """Fold punctuation to separators for blocking; never use this as identity."""
    normalized = unicodedata.normalize("NFKC", value or "").casefold()
    return " ".join("".join(" " if unicodedata.category(char).startswith("P") else char
                            for char in normalized).split())


def normalize_spacing_candidate(value: str | None) -> str:
    """Create a collision-preserving no-spacing key for candidate blocking."""
    return "".join(normalize_punctuation_candidate(value).split())


def _char_ngrams(value: str, n: int = 3) -> set[str]:
    if len(value) < n:
        return {value} if value else set()
    return {value[index:index + n] for index in range(len(value) - n + 1)}


@lru_cache(maxsize=65_536)
def _similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    return SequenceMatcher(None, left, right, autojunk=False).ratio()


def _similarity_length_upper_bound(left: str, right: str) -> float:
    """Cheap upper bound for SequenceMatcher.ratio() from string lengths."""
    if not left or not right:
        return 0.0
    return 2.0 * min(len(left), len(right)) / (len(left) + len(right))


@lru_cache(maxsize=8_192)
def _character_counts(value: str) -> Counter[str]:
    return Counter(value)


@lru_cache(maxsize=8_192)
def _similarity_character_upper_bound(left: str, right: str) -> float:
    """Bound ratio by the multiset of shared characters, preserving recall."""
    if not left or not right:
        return 0.0
    left_map = _character_counts(left)
    right_map = _character_counts(right)
    common = sum(min(count, right_map.get(char, 0))
                 for char, count in left_map.items())
    return 2.0 * common / (len(left) + len(right))


@dataclass(frozen=True)
class SourcePoi:
    region: str
    poi_id: str
    name: str | None
    road_address: str | None
    lot_address: str | None = None
    admin_components: tuple[str, ...] = ()
    admin_crosswalk_validated: bool = False


@dataclass(frozen=True)
class CatalogPoi:
    content_id: str
    title: str | None
    road_address: str | None
    area_code: str | None
    district_code: str | None
    content_type: str | None
    listing_state: Literal["listed", "not_displayed", "unknown"]
    lot_address: str | None = None
    admin_components: tuple[str, ...] = ()
    admin_components_validated: bool = False


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
    source_lot_address: str | None = None
    matched_signals: tuple[str, ...] = ()
    conflicting_signals: tuple[str, ...] = ()


@dataclass(frozen=True)
class CandidateGenerationResult:
    status: PipelineStatus
    stage: Literal["stage1_exact", "stage2_normalized", "stage3_fuzzy", "none"]
    method: str
    candidates: tuple[CandidateEvidence, ...]
    candidate_count: int
    blocking_rule: str
    strict_result: MatchResult
    source_variant_candidate_counts: tuple[tuple[str | None, str | None, str | None, int], ...] = ()
    source_variant_candidate_evidence: tuple[
        tuple[str | None, str | None, str | None, tuple[CandidateEvidence, ...]], ...
    ] = ()


@dataclass(frozen=True)
class PurposeRegionCrosswalk:
    version: str
    supported_purpose_regions: frozenset[str]
    purpose_region_to_ldong_codes: dict[str, tuple[str, ...]]


@dataclass(frozen=True)
class _IdentityFeatures:
    name_exact: str
    name_punctuation: str
    name_spacing: str
    road_exact: str
    road_punctuation: str
    road_spacing: str
    lot_exact: str
    lot_punctuation: str
    lot_spacing: str
    admin_components: tuple[str, ...]


def _identity_features(name: str | None, road: str | None, lot: str | None,
                       admin: tuple[str, ...] = ()) -> _IdentityFeatures:
    name_exact = normalize_exact(name)
    road_exact = normalize_exact(road)
    lot_exact = normalize_exact(lot)
    return _IdentityFeatures(
        name_exact=name_exact,
        name_punctuation=normalize_punctuation_candidate(name),
        name_spacing=normalize_spacing_candidate(name),
        road_exact=road_exact,
        road_punctuation=normalize_punctuation_candidate(road),
        road_spacing=normalize_spacing_candidate(road),
        lot_exact=lot_exact,
        lot_punctuation=normalize_punctuation_candidate(lot),
        lot_spacing=normalize_spacing_candidate(lot),
        admin_components=tuple(normalize_exact(value) for value in admin),
    )


def purpose_region_mapping_status(
    purpose_region: str,
    *,
    supported_purpose_regions: frozenset[str],
    crosswalk: PurposeRegionCrosswalk | None,
) -> RegionMappingStatus:
    """Fail closed when official purpose-region to KTO membership is absent."""
    region = normalize_exact(purpose_region)
    supported = {normalize_exact(value) for value in supported_purpose_regions}
    if not region or region not in supported:
        return "UNSUPPORTED"
    if (crosswalk is None or not crosswalk.version.strip()
            or normalize_exact(purpose_region) not in {
                normalize_exact(value) for value in crosswalk.supported_purpose_regions
            }):
        return "UNMAPPED"
    normalized_keys = [
        codes for key, codes in crosswalk.purpose_region_to_ldong_codes.items()
        if normalize_exact(key) == region
    ]
    if len(normalized_keys) != 1:
        return "UNMAPPED"
    return "MAPPED" if normalized_keys[0] else "UNMAPPED"


class CatalogCandidateIndex:
    """Collision-preserving candidate index; it never makes a fuzzy match."""

    def __init__(self, catalog: list[CatalogPoi], *, snapshot_version: str | None = None,
                 fuzzy_display_limit: int = 5) -> None:
        self.catalog = catalog
        self.snapshot_version = snapshot_version
        self.fuzzy_display_limit = max(1, fuzzy_display_limit)
        self.by_exact_name: dict[str, array] = {}
        self.by_exact_name_and_road_address: dict[tuple[str, str], array] = {}
        self.by_punctuation_name: dict[str, array] = {}
        self.by_punctuation_address: dict[str, array] = {}
        self.by_spacing_name: dict[str, array] = {}
        self.by_spacing_road_address: dict[str, array] = {}
        self.by_spacing_lot_address: dict[str, array] = {}
        self.by_name_token: dict[str, array] = {}
        self.by_name_prefix: dict[str, array] = {}
        self.by_address_piece: dict[str, array] = {}
        self.by_lot_address: dict[str, array] = {}
        self.by_admin_component: dict[str, array] = {}
        self.by_ngram: dict[str, array] = {}
        self.catalog_features: dict[int, _IdentityFeatures] = {}
        self._candidate_masks = array("H", [0]) * len(catalog)
        self._candidate_generations = array("I", [0]) * len(catalog)
        self._candidate_first_seen = array("Q", [0]) * len(catalog)
        self._candidate_generation_number = 0
        self.by_content_id: dict[str, CatalogPoi] = {}
        self.content_id_ordinals: dict[str, int] = {}
        self.catalog_record_ordinals: dict[int, int] = {}
        self.content_id_counts = Counter(item.content_id.strip() for item in catalog
                                         if item.content_id.strip())
        for index, item in enumerate(catalog):
            self.catalog_record_ordinals.setdefault(id(item), index)
            features = self.catalog_features.setdefault(
                id(item), _identity_features(item.title, item.road_address,
                                             item.lot_address, item.admin_components))
            canonical_id = item.content_id.strip()
            self.by_content_id.setdefault(canonical_id, item)
            self.content_id_ordinals.setdefault(canonical_id, len(self.content_id_ordinals))
            exact = features.name_exact
            punctuation = features.name_punctuation
            if exact:
                self.by_exact_name.setdefault(exact, array("Q")).append(index)
                if features.road_exact:
                    self.by_exact_name_and_road_address.setdefault(
                        (exact, features.road_exact), array("Q")).append(index)
            if punctuation:
                self.by_punctuation_name.setdefault(punctuation, array("Q")).append(index)
                tokens = set(punctuation.split())
                for token in tokens:
                    self.by_name_token.setdefault(token, array("Q")).append(index)
                # Prefix is a retrieval block only; its collisions are retained.
                self.by_name_prefix.setdefault(punctuation[:2], array("Q")).append(index)
                for gram in _char_ngrams(punctuation):
                    self.by_ngram.setdefault(gram, array("Q")).append(index)
            spacing_name = features.name_spacing
            if spacing_name:
                self.by_spacing_name.setdefault(spacing_name, array("Q")).append(index)
            address_key = features.road_punctuation
            if address_key:
                self.by_punctuation_address.setdefault(address_key, array("Q")).append(index)
            spacing_road = features.road_spacing
            if spacing_road:
                self.by_spacing_road_address.setdefault(spacing_road, array("Q")).append(index)
            lot_key = features.lot_punctuation
            if lot_key:
                self.by_lot_address.setdefault(lot_key, array("Q")).append(index)
            spacing_lot = features.lot_spacing
            if spacing_lot:
                self.by_spacing_lot_address.setdefault(spacing_lot, array("Q")).append(index)
            for address in (features.road_punctuation, features.lot_punctuation):
                for piece in set(address.split()):
                    self.by_address_piece.setdefault(piece, array("Q")).append(index)
            if item.admin_components_validated:
                for component in item.admin_components:
                    component_key = normalize_exact(component)
                    if component_key:
                        self.by_admin_component.setdefault(component_key, array("Q")).append(index)

    def collision_counts(self) -> dict[str, int]:
        return {
            "exact_name_keys_with_multiple_catalog_items": sum(
                len(items) > 1 for items in self.by_exact_name.values()),
            "punctuation_name_keys_with_multiple_catalog_items": sum(
                len(items) > 1 for items in self.by_punctuation_name.values()),
            "spacing_name_keys_with_multiple_catalog_items": sum(
                len(items) > 1 for items in self.by_spacing_name.values()),
            "catalog_address_keys_with_multiple_items": sum(
                len(items) > 1 for index in (self.by_punctuation_address,
                                             self.by_spacing_road_address,
                                             self.by_lot_address,
                                             self.by_spacing_lot_address)
                for items in index.values()),
        }

    def _evidence(self, source: SourcePoi, item: CatalogPoi, rule: str,
                  source_features: _IdentityFeatures) -> CandidateEvidence:
        catalog_features = self.catalog_features[id(item)]
        source_name = source_features.name_exact
        catalog_name = catalog_features.name_exact
        source_addresses = {
            "road": (source_features.road_exact, source_features.road_punctuation,
                     source_features.road_spacing),
            "lot": (source_features.lot_exact, source_features.lot_punctuation,
                    source_features.lot_spacing),
        }
        catalog_addresses = {
            "road": (catalog_features.road_exact, catalog_features.road_punctuation,
                     catalog_features.road_spacing),
            "lot": (catalog_features.lot_exact, catalog_features.lot_punctuation,
                    catalog_features.lot_spacing),
        }
        matched: list[str] = []
        conflicting: list[str] = []
        if source_name and source_name == catalog_name:
            matched.append("strict_name")
        elif source_name and catalog_name:
            if source_features.name_punctuation == catalog_features.name_punctuation:
                matched.append("punctuation_name")
            elif source_features.name_spacing == catalog_features.name_spacing:
                matched.append("spacing_name")
            else:
                conflicting.append("name")
        for source_kind, (left, left_punctuation, left_spacing) in source_addresses.items():
            catalog_addr1, addr1_punctuation, addr1_spacing = catalog_addresses["road"]
            if left and catalog_addr1:
                if left == catalog_addr1:
                    matched.append(f"strict_{source_kind}_to_generic_addr1")
                elif left_punctuation == addr1_punctuation:
                    matched.append(f"punctuation_{source_kind}_to_generic_addr1")
                elif left_spacing == addr1_spacing:
                    matched.append(f"spacing_{source_kind}_to_generic_addr1")
                else:
                    conflicting.append(f"{source_kind}_to_generic_addr1")
        source_lot, source_lot_punctuation, source_lot_spacing = source_addresses["lot"]
        catalog_lot, catalog_lot_punctuation, catalog_lot_spacing = catalog_addresses["lot"]
        if source_lot and catalog_lot:
            left = source_lot
            if left == catalog_lot:
                matched.append("strict_lot_address")
            elif source_lot_punctuation == catalog_lot_punctuation:
                matched.append("punctuation_lot_address")
            elif source_lot_spacing == catalog_lot_spacing:
                matched.append("spacing_lot_address")
            else:
                conflicting.append("lot_address")
        # Cross-type address overlap is candidate evidence only and cannot
        # override a disagreement between road and lot fields.
        if (source_features.road_exact and catalog_lot
                and source_features.road_punctuation == catalog_lot_punctuation):
            matched.append("cross_type_road_to_lot_address")
        if (source_lot and catalog_addr1
                and source_lot_punctuation == addr1_punctuation):
            matched.append("cross_type_lot_to_generic_addr1")
        if (source.admin_crosswalk_validated and item.admin_components_validated
                and source.admin_components and item.admin_components):
            source_admin = source_features.admin_components
            item_admin = catalog_features.admin_components
            if source_admin == item_admin:
                matched.append("validated_admin_components")
            else:
                conflicting.append("validated_admin_components")
        address_pairs = [(left, right)
                         for source_kind, (left, _, _) in source_addresses.items()
                         for catalog_kind, (right, _, _) in catalog_addresses.items()
                         if left and right]
        address_pairs.sort(key=lambda pair: _similarity_character_upper_bound(*pair), reverse=True)
        address_similarity = 0.0
        for left, right in address_pairs:
            if _similarity_character_upper_bound(left, right) <= address_similarity:
                continue
            address_similarity = max(address_similarity, _similarity(left, right))
        return CandidateEvidence(
            item=item,
            rule=rule,
            name_similarity=_similarity(source_name, catalog_name),
            address_similarity=address_similarity,
            source_name=source.name,
            source_address=source.road_address,
            source_lot_address=source.lot_address,
            matched_signals=tuple(sorted(set(matched))),
            conflicting_signals=tuple(sorted(set(conflicting))),
        )

    def strict_result(self, source: SourcePoi, *,
                      source_conflicted: bool = False) -> MatchResult:
        def result(status: MatchStatus, canonical_id: str | None, method: str,
                   count: int, validation: Literal["unreviewed", "requires_review"]):
            return MatchResult(status, canonical_id, method, count, validation,
                               None, self.snapshot_version)

        name = normalize_exact(source.name)
        address = normalize_exact(source.road_address)
        if source_conflicted:
            return result("AMBIGUOUS", None, "conflicting_source_metadata", 0,
                          "requires_review")
        if not source.region or not source.poi_id.strip() or not name:
            return result("UNMATCHED", None, "insufficient_source_identity", 0,
                          "requires_review")
        named = self.by_exact_name.get(name, [])
        if not named:
            return result("UNMATCHED", None, "no_exact_name", 0, "requires_review")
        if not address:
            return result("AMBIGUOUS", None, "name_without_address", len(named),
                          "requires_review")
        exact = self.by_exact_name_and_road_address.get((name, address), [])
        if not exact:
            return result("AMBIGUOUS", None, "name_address_conflict", len(named),
                          "requires_review")
        if len(exact) != 1 or not self.catalog[exact[0]].content_id.strip():
            return result("AMBIGUOUS", None, "duplicate_exact_pair", len(exact),
                          "requires_review")
        canonical_id = self.catalog[exact[0]].content_id.strip()
        if self.content_id_counts[canonical_id] != 1:
            return result("AMBIGUOUS", None, "conflicting_canonical_id", len(exact),
                          "requires_review")
        return result("MATCHED", canonical_id, "unique_exact_name_address", 1,
                      "unreviewed")

    def generate(self, source: SourcePoi, *, source_conflicted: bool = False,
                 _candidate_id_bitmap: bytearray | None = None,
                 _candidate_record_bitmap: bytearray | None = None,
                 _progress: Callable[[str, int], None] | None = None,
                 _progress_interval: int = 5_000,
                 _block_progress_interval: int = 100_000,
                 _rank_name_first: bool = False,
                 ) -> CandidateGenerationResult:
        source_features = _identity_features(source.name, source.road_address,
                                             source.lot_address, source.admin_components)
        strict = self.strict_result(source, source_conflicted=source_conflicted)
        if strict.status == "MATCHED" and strict.canonical_id:
            item = self.by_content_id[strict.canonical_id]
            self._mark_candidate_id(_candidate_id_bitmap, strict.canonical_id)
            self._mark_candidate_record(
                _candidate_record_bitmap, self.catalog_record_ordinals[id(item)])
            evidence = self._evidence(source, item, strict.method, source_features)
            decision: PipelineStatus = "REVIEW" if evidence.conflicting_signals else "MATCHED"
            method = ("strict_pair_with_signal_conflict" if evidence.conflicting_signals
                      else strict.method)
            return CandidateGenerationResult(
                decision, "stage1_exact", method, (evidence,), 1,
                "unique_normalized_name_and_address_string", strict,
            )
        if source_conflicted:
            return CandidateGenerationResult("AMBIGUOUS", "none", strict.method,
                                             (), 0, "conflicting_source_metadata", strict)
        name = normalize_exact(source.name)
        exact_candidates = self.by_exact_name.get(name, [])
        punctuation_key = normalize_punctuation_candidate(source.name)
        # Stage 2 uses normalized exact keys; Stage 3 is a fallback set of
        # broader blocking rules. Both retain collisions and remain review-only.
        # Fixed-size per-catalog arrays plus a compact ordinal buffer avoid
        # per-candidate dictionaries, sets, and evidence objects. Generation
        # stamps avoid clearing/scanning the full catalog for each source.
        if self._candidate_generation_number >= 0xFFFFFFFF:
            for ordinal in range(len(self.catalog)):
                self._candidate_generations[ordinal] = 0
            self._candidate_generation_number = 0
        self._candidate_generation_number += 1
        generation_number = self._candidate_generation_number
        candidate_ordinals = array("Q")
        candidate_count = 0
        block_union = 0
        indexed_entries = 0

        def add_block(items: array, block: str) -> None:
            nonlocal candidate_count, block_union, indexed_entries
            block_bit = _CANDIDATE_BLOCK_BITS[block]
            for ordinal in items:
                block_union |= block_bit
                if self._candidate_generations[ordinal] != generation_number:
                    self._candidate_generations[ordinal] = generation_number
                    self._candidate_masks[ordinal] = block_bit
                    candidate_count += 1
                    self._candidate_first_seen[ordinal] = candidate_count
                    candidate_ordinals.append(ordinal)
                else:
                    self._candidate_masks[ordinal] |= block_bit
                indexed_entries += 1
                if (_progress is not None and _block_progress_interval > 0
                        and indexed_entries % _block_progress_interval == 0):
                    _progress("blocking", indexed_entries)

        add_block(exact_candidates, "exact_name")
        add_block(self.by_punctuation_name.get(punctuation_key, []), "punctuation_name")
        spacing_name_key = normalize_spacing_candidate(source.name)
        add_block(self.by_spacing_name.get(spacing_name_key, []), "spacing_name")
        source_address_fields = (source.road_address, source.lot_address)
        address_keys = {normalize_punctuation_candidate(value) for value in source_address_fields if value}
        for key in address_keys:
            add_block(self.by_punctuation_address.get(key, []), "catalog_addr1_key")
            add_block(self.by_lot_address.get(key, []), "lot_address_key")
        for value in source_address_fields:
            spacing_key = normalize_spacing_candidate(value)
            if spacing_key:
                add_block(self.by_spacing_road_address.get(spacing_key, []),
                          "spacing_catalog_addr1_key")
                add_block(self.by_spacing_lot_address.get(spacing_key, []),
                          "spacing_lot_address_key")

        stage = "stage2_normalized"
        if candidate_count == 0:
            stage = "stage3_fuzzy"
            if punctuation_key:
                for token in set(punctuation_key.split()):
                    add_block(self.by_name_token.get(token, []), "name_token")
                if len(punctuation_key) >= 2:
                    add_block(self.by_name_prefix.get(punctuation_key[:2], []), "name_prefix_2")
            for value in source_address_fields:
                key = normalize_punctuation_candidate(value)
                for piece in set(key.split()):
                    add_block(self.by_address_piece.get(piece, []), "address_piece")
            if source.admin_crosswalk_validated:
                for component in source.admin_components:
                    key = normalize_exact(component)
                    if key:
                        add_block(self.by_admin_component.get(key, []), "validated_admin_component")
            for gram in _char_ngrams(punctuation_key):
                add_block(self.by_ngram.get(gram, []), "character_trigram")

        if candidate_count:
            all_blocks = {block for block, bit in _CANDIDATE_BLOCK_BITS.items()
                          if block_union & bit}
            evidence_heap: list[tuple[tuple[float, float, str, int], int,
                                      CandidateEvidence]] = []
            scored_candidates = 0
            for ordinal in candidate_ordinals:
                mask = self._candidate_masks[ordinal]
                scored_candidates += 1
                item = self.catalog[ordinal]
                canonical_id = item.content_id.strip()
                self._mark_candidate_id(_candidate_id_bitmap, canonical_id)
                self._mark_candidate_record(_candidate_record_bitmap, ordinal)
                rule = "+".join(sorted(block for block, bit in _CANDIDATE_BLOCK_BITS.items()
                                       if mask & bit))
                features = self.catalog_features[id(item)]
                source_address_values = (
                    source_features.road_exact,
                    source_features.lot_exact,
                )
                catalog_address_values = (
                    features.road_exact,
                    features.lot_exact,
                )
                name_upper = _similarity_length_upper_bound(
                    source_features.name_exact, features.name_exact)
                address_upper = max((_similarity_length_upper_bound(left, right)
                                     for left in source_address_values
                                     for right in catalog_address_values if left and right),
                                    default=0.0)
                rank_upper = ((name_upper, address_upper, item.content_id,
                               -self._candidate_first_seen[ordinal]) if _rank_name_first else
                              (address_upper, name_upper, item.content_id,
                               -self._candidate_first_seen[ordinal]))
                if len(evidence_heap) >= self.fuzzy_display_limit and rank_upper <= evidence_heap[0][0]:
                    if (_progress is not None and _progress_interval > 0
                            and scored_candidates % _progress_interval == 0):
                        _progress("scoring", scored_candidates)
                    continue
                if len(evidence_heap) >= self.fuzzy_display_limit:
                    name_upper = _similarity_character_upper_bound(
                        source_features.name_exact, features.name_exact)
                    address_upper = max((_similarity_character_upper_bound(left, right)
                                         for left in source_address_values
                                         for right in catalog_address_values if left and right),
                                        default=0.0)
                    rank_upper = ((name_upper, address_upper, item.content_id,
                                   -self._candidate_first_seen[ordinal]) if _rank_name_first else
                                  (address_upper, name_upper, item.content_id,
                                   -self._candidate_first_seen[ordinal]))
                    if rank_upper <= evidence_heap[0][0]:
                        if (_progress is not None and _progress_interval > 0
                                and scored_candidates % _progress_interval == 0):
                            _progress("scoring", scored_candidates)
                        continue
                evidence = self._evidence(source, item, rule, source_features)
                # Reverse sorting in the former full materialization was
                # stable, so earlier block discovery wins exact rank ties.
                rank = ((evidence.name_similarity, evidence.address_similarity,
                         item.content_id, -self._candidate_first_seen[ordinal]) if _rank_name_first else
                        (evidence.address_similarity, evidence.name_similarity,
                         item.content_id, -self._candidate_first_seen[ordinal]))
                entry = (rank, ordinal, evidence)
                if len(evidence_heap) < self.fuzzy_display_limit:
                    heappush(evidence_heap, entry)
                else:
                    heappushpop(evidence_heap, entry)
                if (_progress is not None and _progress_interval > 0
                        and scored_candidates % _progress_interval == 0):
                    _progress("scoring", scored_candidates)
            if _progress is not None and scored_candidates % max(1, _progress_interval):
                _progress("scoring", scored_candidates)
            evidence = tuple(value[2] for value in sorted(evidence_heap, reverse=True))
            # Conflicts and all multi-candidate sets require human review.
            status: PipelineStatus = ("AMBIGUOUS" if candidate_count > 1
                                      else "REVIEW")
            blocks = all_blocks
            if stage == "stage2_normalized":
                has_name = bool(blocks & {"exact_name", "punctuation_name", "spacing_name"})
                has_address = bool(blocks & {"catalog_addr1_key", "lot_address_key",
                                             "spacing_catalog_addr1_key", "spacing_lot_address_key"})
                if has_name and has_address:
                    method = "normalized_multi_rule_candidates"
                elif "exact_name" in blocks:
                    method = "exact_name_address_string_variant"
                elif "punctuation_name" in blocks:
                    method = "punctuation_name_variant"
                elif "spacing_name" in blocks:
                    method = "spacing_name_variant"
                elif "catalog_addr1_key" in blocks:
                    method = "punctuation_address_variant"
                elif "lot_address_key" in blocks:
                    method = "punctuation_lot_address_variant"
                elif "spacing_catalog_addr1_key" in blocks:
                    method = "spacing_address_variant"
                else:
                    method = "spacing_lot_address_variant"
            elif blocks == {"character_trigram"}:
                method = "fuzzy_character_trigram_block"
            elif len(blocks) == 1:
                method = next(iter(blocks)) + "_block"
            else:
                method = "stage3_multi_block_candidates"
            blocking = "union:" + "+".join(sorted(all_blocks))
            return CandidateGenerationResult(status, stage, method,
                                             evidence, candidate_count,
                                             blocking, strict)
        if not name:
            return CandidateGenerationResult("UNMATCHED", "none", "missing_source_name",
                                             (), 0, "no_source_name", strict)

        if candidate_count == 0:
            return CandidateGenerationResult("UNMATCHED", "none", "no_candidate_block_hit",
                                             (), 0, "no_stage2_or_stage3_block_hit", strict)

    def _mark_candidate_id(self, bitmap: bytearray | None, canonical_id: str) -> None:
        if bitmap is None:
            return
        ordinal = self.content_id_ordinals[canonical_id.strip()]
        bitmap[ordinal >> 3] |= 1 << (ordinal & 7)

    @staticmethod
    def _mark_candidate_record(bitmap: bytearray | None, ordinal: int) -> None:
        if bitmap is not None:
            bitmap[ordinal >> 3] |= 1 << (ordinal & 7)


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
