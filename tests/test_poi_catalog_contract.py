"""Synthetic contract checks for Issue #4; no actual-data fixtures."""

from __future__ import annotations

import sys
import tempfile
import unittest
import hashlib
import json
import os
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "recommendation"))
from poi_identity_contract import (  # noqa: E402
    CatalogPoi,
    RequestContext,
    SnapshotValidation,
    SourcePoi,
    CatalogCandidateIndex,
    candidate_eligibility,
    match_source_poi,
    normalize_punctuation_candidate,
)
import analyze_poi_source_readiness as readiness  # noqa: E402
import analyze_poi_catalog_identity as catalog_identity  # noqa: E402
import analyze_poi_catalog_scenarios as catalog_scenarios  # noqa: E402
import acquire_tourapi_catalog as catalog_acquisition  # noqa: E402
import acquire_tourapi_sync_state as sync_acquisition  # noqa: E402
import evaluate_popularity as shared  # noqa: E402


def poi(content_id: str, *, title: str = "Synthetic Museum", address: str = "10 Test Road",
        area: str = "R1", district: str = "D1", kind: str = "museum",
        state: str = "listed") -> CatalogPoi:
    return CatalogPoi(content_id, title, address, area, district, kind, state)


class IdentityContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = SourcePoi("synthetic-region", "source-1", "Synthetic Museum", "10 Test Road")

    def test_unique_exact_name_and_address_is_provisional_match(self) -> None:
        result = match_source_poi(self.source, [poi("catalog-1")], snapshot_version="synthetic-v1")
        self.assertEqual((result.status, result.canonical_id, result.method),
                         ("MATCHED", "catalog-1", "unique_exact_name_address"))
        self.assertEqual(result.validation_status, "unreviewed")
        self.assertIsNone(result.confidence)
        self.assertEqual(result.snapshot_version, "synthetic-v1")

    def test_name_only_and_conflicting_address_are_ambiguous(self) -> None:
        no_address = SourcePoi("synthetic-region", "source-1", "Synthetic Museum", None)
        self.assertEqual(match_source_poi(no_address, [poi("catalog-1")]).status, "AMBIGUOUS")
        self.assertEqual(match_source_poi(self.source, [poi("catalog-1", address="Other Road")]).status,
                         "AMBIGUOUS")

    def test_duplicate_exact_pair_and_conflicting_content_id_are_ambiguous(self) -> None:
        self.assertEqual(match_source_poi(self.source, [poi("catalog-1"), poi("catalog-2")]).status,
                         "AMBIGUOUS")
        self.assertEqual(match_source_poi(self.source, [poi("catalog-1"),
                                                       poi("catalog-1", title="Other")]).status,
                         "AMBIGUOUS")

    def test_no_name_candidate_is_unmatched(self) -> None:
        self.assertEqual(match_source_poi(self.source, [poi("catalog-1", title="Other")]).status,
                         "UNMATCHED")

    def test_conflicting_source_metadata_is_ambiguous(self) -> None:
        result = match_source_poi(self.source, [poi("catalog-1")], source_conflicted=True)
        self.assertEqual((result.status, result.method),
                         ("AMBIGUOUS", "conflicting_source_metadata"))

    def test_unicode_whitespace_normalization_is_deterministic(self) -> None:
        source = SourcePoi("synthetic-region", "source-1", "  Ｓｙｎｔｈｅｔｉｃ   Museum ", "10  Test Road")
        self.assertEqual(match_source_poi(source, [poi("catalog-1")]).status, "MATCHED")


class CandidatePipelineTests(unittest.TestCase):
    def test_punctuation_normalization_collisions_remain_ambiguous(self) -> None:
        catalog = [poi("catalog-1", title="Harbor-Museum", address="Road A"),
                   poi("catalog-2", title="Harbor Museum", address="Road B")]
        source = SourcePoi("synthetic-region", "source-1", "Harbor—Museum", "Road C")
        index = CatalogCandidateIndex(catalog, snapshot_version="synthetic-v1")
        self.assertEqual(normalize_punctuation_candidate("Harbor—Museum"), "harbor museum")
        result = index.generate(source)
        self.assertEqual((result.status, result.stage, result.candidate_count),
                         ("AMBIGUOUS", "stage2_normalized", 2))
        self.assertTrue(all(candidate.item.content_id in {"catalog-1", "catalog-2"}
                            for candidate in result.candidates))

    def test_address_string_difference_is_review_only(self) -> None:
        source = SourcePoi("synthetic-region", "source-1", "Synthetic Museum", "Other Road")
        result = CatalogCandidateIndex([poi("catalog-1")]).generate(source)
        self.assertEqual((result.status, result.stage, result.method),
                         ("REVIEW", "stage2_normalized", "exact_name_address_string_variant"))
        self.assertEqual(result.strict_result.status, "AMBIGUOUS")

    def test_punctuation_normalized_address_is_review_only_and_keeps_raw_values(self) -> None:
        catalog_item = poi("catalog-1", title="Museum Name", address="12-3 Main Road.")
        source = SourcePoi("synthetic-region", "source-1", "Museum of History", "１２－３  Main Road")
        result = CatalogCandidateIndex([catalog_item]).generate(source)
        self.assertEqual((result.status, result.stage, result.method),
                         ("REVIEW", "stage2_normalized", "punctuation_address_variant"))
        self.assertEqual(result.candidate_count, 1)
        self.assertEqual(result.candidates[0].item.content_id, "catalog-1")
        self.assertEqual(result.strict_result.status, "UNMATCHED")
        self.assertEqual(catalog_item.road_address, "12-3 Main Road.")
        self.assertEqual(source.road_address, "１２－３  Main Road")

    def test_punctuation_address_collisions_remain_ambiguous_and_display_is_bounded(self) -> None:
        catalog = [poi(f"catalog-{n}", title=f"Place {n}", address="12-3 Main Road.")
                   for n in range(7)]
        source = SourcePoi("synthetic-region", "source-1", "Different Source Name",
                           "１２－３  Main Road")
        result = CatalogCandidateIndex(catalog, fuzzy_display_limit=5).generate(source)
        self.assertEqual((result.status, result.stage, result.method),
                         ("AMBIGUOUS", "stage2_normalized", "punctuation_address_variant"))
        self.assertEqual(result.candidate_count, 7)
        self.assertEqual(len(result.candidates), 5)
        self.assertEqual({candidate.rule for candidate in result.candidates},
                         {"punctuation_address_variant"})

    def test_unique_fuzzy_candidate_is_never_auto_matched(self) -> None:
        source = SourcePoi("synthetic-region", "source-1", "Synthetic Art Museum", "Other Road")
        index = CatalogCandidateIndex([poi("catalog-1", title="Synthetic Arts Museum")])
        result = index.generate(source)
        self.assertEqual((result.status, result.stage, result.candidate_count),
                         ("REVIEW", "stage3_fuzzy", 1))
        self.assertNotEqual(result.status, "MATCHED")
        self.assertEqual(result.blocking_rule, "any_shared_character_trigram_no_area_filter")

    def test_fuzzy_multiple_candidates_are_ambiguous(self) -> None:
        source = SourcePoi("synthetic-region", "source-1", "Synthetic Art Museum", "Other Road")
        catalog = [poi("catalog-1", title="Synthetic Arts Museum"),
                   poi("catalog-2", title="Synthetic Art Museums")]
        result = CatalogCandidateIndex(catalog).generate(source)
        self.assertEqual((result.status, result.stage), ("AMBIGUOUS", "stage3_fuzzy"))
        self.assertEqual(result.candidate_count, 2)

    def test_no_name_block_candidate_stays_unmatched(self) -> None:
        source = SourcePoi("synthetic-region", "source-1", "zz", "Some Road")
        result = CatalogCandidateIndex([poi("catalog-1", title="Museum")]).generate(source)
        self.assertEqual((result.status, result.stage, result.method),
                         ("UNMATCHED", "none", "no_candidate_block_hit"))

    def test_candidate_index_does_not_use_coordinate_or_type_as_auto_match(self) -> None:
        source = SourcePoi("synthetic-region", "source-1", "Synthetic Arts Museum", "10 Test Road")
        result = CatalogCandidateIndex([poi("catalog-1", title="Synthetic Art Museum", kind="12")]).generate(source)
        self.assertIn(result.status, {"REVIEW", "AMBIGUOUS"})
        self.assertNotIn("coordinate", result.method)
        self.assertNotIn("content_type", result.method)


class EligibilityContractTests(unittest.TestCase):
    snapshot = SnapshotValidation(True, True, True, True, True)

    def test_explicit_region_and_supported_type(self) -> None:
        self.assertEqual(candidate_eligibility(RequestContext("R1"), poi("catalog-1"),
                                               frozenset({"museum"}), snapshot=self.snapshot,
                                               region_crosswalk_validated=True),
                         "ELIGIBLE")
        self.assertEqual(candidate_eligibility(RequestContext("R2"), poi("catalog-1"),
                                               frozenset({"museum"}), snapshot=self.snapshot,
                                               region_crosswalk_validated=True),
                         "INELIGIBLE")

    def test_not_displayed_and_unsupported_type_are_ineligible(self) -> None:
        request = RequestContext("R1")
        self.assertEqual(candidate_eligibility(request, poi("catalog-1", state="not_displayed"),
                                               frozenset({"museum"}), snapshot=self.snapshot,
                                               region_crosswalk_validated=True),
                         "INELIGIBLE")
        self.assertEqual(candidate_eligibility(request, poi("catalog-1", kind="hotel"),
                                               frozenset({"museum"}), snapshot=self.snapshot,
                                               region_crosswalk_validated=True),
                         "INELIGIBLE")

    def test_unknown_listing_or_crosswalk_is_unresolved(self) -> None:
        request = RequestContext("R1")
        self.assertEqual(candidate_eligibility(request, poi("catalog-1", state="unknown"),
                                               frozenset({"museum"}), snapshot=self.snapshot,
                                               region_crosswalk_validated=True),
                         "UNRESOLVED")
        self.assertEqual(candidate_eligibility(request, poi("catalog-1"),
                                               frozenset({"museum"}), snapshot=self.snapshot,
                                               region_crosswalk_validated=False),
                         "UNRESOLVED")

    def test_district_only_filters_when_explicit_and_crosswalked(self) -> None:
        request = RequestContext("R1", "D2", explicitly_selected_district=True)
        self.assertEqual(candidate_eligibility(request, poi("catalog-1"), frozenset({"museum"}),
                                               snapshot=self.snapshot, region_crosswalk_validated=True,
                                               district_crosswalk_validated=True), "INELIGIBLE")
        self.assertEqual(candidate_eligibility(request, poi("catalog-1"), frozenset({"museum"}),
                                               snapshot=self.snapshot,
                                               region_crosswalk_validated=True), "UNRESOLVED")

    def test_inferred_category_never_filters(self) -> None:
        self.assertEqual(candidate_eligibility(RequestContext("R1"), poi("catalog-1"),
                                               frozenset({"museum"}), snapshot=self.snapshot,
                                               region_crosswalk_validated=True),
                         "ELIGIBLE")
        explicit = RequestContext("R1", explicitly_selected_category="history")
        self.assertEqual(candidate_eligibility(explicit, poi("catalog-1"), frozenset({"museum"}),
                                               snapshot=self.snapshot,
                                               region_crosswalk_validated=True), "UNRESOLVED")

    def test_snapshot_validation_is_required_and_fail_closed(self) -> None:
        request = RequestContext("R1")
        self.assertEqual(candidate_eligibility(request, poi("catalog-1"), frozenset({"museum"}),
                                               region_crosswalk_validated=True), "UNRESOLVED")
        for field in SnapshotValidation.__dataclass_fields__:
            flags = {name: True for name in SnapshotValidation.__dataclass_fields__}
            flags[field] = False
            for state in ("listed", "not_displayed"):
                with self.subTest(field=field, state=state):
                    self.assertEqual(candidate_eligibility(
                        request, poi("catalog-1", state=state), frozenset({"museum"}),
                        snapshot=SnapshotValidation(**flags), region_crosswalk_validated=True,
                    ), "UNRESOLVED")

    def test_unvalidated_listing_state_provenance_blocks_display_states(self) -> None:
        snapshot = SnapshotValidation(
            provider_use_authorized=True, complete=True, schema_validated=True,
            current_for_request=True, listing_state_provenance_validated=False,
        )
        for state in ("listed", "not_displayed"):
            with self.subTest(state=state):
                self.assertEqual(candidate_eligibility(
                    RequestContext("R1"), poi("catalog-1", state=state),
                    frozenset({"museum"}), snapshot=snapshot,
                    region_crosswalk_validated=True,
                ), "UNRESOLVED")


class SourceReadinessTests(unittest.TestCase):
    def test_tl_proxy_uses_same_vl_event_denominator_for_inside_and_outside(self) -> None:
        tl = shared.SplitSummary(
            events=[shared.Event("synthetic", "train-user", "train-trip", "inside")],
            visit_rows=1, missing_poi_rows=0, unmapped_trip_rows=0, ambiguous_trip_rows=0,
            visit_trip_keys={("synthetic", "train-user", "train-trip")}, travel_ids={"train-trip"},
        )
        events = [shared.Event("synthetic", f"val-user-{n}", f"val-trip-{n}",
                               "inside" if n < 12 else "outside") for n in range(20)]
        vl = shared.SplitSummary(
            events=events, visit_rows=20, missing_poi_rows=0, unmapped_trip_rows=0,
            ambiguous_trip_rows=0, visit_trip_keys={event.trip_key for event in events},
            travel_ids={event.trip_id for event in events},
        )
        rows = readiness.diagnose_region("synthetic", tl, vl, {"inside"},
                                         {"inside": ("synthetic", "road", "district", "", "")}, 0)
        by_metric = {row["metric"]: row["value"] for row in rows}
        self.assertEqual(by_metric["tl_observed_proxy_vl_positive_coverage"], "50-<75%")
        self.assertEqual(by_metric["tl_observed_proxy_vl_outside_positive_share"], "<10/suppressed")

    def test_tl_vl_trip_overlap_is_rejected(self) -> None:
        empty = shared.SplitSummary([], 0, 0, 0, 0, set(), travel_ids={"shared-trip"})
        with self.assertRaises(ValueError):
            readiness.diagnose_region("synthetic", empty, empty, set(), {}, 0)

    def test_missing_visit_table_is_rejected_before_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "TN_TRAVEL.csv").write_text("TRAVEL_ID,TRAVELER_ID\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "required role table is absent"):
                readiness._validate_role_tables(root)

    def test_missing_master_headers_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "TN_POI_MASTER.csv"
            for omitted in ("POI_NM", "ROAD_NM_ADDR", "SGG_CD", "X_COORD", "Y_COORD"):
                path.write_text(",".join(sorted(readiness.FIELDS - {omitted})) + "\n", encoding="utf-8")
                with self.subTest(omitted=omitted), self.assertRaises(ValueError):
                    readiness._read_master(path, {"synthetic-source"})

    def test_differing_source_coordinates_are_conflicted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "TN_POI_MASTER.csv"
            path.write_text(
                "POI_ID,POI_NM,ROAD_NM_ADDR,SGG_CD,X_COORD,Y_COORD\n"
                "synthetic-source,Synthetic Museum,Test Road,D1,1,2\n"
                "synthetic-source,Synthetic Museum,Test Road,D1,3,2\n",
                encoding="utf-8",
            )
            keys, stable, conflicts = readiness._read_master(path, {"synthetic-source"})
            self.assertEqual((len(keys), len(stable), conflicts), (1, 0, 1))


class CatalogSnapshotTests(unittest.TestCase):
    def test_scenario_positive_class_keeps_unmatched_distinct_from_catalog_outside(self) -> None:
        self.assertEqual(catalog_scenarios.positive_class(
            "MATCHED", poi("catalog-1", kind="12"), catalog_scenarios.SCENARIOS["C"]),
            "linked_in_scope")
        self.assertEqual(catalog_scenarios.positive_class(
            "MATCHED", poi("catalog-2", kind="38"), catalog_scenarios.SCENARIOS["C"]),
            "linked_outside_type_scope")
        self.assertEqual(catalog_scenarios.positive_class(
            "AMBIGUOUS", None, catalog_scenarios.SCENARIOS["C"]), "ambiguous")
        self.assertEqual(catalog_scenarios.positive_class(
            "UNMATCHED", None, catalog_scenarios.SCENARIOS["C"]), "unmatched")

    def test_precision_sample_is_deterministic_and_bounded(self) -> None:
        values = {f"synthetic-{i}" for i in range(100)}
        first = catalog_scenarios.deterministic_audit_sample(values, region="synthetic", split="TL")
        second = catalog_scenarios.deterministic_audit_sample(values, region="synthetic", split="TL")
        other_split = catalog_scenarios.deterministic_audit_sample(values, region="synthetic", split="VL")
        self.assertEqual(len(first), 20)
        self.assertEqual(first, second)
        self.assertNotEqual(first, other_split)

    def test_acquisitions_reject_parent_symlink_before_request(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            real = base / "real"
            real.mkdir()
            linked = base / "linked"
            linked.symlink_to(real, target_is_directory=True)
            with (mock.patch.dict(os.environ, {"TOUR_API_SERVICE_KEY": "synthetic-secret"}),
                  mock.patch.object(catalog_acquisition, "RESULTS_ROOT", linked / "catalog"),
                  mock.patch.object(sync_acquisition, "RESULTS_ROOT", linked / "sync"),
                  mock.patch.object(catalog_acquisition, "_page") as catalog_page,
                  mock.patch.object(sync_acquisition, "_collect") as sync_collect):
                with self.assertRaisesRegex(ValueError, "result destination unavailable"):
                    catalog_acquisition.acquire("synthetic", page_size=2, max_pages=2)
                with self.assertRaisesRegex(ValueError, "result destination unavailable"):
                    sync_acquisition.acquire("synthetic", page_size=2, max_pages=2)
                catalog_page.assert_not_called()
                sync_collect.assert_not_called()

    def test_acquisition_accepts_short_final_page_without_storing_key(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            pages = [
                (3, 2, [{"contentid": "one"}, {"contentid": "two"}]),
                (3, 1, [{"contentid": "three"}]),
                (3, 2, [{"contentid": "one"}, {"contentid": "two"}]),
            ]
            with (mock.patch.object(catalog_acquisition, "RESULTS_ROOT", Path(temporary)),
                  mock.patch.object(catalog_acquisition, "_page", side_effect=pages),
                  mock.patch.object(catalog_acquisition.urllib.request, "build_opener"),
                  mock.patch.object(catalog_acquisition.time, "sleep"),
                  mock.patch.dict(os.environ, {"TOUR_API_SERVICE_KEY": "synthetic-secret"})):
                result = catalog_acquisition.acquire("synthetic-snapshot", page_size=2, max_pages=2)
            self.assertEqual((result["total_count"], result["pages"]), (3, 2))
            output = Path(temporary) / "synthetic-snapshot"
            self.assertNotIn("synthetic-secret", (output / "catalog.jsonl").read_text())
            self.assertNotIn("synthetic-secret", (output / "manifest.json").read_text())

    def test_sync_display_set_must_equal_public_listing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "synthetic-sync"
            root.mkdir()
            content = (json.dumps({"contentid": "shown", "showflag": "1"}) + "\n"
                       + json.dumps({"contentid": "hidden", "showflag": "0"}) + "\n")
            (root / "sync_state.jsonl").write_text(content, encoding="utf-8")
            (root / "manifest.json").write_text(json.dumps({
                "sync_sha256": hashlib.sha256(content.encode()).hexdigest(),
                "shown_count": 1, "hidden_count": 1,
            }), encoding="utf-8")
            with mock.patch.object(catalog_identity, "SYNC_ROOT", Path(temporary)):
                catalog_identity._validate_sync([poi("shown")], "synthetic-sync")
                with self.assertRaisesRegex(ValueError, "disagree"):
                    catalog_identity._validate_sync([poi("hidden")], "synthetic-sync")


if __name__ == "__main__":
    unittest.main()
