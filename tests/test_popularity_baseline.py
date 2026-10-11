"""Synthetic-only contract tests for the trip-level popularity baseline."""

from __future__ import annotations

import csv
import json
import sys
import unittest
from collections import Counter
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts" / "recommendation"
sys.path.insert(0, str(SCRIPT_DIR))

from evaluate_popularity import (  # noqa: E402
    RESULTS_ROOT,
    Event,
    InputSpec,
    SplitSummary,
    _event_metrics,
    _read_split,
    group_positive_items,
    main,
    rank_items,
    ranking_metrics,
)


def write_csv(path: Path, headers: list[str], rows: list[tuple[str, ...]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(headers)
        writer.writerows(rows)


class PopularityBaselineTests(unittest.TestCase):
    def test_ranking_metrics_and_top_k(self) -> None:
        ranked = [("west", "a"), ("west", "b"), ("west", "c")]
        relevant = {("west", "a"), ("west", "c")}
        metrics = ranking_metrics(ranked, relevant, (1, 2))
        self.assertEqual(metrics[("precision", 1)], 1.0)
        self.assertEqual(metrics[("recall", 1)], 0.5)
        self.assertEqual(metrics[("mrr", 1)], 1.0)
        self.assertEqual(metrics[("precision", 2)], 0.5)
        self.assertAlmostEqual(metrics[("ndcg", 2)], 1 / (1 + 1 / 1.584962500721156))

    def test_train_counts_keep_repeats_and_validation_never_changes_them(self) -> None:
        train = [
            Event("west", "train-user", "train-trip", "train-popular")
            for _ in range(4)
        ] + [Event("west", "train-user", "train-trip", "train-other")]
        validation = [
            Event("west", "val-user", "val-trip", "validation-only-item")
            for _ in range(20)
        ]
        counts = Counter(event.item_key for event in train)
        before = counts.copy()
        rows = _event_metrics(
            "west", "west",
            SplitSummary(train, 5, 0, 0, 0, {("west", "train-user", "train-trip")}),
            SplitSummary(validation, 20, 0, 0, 0, {("west", "val-user", "val-trip")}),
            (1,),
        )
        self.assertEqual(counts, before)
        self.assertEqual(counts[("west", "train-popular")], 4)
        self.assertNotIn(("west", "validation-only-item"), counts)
        self.assertIn("cold_positive", {row["cohort"] for row in rows})

    def test_ties_are_deterministic_and_namespaced_by_region(self) -> None:
        candidates = {("west", "item-a"), ("west", "item-b")}
        counts = Counter({item: 3 for item in candidates})
        first = rank_items(candidates, counts)
        self.assertEqual(first, rank_items(reversed(sorted(candidates)), counts))
        self.assertEqual(first, rank_items(candidates, counts))
        self.assertNotEqual(("west", "shared-value"), ("east", "shared-value"))

    def test_pooled_diagnostic_cannot_change_region_scoped_candidate_order(self) -> None:
        train = SplitSummary(
            [Event("west", "u", "t", "west-a") for _ in range(12)]
            + [Event("west", "u", "t", "west-b") for _ in range(10)],
            22, 0, 0, 0, {("west", "u", "t")},
        )
        validation = SplitSummary(
            [Event("west", "v", "v-trip", "west-a") for _ in range(12)],
            12, 0, 0, 0, {("west", "v", "v-trip")},
        )
        pooled = Counter({("west", "west-a"): 12, ("west", "west-b"): 10,
                          ("east", "west-b"): 1000})
        rows = _event_metrics("west", "west", train, validation, (1, 2), pooled)
        region = [row for row in rows if row["model"] == "region_popularity"]
        global_diagnostic = [row for row in rows if row["model"] == "global_popularity_diagnostic"]
        self.assertEqual(
            [(row["cohort"], row["metric"], row["value"]) for row in region],
            [(row["cohort"], row["metric"], row["value"]) for row in global_diagnostic],
        )

    def test_repeated_validation_events_remain_events_but_group_by_trip(self) -> None:
        events = [
            Event("east", "user-secret", "same-trip", "poi-one"),
            Event("east", "user-secret", "same-trip", "poi-one"),
            Event("east", "user-secret", "same-trip", "poi-two"),
            Event("east", "user-secret", "other-trip", "poi-one"),
        ]
        grouped = group_positive_items(events)
        self.assertEqual(len(events), 4)
        self.assertEqual(len(grouped), 2)
        self.assertEqual(len(grouped[("east", "user-secret", "same-trip")]), 2)

    def test_csv_loader_handles_blank_missing_poi_and_bad_trip_mapping(self) -> None:
        with TemporaryDirectory() as tmp:
            role = Path(tmp) / "west" / "VL_csv"
            write_csv(
                role / "TN_TRAVEL.csv", ["TRAVEL_ID", "TRAVELER_ID"],
                [("known-trip", "traveler-secret"), ("ambiguous-trip", "traveler-a"),
                 ("ambiguous-trip", "traveler-b")],
            )
            write_csv(
                role / "TN_VISIT_AREA_INFO.csv", ["TRAVEL_ID", "POI_ID", "VISIT_AREA_ID"],
                [("known-trip", " poi-known ", "area-secret"), ("known-trip", "   ", "area-2"),
                 ("unknown-trip", "poi-3", "area-3"), ("ambiguous-trip", "poi-4", "area-4")],
            )
            result = _read_split(InputSpec("west", "VL", role))
            self.assertEqual(result.visit_rows, 4)
            self.assertEqual(result.missing_poi_rows, 1)
            self.assertEqual(result.unmapped_trip_rows, 1)
            self.assertEqual(result.ambiguous_trip_rows, 1)
            self.assertEqual(len(result.events), 1)
            self.assertEqual(result.events[0].item_id, " poi-known ")
            self.assertNotIn("VISIT_AREA_ID", result.events[0].__dict__)

    def test_nested_symlink_file_or_directory_fails_closed(self) -> None:
        for symlink_kind in ("file", "directory"):
            with self.subTest(symlink_kind=symlink_kind), TemporaryDirectory() as tmp:
                root = Path(tmp)
                role = root / "west" / "VL_csv"
                write_csv(role / "TN_TRAVEL.csv", ["TRAVEL_ID", "TRAVELER_ID"], [("trip", "user")])
                write_csv(role / "TN_VISIT_AREA_INFO.csv", ["TRAVEL_ID", "POI_ID"], [("trip", "poi")])
                target_dir = root / "target-dir"
                target_dir.mkdir()
                target_file = root / "target-file.txt"
                target_file.write_text("synthetic", encoding="utf-8")
                link = role / "nested-link"
                try:
                    if symlink_kind == "file":
                        link.symlink_to(target_file)
                    else:
                        link.symlink_to(target_dir, target_is_directory=True)
                except OSError as exc:
                    self.skipTest(f"symlink creation is unavailable: {type(exc).__name__}")
                with self.assertRaisesRegex(ValueError, "symlink"):
                    _read_split(InputSpec("west", "VL", role))

    def test_absent_poi_column_never_uses_area_or_feedback_fallback(self) -> None:
        with TemporaryDirectory() as tmp:
            role = Path(tmp) / "west" / "VL_csv"
            write_csv(role / "TN_TRAVEL.csv", ["TRAVEL_ID", "TRAVELER_ID"], [("trip-secret", "user-secret")])
            write_csv(
                role / "TN_VISIT_AREA_INFO.csv",
                ["TRAVEL_ID", "VISIT_AREA_ID", "DGSTFN", "REVISIT_INTENTION", "RCMDTN_INTENTION"],
                [("trip-secret", "area-secret", "5", "4", "3")],
            )
            result = _read_split(InputSpec("west", "VL", role))
            self.assertEqual(result.events, [])
            self.assertEqual(result.missing_poi_rows, 1)

    def test_empty_candidate_and_empty_validation_are_reported_without_metrics(self) -> None:
        empty = SplitSummary([], 0, 0, 0, 0, set())
        val = SplitSummary(
            [Event("capital", "user-secret", "trip-secret", "cold-item")],
            1, 0, 0, 0, {("capital", "user-secret", "trip-secret")},
        )
        rows = _event_metrics("capital", "capital", empty, val, (5,))
        coverage = [row for row in rows if row["metric"] == "candidate_coverage"]
        self.assertEqual(len(coverage), 2)
        self.assertTrue(all(row["status"] == "observed" or row["status"] == "suppressed_k10" for row in coverage))
        self.assertFalse(any(row["metric"] == "precision@5" and row["status"] == "observed" for row in rows))
        no_validation = _event_metrics("capital", "capital", empty, empty, (5,))
        self.assertTrue(any(row["status"] == "empty_cohort" for row in no_validation))

    def test_small_cells_are_suppressed(self) -> None:
        rows = _event_metrics(
            "west", "west", SplitSummary([], 0, 0, 0, 0, set()),
            SplitSummary(
                [Event("west", "user", "trip", "poi")], 1, 0, 0, 0,
                {("west", "user", "trip")},
            ), (5,),
        )
        self.assertTrue(all(row["value"] == "suppressed" for row in rows if row["status"] == "suppressed_k10"))

    def test_zero_retrieved_positives_are_suppressed(self) -> None:
        train = SplitSummary(
            [Event("west", "train-user", "train-trip", "seen-item") for _ in range(10)],
            10, 0, 0, 0, {("west", "train-user", "train-trip")},
        )
        validation_events = [
            Event("west", f"user-{index}", f"trip-{index}", "cold-item")
            for index in range(10)
        ]
        validation = SplitSummary(
            validation_events, 10, 0, 0, 0,
            {(event.region, event.user_id, event.trip_id) for event in validation_events},
        )
        rows = _event_metrics("west", "west", train, validation, (1,))
        cold_metrics = [
            row for row in rows
            if row["cohort"] == "cold_positive" and row["metric"] in {
                "precision@1", "recall@1", "ndcg@1", "mrr@1",
            }
        ]
        self.assertEqual(len(cold_metrics), 8)
        self.assertTrue(all(row["status"] == "suppressed_k10" for row in cold_metrics))
        self.assertTrue(all(row["value"] == "suppressed" for row in cold_metrics))

    def test_coverage_and_metrics_use_trip_units_and_cold_start_positives(self) -> None:
        train_events = [
            Event("east", "train-user", "train-trip", f"seen-{i}")
            for i in range(10) for _ in range(12)
        ]
        validation_events = []
        for i in range(10):
            validation_events.extend(
                Event("east", f"user-{i}", f"trip-{i}", f"seen-{i}")
                for _ in range(10)
            )
            validation_events.append(
                Event("east", f"user-{i}", f"trip-{i}", f"cold-{i}")
            )
        validation = SplitSummary(
            validation_events, len(validation_events), 0, 0, 0,
            {(event.region, event.user_id, event.trip_id) for event in validation_events},
        )
        rows = _event_metrics(
            "east", "east",
            SplitSummary(train_events, len(train_events), 0, 0, 0, {("east", "train-user", "train-trip")}),
            validation, (10,),
        )
        regional = [row for row in rows if row["model"] == "region_popularity"]
        coverage = {row["metric"]: row["value"] for row in regional if row["cohort"] == "all"}
        self.assertEqual(coverage["positive_coverage"], "90-100%")
        self.assertEqual(coverage["candidate_coverage"], "90-100%")
        self.assertEqual(coverage["cold_start_item_share"], "50-<75%")
        self.assertEqual(coverage["cold_start_event_share"], "0-<10%")
        self.assertEqual(coverage["evaluation_trips"], "count")
        self.assertTrue(any(
            row["metric"] == "precision@10" and row["cohort"] == "all"
            and row["status"] == "observed" for row in regional
        ))
        self.assertTrue(any(
            row["metric"] == "recall@10" and row["cohort"] == "cold_positive"
            and row["status"] == "suppressed_k10" for row in regional
        ))

    def test_public_cli_artifacts_omit_raw_ids_paths_and_row_level_outputs(self) -> None:
        RESULTS_ROOT.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory() as tmp:
            raw_root = Path(tmp) / "raw"
            tl = raw_root / "2023-travel-log-west" / "TL_csv"
            vl = raw_root / "2023-travel-log-west" / "VL_csv"
            traveler = "raw-traveler-identifier-secret"
            trip = "raw-trip-identifier-secret"
            poi = "raw-poi-identifier-secret"
            area = "raw-visit-area-identifier-secret"
            write_csv(tl / "TN_TRAVEL.csv", ["TRAVEL_ID", "TRAVELER_ID"], [(trip, traveler)] * 12)
            write_csv(tl / "TN_VISIT_AREA_INFO.csv", ["TRAVEL_ID", "POI_ID"], [(trip, poi)] * 12)
            write_csv(vl / "TN_TRAVEL.csv", ["TRAVEL_ID", "TRAVELER_ID"], [("validation-trip-secret", traveler)])
            write_csv(vl / "TN_VISIT_AREA_INFO.csv", ["TRAVEL_ID", "POI_ID", "VISIT_AREA_ID"],
                      [("validation-trip-secret", poi, area)])
            run_id = "synthetic-test-popularity-artifact"
            output = RESULTS_ROOT / run_id
            if output.exists():
                self.fail("synthetic test output path already exists")
            args = [
                "--raw-root", str(raw_root),
                "--input", f"west:TL={tl}", "--input", f"west:VL={vl}",
                "--run-id", run_id, "--k", "1", "--confirm-approved", "--confirm-terms",
                "--confirm-poi-candidate",
            ]
            try:
                with redirect_stderr(StringIO()), redirect_stdout(StringIO()):
                    self.assertEqual(main(args), 0)
                metrics_text = (output / "metrics.csv").read_text(encoding="utf-8")
                metadata_text = (output / "run_metadata.json").read_text(encoding="utf-8")
                for secret in (traveler, trip, poi, area, str(raw_root), "validation-trip-secret"):
                    self.assertNotIn(secret, metrics_text)
                    self.assertNotIn(secret, metadata_text)
                metadata = json.loads(metadata_text)
                self.assertEqual({path.name for path in output.iterdir()}, {"metrics.csv", "run_metadata.json"})
                self.assertEqual(metadata["dataset"]["version"], "2023")
                self.assertEqual(metadata["config"]["split"]["TL"], "train")
                self.assertEqual(metadata["config"]["split"]["VL"], "validation")
                self.assertEqual(metadata["privacy"]["row_level_outputs"], False)
                self.assertIn("global_diagnostic_limit", metadata["config"])
                self.assertEqual(
                    metadata["config"]["trip_id_overlap_check"]["per_region"], {"west": "0"}
                )
            finally:
                if output.exists():
                    for child in output.iterdir():
                        child.unlink()
                    output.rmdir()

    def test_confirmation_gate_precedes_input_access(self) -> None:
        error = StringIO()
        with redirect_stderr(error):
            code = main(["--input", "west:TL=/not-read"])
        self.assertEqual(code, 2)
        self.assertIn("확인 옵션", error.getvalue())

    def test_cli_fails_on_train_validation_trip_id_overlap_without_leaking_id(self) -> None:
        trip_id = "overlap-trip-raw-secret"
        traveler_id = "overlap-traveler-raw-secret"
        poi_id = "overlap-poi-raw-secret"
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw_root = root / "raw"
            tl = raw_root / "west" / "TL_csv"
            vl = raw_root / "west" / "VL_csv"
            write_csv(tl / "TN_TRAVEL.csv", ["TRAVEL_ID", "TRAVELER_ID"], [(trip_id, traveler_id)])
            write_csv(tl / "TN_VISIT_AREA_INFO.csv", ["TRAVEL_ID", "POI_ID"], [(trip_id, poi_id)])
            write_csv(vl / "TN_TRAVEL.csv", ["TRAVEL_ID", "TRAVELER_ID"], [(trip_id, traveler_id)])
            write_csv(vl / "TN_VISIT_AREA_INFO.csv", ["TRAVEL_ID", "POI_ID"], [(trip_id, poi_id)])

            isolated_results_root = root / "results" / "experiments" / "popularity-baseline"
            run_id = "overlap-rejected-run"
            stderr = StringIO()
            args = [
                "--raw-root", str(raw_root),
                "--input", f"west:TL={tl}", "--input", f"west:VL={vl}",
                "--run-id", run_id,
                "--confirm-approved", "--confirm-terms", "--confirm-poi-candidate",
            ]
            ranking = Mock(side_effect=AssertionError("ranking must not run"))
            with (
                patch.dict(main.__globals__, {
                    "RESULTS_ROOT": isolated_results_root,
                    "_event_metrics": ranking,
                }),
                redirect_stderr(stderr),
                redirect_stdout(StringIO()),
            ):
                self.assertEqual(main(args), 2)
                ranking.assert_not_called()

            message = stderr.getvalue()
            self.assertIn("west=<10", message)
            for secret in (trip_id, traveler_id, poi_id, str(raw_root), str(tl), str(vl)):
                self.assertNotIn(secret, message)
            self.assertFalse((isolated_results_root / run_id).exists())

    def test_cli_accepts_approved_capital_filekey_roots_without_recording_paths(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw_root = root / "raw"
            tl = raw_root / "2023-travel-log-capital" / "extracted" / "filekey-111"
            vl = raw_root / "2023-travel-log-capital" / "filekey-222"
            write_csv(tl / "tn_travel_여행_E.csv", ["TRAVEL_ID", "TRAVELER_ID"], [("train-trip", "train-user")])
            write_csv(tl / "tn_visit_area_info_방문지정보_E.csv", ["TRAVEL_ID", "POI_ID"], [("train-trip", "train-poi")])
            write_csv(vl / "tn_travel_여행_E.csv", ["TRAVEL_ID", "TRAVELER_ID"], [("validation-trip", "validation-user")])
            write_csv(vl / "tn_visit_area_info_방문지정보_E.csv", ["TRAVEL_ID", "POI_ID"], [("validation-trip", "train-poi")])
            isolated_results_root = root / "results" / "experiments" / "popularity-baseline"
            run_id = "capital-filekey-root-test"
            args = [
                "--raw-root", str(raw_root),
                "--input", f"capital:TL={tl}", "--input", f"capital:VL={vl}",
                "--run-id", run_id, "--k", "1",
                "--allow-approved-capital-filekey-folders",
                "--confirm-approved", "--confirm-terms", "--confirm-poi-candidate",
            ]
            with (
                patch.dict(main.__globals__, {"RESULTS_ROOT": isolated_results_root}),
                redirect_stderr(StringIO()),
                redirect_stdout(StringIO()),
            ):
                self.assertEqual(main(args), 0)
            metadata = (isolated_results_root / run_id / "run_metadata.json").read_text(encoding="utf-8")
            self.assertNotIn("filekey-111", metadata)
            self.assertNotIn("filekey-222", metadata)
            self.assertNotIn(str(raw_root), metadata)


if __name__ == "__main__":
    unittest.main()
