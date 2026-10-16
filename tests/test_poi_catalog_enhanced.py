"""Synthetic tests for the staged Issue #4 identity analysis."""

from __future__ import annotations

import json
import io
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "recommendation"))
import analyze_poi_catalog_enhanced as enhanced  # noqa: E402
import adjudicate_poi_candidate_sample as audit_ui  # noqa: E402
import poi_identity_contract as identity_contract  # noqa: E402
from poi_identity_contract import (CandidateGenerationResult, CandidateEvidence, CatalogPoi,
                                   CatalogCandidateIndex, MatchResult, PurposeRegionCrosswalk, SourcePoi,
                                   purpose_region_mapping_status)  # noqa: E402


def _reference_materialized_result(index: CatalogCandidateIndex, source: SourcePoi):
    """Pre-bounded reference for synthetic equivalence checks."""
    strict = identity_contract.match_source_poi(
        source, [index.catalog[ordinal] for ordinal in index.by_exact_name.get(
            identity_contract.normalize_exact(source.name), [])],
        snapshot_version=index.snapshot_version)
    if (strict.status == "MATCHED" and strict.canonical_id
            and index.content_id_counts[strict.canonical_id] != 1):
        strict = MatchResult("AMBIGUOUS", None, "conflicting_canonical_id", 1,
                             "requires_review", None, index.snapshot_version)
    if strict.status == "MATCHED" and strict.canonical_id:
        return index.generate(source)

    punctuation = identity_contract.normalize_punctuation_candidate(source.name)
    generated: dict[int, tuple[CatalogPoi, set[str]]] = {}

    def add(items, block):
        for ordinal in items:
            if ordinal not in generated:
                generated[ordinal] = (index.catalog[ordinal], set())
            generated[ordinal][1].add(block)

    add(index.by_exact_name.get(identity_contract.normalize_exact(source.name), []), "exact_name")
    add(index.by_punctuation_name.get(punctuation, []), "punctuation_name")
    add(index.by_spacing_name.get(identity_contract.normalize_spacing_candidate(source.name), []),
        "spacing_name")
    for address in (source.road_address, source.lot_address):
        if address:
            key = identity_contract.normalize_punctuation_candidate(address)
            add(index.by_punctuation_address.get(key, []), "catalog_addr1_key")
            add(index.by_lot_address.get(key, []), "lot_address_key")
    for address in (source.road_address, source.lot_address):
        key = identity_contract.normalize_spacing_candidate(address)
        if key:
            add(index.by_spacing_road_address.get(key, []), "spacing_catalog_addr1_key")
            add(index.by_spacing_lot_address.get(key, []), "spacing_lot_address_key")
    stage = "stage2_normalized"
    if not generated:
        stage = "stage3_fuzzy"
        if punctuation:
            for token in set(punctuation.split()):
                add(index.by_name_token.get(token, []), "name_token")
            if len(punctuation) >= 2:
                add(index.by_name_prefix.get(punctuation[:2], []), "name_prefix_2")
        for address in (source.road_address, source.lot_address):
            key = identity_contract.normalize_punctuation_candidate(address)
            for piece in set(key.split()):
                add(index.by_address_piece.get(piece, []), "address_piece")
        for gram in identity_contract._char_ngrams(punctuation):
            add(index.by_ngram.get(gram, []), "character_trigram")

    if not generated:
        return None
    features = identity_contract._identity_features(
        source.name, source.road_address, source.lot_address, source.admin_components)
    all_evidence = [index._evidence(source, item, "+".join(sorted(blocks)), features)
                    for item, blocks in generated.values()]
    all_evidence.sort(key=lambda value: (value.address_similarity, value.name_similarity,
                                         value.item.content_id), reverse=True)
    blocks = {block for _, candidate_blocks in generated.values() for block in candidate_blocks}
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
    return (stage, method, len(all_evidence), "union:" + "+".join(sorted(blocks)),
            tuple((row.item.content_id, row.rule, row.name_similarity, row.address_similarity,
                   row.matched_signals, row.conflicting_signals)
                  for row in all_evidence[:index.fuzzy_display_limit]))


class EnhancedIdentityAnalysisTests(unittest.TestCase):
    def _result(self, *, status="REVIEW", stage="stage2_normalized", method="normalized", count=1):
        item = CatalogPoi("synthetic-catalog", "Synthetic Place", "Synthetic Road", "R1", "D1", "12", "listed")
        evidence = CandidateEvidence(item, method, 0.9, 0.5)
        strict = MatchResult("UNMATCHED", None, "no_exact_name", 0, "requires_review")
        return CandidateGenerationResult(status, stage, method, (evidence,) if count else (), count,
                                         "synthetic-block", strict)

    def _patch_synthetic_run(self):
        observation = enhanced.AuditObservation(
            region="synthetic-region", stratum="stage2_review", partition="development",
            method="synthetic_method", source_name="SYNTHETIC_SOURCE",
            source_address="SYNTHETIC_ADDRESS", source_type="synthetic",
            candidates=(enhanced.CandidateView("SYNTHETIC_CANDIDATE", "SYNTHETIC_ADDRESS", "12"),),
            candidate_count=1,
        )
        sample_support = [{"region": "synthetic-region", "stratum": "stage2_review",
                           "partition": "development", "selected_count": "<10",
                           "available_support": "10+", "methods": {"synthetic_method": "10+"}}]
        metric = {"scope": "all_regions", "scenario": "A", "split": "ALL",
                  "unit": "source_items", "metric": "coverage", "value": "<10",
                  "support": "10+"}
        patches = [
            mock.patch.object(enhanced, "preflight_terminal"),
            mock.patch.object(enhanced.identity, "_load_catalog",
                              return_value=([], {"catalog_sha256": "synthetic-catalog-hash"})),
            mock.patch.object(enhanced.identity, "_validate_sync",
                              return_value={"sync_sha256": "synthetic-sync-hash"}),
            mock.patch.object(enhanced.identity, "_source_specs", return_value=([], {})),
            mock.patch.object(enhanced, "_source_rows", return_value=(
                {}, {}, [], {}, SimpleNamespace(collision_counts=lambda: {}))),
            mock.patch.object(enhanced, "_metrics", return_value=[metric]),
            mock.patch.object(enhanced, "_audit_observations",
                              return_value=([observation], sample_support)),
        ]
        return patches, observation

    def test_small_audit_terminal_fails_before_any_source_read(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with mock.patch.object(enhanced, "RESULTS_ROOT", root), \
                    mock.patch.object(enhanced, "preflight_terminal",
                                      side_effect=ValueError("private terminal too small")) as preflight, \
                    mock.patch.object(enhanced.identity, "_load_catalog") as load_catalog, \
                    mock.patch.object(enhanced.identity, "_source_specs") as source_specs, \
                    redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
                result = enhanced.main([
                    "--snapshot-id", "snapshot-v1", "--sync-id", "sync-v1",
                    "--run-id", "synthetic-small-tty", "--audit",
                ])
            self.assertEqual(result, 2)
            preflight.assert_called_once_with()
            load_catalog.assert_not_called()
            source_specs.assert_not_called()
            self.assertEqual(list(root.iterdir()), [])

    def test_audit_failure_keeps_aggregate_checkpoint_and_failed_status(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "results"
            root.mkdir(mode=0o700)
            temp_root = Path(temporary) / "private-temp"
            temp_root.mkdir(mode=0o700)
            patches, observation = self._patch_synthetic_run()
            for patcher in patches:
                patcher.start()
            try:
                original_results_root = enhanced.RESULTS_ROOT
                enhanced.RESULTS_ROOT = root

                def fail_during_review(*_args, **kwargs):
                    output = root / "synthetic-audit-failure"
                    self.assertTrue((output / "metrics.csv").is_file())
                    self.assertTrue((output / "sample_support.json").is_file())
                    checkpoint = json.loads((output / "aggregate_checkpoint.json").read_text())
                    self.assertEqual(checkpoint["status"], "incomplete")
                    status = json.loads((output / "run_status.json").read_text())
                    self.assertEqual(status["status"], "running")
                    self.assertEqual(status["phase"], "audit_review")

                    def fail_ui(*_ui_args):
                        raise RuntimeError("SYNTHETIC_PRIVATE_EVIDENCE")

                    with mock.patch.object(audit_ui.tempfile, "tempdir", temp_root):
                        return audit_ui.review_ephemeral(
                            [observation], output / "audit", fail_ui,
                            adjudicator_role=kwargs["adjudicator_role"],
                        )

                review_patch = mock.patch.object(enhanced, "review_ephemeral",
                                                 side_effect=fail_during_review)
                review_patch.start()
                try:
                    with redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
                        result = enhanced.main([
                            "--snapshot-id", "snapshot-v1", "--sync-id", "sync-v1",
                            "--run-id", "synthetic-audit-failure", "--audit",
                        ])
                finally:
                    review_patch.stop()
                output = root / "synthetic-audit-failure"
                self.assertEqual(result, 2)
                self.assertTrue((output / "metrics.csv").is_file())
                self.assertTrue((output / "sample_support.json").is_file())
                checkpoint = json.loads((output / "aggregate_checkpoint.json").read_text())
                self.assertEqual(checkpoint["status"], "incomplete")
                status = json.loads((output / "run_status.json").read_text())
                self.assertEqual(status["status"], "failed")
                self.assertEqual(status["phase"], "audit_review")
                self.assertFalse((output / "run_metadata.json").exists())
                self.assertFalse((output / "audit").exists())
                self.assertEqual(list(temp_root.iterdir()), [])
                for name in ("metrics.csv", "sample_support.json", "aggregate_checkpoint.json"):
                    self.assertEqual((output / name).stat().st_mode & 0o777, 0o600)
                encoded = (output / "aggregate_checkpoint.json").read_text()
                self.assertNotIn("SYNTHETIC_SOURCE", encoded)
                self.assertNotIn("SYNTHETIC_PRIVATE_EVIDENCE", encoded)
            finally:
                enhanced.RESULTS_ROOT = original_results_root
                for patcher in reversed(patches):
                    patcher.stop()

    def test_phase_duration_output_uses_coarse_bands(self) -> None:
        bands = enhanced._phase_duration_bands(
            {"source_master_scan": 130, "source_split_read": 20,
             "candidate_generation": 901, "metric_aggregation": 45,
             "sample_frame": 70, "audit_review": 299,
             "audit_reuse_validation": 901},
            None, None, 0,
        )
        self.assertEqual(bands, {
            "source_scan": "1-5m", "candidate_generation": "15m+",
            "metrics": "<1m", "sample_frame": "1-5m", "audit_review": "1-5m",
            "audit_reuse_validation": "15m+",
        })

    def test_reuse_validation_does_not_count_as_manual_audit(self) -> None:
        bands = enhanced._phase_duration_bands(
            {"audit_reuse_validation": 120}, None, None, 0)
        self.assertEqual(bands["audit_review"], "not_run")
        self.assertEqual(bands["audit_reuse_validation"], "1-5m")

    def test_bounded_generation_matches_materialized_reference(self) -> None:
        fixtures = {
            "punctuation_collision": (
                [CatalogPoi("p1", "A-B Hall", "Road 1", "R", "D", "12", "listed"),
                 CatalogPoi("p2", "A B Hall", "Road 2", "R", "D", "12", "listed")],
                SourcePoi("R", "S", "A—B Hall", "Unknown Road")),
            "duplicate_name": (
                [CatalogPoi("d1", "Twin Museum", "Road 1", "R", "D", "12", "listed"),
                 CatalogPoi("d2", "Twin Museum", "Road 2", "R", "D", "12", "listed")],
                SourcePoi("R", "S", "Twin Museum", "Unknown Road")),
            "multi_rule_ambiguous": (
                [CatalogPoi("m1", "Twin-Museum", "Road 1", "R", "D", "12", "listed"),
                 CatalogPoi("m2", "Twin Museum", "Road 1", "R", "D", "12", "listed")],
                SourcePoi("R", "S", "Twin Museum", "Unknown Road")),
        }
        for label, (catalog, source) in fixtures.items():
            with self.subTest(fixture=label):
                index = CatalogCandidateIndex(catalog, fuzzy_display_limit=1)
                expected = _reference_materialized_result(index, source)
                actual = index.generate(source)
                self.assertIsNotNone(expected)
                expected_stage, expected_method, expected_count, expected_blocking, expected_rows = expected
                actual_rows = tuple((row.item.content_id, row.rule, row.name_similarity,
                                     row.address_similarity, row.matched_signals,
                                     row.conflicting_signals) for row in actual.candidates)
                self.assertEqual((actual.stage, actual.method, actual.candidate_count,
                                  actual.blocking_rule, actual_rows),
                                 (expected_stage, expected_method, expected_count,
                                  expected_blocking, expected_rows))
                self.assertEqual(actual.status, "AMBIGUOUS" if expected_count > 1 else "REVIEW")

    def test_bounded_generation_keeps_full_broad_fanout_count_and_top_five(self) -> None:
        catalog = [CatalogPoi(f"broad-{number:04d}", f"Shared Museum {number:04d}",
                              None, "R", "D", "12", "listed")
                   for number in range(750)]
        source = SourcePoi("R", "S", "Shared Museum unknown", None)
        index = CatalogCandidateIndex(catalog, fuzzy_display_limit=5)
        expected = _reference_materialized_result(index, source)
        actual = index.generate(source)

        self.assertEqual(actual.stage, "stage3_fuzzy")
        self.assertEqual(actual.status, "AMBIGUOUS")
        self.assertEqual(actual.candidate_count, 750)
        self.assertEqual(len(actual.candidates), 5)
        self.assertEqual(actual.blocking_rule, expected[3])
        self.assertEqual(tuple(row.item.content_id for row in actual.candidates),
                         tuple(row[0] for row in expected[4]))

    def test_safe_similarity_upper_bounds_skip_noncompetitive_evidence(self) -> None:
        catalog = [CatalogPoi(f"rank-{number:04d}", "Shared Place", None,
                              "R", "D", "12", "listed")
                   for number in reversed(range(1_000))]
        source = SourcePoi("R", "S", "Shared Place", None)
        index = CatalogCandidateIndex(catalog, fuzzy_display_limit=5)
        expected = _reference_materialized_result(index, source)
        with mock.patch.object(index, "_evidence", wraps=index._evidence) as evidence_spy:
            actual = index.generate(source)

        self.assertEqual(actual.candidate_count, 1_000)
        self.assertEqual(tuple(row.item.content_id for row in actual.candidates),
                         tuple(row[0] for row in expected[4]))
        self.assertLess(evidence_spy.call_count, 20)

    def test_character_multiset_bound_prunes_same_length_fuzzy_fanout(self) -> None:
        source_name = "Shared Museum ABCDEFGHIJ"
        close = [CatalogPoi(f"a-{number:03d}", "Shared Museum ABCDEFGHIK", None,
                            "R", "D", "12", "listed") for number in range(5)]
        distant = [CatalogPoi(f"z-{number:04d}", "Shared Museum ZZZZZZZZZZ", None,
                              "R", "D", "12", "listed")
                   for number in range(1_000)]
        catalog = close + distant
        source = SourcePoi("R", "S", source_name, None)
        index = CatalogCandidateIndex(catalog, fuzzy_display_limit=5)
        expected = _reference_materialized_result(index, source)
        with mock.patch.object(index, "_evidence", wraps=index._evidence) as evidence_spy:
            actual = index.generate(source)

        self.assertEqual(actual.stage, "stage3_fuzzy")
        self.assertEqual(actual.candidate_count, 1_005)
        self.assertEqual(tuple(row.item.content_id for row in actual.candidates),
                         tuple(row[0] for row in expected[4]))
        self.assertLess(evidence_spy.call_count, 20)

    def test_candidate_scoring_progress_reports_counts_only(self) -> None:
        catalog = [CatalogPoi(f"progress-{number:02d}", f"Shared Place {number:02d}",
                              None, "R", "D", "12", "listed")
                   for number in range(7)]
        progress = []
        CatalogCandidateIndex(catalog).generate(
            SourcePoi("R", "private-source", "Shared Place unknown", None),
            _progress=lambda phase, count: progress.append((phase, count)),
            _progress_interval=2,
            _block_progress_interval=2)

        self.assertIn(("scoring", 2), progress)
        self.assertIn(("scoring", 7), progress)
        self.assertTrue(any(phase == "blocking" for phase, _ in progress))
        self.assertFalse(any("private-source" in str(value) for value in progress))

    def test_conflicting_variants_count_all_candidate_ids_with_bounded_evidence(self) -> None:
        catalog = [CatalogPoi(f"variant-{number:02d}", f"Shared Place {number:02d}",
                              None, "R", "D", "12", "listed")
                   for number in range(12)]
        metadata = enhanced.SourceMetadata(
            "Shared Place A", None, "synthetic", identity_conflicted=True,
            identity_variants=(("Shared Place A", None, None),
                               ("Shared Place B", None, None)))
        result = enhanced._result_for_source(
            CatalogCandidateIndex(catalog, fuzzy_display_limit=2), "R", "S", metadata)

        self.assertEqual(result.status, "AMBIGUOUS")
        self.assertEqual(result.candidate_count, 12)
        self.assertLessEqual(len(result.candidates), 4)

    def test_conflicted_variant_preserves_duplicate_canonical_record_ambiguity(self) -> None:
        catalog = [
            CatalogPoi("canonical-1", "Harbor-Museum", "Address A", "R1", "D1", "12", "listed"),
            CatalogPoi("canonical-1", "Harbor Museum", "Address B", "R1", "D1", "12", "listed"),
        ]
        metadata = enhanced.SourceMetadata(
            "No Strict Match", None, "synthetic", identity_conflicted=True,
            identity_variants=(("Harbor—Museum", None, None),
                               ("Harbor-Museum", None, None)),
        )

        result = enhanced._result_for_source(
            CatalogCandidateIndex(catalog, fuzzy_display_limit=5), "R1", "S1", metadata)

        self.assertEqual(result.strict_result.status, "UNMATCHED")
        self.assertEqual(result.status, "AMBIGUOUS")
        self.assertEqual(result.candidate_count, 2)
        self.assertEqual(result.source_variant_candidate_counts,
                         (("Harbor—Museum", None, None, 2),
                          ("Harbor-Museum", None, None, 2)))
        self.assertEqual([row.item.content_id for row in result.candidates],
                         ["canonical-1", "canonical-1"])
        self.assertEqual([row.item.road_address for row in result.candidates],
                         ["Address A", "Address B"])
        self.assertEqual([len(pair[3]) for pair in result.source_variant_candidate_evidence],
                         [2, 2])

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

    def test_source_master_scan_progress_contains_only_coarse_counts(self) -> None:
        rows = [
            {"poi_id": "private-source-a", "poi_nm": "Example A",
             "road_nm_addr": "Road A"},
            {"poi_id": "private-source-b", "poi_nm": "Example B",
             "road_nm_addr": "Road B"},
        ]
        progress = []
        with mock.patch.object(enhanced.shared, "_rows", return_value=iter(rows)):
            enhanced._read_source_metadata(
                Path("synthetic-only"), {"private-source-a", "private-source-b"},
                progress=progress.append, progress_interval=1)

        self.assertEqual(progress, [1, 2])
        self.assertFalse(any("private-source" in str(value) for value in progress))

    def test_source_processing_emits_phase_and_chunk_progress_without_ids(self) -> None:
        source_ids = ("private-source-a", "private-source-b", "private-source-c")
        tl = SimpleNamespace(events=[SimpleNamespace(item_id=value) for value in source_ids[:2]],
                             travel_ids={"synthetic-tl-trip"})
        vl = SimpleNamespace(events=[SimpleNamespace(item_id=source_ids[2])],
                             travel_ids={"synthetic-vl-trip"})
        metadata = {value: enhanced.SourceMetadata("Remote Place", "Remote Road", "synthetic")
                    for value in source_ids}
        specs = [SimpleNamespace(region="synthetic-region", role=role) for role in ("TL", "VL")]
        progress = []

        def fake_read_metadata(_path, observed_ids, *, progress=None, progress_interval=None):
            if progress is not None:
                progress(10)
            return {value: metadata[value] for value in observed_ids}

        with (mock.patch.object(enhanced.shared, "REGIONS", ("synthetic-region",)),
              mock.patch.object(enhanced.shared, "_read_split", side_effect=[tl, vl]),
              mock.patch.object(enhanced, "_read_source_metadata", side_effect=fake_read_metadata)):
            results, _, _, _, _ = enhanced._source_rows(
                specs, {"synthetic-region": Path("synthetic-only")}, [], "synthetic-snapshot",
                progress=progress.append, source_chunk_size=1)

        self.assertEqual(len(results), len(source_ids))
        self.assertTrue(any(value.startswith("source_master_scan=started:") for value in progress))
        self.assertTrue(any(value.startswith("source_master_scan=progress:") for value in progress))
        self.assertTrue(any(value.startswith("candidate_generation=started:") for value in progress))
        self.assertEqual(sum(value.startswith("candidate_generation=progress:")
                             for value in progress), len(source_ids))
        self.assertTrue(any(value.startswith("candidate_generation=complete:") for value in progress))
        self.assertFalse(any("private-source" in value for value in progress))

    def test_safe_failure_marker_reports_phase_and_type_without_exception_text(self) -> None:
        stderr = io.StringIO()
        temporary_context = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_context.cleanup)
        temporary = temporary_context.name
        with (
              mock.patch.object(enhanced, "RESULTS_ROOT", Path(temporary)),
              mock.patch.object(enhanced.identity, "_load_catalog",
                                side_effect=RuntimeError("private row value")),
              redirect_stderr(stderr)):
            status = enhanced.main([
                "--snapshot-id", "synthetic-snapshot", "--sync-id", "synthetic-sync",
                "--run-id", "synthetic-run",
            ])

        self.assertEqual(status, 2)
        self.assertIn("phase=catalog_load", stderr.getvalue())
        self.assertIn("exception_type=RuntimeError", stderr.getvalue())
        self.assertIn("row_level_output=false", stderr.getvalue())
        self.assertNotIn("private row value", stderr.getvalue())
        state_path = Path(temporary) / "synthetic-run" / enhanced.RUN_STATUS_FILENAME
        state = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertEqual(state["status"], "failed")
        self.assertEqual(state["phase"], "catalog_load")
        self.assertEqual(state["exception_type"], "RuntimeError")
        self.assertTrue(state["traceback"])
        self.assertTrue(all(set(frame) == {"filename", "line"} for frame in state["traceback"]))
        self.assertNotIn("private row value", json.dumps(state))
        self.assertEqual((Path(temporary) / "synthetic-run").stat().st_mode & 0o777, 0o700)
        self.assertEqual(state_path.stat().st_mode & 0o777, 0o600)

    def test_interrupted_state_is_persisted_and_partial_outputs_stay_incomplete(self) -> None:
        with (tempfile.TemporaryDirectory() as temporary,
              mock.patch.object(enhanced, "RESULTS_ROOT", Path(temporary)),
              mock.patch.object(enhanced.identity, "_load_catalog",
                                side_effect=enhanced.RunInterrupted())):
            status = enhanced.main([
                "--snapshot-id", "synthetic-snapshot", "--sync-id", "synthetic-sync",
                "--run-id", "synthetic-interrupted",
            ])
            output = Path(temporary) / "synthetic-interrupted"
            state = json.loads((output / enhanced.RUN_STATUS_FILENAME).read_text(encoding="utf-8"))
            self.assertEqual(status, 143)
            self.assertEqual(state["status"], "interrupted")
            self.assertEqual(state["phase"], "catalog_load")
            self.assertFalse((output / "run_metadata.json").exists())

    def test_repeated_progress_checkpoints_do_not_fsync_until_heartbeat_or_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "synthetic-run"
            output.mkdir(mode=0o700)
            checkpoint = enhanced.RunStatus(output, "synthetic-run")
            clock = [100.0]
            with (mock.patch.object(enhanced.time, "monotonic", side_effect=lambda: clock[0]),
                  mock.patch.object(enhanced.os, "fsync", wraps=enhanced.os.fsync) as fsync):
                checkpoint.update()
                clock[0] = 101.0
                checkpoint.progress("candidate_generation", region="capital", batch=1)
                for value in range(10_000):
                    checkpoint.progress("candidate_generation", region="capital", batch=1,
                                        work_phase="scoring", completed_work=value)
                self.assertEqual(fsync.call_count, 4)

                clock[0] = 121.0
                checkpoint.progress("candidate_generation", region="capital", batch=1,
                                    work_phase="scoring", completed_work=10_001)
                heartbeat_state = json.loads(
                    (output / enhanced.RUN_STATUS_FILENAME).read_text(encoding="utf-8"))
                self.assertEqual(heartbeat_state["completed_work"], "10+")
                checkpoint.progress("candidate_generation", region="capital", batch=2)
                self.assertEqual(fsync.call_count, 8)

            state = json.loads((output / enhanced.RUN_STATUS_FILENAME).read_text(encoding="utf-8"))
            self.assertEqual(state["batch"], 2)
            self.assertNotIn("completed_work", state)

    def test_heartbeat_advances_during_blocking_scoring_with_coarse_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "synthetic-run"
            output.mkdir(mode=0o700)
            checkpoint = enhanced.RunStatus(output, "synthetic-run")
            checkpoint.progress("candidate_generation", region="capital", batch=7,
                                work_phase="scoring", completed_work=9)
            heartbeat_written = threading.Event()
            scoring_started = threading.Event()
            release_scoring = threading.Event()
            original_update = checkpoint.update

            def observe_update(status="running", **kwargs):
                original_update(status, **kwargs)
                if threading.current_thread().name == "poi-run-status-heartbeat":
                    heartbeat_written.set()

            def blocking_score():
                scoring_started.set()
                release_scoring.wait(timeout=2)

            with (mock.patch.object(checkpoint, "update", side_effect=observe_update),
                  mock.patch.object(enhanced, "STATUS_HEARTBEAT_SECONDS", 0.01)):
                checkpoint.start_heartbeat(interval_seconds=0.01)
                scoring = threading.Thread(target=blocking_score)
                scoring.start()
                self.assertTrue(scoring_started.wait(timeout=1))
                try:
                    self.assertTrue(heartbeat_written.wait(timeout=1))
                    state = json.loads(
                        (output / enhanced.RUN_STATUS_FILENAME).read_text(encoding="utf-8"))
                    self.assertEqual(state["phase"], "candidate_generation")
                    self.assertEqual(state["region"], "capital")
                    self.assertEqual(state["batch"], 7)
                    self.assertEqual(state["work_phase"], "scoring")
                    self.assertEqual(state["completed_work"], "<10")
                    self.assertNotIn("private", json.dumps(state))
                    heartbeat_written.clear()
                    checkpoint.progress("candidate_generation", region="west", batch=8,
                                        work_phase="scoring", completed_work=19)
                    self.assertTrue(heartbeat_written.wait(timeout=1))
                    updated = json.loads(
                        (output / enhanced.RUN_STATUS_FILENAME).read_text(encoding="utf-8"))
                    self.assertEqual(updated["region"], "west")
                    self.assertEqual(updated["batch"], 8)
                    self.assertEqual(updated["completed_work"], "10+")
                finally:
                    release_scoring.set()
                    scoring.join(timeout=1)
                    checkpoint.stop_heartbeat()
            self.assertFalse(scoring.is_alive())
            self.assertIsNone(checkpoint._heartbeat_thread)

    def test_score_progress_marker_output_is_time_bounded_for_many_callbacks(self) -> None:
        clock = [0.0]
        phases, markers = [], []
        reporter = enhanced._candidate_progress_reporter(
            set_phase=lambda *args, **kwargs: phases.append((args, kwargs)),
            emit=markers.append, region="capital", batch=1, started=0.0,
            throttle=enhanced.ProgressThrottle(interval_seconds=15),
        )
        with mock.patch.object(enhanced.time, "monotonic", side_effect=lambda: clock[0]):
            for completed in range(100_000):
                reporter("scoring", completed)
            self.assertEqual(len(markers), 1)
            clock[0] = 14.9
            reporter("scoring", 100_000)
            self.assertEqual(len(markers), 1)
            clock[0] = 15.0
            reporter("scoring", 100_001)
            self.assertEqual(len(markers), 2)

        self.assertEqual(len(phases), 100_002)
        self.assertIn("completed_work=10+", markers[-1])

    def test_jeju_islands_progress_is_retained(self) -> None:
        regions = ("jeju-islands",)
        tl = SimpleNamespace(events=[], travel_ids={"synthetic-tl-trip"})
        vl = SimpleNamespace(events=[], travel_ids={"synthetic-vl-trip"})
        specs = [SimpleNamespace(region=regions[0], role=role) for role in ("TL", "VL")]
        progress = []
        with (mock.patch.object(enhanced.shared, "REGIONS", regions),
              mock.patch.object(enhanced.shared, "_read_split", side_effect=(tl, vl)),
              mock.patch.object(enhanced, "_read_source_metadata", return_value={})):
            enhanced._source_rows(specs, {regions[0]: Path("synthetic-only")}, [],
                                  "synthetic-snapshot", progress=progress.append)
        self.assertTrue(any(value.startswith("candidate_generation=complete:jeju-islands")
                            for value in progress))

    def test_conflicting_source_metadata_keeps_observed_name_address_pairs(self) -> None:
        rows = [
            {"poi_id": "synthetic-source", "poi_nm": "Museum Alpha",
             "road_nm_addr": "Address X", "lotno_addr": "Lot X", "asort_lclasdc": "A"},
            {"poi_id": "synthetic-source", "poi_nm": "Museum Beta",
             "road_nm_addr": "Address Y", "lotno_addr": "Lot Y", "asort_lclasdc": "A"},
        ]
        with mock.patch.object(enhanced.shared, "_rows", return_value=iter(rows)):
            metadata = enhanced._read_source_metadata(
                Path("synthetic-only"), {"synthetic-source"})["synthetic-source"]

        self.assertTrue(metadata.identity_conflicted)
        self.assertEqual(metadata.identity_variants,
                         (("Museum Alpha", "Address X", "Lot X"),
                          ("Museum Beta", "Address Y", "Lot Y")))
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
        self.assertEqual(groups[0].source_address, "Address X")
        self.assertEqual(groups[0].source_lot_address, "Lot X")
        self.assertEqual(groups[0].candidates[0].title, "Museum Alpha")
        self.assertEqual(groups[1].source_name, "Museum Beta")
        self.assertEqual(groups[1].candidates[0].title, "Museum Alpha")

    def test_lot_only_source_variants_preserve_strict_match_and_require_review(self) -> None:
        rows = [
            {"poi_id": "synthetic-source", "poi_nm": "Museum Alpha",
             "road_nm_addr": "Address X", "lotno_addr": "Lot X"},
            {"poi_id": "synthetic-source", "poi_nm": "Museum Alpha",
             "road_nm_addr": "Address X", "lotno_addr": "Lot Y"},
        ]
        with mock.patch.object(enhanced.shared, "_rows", return_value=iter(rows)):
            metadata = enhanced._read_source_metadata(
                Path("synthetic-only"), {"synthetic-source"})["synthetic-source"]

        self.assertTrue(metadata.identity_conflicted)
        self.assertFalse(metadata.strict_identity_conflicted)
        catalog = [CatalogPoi("synthetic-catalog", "Museum Alpha", "Address X",
                              "R1", "D1", "12", "listed", lot_address="Lot X")]
        result = enhanced._result_for_source(
            enhanced.CatalogCandidateIndex(catalog), "capital", "synthetic-source", metadata)

        self.assertEqual(result.strict_result.status, "MATCHED")
        self.assertEqual(result.status, "REVIEW")
        self.assertEqual(result.candidate_count, 1)

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
        self.assertEqual(len(support), 2)
        self.assertTrue(all(item["selected_count"] == "<10" for item in support))

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

    def test_punctuation_and_spacing_key_collisions_keep_every_catalog_record(self) -> None:
        catalog = [
            CatalogPoi("catalog-punct", "Harbor-Museum", "Address A", "R1", "D1", "12", "listed"),
            CatalogPoi("catalog-space", "Harbor Museum", "Address B", "R1", "D1", "12", "listed"),
            CatalogPoi("catalog-compact", "HarborMuseum", "Address C", "R1", "D1", "12", "listed"),
        ]
        source = SourcePoi("capital", "source-1", "Harbor—Museum", "Elsewhere")
        result = enhanced.CatalogCandidateIndex(catalog).generate(source)
        self.assertNotEqual(result.status, "MATCHED")
        self.assertEqual(result.status, "AMBIGUOUS")
        self.assertEqual(result.candidate_count, 3)
        self.assertEqual({item.item.content_id for item in result.candidates},
                         {"catalog-punct", "catalog-space", "catalog-compact"})
        self.assertIn("spacing_name", result.blocking_rule)
        collisions = enhanced.CatalogCandidateIndex(catalog).collision_counts()
        self.assertEqual(collisions["spacing_name_keys_with_multiple_catalog_items"], 1)

    def test_broad_fuzzy_fanout_keeps_total_candidate_count_and_display_order(self) -> None:
        catalog = [
            CatalogPoi(f"catalog-{number:02d}", f"Museum Place {number:02d}",
                       f"Central District Road {number:02d}", "R1", "D1", "12", "listed")
            for number in range(20)
        ]
        result = enhanced.CatalogCandidateIndex(catalog).generate(
            SourcePoi("capital", "synthetic-source", "Museum Remote", "Central Other Road"))

        self.assertEqual(result.status, "AMBIGUOUS")
        self.assertEqual(result.candidate_count, len(catalog))
        self.assertEqual(len(result.candidates), enhanced.FUZZY_CANDIDATE_DISPLAY_LIMIT)
        self.assertEqual(list(result.candidates), sorted(
            result.candidates,
            key=lambda value: (value.address_similarity, value.name_similarity,
                               value.item.content_id), reverse=True))

    def test_similarity_cache_preserves_broad_duplicate_top_five_and_full_count(self) -> None:
        catalog = [CatalogPoi(
            f"duplicate-{number:04d}", "Shared Museum", "10 Central Road",
            "R1", "D1", "12", "listed",
        ) for number in range(1_000)]
        source = SourcePoi("capital", "synthetic-source", "Shared Museum nearby",
                           "10 Central Road nearby")
        index = enhanced.CatalogCandidateIndex(catalog, fuzzy_display_limit=5)
        expected = _reference_materialized_result(index, source)
        identity_contract._similarity.cache_clear()

        actual = index.generate(source)
        cache = identity_contract._similarity.cache_info()

        self.assertEqual(actual.candidate_count, 1_000)
        self.assertEqual(tuple(row.item.content_id for row in actual.candidates),
                         tuple(row[0] for row in expected[4]))
        self.assertGreater(cache.hits, 1_000)

    def test_road_and_lot_address_variants_are_separate_review_signals(self) -> None:
        catalog = [CatalogPoi(
            "catalog-1", "Unrelated Place", "12 North Road", "R1", "D1", "12", "listed",
            lot_address="District 5 10",
        )]
        source = SourcePoi("capital", "source-1", "Different Name", "１２ North Road.",
                           lot_address="District 5-10")
        result = enhanced.CatalogCandidateIndex(catalog).generate(source)
        self.assertEqual(result.status, "REVIEW")
        self.assertEqual(result.candidate_count, 1)
        self.assertIn("punctuation_road_to_generic_addr1", result.candidates[0].matched_signals)
        self.assertIn("punctuation_lot_address", result.candidates[0].matched_signals)

    def test_conflicting_lot_signal_requires_review_without_rewriting_strict_baseline(self) -> None:
        catalog = [CatalogPoi(
            "catalog-1", "Same Place", "12 North Road", "R1", "D1", "12", "listed",
            lot_address="Lot One",
        )]
        source = SourcePoi("capital", "source-1", "Same Place", "12 North Road",
                           lot_address="Lot Two")
        result = enhanced.CatalogCandidateIndex(catalog).generate(source)
        self.assertEqual(result.strict_result.status, "MATCHED")
        self.assertEqual(result.status, "REVIEW")
        self.assertIn("lot_address", result.candidates[0].conflicting_signals)

    def test_duplicate_names_and_multiple_candidates_require_review(self) -> None:
        catalog = [
            CatalogPoi("catalog-1", "Same Name", "Address One", "R1", "D1", "12", "listed"),
            CatalogPoi("catalog-2", "Same Name", "Address Two", "R1", "D1", "12", "listed"),
        ]
        result = enhanced.CatalogCandidateIndex(catalog).generate(
            SourcePoi("capital", "source-1", "Same Name", "Unknown Address"))
        self.assertEqual(result.strict_result.status, "AMBIGUOUS")
        self.assertEqual(result.status, "AMBIGUOUS")
        self.assertEqual(result.candidate_count, 2)

    def test_missing_source_metadata_stays_unmatched_and_not_absent(self) -> None:
        result = enhanced.CatalogCandidateIndex([
            CatalogPoi("catalog-1", "Known Place", "Known Address", "R1", "D1", "12", "listed")
        ]).generate(SourcePoi("capital", "source-1", None, None))
        self.assertEqual(result.status, "UNMATCHED")
        self.assertEqual(result.method, "missing_source_name")
        self.assertEqual(result.candidate_count, 0)

    def test_strict_baseline_is_preserved_while_address_block_recovers_review_candidate(self) -> None:
        index = enhanced.CatalogCandidateIndex([
            CatalogPoi("catalog-1", "Harbor Museum", "12 North Road", "R1", "D1", "12", "listed")
        ])
        result = index.generate(SourcePoi("capital", "source-1", "Different Museum", "12 North Road"))
        self.assertEqual(result.strict_result.status, "UNMATCHED")
        self.assertEqual(result.status, "REVIEW")
        self.assertEqual(result.candidate_count, 1)
        self.assertEqual(result.stage, "stage2_normalized")

    def test_admin_component_block_requires_explicit_crosswalk_validation(self) -> None:
        catalog = [CatalogPoi(
            "catalog-1", "Remote Place", None, "R1", "D1", "12", "listed",
            admin_components=("region-x", "district-y"), admin_components_validated=True,
        )]
        index = enhanced.CatalogCandidateIndex(catalog)
        source = SourcePoi("capital", "source-1", "Dissimilar Title", None,
                           admin_components=("region-x", "district-y"),
                           admin_crosswalk_validated=False)
        self.assertEqual(index.generate(source).status, "UNMATCHED")
        validated = SourcePoi("capital", "source-1", "Dissimilar Title", None,
                              admin_components=("region-x", "district-y"),
                              admin_crosswalk_validated=True)
        result = index.generate(validated)
        self.assertEqual(result.status, "REVIEW")
        self.assertIn("validated_admin_components", result.candidates[0].matched_signals)

    def test_purpose_region_mapping_is_explicit_or_unmapped(self) -> None:
        supported = frozenset({"purpose-west", "purpose-east"})
        self.assertEqual(purpose_region_mapping_status(
            "purpose-west", supported_purpose_regions=supported, crosswalk=None), "UNMAPPED")
        self.assertEqual(purpose_region_mapping_status(
            "purpose-unknown", supported_purpose_regions=supported, crosswalk=None), "UNSUPPORTED")
        crosswalk = PurposeRegionCrosswalk(
            version="synthetic-v1", supported_purpose_regions=supported,
            purpose_region_to_ldong_codes={"purpose-west": ("synthetic-code",)},
        )
        self.assertEqual(purpose_region_mapping_status(
            "purpose-west", supported_purpose_regions=supported, crosswalk=crosswalk), "MAPPED")
        self.assertEqual(purpose_region_mapping_status(
            " PURPOSE-WEST ", supported_purpose_regions=supported, crosswalk=crosswalk), "MAPPED")
        self.assertEqual(purpose_region_mapping_status(
            "purpose-east", supported_purpose_regions=supported, crosswalk=crosswalk), "UNMAPPED")
        colliding_crosswalk = PurposeRegionCrosswalk(
            version="synthetic-collision-v1", supported_purpose_regions=supported,
            purpose_region_to_ldong_codes={
                "purpose-west": ("synthetic-code-a",),
                " PURPOSE-WEST ": ("synthetic-code-b",),
            },
        )
        self.assertEqual(purpose_region_mapping_status(
            "purpose-west", supported_purpose_regions=supported,
            crosswalk=colliding_crosswalk), "UNMAPPED")

    def test_padded_catalog_content_id_is_indexed_by_strict_canonical_id(self) -> None:
        index = enhanced.CatalogCandidateIndex([
            CatalogPoi(" catalog-padded ", "Same Place", "Same Road",
                       "R1", "D1", "12", "listed")
        ])
        result = index.generate(SourcePoi(
            "capital", "synthetic-source", "Same Place", "Same Road"))

        self.assertEqual(result.status, "MATCHED")
        self.assertEqual(result.strict_result.canonical_id, "catalog-padded")
        self.assertEqual(result.candidates[0].item.content_id, " catalog-padded ")

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
        self.assertTrue(any("no_stage2_or_stage3_block_hit" in row["metric"]
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
                    "partition": "development", "selected_count": "<10",
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
            (run / enhanced.RUN_STATUS_FILENAME).write_text(json.dumps({
                "run_id": "audit-run", "status": "complete",
            }))
            (run / "aggregate_checkpoint.json").write_text(json.dumps({
                "status": "complete",
            }))
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
                    enhanced._validate_reusable_audit(
                        "audit-run", "snapshot-v1", "sync-v1", support, expected_count=1),
                    run / "audit" / "aggregate.json",
                )
                run_status_path = run / enhanced.RUN_STATUS_FILENAME
                run_status_payload = run_status_path.read_text()
                checkpoint_path = run / "aggregate_checkpoint.json"
                checkpoint_payload = checkpoint_path.read_text()
                run_status_path.unlink()
                with self.assertRaises(ValueError):
                    enhanced._validate_reusable_audit(
                        "audit-run", "snapshot-v1", "sync-v1", support, expected_count=1)
                run_status_path.write_text(run_status_payload)
                checkpoint_path.unlink()
                with self.assertRaises(ValueError):
                    enhanced._validate_reusable_audit(
                        "audit-run", "snapshot-v1", "sync-v1", support, expected_count=1)
                checkpoint_path.write_text(checkpoint_payload)
                run_status_path.write_text(json.dumps({
                    "run_id": "audit-run", "status": "interrupted",
                }))
                with self.assertRaisesRegex(ValueError, "incomplete"):
                    enhanced._validate_reusable_audit(
                        "audit-run", "snapshot-v1", "sync-v1", support, expected_count=1)
                run_status_path.write_text(run_status_payload)
                checkpoint_path.write_text(json.dumps({"status": "incomplete"}))
                with self.assertRaisesRegex(ValueError, "incomplete"):
                    enhanced._validate_reusable_audit(
                        "audit-run", "snapshot-v1", "sync-v1", support, expected_count=1)
                with self.assertRaises(ValueError):
                    enhanced._validate_reusable_audit(
                        "audit-run", "snapshot-v1", "sync-v1", [], expected_count=1)
            finally:
                enhanced.RESULTS_ROOT = original


if __name__ == "__main__":
    unittest.main()
