from __future__ import annotations

import unittest
from types import SimpleNamespace

from scripts.recommendation.analyze_poi_catalog_candidate_coverage import (
    _match_sources,
    _row,
)
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

    def test_small_aggregate_support_is_suppressed(self) -> None:
        row = _row("capital", "MATCHED", "name_address", 2)
        self.assertEqual(row["support"], "<10")
        self.assertEqual(row["status"], "privacy_limited")
        self.assertNotIn("source-private-fixture", str(row))
        self.assertNotIn("catalog-private-fixture", str(row))


if __name__ == "__main__":
    unittest.main()
