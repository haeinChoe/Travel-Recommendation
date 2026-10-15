"""Synthetic tests for the staged Issue #4 identity analysis."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "recommendation"))
import analyze_poi_catalog_enhanced as enhanced  # noqa: E402
from poi_identity_contract import (CandidateGenerationResult, CandidateEvidence, CatalogPoi,
                                   MatchResult, SourcePoi)  # noqa: E402


class EnhancedIdentityAnalysisTests(unittest.TestCase):
    def _result(self, *, status="REVIEW", stage="stage2_normalized", method="normalized", count=1):
        item = CatalogPoi("synthetic-catalog", "Synthetic Place", "Synthetic Road", "R1", "D1", "12", "listed")
        evidence = CandidateEvidence(item, method, 0.9, 0.5)
        strict = MatchResult("UNMATCHED", None, "no_exact_name", 0, "requires_review")
        return CandidateGenerationResult(status, stage, method, (evidence,) if count else (), count,
                                         "synthetic-block", strict)

    def test_equivalent_source_spellings_use_one_real_deterministic_variant(self) -> None:
        rows = [
            {"poi_id": "synthetic-source", "poi_nm": "example   place",
             "road_nm_addr": "12   North Road", "asort_lclasdc": "A"},
            {"poi_id": "synthetic-source", "poi_nm": "Example Place",
             "road_nm_addr": "12 North Road", "asort_lclasdc": "A"},
        ]
        with mock.patch.object(enhanced.shared, "_rows", return_value=iter(rows)):
            metadata = enhanced._read_source_metadata(Path("synthetic-only"),
                                                       {"synthetic-source"})["synthetic-source"]

        self.assertFalse(metadata.identity_conflicted)
        self.assertEqual((metadata.name, metadata.address),
                         ("Example Place", "12 North Road"))
        catalog = [CatalogPoi("synthetic-catalog", "Example Place", "12 North Road",
                              "R1", "D1", "12", "listed")]
        result = enhanced.CatalogCandidateIndex(catalog).generate(
            SourcePoi("capital", "synthetic-source", metadata.name, metadata.address))
        self.assertEqual(result.status, "MATCHED")
        self.assertEqual(result.stage, "stage1_exact")

    def test_conflicting_source_metadata_keeps_observed_name_address_pairs(self) -> None:
        rows = [
            {"poi_id": "synthetic-source", "poi_nm": "Museum Alpha",
             "road_nm_addr": "Address X", "asort_lclasdc": "A"},
            {"poi_id": "synthetic-source", "poi_nm": "Museum Beta",
             "road_nm_addr": "Address Y", "asort_lclasdc": "A"},
        ]
        with mock.patch.object(enhanced.shared, "_rows", return_value=iter(rows)):
            metadata = enhanced._read_source_metadata(
                Path("synthetic-only"), {"synthetic-source"})["synthetic-source"]

        self.assertTrue(metadata.identity_conflicted)
        self.assertEqual(metadata.identity_variants,
                         (("Museum Alpha", "Address X"), ("Museum Beta", "Address Y")))
        catalog = [CatalogPoi("synthetic-catalog", "Museum Alpha", "Address Y",
                              "R1", "D1", "12", "listed")]
        result = enhanced._result_for_source(
            enhanced.CatalogCandidateIndex(catalog), "capital", "synthetic-source", metadata)

        self.assertEqual(result.status, "AMBIGUOUS")
        self.assertEqual(result.method, "conflicting_source_metadata")
        self.assertFalse(any(candidate.name_similarity == 1.0
                             and candidate.address_similarity == 1.0
                             for candidate in result.candidates))
        observations, _ = enhanced._audit_observations(
            {("capital", "synthetic-source"): result},
            {("capital", "synthetic-source"): metadata})
        groups = observations[0].source_candidate_groups
        self.assertEqual(len(groups), 2)
        self.assertEqual(len(groups[0].candidates), 1)
        self.assertEqual(len(groups[1].candidates), 1)
        self.assertEqual(groups[0].source_name, "Museum Alpha")
        self.assertEqual(groups[0].candidates[0].title, "Museum Alpha")
        self.assertEqual(groups[1].source_name, "Museum Beta")
        self.assertEqual(groups[1].candidates[0].title, "Museum Alpha")

    def test_conflicted_pair_display_cap_does_not_hide_another_pairs_candidates(self) -> None:
        rows = [
            {"poi_id": "synthetic-source", "poi_nm": "Museum Alpha",
             "road_nm_addr": "Address X", "asort_lclasdc": "A"},
            {"poi_id": "synthetic-source", "poi_nm": "Museum Beta",
             "road_nm_addr": "Address Y", "asort_lclasdc": "A"},
        ]
        with mock.patch.object(enhanced.shared, "_rows", return_value=iter(rows)):
            metadata = enhanced._read_source_metadata(
                Path("synthetic-only"), {"synthetic-source"})["synthetic-source"]
        catalog = [CatalogPoi(f"alpha-{n}", "Museum Alpha", f"Address X variant {n}",
                              "R1", "D1", "12", "listed") for n in range(6)]
        catalog.append(CatalogPoi("beta-address", "Remote Museum", "Address Y",
                                  "R1", "D1", "14", "listed"))
        result = enhanced._result_for_source(
            enhanced.CatalogCandidateIndex(catalog), "capital", "synthetic-source", metadata)
        observations, _ = enhanced._audit_observations(
            {("capital", "synthetic-source"): result},
            {("capital", "synthetic-source"): metadata})

        groups = observations[0].source_candidate_groups
        self.assertEqual(result.candidate_count, 7)
        self.assertEqual(groups[0].candidate_count, 6)
        self.assertEqual(len(groups[0].candidates), 5)
        self.assertEqual(groups[1].candidate_count, 1)
        self.assertEqual(len(groups[1].candidates), 1)
        self.assertEqual(groups[1].candidates[0].title, "Remote Museum")

    def test_primary_sample_strata_preserve_status_separation(self) -> None:
        metadata = enhanced.SourceMetadata("Synthetic Place", "Synthetic Road", "L1=synthetic")
        self.assertEqual(enhanced._identity_stratum(metadata, self._result()), "stage2_normalized_review")
        self.assertEqual(enhanced._identity_stratum(metadata, self._result(
            status="AMBIGUOUS", count=2)), "multi_candidate_ambiguous")
        self.assertEqual(enhanced._identity_stratum(metadata, self._result(
            status="UNMATCHED", stage="none", method="no_candidate_block_hit", count=0)), "still_unmatched")
        missing = enhanced.SourceMetadata(None, None, "[not supplied]", missing_master=True)
        self.assertEqual(enhanced._identity_stratum(missing, self._result()), "missing_metadata")

    def test_sample_manifest_contains_only_aggregate_support(self) -> None:
        metadata = enhanced.SourceMetadata("Synthetic Place", "Synthetic Road", "L1=synthetic")
        key = ("synthetic-region", "private-source-id")
        results = {key: self._result()}
        metadata_map = {key: metadata}
        observations, support = enhanced._audit_observations(results, metadata_map)
        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0].partition, "development")
        encoded = json.dumps(support)
        self.assertNotIn("private-source-id", encoded)
        self.assertNotIn("Synthetic Place", encoded)

    def test_targeted_address_audit_is_deduplicated_bounded_and_primary_only(self) -> None:
        catalog = [CatalogPoi(f"catalog-{n}", f"Place {n}", "12-3 Main Road.",
                              "R1", "D1", "12", "listed") for n in range(7)]
        index = enhanced.CatalogCandidateIndex(catalog)
        results = {}
        metadata = {}
        for n in range(7):
            key = ("capital", f"source-{n}")
            source = SourcePoi("capital", key[1], f"Different Name {n}", "１２－３ Main Road")
            results[key] = index.generate(source)
            metadata[key] = enhanced.SourceMetadata(source.name, source.road_address, "synthetic")

        observations, support = enhanced._audit_observations(
            results, metadata, audit_method="punctuation_address_variant", primary_pair=True)

        self.assertEqual(len(observations), 6)
        self.assertTrue(all(item.stratum == "address_punctuation_variant_primary_pair"
                            for item in observations))
        self.assertTrue(all(len(item.candidates) == 1 and item.candidate_count == 7
                            for item in observations))
        self.assertEqual(sum(item["selected_count"] for item in support), 6)

    def test_targeted_multi_rule_address_audit_has_separate_primary_pair_stratum(self) -> None:
        catalog = [
            CatalogPoi("catalog-1", "Harbor-Museum", "Other Road", "R1", "D1", "12", "listed"),
            CatalogPoi("catalog-2", "Harbor Museum", "Another Road", "R1", "D1", "12", "listed"),
            CatalogPoi("catalog-3", "Other Place", "12-3 Main Road.", "R1", "D1", "12", "listed"),
        ]
        source = SourcePoi("capital", "source-1", "Harbor—Museum", "１２－３ Main Road")
        result = enhanced.CatalogCandidateIndex(catalog).generate(source)
        self.assertEqual(result.method, "normalized_multi_rule_candidates")
        observations, _ = enhanced._audit_observations(
            {("capital", source.poi_id): result},
            {("capital", source.poi_id): enhanced.SourceMetadata(
                source.name, source.road_address, "synthetic")},
            audit_method="normalized_multi_rule_candidates", primary_pair=True,
        )
        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0].stratum, "normalized_multi_rule_primary_pair")
        self.assertEqual(len(observations[0].candidates), 1)

    def test_review_candidates_never_count_as_confirmed_candidate_coverage(self) -> None:
        result = self._result(status="REVIEW", stage="stage2_normalized", count=1)
        self.assertNotEqual(result.status, "MATCHED")
        self.assertEqual(result.strict_result.status, "UNMATCHED")

    def test_candidate_count_metrics_retain_blocking_rule_with_coarse_counts(self) -> None:
        catalog = [CatalogPoi("catalog-1", "Quantum lighthouse", "Remote avenue",
                              "R1", "D1", "12", "listed")]
        index = enhanced.CatalogCandidateIndex(catalog)
        source = SourcePoi("capital", "source-1", "Synthetic title", "Synthetic road")
        result = index.generate(source)
        key = ("capital", "source-1")
        rows = enhanced._metrics(
            catalog,
            {key: result},
            {key: enhanced.SourceMetadata(source.name, source.road_address, "synthetic-type")},
            defaultdict(list),
            defaultdict(set),
        )
        self.assertEqual(enhanced._candidate_count_bucket(0), "0")
        self.assertEqual(enhanced._candidate_count_bucket(1), "1")
        self.assertEqual(enhanced._candidate_count_bucket(3), "2-4")
        self.assertEqual(enhanced._candidate_count_bucket(5), "5+")
        generated = [row for row in rows if row["unit"] == "candidate_generation"
                     and "candidate_count_0" in row["metric"]]
        self.assertTrue(any("no_shared_character_trigram" in row["metric"]
                            for row in generated))

    def test_catalog_area_metrics_group_only_confirmed_links(self) -> None:
        catalog = [
            CatalogPoi("catalog-12", "Harbor Garden", "1 Example Road", "R1", "D1", "12", "listed"),
            CatalogPoi("catalog-32", "Forest Walk", "2 Example Road", "R2", "D2", "32", "listed"),
        ]
        index = enhanced.CatalogCandidateIndex(catalog)
        sources = [
            SourcePoi("capital", "source-12", "Harbor Garden", "1 Example Road"),
            SourcePoi("capital", "source-32", "Forest Walk", "2 Example Road"),
        ]
        results = {("capital", source.poi_id): index.generate(source) for source in sources}
        events = [SimpleNamespace(region="capital", item_id=source.poi_id) for source in sources]
        by_id = {item.content_id: item for item in catalog}

        area_counts = enhanced._catalog_area_positive_counts(
            events, results, by_id, {"12", "14", "15", "25", "28", "32", "38", "39"})

        self.assertEqual(area_counts["R1"]["matched_in_scenario"], 1)
        self.assertEqual(area_counts["R2"]["matched_in_scenario"], 1)
        scenario_c = enhanced._catalog_area_positive_counts(
            events, results, by_id, {"12", "14", "28"})
        self.assertEqual(scenario_c["R1"]["matched_in_scenario"], 1)
        self.assertEqual(scenario_c["R2"]["matched_outside_scenario"], 1)

        review = self._result(status="REVIEW", method="fuzzy_character_trigram_block")
        mixed_results = dict(results)
        mixed_results[("capital", "source-32")] = review
        review_counts = enhanced._catalog_area_positive_counts(
            events, mixed_results, by_id, {"12", "14", "15", "25", "28"})
        self.assertNotIn("R2", review_counts)

    def test_reusable_audit_requires_matching_aggregate_sample_frame(self) -> None:
        support = [{"region": "synthetic-region", "stratum": "synthetic",
                    "partition": "development", "selected_count": 1,
                    "available_support": "10+", "methods": {"synthetic_method": "10+"}}]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = root / "audit-run"
            (run / "audit").mkdir(parents=True)
            (run / "run_metadata.json").write_text(json.dumps({
                "catalog_snapshot_id": "snapshot-v1",
                "sync_snapshot_id": "sync-v1",
                "sample": {"seed": enhanced.SAMPLE_SEED},
            }))
            (run / "sample_support.json").write_text(json.dumps(support))
            (run / "audit" / "aggregate.json").write_text(json.dumps({
                "reviewed_count": 1,
                "labels": {"MATCH": 1, "NO_MATCH": 0, "UNCERTAIN": 0},
                "by_method_stratum_partition": {
                    "synthetic_method|synthetic|development": {
                        "reviewed_count": 1,
                        "labels": {"MATCH": 1, "NO_MATCH": 0, "UNCERTAIN": 0},
                    },
                },
                "adjudicator_role": "independent",
            }))
            original = enhanced.RESULTS_ROOT
            enhanced.RESULTS_ROOT = root
            try:
                self.assertEqual(
                    enhanced._validate_reusable_audit("audit-run", "snapshot-v1", "sync-v1", support),
                    run / "audit" / "aggregate.json",
                )
                with self.assertRaises(ValueError):
                    enhanced._validate_reusable_audit("audit-run", "snapshot-v1", "sync-v1", [])
            finally:
                enhanced.RESULTS_ROOT = original


if __name__ == "__main__":
    unittest.main()
