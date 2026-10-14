"""Synthetic-only acceptance tests for candidate/choice feasibility diagnostics."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts" / "recommendation"
sys.path.insert(0, str(SCRIPT_DIR))
import analyze_candidate_choice_feasibility as analysis  # noqa: E402
import evaluate_popularity as shared  # noqa: E402


def event(user: str, trip: str, item: str, region: str = "west") -> shared.Event:
    return shared.Event(region, user, trip, item)


def split(events: list[shared.Event], trip_keys: set[tuple[str, str, str]],
          travel_ids: set[str] | None = None) -> shared.SplitSummary:
    return shared.SplitSummary(events, len(events), 0, 0, 0, trip_keys, travel_ids or set())


class CandidateChoiceFeasibilityTests(unittest.TestCase):
    def test_candidates_are_tl_only_and_vl_unseen_positives_are_cold_start(self):
        train = split([event("train-user", "train-trip", "tl-item"),
                       event("train-user-2", "train-trip-2", "second-tl-item")],
                      set(), {"train-trip", "train-trip-2"})
        val = split(
            [event("vl-user", "vl-trip", "tl-item"), event("vl-user", "vl-trip", "vl-only")],
            {("west", "vl-user", "vl-trip")}, {"vl-trip"},
        )
        rows = analysis.diagnose_region("west", train, val, (1,))
        self.assertEqual(analysis.candidate_universe(train), {("west", "tl-item"), ("west", "second-tl-item")})
        self.assertNotIn(("west", "vl-only"), analysis.candidate_universe(train))
        status = next(row for row in rows if row["metric"] == "choice_set_status")
        self.assertEqual((status["bucket"], status["support"], status["status"]),
                         ("positive_outside_candidate_universe", "<10", "privacy_limited"))
        positive_status = next(row for row in rows if row["metric"] == "positive_coverage_status")
        self.assertEqual(positive_status["bucket"], "positive_outside_candidate_universe")
        positive_coverage = next(row for row in rows if row["metric"] == "positive_event_coverage")
        self.assertEqual(positive_coverage["bucket"], "<10/suppressed")
        cold = next(row for row in rows if row["metric"] == "cold_start_positive_event_share")
        self.assertEqual(cold["bucket"], "<10/suppressed")

    def test_multiple_positives_use_distinct_trip_relevance_and_separate_cold_start(self):
        train = split([event("u1", "t1", "a"), event("u2", "t2", "b")], set(), {"t1", "t2"})
        val = split(
            [event("u3", "t3", "a"), event("u3", "t3", "a"), event("u3", "t3", "new")],
            {("west", "u3", "t3")}, {"t3"},
        )
        first = analysis.diagnose_region("west", train, val, (1,))
        second = analysis.diagnose_region("west", train, val, (1,))
        self.assertEqual(first, second)
        status = next(row for row in first if row["metric"] == "choice_set_status")
        self.assertEqual(status["bucket"], "positive_outside_candidate_universe")
        self.assertTrue(any(row["metric"] == "in_candidate_positive:recall@1" for row in first))

    def test_empty_candidate_and_unobserved_candidates_are_not_negative_labels(self):
        train = split([], set(), set())
        val = split([event("u1", "t1", "outside")], {("west", "u1", "t1")}, {"t1"})
        rows = analysis.diagnose_region("west", train, val, (1,))
        status = next(row for row in rows if row["metric"] == "choice_set_status")
        self.assertEqual(status["bucket"], "empty_candidate")
        positive_status = next(row for row in rows if row["metric"] == "positive_coverage_status")
        self.assertEqual(positive_status["bucket"], "cold_start_only")
        self.assertFalse(any("negative" in str(row).casefold() for row in rows))

        train = split([event("u1", "t1", "known"), event("u2", "t2", "another")], set())
        val = split([event("u3", "t3", "outside")], {("west", "u3", "t3")})
        rows = analysis.diagnose_region("west", train, val, (1,))
        status = next(row for row in rows if row["metric"] == "choice_set_status")
        positive_status = next(row for row in rows if row["metric"] == "positive_coverage_status")
        self.assertEqual(status["bucket"], "cold_start_only")
        self.assertEqual(positive_status["bucket"], "cold_start_only")

    def test_evaluable_and_insufficient_choice_sets_are_distinct(self):
        train = split([event("u1", "t1", "a"), event("u2", "t2", "b")], set())
        val = split([event("u3", "t3", "a")], {("west", "u3", "t3")})
        rows = analysis.diagnose_region("west", train, val, (1,))
        status = next(row for row in rows if row["metric"] == "choice_set_status")
        self.assertEqual(status["bucket"], "evaluable")

        one_candidate = split([event("u1", "t1", "a")], set())
        val_mixed = split(
            [event("u3", "t3", "a"), event("u3", "t3", "outside")],
            {("west", "u3", "t3")},
        )
        rows = analysis.diagnose_region("west", one_candidate, val_mixed, (1,))
        status = next(row for row in rows if row["metric"] == "choice_set_status")
        self.assertEqual(status["bucket"], "insufficient_candidate_support")
        candidate_status = next(row for row in rows if row["metric"] == "candidate_support_status")
        positive_status = next(row for row in rows if row["metric"] == "positive_coverage_status")
        self.assertEqual(candidate_status["bucket"], "insufficient_candidate_support")
        self.assertEqual(positive_status["bucket"], "positive_outside_candidate_universe")
        ranking = next(row for row in rows if row["metric"] == "in_candidate_positive:recall@1")
        self.assertEqual(ranking["status"], "empty_cohort")

    def test_trip_overlap_fails_closed(self):
        train = split([event("u1", "same", "a")], set(), {"same"})
        val = split([event("u2", "same", "a")], set(), {"same"})
        with self.assertRaises(ValueError):
            analysis._validate_split_pair(train, val)

    def test_reused_loader_excludes_post_event_feedback_fields(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "TL_csv"
            root.mkdir()
            (root / "TN_TRAVEL.csv").write_text(
                "TRAVEL_ID,TRAVELER_ID\nt1,u1\n", encoding="utf-8"
            )
            (root / "TN_VISIT_AREA_INFO.csv").write_text(
                "TRAVEL_ID,POI_ID,DGSTFN,REVISIT_INTENTION,RCMDTN_INTENTION\n"
                "t1,p1,5,5,5\n", encoding="utf-8"
            )
            loaded = shared._read_split(shared.InputSpec("west", "TL", root))
            self.assertEqual([(item.region, item.item_id) for item in loaded.events], [("west", "p1")])
            self.assertFalse(hasattr(loaded.events[0], "feedback"))
            self.assertEqual(loaded.travel_trip_keys, {("west", "u1", "t1")})

    def test_trip_and_repeat_visit_aggregates_use_buckets(self):
        trip_keys = {
            ("west", "u1", "t1"), ("west", "u1", "t2"), ("west", "u2", "t3"),
        }
        data = split([
            event("u1", "t1", "a"), event("u1", "t1", "a"), event("u1", "t1", "b"),
            event("u1", "t2", "c"),
        ], trip_keys, {"t1", "t2", "t3"})
        data.travel_trip_keys = trip_keys
        rows = analysis._structural_diagnostics("west", "vl", data)
        trip_row = next(row for row in rows if row["metric"] == "vl_distinct_trips_per_traveler_distribution" and row["bucket"] == "2-3")
        self.assertEqual(trip_row["support"], "<10")
        positive_row = next(row for row in rows if row["metric"] == "vl_distinct_positive_pois_per_trip_distribution" and row["bucket"] == "2-4")
        self.assertEqual(positive_row["support"], "<10")
        repeat_row = next(row for row in rows if row["metric"] == "vl_repeated_visit_events_per_trip_distribution" and row["bucket"] == "1")
        self.assertEqual(repeat_row["support"], "<10")
        repeat_share = next(row for row in rows if row["metric"] == "vl_repeated_visit_event_share")
        self.assertEqual(repeat_share["bucket"], "<10/suppressed")

    def test_safe_error_path_does_not_echo_path_bearing_exception(self):
        stderr = io.StringIO()
        args = [
            "--input", "west:TL=/private/raw/source", "--run-id", "synthetic",
            "--confirm-approved", "--confirm-terms", "--confirm-poi-candidate",
        ]
        with patch.object(analysis, "_validate_inputs", side_effect=ValueError("/private/raw/source")):
            with contextlib.redirect_stderr(stderr):
                code = analysis.main(args)
        self.assertEqual(code, 2)
        self.assertIn("failed safely", stderr.getvalue())
        self.assertNotIn("/private/raw/source", stderr.getvalue())

    def test_public_rows_do_not_contain_identifiers_or_paths(self):
        train = split([event("PRIVATE_USER", "PRIVATE_TRAIN_TRIP", "PRIVATE_POI")], set())
        val = split([event("PRIVATE_USER", "PRIVATE_VAL_TRIP", "PRIVATE_POI")],
                    {("west", "PRIVATE_USER", "PRIVATE_VAL_TRIP")})
        serialized = repr(analysis.diagnose_region("west", train, val, (1,)))
        for secret in ("PRIVATE_USER", "PRIVATE_TRAIN_TRIP", "PRIVATE_VAL_TRIP", "PRIVATE_POI", "/tmp/"):
            self.assertNotIn(secret, serialized)

    def test_preflight_binds_capital_roles_explicitly_and_rejects_swap(self):
        with tempfile.TemporaryDirectory() as temp:
            raw = Path(temp) / "raw"
            folders = {
                ("capital", "TL"): raw / "2023-travel-log-capital" / "extracted" / "filekey-tl",
                ("capital", "VL"): raw / "2023-travel-log-capital" / "filekey-vl",
            }
            for region in ("west", "east", "jeju-islands"):
                for role in ("TL", "VL"):
                    folders[(region, role)] = raw / region / f"{role}_csv"
            for folder in folders.values():
                folder.mkdir(parents=True)

            args = argparse.Namespace(
                confirm_approved=True, confirm_terms=True, confirm_poi_candidate=True,
                k=[5, 10], run_id="synthetic", raw_root=raw,
                allow_approved_capital_filekey_folders=True,
                input=[(region, role, path) for (region, role), path in folders.items()],
            )
            specs, regions = analysis._validate_inputs(args)
            self.assertEqual(len(specs), 8)
            self.assertEqual(set(regions), set(analysis.REGION_ENV))

            args.input[0] = ("capital", "VL", folders[("capital", "TL")])
            with self.assertRaises(ValueError):
                analysis._validate_inputs(args)

    def test_ignored_artifact_writer_keeps_only_aggregate_rows(self):
        with tempfile.TemporaryDirectory() as temp:
            result_root = Path(temp) / "results"
            output = result_root / "run"
            rows = [{"scope": "west", "metric": "candidate_items", "bucket": "10+", "support": "10+"}]
            metadata = {"unvisited": "unknown/unlabeled", "raw_paths": False}
            with patch.object(analysis, "RESULTS_ROOT", result_root):
                analysis._write_artifacts(output, rows, metadata, False)
            metrics = (output / "metrics.csv").read_text(encoding="utf-8")
            run_metadata = (output / "run_metadata.json").read_text(encoding="utf-8")
            self.assertIn("candidate_items", metrics)
            self.assertIn("unknown/unlabeled", run_metadata)
            self.assertNotIn("POI_ID", metrics)
            self.assertNotIn("/tmp/", run_metadata)

    def test_run_fingerprints_cover_analyzer_and_modified_shared_helper(self):
        fingerprints = analysis._code_fingerprints()
        self.assertEqual(
            set(fingerprints),
            {"analyze_candidate_choice_feasibility.py", "evaluate_popularity.py"},
        )
        self.assertEqual(
            fingerprints["analyze_candidate_choice_feasibility.py"],
            hashlib.sha256(Path(analysis.__file__).read_bytes()).hexdigest(),
        )
        self.assertEqual(
            fingerprints["evaluate_popularity.py"],
            hashlib.sha256(Path(shared.__file__).read_bytes()).hexdigest(),
        )


if __name__ == "__main__":
    unittest.main()
