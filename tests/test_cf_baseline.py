"""Synthetic-only tests for TL-only binary implicit collaborative filtering."""

from __future__ import annotations

import csv
import json
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts" / "recommendation"
sys.path.insert(0, str(SCRIPT_DIR))

import evaluate_cf as cf  # noqa: E402
import evaluate_popularity as popularity  # noqa: E402


def event(region, user, trip, item):
    return popularity.Event(region, user, trip, item)


def write_csv(path: Path, headers, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(headers)
        writer.writerows(rows)


def make_split(root: Path, region: str, role: str, trips):
    folder = root / region / f"{role}_csv"
    travel, visits = [], []
    for trip, user, items in trips:
        travel.append((trip, user))
        visits.extend((trip, item) for item in items)
    write_csv(folder / "TN_TRAVEL.csv", ["TRAVEL_ID", "TRAVELER_ID"], travel)
    write_csv(folder / "TN_VISIT_AREA_INFO.csv", ["TRAVEL_ID", "POI_ID"], visits)
    return folder


class CollaborativeFilteringTests(unittest.TestCase):
    def test_binary_presence_and_user_cosine_weighted_sum(self):
        train = [
            event("west", "target", "a", "x"),
            event("west", "target", "a", "x"),  # repeated event does not change vectors
            event("west", "target", "a", "y"),
            event("west", "n1", "b", "x"),
            event("west", "n1", "b", "z"),
            event("west", "n2", "c", "x"),
            event("west", "n2", "c", "z"),
        ]
        histories, adjacency = cf.build_user_model(train, neighbors=10)
        self.assertEqual(histories[("west", "target")], {("west", "x"), ("west", "y")})
        self.assertAlmostEqual(dict(adjacency[("west", "target")])[("west", "n1")], 0.5)
        scores = cf.user_scores(("west", "target"), histories, adjacency)
        self.assertAlmostEqual(scores[("west", "z")], 1.0)
        self.assertNotIn(("west", "y"), scores)

    def test_user_self_exclusion_top_n_and_zero_similarity(self):
        train = [event("west", "a", "ta", "x"), event("west", "a", "ta", "y"),
                 event("west", "b", "tb", "x"), event("west", "c", "tc", "z")]
        histories, adjacency = cf.build_user_model(train, neighbors=1)
        self.assertEqual(len(adjacency[("west", "a")]), 1)
        self.assertNotIn(("west", "a"), [user for user, _ in adjacency[("west", "a")]])
        self.assertEqual(cf.user_scores(("west", "cold"), histories, adjacency), {})
        self.assertEqual(cf.user_scores(("west", "a"), histories, adjacency)[("west", "x")], 1 / 2**0.5)

    def test_item_cosine_sum_top_n_and_self_exclusion(self):
        train = [event("east", "u1", "t1", "a"), event("east", "u1", "t1", "b"),
                 event("east", "u2", "t2", "a"), event("east", "u2", "t2", "b"),
                 event("east", "u2", "t2", "c")]
        histories, adjacency = cf.build_item_model(train, top_n=5)
        sims = dict(adjacency[("east", "a")])
        self.assertAlmostEqual(sims[("east", "b")], 1.0)
        self.assertAlmostEqual(sims[("east", "c")], 1 / 2**0.5)
        self.assertNotIn(("east", "a"), sims)
        scores = cf.item_scores(("east", "u1"), histories, adjacency)
        self.assertAlmostEqual(scores[("east", "a")], 1.0)  # known TL items remain candidates
        self.assertAlmostEqual(scores[("east", "c")], 2 / 2**0.5)
        limited, limited_adj = cf.build_item_model(train, top_n=1)
        self.assertLessEqual(len(limited_adj[("east", "a")]), 1)
        self.assertEqual(limited[("east", "u1")], histories[("east", "u1")])

    def test_validation_cannot_change_tl_similarity_or_scores(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "raw"
            tl = make_split(root, "west", "TL", [("tl1", "u1", ["a", "b"]),
                                                       ("tl2", "u2", ["a", "c"])])
            vl = make_split(root, "west", "VL", [(f"val{i}", f"val-user-{i}", ["validation-only"])
                                                       for i in range(10)])
            observed_train = []
            original_builder = cf.build_item_model

            def capture_train(events, top_n):
                events = list(events)
                observed_train.extend(events)
                return original_builder(events, top_n)

            with patch.object(cf, "RESULTS_ROOT", Path(tmp) / "results"), patch.object(
                cf, "build_item_model", side_effect=capture_train
            ), redirect_stdout(StringIO()):
                args = ["--raw-root", str(root), "--input", f"west:TL={tl}", "--input", f"west:VL={vl}",
                        "--model", "item-cf", "--run-id", "leakage-check", "--confirm-approved",
                        "--confirm-terms", "--confirm-poi-candidate"]
                self.assertEqual(cf.main(args), 0)
            self.assertTrue(observed_train)
            self.assertNotIn("validation-only", {item.item_id for item in observed_train})

    def test_region_namespace_never_merges_users_or_items(self):
        train = [event("west", "same-user", "w", "same-item"),
                 event("east", "same-user", "e", "same-item")]
        histories, adjacency = cf.build_user_model(train, 10)
        self.assertEqual(len(histories), 2)
        self.assertEqual(adjacency[("west", "same-user")], [])
        self.assertEqual(adjacency[("east", "same-user")], [])
        candidates = {("west", "same-item")}
        ranked = cf.rank_cf(candidates, {("east", "same-item"): 100})
        self.assertEqual(ranked, cf.rank_cf(candidates, {}))

    def test_deterministic_ties_and_no_popularity_fallback(self):
        candidates = {("west", "a"), ("west", "b"), ("west", "c")}
        scores = {("west", "a"): 1, ("west", "b"): 1}
        first = cf.rank_cf(candidates, scores)
        self.assertEqual(first, cf.rank_cf(reversed(sorted(candidates)), scores))
        self.assertEqual(set(first), candidates)
        self.assertEqual(first[-1], ("west", "c"))
        zero_score_order = cf.rank_cf(candidates, {})
        self.assertEqual(zero_score_order, sorted(candidates, key=popularity.stable_tie_key))

    def test_zero_scores_preserve_denominator_without_creating_no_signal_hits(self):
        train_events = [event("west", "u1", "t1", "a"), event("west", "u2", "t2", "b")]
        candidates = {("west", "a"), ("west", "b")}
        no_signal_order = cf.rank_cf(candidates, {})
        # Make the arbitrary HMAC winner relevant: without the zero-signal guard,
        # this fixture would report a perfect Precision@1.
        validation_events = [event("west", f"v{i}", f"v{i}", no_signal_order[0][1]) for i in range(10)]
        train = popularity.SplitSummary(
            train_events, 2, 0, 0, 0, {("west", "u1", "t1"), ("west", "u2", "t2")},
        )
        validation = popularity.SplitSummary(
            validation_events, 10, 0, 0, 0, {e.trip_key for e in validation_events},
        )
        rankings = {e.trip_key: cf.rank_cf(candidates, {("west", "a"): 1}) for e in validation_events}
        signal = {e.trip_key: True for e in validation_events}
        rows = cf._metric_rows("item-cf", "west", train, validation, (2,), rankings, set(), signal)
        precision = {row["metric"]: row["value"] for row in rows if row["cohort"] == "all"}
        self.assertEqual(len(rankings[validation_events[0].trip_key]), 2)
        self.assertEqual(precision["precision@2"], "0.500000")

        no_signal_rankings = {e.trip_key: cf.rank_cf(candidates, {}) for e in validation_events}
        no_signal = {e.trip_key: False for e in validation_events}
        no_signal_rows = cf._metric_rows(
            "item-cf", "west", train, validation, (1, 2), no_signal_rankings, set(), no_signal,
        )
        coverage = next(row for row in no_signal_rows if row["metric"] == "recommendation_coverage")
        self.assertEqual(coverage["value"], "0-<10%")
        self.assertEqual(no_signal_rankings[validation_events[0].trip_key], no_signal_order)
        no_signal_precision = next(
            row for row in no_signal_rows if row["cohort"] == "all" and row["metric"] == "precision@1"
        )
        self.assertEqual(no_signal_precision["value"], "suppressed")
        self.assertEqual(no_signal_precision["status"], "suppressed_k10")
        self.assertEqual(no_signal_precision["cell_size"], "10+")
        self.assertEqual(len(no_signal_rankings[validation_events[0].trip_key]), len(candidates))

    def test_metrics_use_trip_units_cohorts_and_suppression(self):
        train_events = [event("west", "u1", "t1", "a"), event("west", "u2", "t2", "b")]
        val_events = [event("west", f"v{i}", f"v{i}", "a") for i in range(10)]
        train = popularity.SplitSummary(train_events, 2, 0, 0, 0, {("west", "u1", "t1"), ("west", "u2", "t2")})
        val = popularity.SplitSummary(val_events, 10, 0, 0, 0, {(e.region,e.user_id,e.trip_id) for e in val_events})
        rankings = {e.trip_key: [("west", "a"), ("west", "b")] for e in val_events}
        rows = cf._metric_rows("user-cf", "west", train, val, (1, 2), rankings, {("west", "v0")})
        row = next(r for r in rows if r["cohort"] == "all" and r["metric"] == "precision@1")
        self.assertEqual(row["value"], "1.000000")
        self.assertEqual(row["cell_size"], "10+")
        self.assertIn("user_history", {r["cohort"] for r in rows})
        self.assertIn("cold_start_user", {r["cohort"] for r in rows})
        user_rows = [r for r in rows if r["cohort"] == "user_history" and r["metric"] == "evaluation_trips"]
        self.assertEqual(user_rows[0]["cell_size"], "<10")
        self.assertEqual(user_rows[0]["status"], "suppressed_k10")
        self.assertEqual(user_rows[0]["value"], "suppressed")
        cold_rows = [r for r in rows if r["cohort"] == "cold_start_user" and r["metric"] == "evaluation_trips"]
        self.assertEqual(cold_rows[0]["cell_size"], "<10")
        self.assertEqual(cold_rows[0]["status"], "suppressed_k10")
        cold_precision = next(r for r in rows if r["cohort"] == "cold_start_user" and r["metric"] == "precision@1")
        self.assertEqual(cold_precision["status"], "suppressed_k10")

    def test_validation_user_coverage_includes_mapped_blank_poi_visits(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "raw"
            tl = make_split(root, "west", "TL", [("tl-trip", "v0", ["known-poi"])])
            vl_trips = [(f"val-trip-{i}", f"v{i}", ["known-poi"] if i == 0 else [""])
                        for i in range(10)]
            vl = make_split(root, "west", "VL", vl_trips)
            validation = popularity._read_split(popularity.InputSpec("west", "VL", vl))
            self.assertEqual(len(validation.events), 1)
            self.assertEqual(len(validation.visit_trip_keys), 10)
            train = popularity._read_split(popularity.InputSpec("west", "TL", tl))
            rankings = {event.trip_key: [("west", "known-poi")] for event in validation.events}
            rows = cf._metric_rows("item-cf", "west", train, validation, (1,), rankings, {("west", "v0")})
            history = next(row for row in rows if row["metric"] == "user_history_coverage")
            cold = next(row for row in rows if row["metric"] == "user_cold_start_share")
            self.assertEqual(history["value"], "<10/suppressed")
            self.assertEqual(cold["value"], "<10/suppressed")

    def test_candidate_coverage_matches_popularity_candidate_universe(self):
        train = popularity.SplitSummary([event("west", "u", "t", "a"), event("east", "u", "t", "b")], 2,0,0,0,{("west","u","t"),("east","u","t")})
        val_events = [event("west", f"v{i}", f"v{i}", "a") for i in range(10)]
        trip_keys = {e.trip_key for e in val_events} | {("west", f"blank{i}", f"blank{i}") for i in range(10)}
        val = popularity.SplitSummary(val_events, 20,10,0,0,trip_keys)
        rankings = {e.trip_key: [e.item_key] for e in val_events}
        rows = cf._metric_rows("item-cf", "aggregate", train, val, (1,), rankings, set())
        coverage = next(r for r in rows if r["metric"] == "candidate_coverage")
        self.assertEqual(coverage["value"], "90-100%")
        evaluation = next(r for r in rows if r["metric"] == "evaluation_trip_coverage")
        self.assertEqual(evaluation["value"], "50-<75%")
        popularity_rows = popularity._event_metrics("", "aggregate", train, val, (1,))
        baseline_coverage = next(r for r in popularity_rows if r["model"] == "region_popularity" and r["metric"] == "candidate_coverage")
        self.assertEqual(coverage["value"], baseline_coverage["value"])

    def test_tl_vl_trip_overlap_fails_before_ranking_and_hides_identifier(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "raw"
            tl = make_split(root, "west", "TL", [("shared-secret-trip", "u", ["poi-a"])])
            vl = make_split(root, "west", "VL", [("shared-secret-trip", "u", ["poi-a"])])
            args = ["--raw-root", str(root), "--input", f"west:TL={tl}", "--input", f"west:VL={vl}",
                    "--model", "user-cf", "--confirm-approved", "--confirm-terms", "--confirm-poi-candidate"]
            err = StringIO()
            with redirect_stderr(err), patch.object(cf, "build_user_model", side_effect=AssertionError("ranked")):
                self.assertEqual(cf.main(args), 2)
            self.assertNotIn("shared-secret-trip", err.getvalue())
            self.assertIn("<10", err.getvalue())

    def test_cli_artifacts_are_aggregate_only_and_path_free(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "raw"
            tl = make_split(root, "west", "TL", [("tl-trip", "tl-user", ["poi-a", "poi-b"]),
                                                       ("tl-trip-2", "neighbor", ["poi-a", "poi-c"])])
            vl = make_split(root, "west", "VL", [(f"val-trip-{i}", f"val-user-{i}", ["poi-c"])
                                                       for i in range(10)])
            output = Path(tmp) / "output"
            with patch.object(cf, "RESULTS_ROOT", output):
                args = ["--raw-root", str(root), "--input", f"west:TL={tl}", "--input", f"west:VL={vl}",
                        "--model", "item-cf", "--neighbors", "10", "--k", "5", "10", "20", "--run-id", "synthetic-cf",
                        "--confirm-approved", "--confirm-terms", "--confirm-poi-candidate"]
                stdout = StringIO()
                with redirect_stdout(stdout): self.assertEqual(cf.main(args), 0)
            metadata = json.loads((output / "synthetic-cf" / "run_metadata.json").read_text())
            metrics = (output / "synthetic-cf" / "metrics.csv").read_text()
            public = json.dumps(metadata) + metrics + stdout.getvalue()
            for secret in (str(root), str(tl), str(vl), "tl-user", "val-user-0", "poi-a", "tl-trip"):
                self.assertNotIn(secret, public)
            self.assertIs(metadata["config"]["popularity_fallback"], False)
            self.assertEqual(metadata["code_worktree_dirty"], True)
            self.assertTrue(metadata["safe_metric_summary"])
            self.assertFalse(any(token in public for token in ("TN_TRAVEL.csv", "TN_VISIT_AREA_INFO.csv")))

    def test_invalid_confirmation_and_input_mapping_fail_before_read(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "raw"
            tl = make_split(root, "west", "TL", [("t", "u", ["a"])])
            vl = make_split(root, "west", "VL", [("v", "v", ["a"])])
            args = ["--raw-root", str(root), "--input", f"west:TL={tl}", "--input", f"west:VL={vl}", "--model", "item-cf"]
            err = StringIO()
            with redirect_stderr(err), patch.object(popularity, "_read_split", side_effect=AssertionError("read")):
                self.assertEqual(cf.main(args), 2)
            self.assertNotIn(str(root), err.getvalue())


if __name__ == "__main__":
    unittest.main()
