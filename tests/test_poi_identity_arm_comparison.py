from __future__ import annotations

import unittest
from collections import defaultdict

from scripts.recommendation.compare_poi_identity_arms import (
    CANONICAL_IDENTITY_ARM, _arm_counts, _master_visit_diagnostics, _resolve_one,
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
        self.assertEqual(result["UNMATCHED"], 1)
        self.assertEqual(result["identity_source_missing"], 1)

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
