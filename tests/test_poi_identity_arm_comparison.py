from __future__ import annotations

import unittest
from collections import defaultdict

from scripts.recommendation.compare_poi_identity_arms import (
    CANONICAL_IDENTITY_ARM, _arm_counts, _arm_e_sources, _compare_master_visit_identity,
    _address_resolution_shadow, _address_relation_a2, _normalize_address_a1,
    _cross_region_master_diagnostic,
    _diagnose_name_miss, _master_visit_diagnostics, _name_recovery_indexes,
    _name_recovery_for_units, _resolve_one, BRANCH_PATTERN,
)
from scripts.recommendation.poi_catalog_candidate_contract import (
    CatalogPoi, SourcePoi, match_source_item,
)


class IdentityArmComparisonTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = type("Policy", (), {
            "product_region_to_ldong_regn_cd": {
                "capital": frozenset({"11"}), "west": frozenset({"26"}),
                "east": frozenset({"27"}), "jeju-islands": frozenset({"50"}),
            },
            "supported_content_type_ids": frozenset({"12", "14", "28"}),
        })()

    def test_global_master_arm_is_selected_as_canonical_followup_path(self) -> None:
        self.assertEqual(CANONICAL_IDENTITY_ARM, "D")

    def test_global_exact_name_address_matches_across_source_region(self) -> None:
        item = CatalogPoi("canonical", title="Museum", address="Road 1",
                          content_type_id="12", region_codes=frozenset({"26"}))
        result = _resolve_one("source", {("Museum", "", "", "Road 1")},
                              "capital", [item], {}, global_scope=True)
        self.assertEqual((result.status, result.canonical_item_id), ("MATCHED", "canonical"))

    def test_arm_a_region_constrained_match_regresses_to_existing_contract(self) -> None:
        item = CatalogPoi("canonical", title="Museum", address="Road 1",
                          content_type_id="12", region_codes=frozenset({"11"}))
        signals = {("Museum", "", "", "Road 1")}
        result = _resolve_one("source", signals, "capital", [item],
                              {"capital": frozenset({"11"})})
        baseline = match_source_item(
            SourcePoi("source", "capital", name="Museum", address="Road 1"),
            [item], source_region_to_admin_codes={"capital": frozenset({"11"})},
        )
        self.assertEqual((result.status, result.canonical_item_id, result.method, result.candidate_count),
                         (baseline.status, baseline.canonical_item_id, baseline.method, baseline.candidate_count))

    def test_master_single_signal_stabilizes_visit_metadata_conflict(self) -> None:
        visits = {"poi": {("Name", "11", "", "Road 1"), ("Name", "11", "Lot 2", "Road 1")}}
        master = {"poi": {("Name", "11", "Lot 2", "Road 1")}}
        candidate = CatalogPoi("canonical", title="Name", address="Road 1",
                               content_type_id="12", region_codes=frozenset({"11"}))
        result = _resolve_one("poi", master["poi"], "capital", [candidate],
                              {"capital": frozenset({"11"})})
        self.assertEqual((result.status, result.canonical_item_id), ("MATCHED", "canonical"))
        diagnostic = _master_visit_diagnostics(visits, master)
        self.assertEqual(diagnostic["visit_internally_inconsistent"], 1)
        self.assertEqual(diagnostic["visit_conflict_stabilized_by_master"], 1)

    def test_master_missing_does_not_fall_back_to_visit_fields(self) -> None:
        # Master arm's absent key is surfaced as UNMATCHED/master_missing by the arm path.
        catalog = [CatalogPoi("canonical", title="Name", address="Road 1",
                              content_type_id="12", region_codes=frozenset({"11"}))]
        regions = {("capital", "name"): catalog}
        globals_ = {"name": catalog}
        result = _arm_counts("capital", "TL", {}, {("trip", "missing")}, catalog,
                             regions, globals_, frozenset({"11"}), self.policy, "B")
        self.assertEqual(result["UNMATCHED"], 0)
        self.assertEqual(result["identity_source_missing"], 1)
        self.assertEqual(result["identity_source_available"], 0)
        self.assertEqual(result["positives_with_identity_source"], 0)
        self.assertEqual(result["candidate_title_count_0_1_2plus_by_positive"], {})
        self.assertEqual(result["global_exact_title_diagnostic_by_positive"], {})
        self.assertNotIn("global_exact_title_absent",
                         result["global_exact_title_diagnostic_by_positive"])

    def test_master_title_diagnostic_denominator_contains_available_positives_only(self) -> None:
        item = CatalogPoi("canonical", title="Name", address="Road 1",
                          content_type_id="12", region_codes=frozenset({"11"}))
        result = _arm_counts("capital", "TL", {"available": {("Name", "", "", "Road 1")}},
                             {("trip-1", "available"), ("trip-2", "missing")}, [item],
                             {("capital", "name"): [item]}, {"name": [item]},
                             frozenset({"11", "26", "27", "50"}), self.policy, "B")
        self.assertEqual((result["identity_source_available"], result["identity_source_missing"]), (1, 1))
        self.assertEqual(result["positives_with_identity_source"], 1)
        self.assertEqual(result["candidate_title_count_positive_denominator"], 1)
        self.assertEqual(result["candidate_title_count_0_1_2plus_by_positive"], {"1": 1})
        self.assertEqual(result["MATCHED"] + result["AMBIGUOUS"] + result["UNMATCHED"]
                         + result["identity_source_missing"], result["all_positives"])

    def _arm_e(self, master, visits, item, poi_id="poi"):
        sources, provenance = _arm_e_sources(master, visits, {poi_id})
        catalog = [item] if item else []
        regional = {("capital", "name"): catalog} if item and item.title == "Name" else {}
        global_ = {"name": catalog} if item and item.title == "Name" else {}
        return _arm_counts("capital", "TL", sources, {("trip", poi_id)}, catalog,
                           regional, global_, frozenset({"11", "26", "27", "50"}),
                           self.policy, "E", provenance)

    def test_arm_e_master_metadata_wins_when_visit_values_differ(self) -> None:
        master = {"poi": {("Name", "11", "", "Road 1")}}
        visits = {"poi": {("Other title", "26", "", "Other road")}}
        sources, provenance = _arm_e_sources(master, visits, {"poi"})
        self.assertEqual(sources["poi"], master["poi"])
        self.assertEqual(provenance["poi"], "master")
        item = CatalogPoi("canonical", title="Name", address="Road 1",
                          content_type_id="12", region_codes=frozenset({"11"}))
        result = _arm_counts("capital", "TL", sources, {("trip", "poi")}, [item],
                             {("capital", "name"): [item]}, {"name": [item]},
                             frozenset({"11", "26", "27", "50"}), self.policy, "E", provenance)
        self.assertEqual(result["MATCHED"], 1)
        self.assertEqual(result["identity_metadata_source_by_positive"], {"master": 1})

    def test_arm_e_master_missing_uses_visit_fallback(self) -> None:
        result = self._arm_e({}, {"poi": {("Name", "11", "", "Road 1")}},
                             CatalogPoi("canonical", title="Name", address="Road 1",
                                        content_type_id="12", region_codes=frozenset({"11"})))
        self.assertEqual(result["MATCHED"], 1)
        self.assertEqual(result["identity_metadata_source_by_positive"], {"visit_fallback": 1})
        self.assertEqual(result["visit_fallback_subset"]["all_positives"], 1)

    def test_arm_e_master_missing_visit_conflict_preserves_conflict_behavior(self) -> None:
        result = self._arm_e({}, {"poi": {("Name", "11", "", "Road 1"),
                                         ("Name", "11", "Lot 2", "Road 1")}}, None)
        self.assertEqual((result["AMBIGUOUS"], result["MATCHED"]), (1, 0))
        self.assertEqual(result["positive_match_methods"], {"source_signal_conflict": 1})

    def test_arm_e_master_missing_visit_without_exact_title_is_unmatched(self) -> None:
        item = CatalogPoi("canonical", title="Different", address="Road 1",
                          content_type_id="12", region_codes=frozenset({"11"}))
        result = self._arm_e({}, {"poi": {("Name", "11", "", "Road 1")}}, item)
        self.assertEqual(result["UNMATCHED"], 1)
        self.assertEqual(result["visit_fallback_subset"]["exact_title_candidate_count_0_1_2plus"], {"0": 1})

    def test_arm_e_fallback_match_reports_unsupported_type(self) -> None:
        item = CatalogPoi("canonical", title="Name", address="Road 1",
                          content_type_id="39", region_codes=frozenset({"11"}))
        result = self._arm_e({}, {"poi": {("Name", "11", "", "Road 1")}}, item)
        self.assertEqual(result["MATCHED"], 1)
        self.assertEqual(result["visit_fallback_subset"]["matched_eligibility_reasons"],
                         {"unsupported_content_type": 1})

    def test_arm_e_fallback_match_outside_request_region_is_not_eligible(self) -> None:
        item = CatalogPoi("canonical", title="Name", address="Road 1",
                          content_type_id="12", region_codes=frozenset({"26"}))
        result = self._arm_e({}, {"poi": {("Name", "11", "", "Road 1")}}, item)
        self.assertEqual(result["MATCHED"], 1)
        self.assertEqual(result["visit_fallback_subset"]["matched_eligibility_reasons"],
                         {"outside_request_region": 1})

    def test_master_visit_shadow_validation_agreement_and_visit_conflicts(self) -> None:
        item_a = CatalogPoi("provider-a", title="Place", address="Road A",
                            content_type_id="12", region_codes=frozenset({"11"}))
        item_b = CatalogPoi("provider-b", title="Place", address="Road B",
                            content_type_id="12", region_codes=frozenset({"11"}))
        visits = {
            "same": {("Place", "", "", "Road A")},
            "different": {("Place", "", "", "Road B")},
            "conflict": {("Place", "", "", "Road A"), ("Place", "", "Lot A", "Road A")},
            "master_unmatched": {("Place", "", "", "Road A")},
        }
        masters = {
            "same": {("Place", "", "", "Road A")},
            "different": {("Place", "", "", "Road A")},
            "conflict": {("Place", "", "", "Road A")},
            "master_unmatched": {("Absent", "", "", "Road A")},
        }
        result = _compare_master_visit_identity(
            "capital", [(f"trip-{poi_id}", poi_id) for poi_id in visits],
            visits, masters, {"place": [item_a, item_b]}, self.policy)
        overall = result["overall"]
        self.assertEqual(overall["positive_count"], 4)
        self.assertEqual(overall["both_MATCHED"], 2)
        self.assertEqual(overall["both_MATCHED_same_contentid"], 1)
        self.assertEqual(overall["both_MATCHED_different_contentid"], 1)
        self.assertEqual(overall["canonical_contentid_agreement_rate_among_both_MATCHED"], {
            "count": 1, "denominator": 2, "percent": 50.0,
        })
        self.assertEqual(overall["status_pair_counts"]["Master_MATCHED_visit_AMBIGUOUS"], 1)
        self.assertEqual(overall["status_pair_counts"]["Master_UNMATCHED_visit_MATCHED"], 1)
        self.assertEqual(result["by_visit_signal_class"]["source_signal_conflict"]["positive_count"], 1)
        self.assertEqual(result["by_visit_signal_class"]["single_metadata"]["positive_count"], 3)
        self.assertEqual(result["canonical_promotion"], False)

    def _recovery(self, source_name, catalog, road="Road 1"):
        global_index = {}
        for item in catalog:
            if item.title:
                global_index.setdefault(item.title.casefold(), []).append(item)
        n1, titles, grams = _name_recovery_indexes(catalog)
        signals = {(source_name, "", "", road)}
        return _diagnose_name_miss(signals, global_index, n1, titles, grams)

    def test_name_recovery_punctuation_only_difference_and_exact_address(self) -> None:
        item = CatalogPoi("poi-1", title="Cafe River", address="Road 1",
                          content_type_id="12", region_codes=frozenset({"11"}))
        result = self._recovery("Cafe-River", [item])
        self.assertEqual(result["n1_ids"], {"poi-1"})
        self.assertEqual(result["n1_address_category"], "exact_address_match")

    def test_name_recovery_no_exact_title_candidate_is_retained_as_miss(self) -> None:
        result = self._recovery("Unrelated Place", [])
        self.assertIsNotNone(result)
        self.assertEqual(result["n1_ids"], set())
        self.assertEqual(result["n2_ids"], set())

    def test_name_recovery_parenthetical_variant_is_diagnostic(self) -> None:
        item = CatalogPoi("poi-1", title="Museum", address="Road 1",
                          content_type_id="12", region_codes=frozenset({"11"}))
        result = self._recovery("Museum (North)", [item])
        self.assertEqual(result["n1_ids"], set())
        self.assertEqual(result["n2_incremental_ids"], {"poi-1"})

    def test_name_suffixes_are_tags_and_never_removed_for_recovery(self) -> None:
        branch = CatalogPoi("branch", title="Cafe Gangnam", address="Road 1",
                            content_type_id="12", region_codes=frozenset({"11"}))
        facility = CatalogPoi("facility", title="Hall", address="Road 1",
                              content_type_id="12", region_codes=frozenset({"11"}))
        branch_result = self._recovery("Cafe Gangnam점", [branch])
        facility_result = self._recovery("Hall 주차장", [facility])
        self.assertEqual(branch_result["n1_ids"], set())
        self.assertIn("branch_suffix_present", branch_result["tags"])
        canonical = match_source_item(
            SourcePoi("source", "capital", name="Cafe Gangnam점", address="Road 1"),
            [branch], source_region_to_admin_codes={"capital": frozenset({"11"})},
        )
        self.assertEqual(canonical.status, "UNMATCHED")
        self.assertEqual(facility_result["n1_ids"], set())
        self.assertIn("facility_subpoi_suffix_present", facility_result["tags"])

    def test_branch_suffix_requires_terminal_branch_token(self) -> None:
        self.assertIsNotNone(BRANCH_PATTERN.search("서울점"))
        self.assertIsNotNone(BRANCH_PATTERN.search("Cafe 강남지점"))
        self.assertIsNone(BRANCH_PATTERN.search("점심 먹으러 갈 장소"))
        self.assertIsNone(BRANCH_PATTERN.search("관광지점검 안내"))
        result = self._recovery("관광지점검 안내", [])
        self.assertNotIn("branch_suffix_present", result["tags"])

    def test_address_shadow_splits_ambiguous_title_candidate_buckets(self) -> None:
        one = CatalogPoi("single", title="Place", address="Different Road",
                         content_type_id="12", region_codes=frozenset({"11"}))
        two_a = CatalogPoi("two-a", title="Branch", address="Same Road",
                           content_type_id="12", region_codes=frozenset({"11"}))
        two_b = CatalogPoi("two-b", title="Branch", address="Same Road",
                           content_type_id="12", region_codes=frozenset({"11"}))
        missing = CatalogPoi("missing", title="Missing", address="Catalog Road",
                             content_type_id="12", region_codes=frozenset({"11"}))
        sources = {
            "one": {("Place", "", "", "Source Road")},
            "two": {("Branch", "", "", "Same Road")},
            "missing": {("Missing", "", "", "   ")},
        }
        diagnostic = _address_resolution_shadow(
            "capital", sources, [("trip-1", "one"), ("trip-2", "two"), ("trip-3", "missing")],
            {"place": [one], "branch": [two_a, two_b], "missing": [missing]},
            {"capital": frozenset({"11"})},
        )
        result = diagnostic["overall"]
        self.assertEqual(result["ambiguous_positive_count"], 3)
        self.assertEqual(result["exact_title_candidate_counts_0_1_2plus"], {"0": 0, "1": 2, "2+": 1})
        self.assertEqual(result["address_resolution_outcome_counts"], {
            "address_mismatch": 1, "multiple_exact_address_candidates": 1,
            "source_address_missing": 1,
        })
        self.assertEqual(result["source_address_presence_counts"]["none"], 1)

    def test_address_a1_normalizes_punctuation_and_whitespace_only(self) -> None:
        self.assertEqual(_normalize_address_a1(" 서울시  강남구, 테헤란로 12-3 "),
                         _normalize_address_a1("서울시 강남구 테헤란로 12 3"))
        self.assertEqual(_address_relation_a2("서울시 강남구, 테헤란로 12-3",
                                              "서울시 강남구 테헤란로 12 3"), "normalized_exact")
        self.assertEqual(_address_relation_a2("서울시 강남구 테헤란로",
                                              "서울시 서초구 테헤란로"), "partial_overlap")

    def test_address_a1_does_not_normalize_meaningful_text(self) -> None:
        self.assertNotEqual(_normalize_address_a1("서울 강남구 테헤란로"),
                            _normalize_address_a1("서울 서초구 테헤란로"))
        self.assertEqual(_address_relation_a2("서울 강남구 테헤란로",
                                              "서울 서초구 테헤란로"), "partial_overlap")

    def test_address_a2_reports_token_relations_and_missing_values(self) -> None:
        self.assertEqual(_address_relation_a2("서울 강남구", "서울 강남구 테헤란로"),
                         "source_tokens_subset_of_catalog")
        self.assertEqual(_address_relation_a2("서울 강남구 테헤란로", "서울 강남구"),
                         "catalog_tokens_subset_of_source")
        self.assertEqual(_address_relation_a2("서울 강남구", "서울 서초구"), "partial_overlap")
        self.assertEqual(_address_relation_a2("서울 강남구", "부산 해운대구"), "no_meaningful_overlap")
        self.assertEqual(_address_relation_a2("", "부산 해운대구"), "source_address_missing")
        self.assertEqual(_address_relation_a2("서울 강남구", ""), "catalog_address_missing")

    def test_address_shadow_a1_selects_unique_or_multiple_candidates(self) -> None:
        def run(candidates, source_address):
            sources = {"poi": {("Place", "", "", source_address)}}
            result = _address_resolution_shadow(
                "capital", sources, [("trip", "poi")],
                {"place": candidates}, {"capital": frozenset({"11"})},
            )["overall"]
            return result

        one = run([
            CatalogPoi("a", title="Place", address="12-3 Main St.", content_type_id="12"),
            CatalogPoi("b", title="Place", address="Other Road", content_type_id="12"),
        ], "12 3 Main St")
        self.assertEqual(one["exact_title_candidate_counts_0_1_2plus"]["2+"], 1)
        self.assertEqual(one["A1_outcome_counts_by_exact_title_candidate_count"]["2+"]
                         ["exactly_one_candidate_selected"], 1)
        self.assertEqual(one["A1_selected_candidate_counts_by_exact_title_candidate_count"]["2+"]["1"], 1)

        multiple = run([
            CatalogPoi("a", title="Place", address="12-3 Main St", content_type_id="12"),
            CatalogPoi("b", title="Place", address="12/3 Main St", content_type_id="12"),
        ], "12 3 Main St")
        self.assertEqual(multiple["A1_outcome_counts_by_exact_title_candidate_count"]["2+"]
                         ["multiple_candidates_selected"], 1)

    def test_address_shadow_keeps_a0_and_reports_a1_exact_and_unresolved(self) -> None:
        exact = CatalogPoi("exact", title="Place", address="12-3 Main St.", content_type_id="12")
        mismatch = CatalogPoi("mismatch", title="Other", address="Different Rd", content_type_id="12")
        missing = CatalogPoi("missing", title="Missing", address="Catalog Rd", content_type_id="12")
        sources = {
            "exact": {("Place", "", "", "12 3 Main St")},
            "mismatch": {("Other", "", "", "Source Rd")},
            "missing": {("Missing", "", "", "")},
        }
        positives = [("t1", "exact"), ("t2", "mismatch"), ("t3", "missing"), ("t4", "exact")]
        diagnostic = _address_resolution_shadow(
            "capital", sources, positives,
            {"place": [exact], "other": [mismatch], "missing": [missing]},
            {"capital": frozenset({"11"})},
        )["overall"]
        self.assertEqual(diagnostic["ambiguous_positive_count"], 4)
        self.assertEqual(diagnostic["A1_outcome_counts_by_exact_title_candidate_count"]["1"]["normalized_exact"], 2)
        self.assertEqual(diagnostic["A1_outcome_counts_by_exact_title_candidate_count"]["1"]["still_mismatch"], 1)
        self.assertEqual(diagnostic["A1_outcome_counts_by_exact_title_candidate_count"]["1"]["source_missing"], 1)
        # A0 remains exact under the old normalizer, so the punctuation-only case
        # also remains an A0 mismatch even though A1 diagnoses it as exact.
        self.assertEqual(diagnostic["address_resolution_outcome_counts"]["address_mismatch"], 3)
        self.assertEqual(diagnostic["address_resolution_outcome_counts"]["source_address_missing"], 1)

    def test_address_shadow_has_distinct_unique_poi_and_repeated_positive_denominators(self) -> None:
        candidates = [CatalogPoi("a", title="Place", address="Different", content_type_id="12")]
        sources = {"poi": {("Place", "", "", "Source")}}
        repeated = _address_resolution_shadow(
            "capital", sources, [("t1", "poi"), ("t2", "poi")],
            {"place": candidates}, {"capital": frozenset({"11"})},
        )["overall"]
        unique = _address_resolution_shadow(
            "capital", sources, [("poi", "poi")],
            {"place": candidates}, {"capital": frozenset({"11"})},
        )["overall"]
        self.assertEqual(repeated["ambiguous_positive_count"], 2)
        self.assertEqual(unique["ambiguous_positive_count"], 1)
        self.assertEqual(repeated["A1_outcome_counts_by_exact_title_candidate_count"]["1"]["still_mismatch"], 2)
        self.assertEqual(unique["A1_outcome_counts_by_exact_title_candidate_count"]["1"]["still_mismatch"], 1)

    def test_name_recovery_multiple_relaxed_candidates_and_address_mismatch(self) -> None:
        items = [
            CatalogPoi("poi-1", title="Cafe River", address="Other Road",
                       content_type_id="12", region_codes=frozenset({"11"})),
            CatalogPoi("poi-2", title="Cafe River", address="Another Road",
                       content_type_id="12", region_codes=frozenset({"11"})),
        ]
        result = self._recovery("Cafe-River", items)
        self.assertEqual(result["n1_ids"], {"poi-1", "poi-2"})
        self.assertEqual(result["n1_address_category"], "address_mismatch")

    def test_name_recovery_reports_source_address_missing(self) -> None:
        item = CatalogPoi("poi-1", title="Cafe River", address="Road 1",
                          content_type_id="12", region_codes=frozenset({"11"}))
        result = self._recovery("Cafe-River", [item], road="")
        self.assertEqual(result["n1_address_category"], "source_address_missing")

    def test_fuzzy_retrieval_is_diagnostic_and_does_not_match(self) -> None:
        item = CatalogPoi("poi-1", title="Museum Gallery", address="Road 1",
                          content_type_id="12", region_codes=frozenset({"11"}))
        result = self._recovery("Museum Gallerie", [item])
        self.assertIn("poi-1", result["n4_ids"])
        canonical = match_source_item(
            SourcePoi("source", "capital", name="Museum Gallerie", address="Road 1"),
            [item], source_region_to_admin_codes={"capital": frozenset({"11"})},
        )
        self.assertNotEqual(canonical.status, "MATCHED")

    def test_name_recovery_counts_unique_and_positive_denominators_separately(self) -> None:
        catalog = [CatalogPoi("poi-1", title="Cafe River", address="Road 1",
                             content_type_id="12", region_codes=frozenset({"11"}))]
        global_index = {"cafe river": catalog}
        n1, titles, grams = _name_recovery_indexes(catalog)
        result = _name_recovery_for_units(
            "capital", {"source": {("Cafe-River", "", "", "Road 1")}},
            ["source", "source"], global_index, n1, titles, grams,
        )
        self.assertEqual(result["unique_source_poi"]["global_exact_title_absent_N0"], 1)
        self.assertEqual(result["observed_positive"]["global_exact_title_absent_N0"], 2)

    def test_cross_region_master_reports_one_other_master(self) -> None:
        masters = {"capital": {}, "west": {"poi": {("Name", "26", "Lot", "Road")} },
                   "east": {}, "jeju-islands": {}}
        result = _cross_region_master_diagnostic({"poi"}, [("trip", "poi")], "capital", masters)
        expected = {"absent_from_all_masters": 0, "found_in_one_other_master": 1,
                    "found_in_multiple_masters_same_metadata": 0,
                    "found_in_multiple_masters_conflicting_metadata": 0}
        self.assertEqual(result["source_poi"]["categories"], expected)
        self.assertEqual(result["observed_positive"]["categories"], expected)

    def test_cross_region_master_identical_metadata_is_classified(self) -> None:
        metadata = ("Name", "26", "Lot", "Road")
        masters = {"capital": {}, "west": {"poi": {metadata}},
                   "east": {"poi": {metadata}}, "jeju-islands": {}}
        result = _cross_region_master_diagnostic({"poi"}, [("trip", "poi")], "capital", masters)
        self.assertEqual(result["source_poi"]["categories"]["found_in_multiple_masters_same_metadata"], 1)

    def test_cross_region_master_conflicting_metadata_is_classified(self) -> None:
        masters = {"capital": {}, "west": {"poi": {("Name", "26", "Lot", "Road")}},
                   "east": {"poi": {("Name", "26", "Lot 2", "Road")}}, "jeju-islands": {}}
        result = _cross_region_master_diagnostic({"poi"}, [("trip", "poi")], "capital", masters)
        self.assertEqual(result["observed_positive"]["categories"]["found_in_multiple_masters_conflicting_metadata"], 1)

    def test_global_title_diagnostic_finds_candidate_outside_source_region(self) -> None:
        item = CatalogPoi("canonical", title="Museum", address="Different road",
                          content_type_id="12", region_codes=frozenset({"26"}))
        result = _arm_counts("capital", "TL", {"poi": {("Museum", "", "", "Road 1")}},
                             {("trip", "poi")}, [item], {}, {"museum": [item]},
                             frozenset({"11", "26", "27", "50"}), self.policy, "C")
        self.assertEqual(result["AMBIGUOUS"], 1)
        self.assertEqual(result["global_exact_title_diagnostic_by_positive"], {
            "exact_title_exists_outside_source_region_single": 1,
        })

    def test_global_identity_scope_includes_catalog_item_without_region_code(self) -> None:
        item = CatalogPoi("canonical", title="Museum", address="Road 1", content_type_id="12")
        result = _resolve_one("source", {("Museum", "", "", "Road 1")},
                              "capital", [item], {}, global_scope=True)
        self.assertEqual((result.status, result.canonical_item_id), ("MATCHED", "canonical"))

    def test_global_match_keeps_identity_matched_and_reports_eligibility(self) -> None:
        item = CatalogPoi("canonical", title="Restaurant", address="Road 1",
                          content_type_id="39", region_codes=frozenset({"26"}))
        result = _arm_counts("capital", "TL", {"poi": {("Restaurant", "", "", "Road 1")}},
                             {("trip", "poi")}, [item], {}, {"restaurant": [item]},
                             frozenset({"11", "26", "27", "50"}), self.policy, "C")
        self.assertEqual(result["MATCHED"], 1)
        self.assertEqual(result["matched_eligibility_reasons"], {
            "unsupported_content_type": 1,
        })

    def test_global_match_outside_request_region_remains_matched(self) -> None:
        item = CatalogPoi("canonical", title="Museum", address="Road 1",
                          content_type_id="12", region_codes=frozenset({"26"}))
        result = _arm_counts("capital", "TL", {"poi": {("Museum", "", "", "Road 1")}},
                             {("trip", "poi")}, [item], {}, {"museum": [item]},
                             frozenset({"11", "26", "27", "50"}), self.policy, "C")
        self.assertEqual(result["MATCHED"], 1)
        self.assertEqual(result["matched_eligibility_reasons"], {
            "outside_request_region": 1,
        })


if __name__ == "__main__":
    unittest.main()
