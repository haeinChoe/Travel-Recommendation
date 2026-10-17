from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from scripts.recommendation.analyze_poi_catalog_candidate_coverage import (
    REGIONS,
    ROLES,
    _match_sources,
    _rate,
    _row,
    analyze,
)
from scripts.recommendation.analyze_candidate_choice_feasibility import _summary_row, diagnose_region
from scripts.recommendation.evaluate_popularity import Event, SplitSummary
from scripts.recommendation.poi_catalog_candidate_contract import CatalogPoi


class ActualPoiExperimentTest(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = SimpleNamespace(product_region_to_ldong_regn_cd={"capital": frozenset({"11"})})
        self.catalog = CatalogPoi(
            content_id="catalog-private-fixture", title="Fixture Place", address="1 Test Road",
            content_type_id="12", region_codes=frozenset({"11"}),
            district_codes=frozenset({"101"}),
        )
        self.index = {("capital", "fixture place"): [self.catalog]}

    def test_exact_name_address_match(self) -> None:
        sources = {"source-private-fixture": {("Fixture Place", "101", "1 Test Road", "")}}
        matches, methods = _match_sources("capital", sources, self.index, self.policy)
        self.assertEqual(matches["source-private-fixture"].status, "MATCHED")
        self.assertEqual(matches["source-private-fixture"].method, "name_address")
        self.assertEqual(methods["name_address"], 1)

    def test_exact_address_is_not_vetoed_by_weak_alternate_address(self) -> None:
        other = CatalogPoi(
            content_id="second-private-fixture", title="Fixture Place", address="9 Other Road",
            content_type_id="12", region_codes=frozenset({"11"}),
            district_codes=frozenset({"101"}),
        )
        index = {("capital", "fixture place"): [self.catalog, other]}
        sources = {"source-private-fixture": {
            ("Fixture Place", "101", "1 Test Road", "9 Unknown Road")
        }}
        matches, _ = _match_sources("capital", sources, index, self.policy)
        self.assertEqual(matches["source-private-fixture"].status, "MATCHED")
        self.assertEqual(matches["source-private-fixture"].canonical_item_id,
                         "catalog-private-fixture")

    def test_conflicting_source_metadata_is_ambiguous(self) -> None:
        sources = {"source-private-fixture": {
            ("Fixture Place", "101", "1 Test Road", ""),
            ("Other Name", "102", "2 Other Road", ""),
        }}
        matches, methods = _match_sources("capital", sources, self.index, self.policy)
        self.assertEqual(matches["source-private-fixture"].status, "AMBIGUOUS")
        self.assertEqual(matches["source-private-fixture"].method, "source_signal_conflict")
        self.assertEqual(methods["source_signal_conflict"], 1)

    def test_default_aggregate_mode_keeps_existing_suppression(self) -> None:
        row = _row("capital", "MATCHED", "name_address", 2)
        self.assertEqual(row["support"], "<10")
        self.assertEqual(row["status"], "privacy_limited")
        self.assertNotIn("source-private-fixture", str(row))
        self.assertNotIn("catalog-private-fixture", str(row))

    def test_exact_aggregate_mode_reports_small_counts_without_identifiers(self) -> None:
        row = _row("capital", "MATCHED", "name_address", 2,
                   exact=True, denominator=5)
        self.assertEqual(row["support"], "2")
        self.assertEqual(row["denominator"], "5")
        self.assertEqual(row["rate_percent"], "40.00%")
        self.assertEqual(row["status"], "observed_exact")
        self.assertNotIn("source-private-fixture", str(row))
        self.assertNotIn("catalog-private-fixture", str(row))

    def test_exact_rate_includes_numerator_denominator_and_percentage(self) -> None:
        self.assertEqual(_rate(2, 3, exact=True), "2/3 (66.67%)")

    def test_proxy_summary_exact_mode_is_opt_in(self) -> None:
        default = _summary_row("capital", "trip_candidate_coverage", "privacy_limited", 2)
        exact = _summary_row("capital", "trip_candidate_coverage", "2/5 (40.00%)", 5,
                             exact_aggregates=True, numerator=2, denominator=5)
        self.assertEqual(default["support"], "<10")
        self.assertEqual(exact["support"], "2")
        self.assertEqual(exact["denominator"], "5")
        self.assertEqual(exact["rate_percent"], "40.00%")
        self.assertEqual(exact["status"], "observed_exact")

    def test_positive_funnel_reports_three_denominators_separately(self) -> None:
        catalog = [CatalogPoi(
            content_id=f"catalog-{region}", title="Fixture Place", address="1 Test Road",
            content_type_id="12", region_codes=frozenset({code}),
        ) for region, code in (("capital", "11"), ("west", "12"),
                               ("east", "26"), ("jeju-islands", "50"))]
        policy = SimpleNamespace(
            product_region_to_ldong_regn_cd={
                "capital": frozenset({"11"}), "west": frozenset({"12"}),
                "east": frozenset({"26"}), "jeju-islands": frozenset({"50"}),
            },
            supported_content_type_ids=frozenset({"12"}),
        )
        split_data = {(region, role): SimpleNamespace(travel_ids={"trip-1", "trip-2", "trip-3"})
                      for region in REGIONS for role in ROLES}
        source_maps = {(region, role): {} for region in REGIONS for role in ROLES}
        source_maps["capital", "TL"] = {
            "matched": {("Fixture Place", "", "1 Test Road", "")},
            "ambiguous": {("Fixture Place", "", "1 Test Road", ""),
                          ("Different Name", "", "2 Other Road", "")},
            "unmatched": {("Unknown Place", "", "", "")},
        }
        positive_maps = {(region, role): set() for region in REGIONS for role in ROLES}
        positive_maps["capital", "TL"] = {
            ("trip-1", "matched"), ("trip-2", "ambiguous"), ("trip-3", "unmatched"),
        }
        missing_trip_counts = {(region, role): 0 for region in REGIONS for role in ROLES}
        with patch("scripts.recommendation.analyze_poi_catalog_candidate_coverage.diagnose_region",
                   return_value=[]):
            rows = analyze(catalog, split_data, source_maps, positive_maps,
                           missing_trip_counts, policy, exact_aggregates=True)

        def metric(name: str, category: str) -> dict[str, str]:
            return next(row for row in rows if row["scope"] == "capital"
                        and row["metric"] == name and row["bucket"] == category)

        self.assertEqual(metric("TL_observed_positive_count", "all")["support"], "3")
        self.assertEqual(metric("TL_identity_resolution_rate", "resolved")["rate_percent"], "33.33%")
        self.assertEqual(metric("TL_end_to_end_positive_candidate_coverage",
                                "contained/all_observed_positives")["rate_percent"], "33.33%")
        self.assertEqual(metric("TL_conditional_candidate_coverage",
                                "contained/resolved_positives")["rate_percent"], "100.00%")
        self.assertEqual(metric("TL_positive_identity_status", "AMBIGUOUS")["support"], "1")
        self.assertEqual(metric("TL_positive_identity_status", "UNMATCHED")["support"], "1")

    def test_issue60_proxy_exact_mode_is_opt_in_and_reports_small_cells(self) -> None:
        train_event = Event("capital", "traveler-a", "trip-a", "poi-a")
        validation_event = Event("capital", "traveler-b", "trip-b", "poi-a")
        train = SplitSummary([train_event], 1, 0, 0, 0,
                             {train_event.trip_key}, {"trip-a"}, {train_event.trip_key})
        validation = SplitSummary([validation_event], 1, 0, 0, 0,
                                  {validation_event.trip_key}, {"trip-b"}, {validation_event.trip_key})
        default_rows = diagnose_region("capital", train, validation)
        exact_rows = diagnose_region("capital", train, validation, exact_aggregates=True)
        default_candidate_count = next(row for row in default_rows if row["metric"] == "candidate_items")
        exact_candidate_count = next(row for row in exact_rows if row["metric"] == "candidate_items")
        exact_trip_coverage = next(row for row in exact_rows if row["metric"] == "trip_candidate_coverage")
        self.assertEqual(default_candidate_count["support"], "<10")
        self.assertEqual(exact_candidate_count["support"], "1")
        self.assertEqual(exact_trip_coverage["support"], "1")
        self.assertEqual(exact_trip_coverage["denominator"], "1")
        self.assertEqual(exact_trip_coverage["rate_percent"], "100.00%")


if __name__ == "__main__":
    unittest.main()
