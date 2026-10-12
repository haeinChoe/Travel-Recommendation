"""Synthetic-only safety and statistics tests for Issue #45."""

from __future__ import annotations

import csv
import math
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts" / "recommendation"
sys.path.insert(0, str(SCRIPT_DIR))

from experiment_context_poi_signal import (  # noqa: E402
    FEEDBACK_FIELDS,
    REGIONS,
    RESULTS_ROOT,
    SafeInputError,
    Source,
    Visit,
    _fit_nb,
    _features,
    _predict_log_probs,
    ablation_rows,
    association_rows,
    chi_square_effect,
    collect_events,
    context_poi_distributions,
    feedback_diagnostics,
    feedback_cross_distributions,
    feedback_context_poi_distributions,
    main,
    resolve_sources,
    validate_headers,
    validate_join_quality,
    validate_trip_overlap,
)


class ContextPoiSignalSyntheticTests(unittest.TestCase):
    def test_chi_square_reports_effect_and_suppresses_small_cells(self) -> None:
        independent_support = [("a", "x")] * 10 + [("b", "y")] * 10
        result = chi_square_effect(independent_support)
        self.assertEqual(result["status"], "observed")
        self.assertAlmostEqual(result["cramers_v"], 1.0)
        self.assertLess(result["p_value"], 0.001)
        self.assertEqual(chi_square_effect([("a", "x")] * 9)["status"], "insufficient_support")
        self.assertEqual(
            chi_square_effect([("a", "x")] * 9 + [("b", "y")] * 10)["status"],
            "suppressed_k10",
        )
        balanced = [(left, right) for left in ("a", "b") for right in ("x", "y") for _ in range(10)]
        self.assertAlmostEqual(chi_square_effect(balanced)["p_value"], 1.0)

    def test_row_chi_square_is_exported_as_descriptive_only(self) -> None:
        events = {("west", "TL"): [
            Visit("west", "TL", (str(index % 2), "month_01"),
                  ("west", "area", "type"), "2-4", {
                      "DGSTFN": "1", "REVISIT_INTENTION": "2", "RCMDTN_INTENTION": "3"
                  })
            for index in range(20)
        ]}
        rows = association_rows(events)
        self.assertTrue(rows)
        self.assertTrue(all("p_value_descriptive" in row for row in rows))
        self.assertTrue(all("p_value" not in row for row in rows))

    def test_ablation_suppresses_validation_class_missing_from_training(self) -> None:
        def event(role: str, label: str) -> Visit:
            return Visit(
                "west", role, ("purpose", "month_01"), ("west", "area", "type"),
                "1", {
                    "DGSTFN": label,
                    "REVISIT_INTENTION": label,
                    "RCMDTN_INTENTION": label,
                },
            )

        events = {
            ("west", "TL"): [
                event("TL", label) for label in ("1", "2") for _ in range(10)
            ],
            ("west", "VL"): [
                event("VL", label) for label in ("1", "3") for _ in range(10)
            ],
        }
        west_dgstfn = [
            row for row in ablation_rows(events)
            if row["region"] == "west" and row["outcome"] == "DGSTFN"
        ]
        self.assertEqual(len(west_dgstfn), 4)
        self.assertTrue(all(
            row["status"] == "suppressed_unseen_validation_class"
            for row in west_dgstfn
        ))

    def test_feature_ablations_keep_raw_identifiers_out_of_model_inputs(self) -> None:
        event = Visit(
            "west", "TL", ("purpose-a", "month_01"),
            ("west", "area-a", "type-a"), "10-49",
            {"DGSTFN": "1", "REVISIT_INTENTION": "2", "RCMDTN_INTENTION": "3"},
        )
        self.assertEqual(_features(event, "popularity_only"), ("10-49",))
        self.assertEqual(_features(event, "context_only"), ("purpose-a", "month_01"))
        self.assertEqual(_features(event, "poi_only"), ("west", "area-a", "type-a"))
        self.assertEqual(
            _features(event, "context_plus_poi"),
            ("purpose-a", "month_01", "west", "area-a", "type-a"),
        )
        training_rows = [(_features(event, "context_only"), "1")] * 10
        training_rows.extend([(("b", "month_02"), "2")] * 10)
        fitted = _fit_nb(training_rows)
        prediction = _predict_log_probs(("purpose-a", "month_01"), fitted)
        self.assertAlmostEqual(sum(math.exp(value) for value in prediction.values()), 1.0)

    def test_feedback_values_remain_three_independent_outcomes(self) -> None:
        events = {
            ("west", "TL"): [
                Visit("west", "TL", ("purpose", "month_01"), ("west", "area", "type"), "10-49",
                      {"DGSTFN": "1", "REVISIT_INTENTION": "2", "RCMDTN_INTENTION": "3"})
                for _ in range(12)
            ]
        }
        distributions, associations = feedback_diagnostics(events)
        labels = {row["outcome"] for row in distributions}
        self.assertEqual(labels, set(FEEDBACK_FIELDS))
        self.assertEqual({row["outcome"] for row in associations}, set(FEEDBACK_FIELDS))
        self.assertFalse(
            any("composite" in str(row).casefold() for row in distributions + associations)
        )

    def test_feedback_distribution_hides_small_category_labels(self) -> None:
        event = Visit(
            "west", "VL", ("purpose", "month_01"), ("west", "area", "type"), "1",
            {"DGSTFN": "1", "REVISIT_INTENTION": "2", "RCMDTN_INTENTION": "3"},
        )
        events = {("west", "VL"): [event] * 9}
        distributions, _ = feedback_diagnostics(events)
        self.assertTrue(all(row["category"] == "<suppressed>" for row in distributions))
        self.assertTrue(all(row["support"] == "<10" for row in distributions))
        cross = feedback_cross_distributions(events)
        self.assertTrue(all(row["feature_category"] == "" for row in cross))
        self.assertTrue(all(row["outcome_category"] == "" for row in cross))

    def test_joint_context_poi_feedback_distribution_uses_opaque_k10_cells(self) -> None:
        event = Visit(
            "west", "TL", ("raw-mission", "month_01"),
            ("west", "raw-area", "raw-type"), "1",
            {"DGSTFN": "1", "REVISIT_INTENTION": "2", "RCMDTN_INTENTION": "3"},
        )
        distributions = feedback_context_poi_distributions({("west", "TL"): [event] * 10})
        west_rows = [row for row in distributions if row["region"] == "west"]
        self.assertEqual(len(west_rows), len(FEEDBACK_FIELDS) * 2 * 3)
        self.assertTrue(all(row["status"] == "observed" for row in west_rows))
        self.assertTrue(all(row["context_category"] == "context_1" for row in west_rows))
        self.assertTrue(all(row["poi_category"] == "poi_1" for row in west_rows))
        self.assertTrue(all(row["outcome_category"] == "outcome_1" for row in west_rows))
        self.assertEqual({row["outcome"] for row in west_rows}, set(FEEDBACK_FIELDS))
        self.assertNotIn("raw-mission", repr(west_rows))
        self.assertNotIn("raw-area", repr(west_rows))
        self.assertNotIn("raw-type", repr(west_rows))
        self.assertNotIn("code_1", repr(west_rows))

        suppressed = feedback_context_poi_distributions({("west", "TL"): [event] * 9})
        west_suppressed = [row for row in suppressed if row["region"] == "west"]
        self.assertTrue(all(row["status"] == "suppressed_k10" for row in west_suppressed))
        self.assertTrue(all(row["context_category"] == "" for row in west_suppressed))
        self.assertTrue(all(row["poi_category"] == "" for row in west_suppressed))
        self.assertTrue(all(row["outcome_category"] == "" for row in west_suppressed))

    def test_joint_feedback_distribution_marks_missing_features_unavailable(self) -> None:
        event = Visit(
            "west", "TL", ("raw-mission", "month_01"),
            ("west", "raw-area", "raw-type"), "1",
            {"DGSTFN": "1", "REVISIT_INTENTION": "2", "RCMDTN_INTENTION": "3"},
            frozenset({"TRAVEL_START_YMD", "VISIT_AREA_TYPE_CD", *FEEDBACK_FIELDS}),
        )
        rows = feedback_context_poi_distributions({("west", "TL"): [event] * 10})
        west_rows = [row for row in rows if row["region"] == "west"]
        mission_rows = [row for row in west_rows if row["context_feature"] == "TRAVEL_MISSION"]
        sgg_rows = [row for row in west_rows if row["poi_feature"] == "SGG_CD"]
        self.assertTrue(all(row["status"] == "unavailable_missing_column" for row in mission_rows))
        self.assertTrue(all(row["status"] == "unavailable_missing_column" for row in sgg_rows))

    def test_loads_only_synthetic_inputs_and_keeps_ids_ephemeral(self) -> None:
        with TemporaryDirectory(prefix="context-poi-synthetic-") as temporary:
            root = Path(temporary)
            sources: list[Source] = []
            for region in REGIONS:
                for role in ("TL", "VL"):
                    folder = root / region / role
                    folder.mkdir(parents=True)
                    travel = folder / "TN_TRAVEL.csv"
                    visits = folder / "TN_VISIT_AREA_INFO.csv"
                    with travel.open("w", newline="", encoding="utf-8") as stream:
                        writer = csv.DictWriter(
                            stream,
                            fieldnames=("TRAVEL_ID", "TRAVEL_MISSION", "TRAVEL_START_YMD"),
                        )
                        writer.writeheader()
                        for index in range(20):
                            writer.writerow(
                                {
                                    "TRAVEL_ID": f"synthetic-trip-{role}-{index}",
                                    "TRAVEL_MISSION": str(index % 2 + 1),
                                    "TRAVEL_START_YMD": (
                                        "2023-01-01" if index % 2 == 0 else "2023-02-01"
                                    ),
                                }
                            )
                    with visits.open("w", newline="", encoding="utf-8") as stream:
                        writer = csv.DictWriter(
                            stream,
                            fieldnames=(
                                "TRAVEL_ID", "VISIT_AREA_ID", "POI_ID", "VISIT_AREA_TYPE_CD",
                                "SGG_CD", *FEEDBACK_FIELDS,
                            ),
                        )
                        writer.writeheader()
                        for index in range(20):
                            writer.writerow(
                                {
                                    "TRAVEL_ID": f"synthetic-trip-{role}-{index}",
                                    "VISIT_AREA_ID": f"synthetic-area-{index}",
                                    "POI_ID": f"synthetic-poi-{index % 2}",
                                    "VISIT_AREA_TYPE_CD": str(index % 2 + 1),
                                    "SGG_CD": "area-a" if index % 2 == 0 else "area-b",
                                    "DGSTFN": "1" if index < 10 else "2",
                                    "REVISIT_INTENTION": "2" if index < 10 else "3",
                                    "RCMDTN_INTENTION": "3" if index < 10 else "4",
                                }
                            )
                    sources.append(Source(region, role, folder, (travel,), (visits,)))
            events = collect_events(sources)
            self.assertEqual(len(events[("west", "TL")]), 20)
            self.assertEqual(events[("west", "TL")][0].popularity, "5-9")
            self.assertNotIn("synthetic-trip-", repr(events))
            self.assertNotIn("synthetic-poi-", repr(events))
            distributions = context_poi_distributions(events)
            self.assertTrue(distributions)
            self.assertNotIn("purpose", repr(distributions))
            self.assertNotIn("area-a", repr(distributions))
            feedback_tables = feedback_cross_distributions(events)
            self.assertTrue(feedback_tables)
            self.assertNotIn("area-a", repr(feedback_tables))
            self.assertNotIn("code_1", repr(feedback_tables))
            rows = ablation_rows(events)
            self.assertEqual(len(rows), 5 * 3 * 4)
            self.assertEqual(
                {row["ablation"] for row in rows},
                {"popularity_only", "context_only", "poi_only", "context_plus_poi"},
            )
            west_rows = [row for row in rows if row["region"] == "west"]
            self.assertEqual(len(west_rows), 3 * 4)
            self.assertTrue(all(row["status"] == "observed" for row in west_rows))

    def test_original_shell_preflight_confirmation_is_required_before_input_access(self) -> None:
        error = StringIO()
        with redirect_stderr(error):
            with self.assertRaises(SystemExit) as raised:
                main([
                    "--raw-root", "/not-read", "--input", "capital:TL=/not-read",
                    "--output", "results/experiments/context-poi-signal/synthetic",
                    "--run-id", "synthetic",
                ])
        self.assertEqual(raised.exception.code, 2)
        self.assertIn("original-shell preflight", error.getvalue())

    def test_required_headers_fail_and_optional_columns_are_explicit(self) -> None:
        with TemporaryDirectory(prefix="context-poi-header-check-") as temporary:
            folder = Path(temporary)
            travel = folder / "TN_TRAVEL.csv"
            visits = folder / "TN_VISIT_AREA_INFO.csv"
            travel.write_text("TRAVEL_MISSION,TRAVEL_START_YMD\n1,2023-01-01\n", encoding="utf-8")
            visits.write_text("TRAVEL_ID\nsynthetic-trip\n", encoding="utf-8")
            source = Source("west", "TL", folder, (travel,), (visits,))
            with self.assertRaisesRegex(SafeInputError, "required ID or join column"):
                validate_headers([source])

            travel.write_text("TRAVEL_ID\nsynthetic-trip\n", encoding="utf-8")
            availability = validate_headers([source])
            travel_columns = {
                row["column"]: row["status"]
                for row in availability
                if row["table"] == "TN_TRAVEL"
            }
            self.assertEqual(travel_columns["TRAVEL_MISSION"], "missing")
            self.assertEqual(travel_columns["TRAVEL_START_YMD"], "missing")
            visit_columns = {
                row["column"]: row["status"]
                for row in availability
                if row["table"] == "TN_VISIT_AREA_INFO"
            }
            self.assertEqual(visit_columns["POI_ID"], "missing")
            self.assertEqual(visit_columns["DGSTFN"], "missing")

            partially_available = frozenset({
                "POI_ID", "VISIT_AREA_TYPE_CD", *FEEDBACK_FIELDS,
            })
            synthetic_event = Visit(
                "west", "TL", ("purpose", "month_01"), ("west", "area", "type"),
                "1", {field: "1" for field in FEEDBACK_FIELDS}, partially_available,
            )
            ablations = ablation_rows({
                ("west", "TL"): [synthetic_event],
                ("west", "VL"): [synthetic_event],
            })
            west_poi = [
                row for row in ablations
                if row["region"] == "west" and row["outcome"] == "DGSTFN"
                and row["ablation"] == "poi_only"
            ]
            self.assertEqual(len(west_poi), 1)
            self.assertEqual(west_poi[0]["status"], "unavailable_missing_column")
            context_ablation = [
                row for row in ablations
                if row["region"] == "west" and row["outcome"] == "DGSTFN"
                and row["ablation"] == "context_only"
            ]
            self.assertEqual(context_ablation[0]["status"], "unavailable_missing_column")
            context_assoc = association_rows({("west", "TL"): [synthetic_event]})
            mission_rows = [
                row for row in context_assoc
                if row["region"] == "west" and row["context_feature"] == "TRAVEL_MISSION"
            ]
            self.assertTrue(mission_rows)
            self.assertTrue(all(
                row["status"] == "unavailable_missing_column" for row in mission_rows
            ))

    def test_trip_overlap_error_only_contains_safe_count_bucket(self) -> None:
        with TemporaryDirectory(prefix="context-poi-overlap-") as temporary:
            root = Path(temporary)
            sources: list[Source] = []
            for region in REGIONS:
                for role in ("TL", "VL"):
                    folder = root / region / role
                    folder.mkdir(parents=True)
                    trip = "synthetic-shared-id" if region == "west" else f"{region}-{role}"
                    travel = folder / "TN_TRAVEL.csv"
                    visits = folder / "TN_VISIT_AREA_INFO.csv"
                    travel.write_text(
                        "TRAVEL_ID,TRAVEL_MISSION,TRAVEL_START_YMD\n"
                        f"{trip},1,2023-01-01\n", encoding="utf-8",
                    )
                    visits.write_text("TRAVEL_ID\n", encoding="utf-8")
                    sources.append(Source(region, role, folder, (travel,), (visits,)))
            validate_headers(sources)
            with self.assertRaises(SafeInputError) as raised:
                validate_trip_overlap(sources)
            message = str(raised.exception)
            self.assertIn("region west", message)
            self.assertIn("count bucket=<10", message)
            self.assertNotIn("synthetic-shared-id", message)
            self.assertNotIn(temporary, message)

    def test_join_quality_fails_with_bucketed_integrity_counts(self) -> None:
        with TemporaryDirectory(prefix="context-poi-join-quality-") as temporary:
            folder = Path(temporary)
            travel = folder / "TN_TRAVEL.csv"
            visits = folder / "TN_VISIT_AREA_INFO.csv"
            travel.write_text(
                "TRAVEL_ID,TRAVEL_MISSION,TRAVEL_START_YMD\n"
                "shared-trip,1,2023-01-01\n"
                "shared-trip,2,2023-01-01\n"
                "missing-context,,2023-02-01\n"
                ",1,2023-03-01\n",
                encoding="utf-8",
            )
            visits.write_text(
                "TRAVEL_ID\nshared-trip\nmissing-context\nunknown-trip\n\n",
                encoding="utf-8",
            )
            source = Source("west", "TL", folder, (travel,), (visits,))
            validate_headers([source])
            with self.assertRaises(SafeInputError) as raised:
                validate_join_quality([source])
            message = str(raised.exception)
            for bucket in (
                "missing_trip_ids=<10",
                "missing_trip_contexts=<10",
                "ambiguous_trip_contexts=<10",
                "unjoinable_visits=<10",
            ):
                self.assertIn(bucket, message)
            for identifier in ("shared-trip", "missing-context", "unknown-trip"):
                self.assertNotIn(identifier, message)
            self.assertNotIn(temporary, message)

    def test_resolver_matches_popularity_evaluator_role_folder_contract(self) -> None:
        with TemporaryDirectory(prefix="context-poi-source-map-") as temporary:
            raw_root = Path(temporary)
            specs: list[tuple[str, str, Path]] = []
            for region in REGIONS:
                for role in ("TL", "VL"):
                    if region == "capital":
                        base = raw_root / "2023-travel-log-capital"
                        folder = base / "extracted" / f"filekey-synthetic-{role.lower()}" if role == "TL" else base / f"filekey-synthetic-{role.lower()}"
                    else:
                        folder = raw_root / f"2023-travel-log-{region}" / f"{role}_csv"
                    folder.mkdir(parents=True)
                    (folder / "TN_TRAVEL.csv").write_text(
                        "TRAVEL_ID,TRAVEL_MISSION,TRAVEL_START_YMD\n", encoding="utf-8"
                    )
                    (folder / "TN_VISIT_AREA_INFO.csv").write_text(
                        "TRAVEL_ID\n", encoding="utf-8"
                    )
                    specs.append((region, role, folder))
            with self.assertRaisesRegex(ValueError, "TL/VL role-folder contract"):
                resolve_sources(specs, raw_root)
            resolved = resolve_sources(specs, raw_root, True)
            self.assertEqual(len(resolved), 8)

            wrong_root = raw_root / "wrong-2023-source" / "TL_csv"
            wrong_root.mkdir(parents=True)
            (wrong_root / "TN_TRAVEL.csv").write_text(
                "TRAVEL_ID,TRAVEL_MISSION,TRAVEL_START_YMD\n", encoding="utf-8"
            )
            (wrong_root / "TN_VISIT_AREA_INFO.csv").write_text("TRAVEL_ID\n", encoding="utf-8")
            bad_specs = [
                (region, role, wrong_root if region == "west" and role == "TL" else path)
                for region, role, path in specs
            ]
            self.assertEqual(len(resolve_sources(bad_specs, raw_root, True)), 8)

            wrong_role = raw_root / "other-folder"
            wrong_role.mkdir()
            (wrong_role / "TN_TRAVEL.csv").write_text(
                "TRAVEL_ID,TRAVEL_MISSION,TRAVEL_START_YMD\n", encoding="utf-8"
            )
            (wrong_role / "TN_VISIT_AREA_INFO.csv").write_text("TRAVEL_ID\n", encoding="utf-8")
            wrong_role_specs = [
                (region, role, wrong_role if region == "west" and role == "TL" else path)
                for region, role, path in specs
            ]
            with self.assertRaisesRegex(ValueError, "TL/VL role-folder contract"):
                resolve_sources(wrong_role_specs, raw_root, True)

            duplicate_root = (
                raw_root / "2023-travel-log-west" / "2023-travel-log-west" / "TL_csv"
            )
            duplicate_root.mkdir(parents=True)
            (duplicate_root / "TN_TRAVEL.csv").write_text(
                "TRAVEL_ID,TRAVEL_MISSION,TRAVEL_START_YMD\n", encoding="utf-8"
            )
            (duplicate_root / "TN_VISIT_AREA_INFO.csv").write_text(
                "TRAVEL_ID\n", encoding="utf-8"
            )
            nested_specs = [
                (region, role, duplicate_root if region == "west" and role == "TL" else path)
                for region, role, path in specs
            ]
            self.assertEqual(len(resolve_sources(nested_specs, raw_root, True)), 8)

            nested_capital_root = raw_root / "nested" / "2023-travel-log-capital"
            nested_capital_tl = nested_capital_root / "extracted" / "filekey-synthetic-tl"
            nested_capital_tl.mkdir(parents=True)
            (nested_capital_tl / "TN_TRAVEL.csv").write_text(
                "TRAVEL_ID,TRAVEL_MISSION,TRAVEL_START_YMD\n", encoding="utf-8"
            )
            (nested_capital_tl / "TN_VISIT_AREA_INFO.csv").write_text(
                "TRAVEL_ID\n", encoding="utf-8"
            )
            nested_capital_specs = [
                (region, role, nested_capital_tl if region == "capital" and role == "TL" else path)
                for region, role, path in specs
            ]
            self.assertEqual(len(resolve_sources(nested_capital_specs, raw_root, True)), 8)

    def test_synthetic_cli_keeps_outputs_aggregate_and_inside_ignored_results(self) -> None:
        RESULTS_ROOT.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix="context-poi-cli-input-") as raw_temp, TemporaryDirectory(
            prefix="context-poi-cli-output-", dir=RESULTS_ROOT
        ) as output_temp:
            raw_root = Path(raw_temp)
            args = [
                "--raw-root", str(raw_root),
                "--output", str(Path(output_temp) / "run"),
                "--run-id", "synthetic-run",
            ]
            for region in REGIONS:
                for role in ("TL", "VL"):
                    if region == "capital":
                        base = raw_root / "2023-travel-log-capital"
                        folder = (
                            base / "extracted" / "filekey-synthetic-tl"
                            if role == "TL"
                            else base / "filekey-synthetic-vl"
                        )
                    else:
                        folder = raw_root / f"2023-travel-log-{region}" / f"{role}_csv"
                    folder.mkdir(parents=True)
                    if region == "west" and role == "TL":
                        travel_csv = "TRAVEL_ID\nsynthetic-trip-TL\n"
                    else:
                        travel_csv = (
                            "TRAVEL_ID,TRAVEL_MISSION,TRAVEL_START_YMD\n"
                            f"synthetic-trip-{role},1,2023-01-01\n"
                        )
                    (folder / "TN_TRAVEL.csv").write_text(travel_csv, encoding="utf-8")
                    (folder / "TN_VISIT_AREA_INFO.csv").write_text(
                        "TRAVEL_ID,POI_ID,SGG_CD,VISIT_AREA_TYPE_CD,DGSTFN,"
                        "REVISIT_INTENTION,RCMDTN_INTENTION\n"
                        f"synthetic-trip-{role},synthetic-poi,synthetic-area,1,1,2,3\n",
                        encoding="utf-8",
                    )
                    args.extend(("--input", f"{region}:{role}={folder}"))
            args.extend(
                (
                    "--confirm-approved", "--confirm-terms",
                    "--confirm-user-shell-preflight", "--confirm-poi-candidate",
                    "--allow-approved-capital-filekey-folders",
                )
            )
            with redirect_stdout(StringIO()):
                self.assertEqual(main(args), 0)
            output = Path(output_temp) / "run"
            self.assertEqual(
                {path.name for path in output.iterdir()},
                {
                    "associations.csv", "context_poi_distributions.csv",
                    "column_availability.csv",
                    "feedback_distributions.csv", "feedback_cross_distributions.csv",
                    "feedback_context_poi_distributions.csv",
                    "feedback_associations.csv",
                    "feedback_ablations.csv", "run_metadata.json",
                },
            )
            artifact_text = "".join(path.read_text(encoding="utf-8") for path in output.iterdir())
            self.assertNotIn("synthetic-trip", artifact_text)
            self.assertNotIn("synthetic-poi", artifact_text)
            self.assertNotIn("synthetic-area", artifact_text)
            self.assertNotIn("filekey-synthetic-tl", artifact_text)
            self.assertNotIn("filekey-synthetic-vl", artifact_text)
            self.assertNotIn(str(raw_root), artifact_text)
            with (output / "column_availability.csv").open(encoding="utf-8", newline="") as stream:
                availability = list(csv.DictReader(stream))
            self.assertTrue(any(
                row["region"] == "west" and row["source_role"] == "TL"
                and row["table"] == "TN_TRAVEL" and row["column"] == "TRAVEL_MISSION"
                and row["status"] == "missing"
                for row in availability
            ))
            with (output / "feedback_ablations.csv").open(encoding="utf-8", newline="") as stream:
                ablation_results = list(csv.DictReader(stream))
            self.assertTrue(any(
                row["region"] == "west" and row["outcome"] == "DGSTFN"
                and row["ablation"] == "context_only"
                and row["status"] == "unavailable_missing_column"
                for row in ablation_results
            ))


if __name__ == "__main__":
    unittest.main()
