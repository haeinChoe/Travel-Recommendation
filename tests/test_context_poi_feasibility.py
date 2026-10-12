"""Synthetic-only safety and analysis checks for Issue #45."""

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

import analyze_context_poi as analysis  # noqa: E402


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


class ContextPoiSyntheticTests(unittest.TestCase):
    def test_association_statistics_and_support_states(self) -> None:
        observed = analysis._association(
            "synthetic", "visit-row", "association", "context", "poi",
            [("a", "x")] * 12 + [("b", "y")] * 12,
        )
        self.assertEqual(observed["status"], "observed")
        self.assertGreater(float(observed["cramers_v"]), 0.99)
        self.assertEqual(
            analysis._association("synthetic", "visit-row", "association", "x", "y",
                                  [("a", "x")] * 5 + [("b", "y")] * 4)["status"],
            "privacy-limited",
        )
        self.assertEqual(
            analysis._association("synthetic", "visit-row", "association", "x", "y",
                                  [("a", "x")] * 12)["status"],
            "insufficient-support",
        )

    def test_trip_pair_sensitivity_uses_trip_identity_and_buckets_missing_ids(self) -> None:
        rows = [
            {"region": "west", "role": "TL", "trip_id": "trip-a", "traveler_id": "owner-a", "x": "c", "y": "p"},
            {"region": "west", "role": "TL", "trip_id": "trip-a", "traveler_id": "owner-b", "x": "c", "y": "p"},
            {"region": "west", "role": "TL", "trip_id": None, "traveler_id": "owner-c", "x": "c", "y": "p"},
        ]
        pairs, excluded = analysis._distinct_trip_pairs(rows, lambda row: row["x"], lambda row: row["y"])
        self.assertEqual(pairs, [("c", "p")])
        self.assertEqual(excluded, "<10")

    def test_feedback_audit_buckets_missing_cardinality_and_out_of_range_values(self) -> None:
        audit = analysis._feedback_audit(
            "west:TL", "DGSTFN", ["1", "2", "opaque-invalid-feedback", None, "  "]
        )
        self.assertEqual(audit["rows"], "<10")
        self.assertEqual(audit["nonmissing"], "<10")
        self.assertEqual(audit["cardinality"], "<10")
        self.assertEqual(audit["outside_documented_range"], "<10")
        self.assertEqual(audit["outside_range_cardinality"], "<10")
        self.assertNotIn("opaque-invalid-feedback", repr(audit))

    def test_poi_join_coverage_includes_visits_without_trip_match(self) -> None:
        with TemporaryDirectory(prefix="context-poi-trip-link-") as temp:
            root = Path(temp)
            role_root = root / "TL_csv"
            poi_root = root / "Other"
            write_csv(role_root / "tn_travel_west.csv", ["TRAVEL_ID", "TRAVELER_ID"],
                      [{"TRAVEL_ID": "private-trip", "TRAVELER_ID": "private-traveler"}])
            visits = [{"TRAVEL_ID": f"unmatched-{i}", "POI_ID": "private-poi"} for i in range(12)]
            visits.append({"TRAVEL_ID": "private-trip", "POI_ID": "private-poi"})
            write_csv(role_root / "tn_visit_area_info_west.csv", ["TRAVEL_ID", "POI_ID"], visits)
            write_csv(poi_root / "tn_poi_master.csv", ["POI_ID"], [{"POI_ID": "private-poi"}])
            loaded = analysis._load_split(analysis.InputSpec("west", "TL", role_root), poi_root)
            audits = {row["field"]: row for row in loaded.audit}
            poi_join = audits["POI_ID exact candidate join"]
            trip_join = audits["TRAVEL_ID candidate join"]
            self.assertEqual(poi_join["visit_nonblank_poi_rows"], "10+")
            self.assertEqual(poi_join["matched_visit_rows"], "10+")
            self.assertEqual(poi_join["coverage"], "90-100%")
            self.assertEqual(trip_join["nonmissing"], "<10")
            self.assertEqual(len(loaded.observations), 1)

    def test_post_event_targets_and_identifiers_are_never_features(self) -> None:
        row = {
            "region": "west", "poi_id": "private-item-marker", "visit_area_type": "opaque-type",
            "visit_sgg": "opaque-sgg", "master_sgg": None, "poi_l1": "opaque-category",
            "poi_l2": None, "poi_l3": None, "context": {"TRAVEL_STYL_1": "opaque-style",
            "TRAVEL_MISSION": "opaque-mission", "TRAVEL_START_YMD": "2023-01-02",
            "TRAVEL_END_YMD": "2023-01-03"}, "month": "01", "elapsed_days": 1,
            "companion_relations": (), "feedback": {target: "5" for target in analysis.TARGETS},
            "popularity_band": "10+",
        }
        feature_sets = analysis._feature_sets(row)
        serialized_names = repr(feature_sets)
        self.assertNotIn("poi_id", serialized_names.casefold())
        self.assertNotIn("DGSTFN", serialized_names)
        self.assertNotIn("REVISIT_INTENTION", serialized_names)
        self.assertNotIn("RCMDTN_INTENTION", serialized_names)
        self.assertNotIn("TRAVEL_MISSION", serialized_names)
        self.assertNotIn("2023-01-02", serialized_names)
        self.assertIn("elapsed_days", feature_sets["context_only"])

    def test_cli_requires_approval_confirmations_before_paths_are_read(self) -> None:
        error = StringIO()
        with redirect_stderr(error), patch.object(analysis, "_load_split") as load_split:
            code = analysis.main(["--input", "west:TL=/synthetic/not-read"])
        self.assertEqual(code, 2)
        load_split.assert_not_called()
        self.assertIn("확인 옵션", error.getvalue())

    def test_synthetic_run_writes_only_safe_aggregates(self) -> None:
        with TemporaryDirectory(prefix="context-poi-synthetic-") as temp:
            base = Path(temp)
            raw_root = base / "raw"
            role_paths = {role: raw_root / "west-data" / f"{role}_csv" for role in ("TL", "VL")}
            poi_root = raw_root / "west-data" / "Other"
            for role, role_path in role_paths.items():
                trips = []
                travelers = []
                companions = []
                visits = []
                for i in range(24):
                    suffix = f"{role.lower()}-{i}"
                    trips.append({
                        "TRAVEL_ID": f"private-trip-{suffix}",
                        "TRAVELER_ID": "private-shared-traveler" if i == 0 else f"private-traveler-{suffix}",
                        "TRAVEL_MISSION": "unresolved-code",
                        "TRAVEL_START_YMD": f"2023-0{1 + (i % 2)}-01",
                        "TRAVEL_END_YMD": f"2023-0{1 + (i % 2)}-02",
                    })
                    travelers.append({
                        "TRAVELER_ID": "private-shared-traveler" if i == 0 else f"private-traveler-{suffix}",
                        "TRAVEL_STATUS_ACCOMPANY": f"opaque-companion-{i % 2}",
                        "TRAVEL_STATUS_DESTINATION": f"opaque-destination-{i % 2}",
                        "TRAVEL_COMPANIONS_NUM": str(i % 3),
                        "GENDER": f"opaque-demographic-{i % 2}",
                        "AGE_GRP": "opaque-age",
                        **{f"TRAVEL_STYL_{index}": f"opaque-style-{i % 2}" for index in range(1, 9)},
                        **{f"TRAVEL_MOTIVE_{index}": f"opaque-motive-{i % 2}" for index in range(1, 4)},
                    })
                    companions.append({
                        "TRAVEL_ID": f"private-trip-{suffix}", "REL_CD": f"opaque-relation-{i % 2}",
                        "COMPANION_GENDER": "opaque-gender", "COMPANION_AGE_GRP": "opaque-age",
                        "COMPANION_SITUATION": "opaque-situation",
                    })
                    visits.append({
                        "TRAVEL_ID": f"private-trip-{suffix}",
                        "POI_ID": f"private-poi-{i % 12}",
                        "VISIT_AREA_TYPE_CD": f"opaque-visit-type-{i % 2}",
                        "SGG_CD": f"opaque-visit-sgg-{i % 2}",
                        "DGSTFN": "opaque-invalid-feedback" if i == 0 else str(1 + (i % 2)),
                        "REVISIT_INTENTION": str(2 + (i % 2)),
                        "RCMDTN_INTENTION": str(3 + (i % 2)),
                    })
                write_csv(role_path / "tn_travel_west.csv", list(trips[0]), trips)
                write_csv(role_path / "tn_traveller_master_west.csv", list(travelers[0]), travelers)
                write_csv(role_path / "tn_companion_info_west.csv", list(companions[0]), companions)
                write_csv(role_path / "tn_visit_area_info_west.csv", list(visits[0]), visits)
            poi_rows = [{
                "POI_ID": f"private-poi-{i}", "SGG_CD": f"opaque-master-sgg-{i % 2}",
                "ASORT_LCLASDC": f"opaque-category-{i % 2}",
                "ASORT_MLSFCDC": f"opaque-subcategory-{i % 3}",
                "ASORT_SDASDC": f"opaque-subcategory-{i % 4}",
            } for i in range(12)]
            write_csv(poi_root / "tn_poi_master_POIMaster.csv", list(poi_rows[0]), poi_rows)
            out_root = base / "results"
            args = [
                "--raw-root", str(raw_root),
                "--input", f"west:TL={role_paths['TL']}",
                "--input", f"west:VL={role_paths['VL']}",
                "--poi-master", f"west={poi_root}", "--run-id", "synthetic-check",
                "--confirm-approved", "--confirm-terms", "--confirm-poi-candidate",
            ]
            with patch.object(analysis, "RESULTS_ROOT", out_root), redirect_stdout(StringIO()):
                self.assertEqual(analysis.main(args), 0)
            output = out_root / "synthetic-check"
            metadata = json.loads((output / "run_metadata.json").read_text(encoding="utf-8"))
            audit = (output / "availability_audit.csv").read_text(encoding="utf-8")
            with (output / "availability_audit.csv").open(encoding="utf-8") as audit_file:
                audit_rows = list(csv.DictReader(audit_file))
            associations = (output / "associations.csv").read_text(encoding="utf-8")
            predictive = (output / "predictive_ablation.csv").read_text(encoding="utf-8")
            joined = audit + associations + predictive + json.dumps(metadata)
            for forbidden in (
                "private-trip-", "private-traveler-", "private-poi-", "opaque-style-",
                "opaque-category-", "opaque-demographic-", str(raw_root), str(poi_root),
            ):
                self.assertNotIn(forbidden, joined)
            self.assertEqual(metadata["protocol"]["discovery"], "TL")
            self.assertEqual(metadata["protocol"]["replication"], "VL")
            overlap = metadata["protocol"]["tl_vl_overlap_diagnostics"]["per_region"]["west"]
            self.assertEqual(overlap["traveler_overlap_count"], "<10")
            self.assertEqual(overlap["candidate_item_overlap_rate"], "90-100%")
            self.assertEqual(overlap["vl_item_cold_start_rate"], "0-<10%")
            self.assertFalse(metadata["privacy"]["raw_identifiers_written"])
            self.assertIn("joint_context_poi_to_feedback", associations)
            self.assertIn("context_plus_richer_poi", predictive)
            self.assertIn("candidate_metadata_coverage", audit)
            self.assertIn("outside_documented_range", audit)
            self.assertIn("outside_range_cardinality", audit)
            for scope in ("west:TL", "west:VL"):
                for target in analysis.TARGETS:
                    target_rows = [row for row in audit_rows if row["scope"] == scope and row["field"] == target]
                    self.assertEqual(len(target_rows), 1, (scope, target))
                    self.assertNotEqual(target_rows[0]["outside_documented_range"], "")
                    self.assertNotEqual(target_rows[0]["outside_range_cardinality"], "")
            self.assertIn("missing_trip_id_exclusions", associations)
            self.assertIn("observed", predictive)
            self.assertNotIn("2023-01-02", joined)
            self.assertNotIn("opaque-invalid-feedback", joined)
            self.assertEqual(len(list(output.iterdir())), 4)

    def test_overlapping_trip_ids_between_tl_and_vl_fail_safely(self) -> None:
        with TemporaryDirectory(prefix="context-poi-overlap-") as temp:
            base = Path(temp)
            raw_root = base / "raw"
            roles = {role: raw_root / "west-data" / f"{role}_csv" for role in ("TL", "VL")}
            for role, root in roles.items():
                rows = [{"TRAVEL_ID": "private-overlap", "TRAVELER_ID": f"private-owner-{role}"}]
                write_csv(root / "tn_travel_west.csv", list(rows[0]), rows)
                write_csv(root / "tn_visit_area_info_west.csv",
                          ["TRAVEL_ID", "POI_ID", "VISIT_AREA_TYPE_CD"],
                          [{"TRAVEL_ID": "private-overlap", "POI_ID": "private-item", "VISIT_AREA_TYPE_CD": "x"}])
                write_csv(root / "tn_traveller_master_west.csv", ["TRAVELER_ID"], [])
            poi_root = raw_root / "west-data" / "Other"
            write_csv(poi_root / "tn_poi_master.csv", ["POI_ID"], [])
            out_root = base / "results"
            args = ["--raw-root", str(raw_root), "--input", f"west:TL={roles['TL']}",
                    "--input", f"west:VL={roles['VL']}", "--poi-master", f"west={poi_root}",
                    "--run-id", "overlap-check",
                    "--confirm-approved", "--confirm-terms", "--confirm-poi-candidate"]
            error = StringIO()
            with patch.object(analysis, "RESULTS_ROOT", out_root), redirect_stderr(error):
                self.assertEqual(analysis.main(args), 2)
            self.assertIn("ValueError", error.getvalue())
            self.assertNotIn("private-overlap", error.getvalue())
            self.assertFalse((out_root / "overlap-check").exists())


if __name__ == "__main__":
    unittest.main()
