from __future__ import annotations

import unittest
from collections import defaultdict

from scripts.recommendation.compare_poi_identity_arms import (
    CANONICAL_IDENTITY_ARM, _arm_counts, _arm_e_sources, _compare_master_visit_identity,
    _cross_region_master_diagnostic,
    _master_visit_diagnostics, _resolve_one,
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
