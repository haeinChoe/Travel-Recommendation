from __future__ import annotations

import tempfile
import unittest
import csv
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from scripts.recommendation import run_catboost_tl_smoke as runner
from scripts.recommendation.canonical_admin_location import build_admin_lookup

from scripts.recommendation.run_catboost_tl_smoke import (
    SafeFailure,
    iter_projected_csv,
    iter_projected_values,
    read_projected_csv,
)


class ProjectedCsvTests(unittest.TestCase):
    def test_codebook_normalizes_only_padded_district_rows(self):
        base = {"SGG_CD1": "41", "SGG_CD2": "110", "SIDO_NM": "경기", "SGG_NM": "수원시"}
        rows = [{**base, "SGG_CD": code} for code in ("41110", "4111000000", "4111012345", "4211000000")]
        normalized = runner._normalize_admin_codebook_rows(rows)
        self.assertEqual([row["SGG_CD"] for row in normalized], ["41110", "41110"])
        self.assertEqual(set(build_admin_lookup(normalized)), {"41110"})
        with self.assertRaises(ValueError):
            build_admin_lookup(normalized + [{**normalized[0], "SGG_NM": "conflict"}])

    def test_probe_assembles_core_only_labels_and_i3_with_full_catalog(self):
        def write_table(root, name, columns, rows):
            with (root / name).open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=columns)
                writer.writeheader()
                writer.writerows(rows)

        captured = {}
        class Ranker:
            def predict(self, frame):
                return frame["train_positive_interaction_count"].to_numpy()
        def fit(train, **kwargs):
            captured["train"] = train
            captured["materialization"] = kwargs["inner_train_materialization"]
            return Ranker()

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tl = root / "TL_csv"
            other = root / "Other"
            tl.mkdir(); other.mkdir()
            trips = [f"trip-{i:03}" for i in range(40)]
            travelers = []
            travels = []
            visits = []
            for i, trip in enumerate(trips):
                travelers.append({**dict.fromkeys(runner.TRAVELER_COLUMNS, ""), "TRAVELER_ID": f"traveler-{i}"})
                travels.append({"TRAVEL_ID": trip, "TRAVELER_ID": f"traveler-{i}", "TRAVEL_START_YMD": "2023-01-01", "TRAVEL_END_YMD": "2023-01-02"})
                for item, kind in (("core", "1"), ("noncore", "21")):
                    visits.append({"TRAVEL_ID": trip, "VISIT_AREA_ID": f"{trip}-{item}", "POI_ID": item, "VISIT_AREA_TYPE_CD": kind, "SGG_CD": "4111000000"})
            write_table(tl, "tn_travel_fixture.csv", runner.TRAVEL_COLUMNS, travels)
            write_table(tl, "tn_traveller_master.csv", runner.TRAVELER_COLUMNS, travelers)
            write_table(tl, "tn_visit_area_info.csv", runner.VISIT_COLUMNS, visits)
            write_table(tl, "tc_sgg.csv", runner.SGG_COLUMNS, [{"SGG_CD": "4111000000", "SGG_CD1": "41", "SGG_CD2": "110", "SIDO_NM": "경기", "SGG_NM": "수원시"}])
            write_table(other, "tn_poi_master.csv", runner.MASTER_COLUMNS, [
                {**dict.fromkeys(runner.MASTER_COLUMNS, ""), "POI_ID": item, "SGG_CD": "4111000000"}
                for item in ("core", "noncore", "unseen", "duplicate", "duplicate")
            ])
            with patch.object(runner, "_bound_inputs", return_value=(root, tl, other)), patch.object(runner, "fit_catboost", side_effect=fit), patch.object(runner, "_available_bytes", return_value=32 * 1024**3), redirect_stdout(StringIO()):
                result = runner.run("west", "probe")
        train = captured["train"]
        self.assertEqual(set(train.loc[train.label == 1, "item_id"]), {"core"})
        items = {row["item_id"]: row for row in captured["materialization"].item_features}
        self.assertEqual(items["noncore"]["train_positive_interaction_count"], 0)
        self.assertEqual(result["candidate_items"], 3)
        self.assertEqual(result["metrics"]["recall@5"], 1.0)
        self.assertLessEqual(result["train_queries"], runner.PROBE_TRAIN_TRIPS)
        self.assertEqual(result["iterations"], runner.PROBE_ITERATIONS)

    def test_reads_only_selected_columns_and_preserves_row_values(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.csv"
            source.write_text("ID,POI_ID,PRIVATE_TEXT\na,p1,unused\nb,p2,unused\n", encoding="utf-8")
            rows = read_projected_csv(source, {"ID", "POI_ID"}, {"POI_ID"})
        self.assertEqual(rows, [{"POI_ID": "p1"}, {"POI_ID": "p2"}])

    def test_tuple_reader_matches_projected_dict_reader(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.csv"
            source.write_text("ID,POI_ID\na,p1\nb,p2\n", encoding="utf-8")
            expected = read_projected_csv(source, {"ID", "POI_ID"}, {"ID", "POI_ID"})
            actual = list(iter_projected_values(source, {"ID", "POI_ID"}, ("ID", "POI_ID")))
        self.assertEqual(actual, [tuple(row[name] for name in ("ID", "POI_ID")) for row in expected])

    def test_streaming_reader_rejects_malformed_row_width(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.csv"
            source.write_text("ID,POI_ID\na,p1,extra\n", encoding="utf-8")
            with self.assertRaises(SafeFailure):
                list(iter_projected_csv(source, {"ID", "POI_ID"}, {"POI_ID"}))

    def test_rejects_duplicate_or_missing_required_columns(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.csv"
            source.write_text("ID,ID\na,b\n", encoding="utf-8")
            with self.assertRaises(SafeFailure):
                read_projected_csv(source, {"ID"}, {"ID"})
            source.write_text("ID,POI_ID\na,p1\n", encoding="utf-8")
            with self.assertRaises(SafeFailure):
                read_projected_csv(source, {"TRAVEL_ID"}, {"POI_ID"})


if __name__ == "__main__":
    unittest.main()
