"""Synthetic-only checks for recommendation-fit aggregates and k=10 suppression."""

from __future__ import annotations

import csv
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import duckdb

EDA_DIR = Path(__file__).resolve().parents[1] / "scripts" / "eda"
sys.path.insert(0, str(EDA_DIR))

from analyze_recommendation_fit import (  # noqa: E402
    RESULTS_ROOT,
    Source,
    compute_scope,
    count_bucket,
    main,
    normalized_union_sql,
    overlap_rows,
    pooled_scope_prefix,
    rate_band,
    safe_distribution,
    scalar,
    write_rows,
)


class RecommendationFitSyntheticTests(unittest.TestCase):
    def test_poi_candidate_acknowledgement_is_required_before_input_access(self) -> None:
        error = StringIO()
        with redirect_stderr(error):
            code = main(
                [
                    "--input",
                    "capital:TL=/not-read",
                    "--confirm-approved",
                    "--confirm-terms",
                ]
            )
        self.assertEqual(code, 2)
        self.assertIn("후보 분석", error.getvalue())

    def test_cli_rejects_same_resolved_root_for_distinct_split_labels(self) -> None:
        RESULTS_ROOT.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix="recommendation-fit-duplicate-root-") as raw_temp:
            raw_root = Path(raw_temp)
            shared = raw_root / "shared"
            shared.mkdir()
            with TemporaryDirectory(
                prefix="recommendation-fit-duplicate-out-", dir=RESULTS_ROOT
            ) as out_temp:
                error = StringIO()
                args = [
                    "--raw-root", str(raw_root),
                    "--input", f"capital:TL={shared}",
                    "--input", f"capital:VL={shared / '..' / shared.name}",
                    "--output", str(Path(out_temp) / "result"),
                    "--confirm-approved", "--confirm-terms", "--confirm-poi-candidate",
                ]
                with (
                    patch("analyze_recommendation_fit.csv_files") as scan_files,
                    redirect_stderr(error),
                    redirect_stdout(StringIO()),
                ):
                    code = main(args)
                scan_files.assert_not_called()
        self.assertEqual(code, 2)
        self.assertIn("분석 실패: ValueError", error.getvalue())

    def test_four_region_pool_isolation_and_missing_overlap_statuses(self) -> None:
        con = duckdb.connect(":memory:")
        regions = sorted({"capital", "west", "east", "jeju-islands"})
        tl_sources = []
        vl_sources = []
        for index, region in enumerate(regions):
            trip_rows = ",".join(
                f"('synthetic-traveler-{i}', 'synthetic-trip-{i}')" for i in range(3)
            )
            con.execute(
                f"CREATE TEMP VIEW travel_{index} AS SELECT * FROM (VALUES {trip_rows}) "
                "AS t(TRAVELER_ID, TRAVEL_ID)"
            )
            poi_visit_rows = ",".join(
                f"('synthetic-trip-{i}', 'synthetic-area-{i}', 'synthetic-poi-{i}')"
                for i in range(3)
            )
            con.execute(
                f"CREATE TEMP VIEW visits_tl_{index} AS SELECT * FROM (VALUES {poi_visit_rows}) "
                "AS v(TRAVEL_ID, VISIT_AREA_ID, POI_ID)"
            )
            con.execute(
                f"CREATE TEMP VIEW visits_vl_{index} AS SELECT * FROM (VALUES {poi_visit_rows}) "
                "AS v(TRAVEL_ID, VISIT_AREA_ID, POI_ID)"
            )
            tl_sources.append(
                Source(
                    region, "TL", Path("/synthetic/raw"),
                    f"travel_{index}", f"visits_tl_{index}",
                )
            )
            vl_visit_view = f"visits_vl_{index}"
            if region == "jeju-islands":
                con.execute(
                    f"CREATE TEMP VIEW visits_vl_missing_poi_{index} AS "
                    f"SELECT TRAVEL_ID, VISIT_AREA_ID FROM visits_vl_{index}"
                )
                vl_visit_view = f"visits_vl_missing_poi_{index}"
            vl_sources.append(
                Source(region, "VL", Path("/synthetic/raw"), None, vl_visit_view)
            )

        prefix = pooled_scope_prefix(regions)
        self.assertEqual(prefix, "integrated")
        pooled_rows = compute_scope(con, f"{prefix}:TL", tl_sources)
        metrics = {row["metric"]: row for row in pooled_rows}
        self.assertEqual(metrics["unique_trips"]["count"], "10+")
        self.assertEqual(metrics["unique_travelers"]["count"], "10+")
        self.assertEqual(metrics["unique_visit_areas"]["count"], "10+")
        self.assertEqual(metrics["unique_pois"]["count"], "10+")
        self.assertEqual(pooled_scope_prefix(["capital", "west"]), "selected[capital+west]")

        overlap = overlap_rows(con, prefix, tl_sources, vl_sources)
        overlap_status = {row["metric"]: row["status"] for row in overlap}
        for metric in (
            "tl_unique_pois",
            "vl_unique_pois",
            "tl_vl_poi_overlap",
            "vl_cold_start_pois",
            "vl_cold_start_poi_share",
        ):
            self.assertEqual(
                overlap_status[metric], "unavailable_missing_or_incomplete_POI_ID"
            )
        missing_visit_sources = [
            Source(source.region, "VL", source.root, None, None) for source in vl_sources
        ]
        missing_visit_overlap = overlap_rows(
            con, prefix, tl_sources, missing_visit_sources
        )
        missing_visit_status = {
            row["metric"]: row["status"] for row in missing_visit_overlap
        }
        for metric in (
            "tl_unique_pois",
            "vl_unique_pois",
            "tl_vl_poi_overlap",
            "vl_cold_start_pois",
            "vl_cold_start_poi_share",
        ):
            self.assertEqual(missing_visit_status[metric], "unavailable_visit_table_missing")
        self.assertNotIn("synthetic-poi-", repr(pooled_rows + overlap))
        con.close()

    def test_scalar_propagates_duckdb_errors(self) -> None:
        con = duckdb.connect(":memory:")
        with self.assertRaises(duckdb.CatalogException):
            scalar(con, "SELECT * FROM synthetic_missing_view")
        con.close()

    def test_overwrite_stages_both_artifacts_before_replacing(self) -> None:
        RESULTS_ROOT.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix="recommendation-fit-atomic-", dir=RESULTS_ROOT) as temp:
            output = Path(temp) / "ready"
            output.mkdir()
            csv_path = output / "recommendation_fit.csv"
            metadata_path = output / "run_metadata.json"
            csv_path.write_text("old aggregate", encoding="utf-8")
            metadata_path.write_text("old metadata", encoding="utf-8")
            with patch("analyze_recommendation_fit.json.dumps", side_effect=ValueError):
                with self.assertRaises(ValueError):
                    write_rows(output, [], {}, overwrite=True)
            self.assertEqual(csv_path.read_text(encoding="utf-8"), "old aggregate")
            self.assertEqual(metadata_path.read_text(encoding="utf-8"), "old metadata")

    def test_identifier_normalization_only_nulls_blank_values(self) -> None:
        con = duckdb.connect(":memory:")
        con.execute(
            "CREATE TEMP VIEW trips AS SELECT * FROM (VALUES "
            "('synthetic-trip', 'synthetic-traveler'), "
            "(' synthetic-trip ', 'synthetic-traveler'), "
            "('   ', 'synthetic-traveler'), (NULL, 'synthetic-traveler')) "
            "AS t(TRAVEL_ID, TRAVELER_ID)"
        )
        source = Source("west", "TL", Path("/synthetic/raw"), "trips", None)
        sql, fields = normalized_union_sql([source], con, "travel")
        self.assertIn("TRAVEL_ID", fields["west:TL:0"])
        con.execute(f"CREATE TEMP VIEW normalized AS {sql}")
        identifiers = {
            row[0] for row in con.execute("SELECT DISTINCT TRAVEL_ID FROM normalized").fetchall()
        }
        self.assertEqual(identifiers, {"synthetic-trip", " synthetic-trip ", None})
        con.close()

    def test_distribution_uses_complementary_suppression(self) -> None:
        self.assertEqual(
            safe_distribution([("small-a", 3), ("small-b", 4), ("large", 12)]),
            [("<suppressed>", 19)],
        )
        self.assertEqual(safe_distribution([("one-small-cell", 7)]), [])

    def test_public_counts_and_rates_are_bucketed(self) -> None:
        self.assertEqual(
            [count_bucket(n) for n in (0, 1, 9, 10, 100)],
            ["0", "<10", "<10", "10+", "10+"],
        )
        self.assertEqual(rate_band(0, 100), "0-<10%")
        self.assertEqual(rate_band(1, 100), "<10/suppressed")
        self.assertEqual(rate_band(10, 100), "10-<25%")
        self.assertEqual(rate_band(100, 100), "90-100%")
        self.assertEqual(rate_band(0, 0), "n/a")

    def test_scope_metrics_contain_no_identifier_values(self) -> None:
        con = duckdb.connect(":memory:")
        con.execute(
            "CREATE TEMP VIEW trips AS SELECT * FROM (VALUES "
            + ",".join(
                f"('synthetic-traveler-{i}', 'synthetic-trip-{i}')" for i in range(12)
            )
            + ") AS t(TRAVELER_ID, TRAVEL_ID)"
        )
        con.execute(
            "CREATE TEMP VIEW visits AS SELECT * FROM (VALUES "
            + ",".join(
                f"('synthetic-trip-{i}', 'area-{i}', 'poi-{i}', '4', '3', '5')"
                for i in range(12)
            )
            + ") AS v(TRAVEL_ID, VISIT_AREA_ID, POI_ID, DGSTFN, "
            "REVISIT_INTENTION, RCMDTN_INTENTION)"
        )
        source = Source("west", "TL", Path("/synthetic/raw"), "trips", "visits")

        rows = compute_scope(con, "west:TL", [source])
        values = {(row["metric"], row["category"]): row["count"] for row in rows}
        self.assertEqual(values[("unique_travelers", "total")], "10+")
        self.assertEqual(values[("unique_trips", "total")], "10+")
        self.assertEqual(values[("unique_visit_areas", "total")], "10+")
        self.assertEqual(values[("unique_pois", "total")], "10+")
        self.assertEqual(values[("visits_per_trip", "1")], "10+")
        self.assertEqual(values[("trips_per_traveler", "1")], "10+")
        self.assertTrue(all(row["count"] in {None, "0", "<10", "10+"} for row in rows))
        self.assertTrue(all(not isinstance(row["rate"], (int, float)) for row in rows))
        rendered = repr(rows)
        self.assertNotIn("synthetic-traveler-", rendered)
        self.assertNotIn("synthetic-trip-", rendered)
        self.assertNotIn("area-", rendered)
        self.assertNotIn("poi-", rendered)
        capital_rows = compute_scope(con, "capital:combined", [source], True)
        statuses = {row["metric"]: row["status"] for row in capital_rows}
        self.assertEqual(
            statuses["unique_trips"],
            "unavailable_existing_capital_observation_not_recomputed",
        )
        self.assertEqual(
            statuses["unique_travelers"],
            "unavailable_existing_capital_observation_not_recomputed",
        )
        capital_tl_rows = compute_scope(con, "capital:TL", [source])
        capital_tl = {row["metric"]: row for row in capital_tl_rows}
        self.assertEqual(capital_tl["unique_trips"]["count"], "10+")
        self.assertEqual(capital_tl["unique_travelers"]["count"], "10+")
        con.close()

    def test_requested_metrics_are_explicitly_unavailable_when_inputs_are_missing(self) -> None:
        con = duckdb.connect(":memory:")
        con.execute(
            "CREATE TEMP VIEW trips AS SELECT * FROM (VALUES "
            + ",".join(
                f"('synthetic-traveler-{i}', 'synthetic-trip-{i}')" for i in range(12)
            )
            + ") AS t(TRAVELER_ID, TRAVEL_ID)"
        )
        no_visits = Source("east", "TL", Path("/synthetic/raw"), "trips", None)
        no_visit_rows = compute_scope(con, "east:TL", [no_visits])
        no_visit_status = {row["metric"]: row["status"] for row in no_visit_rows}
        for metric in (
            "visits_per_trip",
            "trips_per_traveler",
            "visits_per_traveler",
            "visitors_per_poi",
            "poi_visit_frequency",
            "single_visit_pois",
            "DGSTFN_distribution",
            "REVISIT_INTENTION_distribution",
            "RCMDTN_INTENTION_distribution",
        ):
            self.assertEqual(no_visit_status[metric], "unavailable_visit_table_missing")

        con.execute(
            "CREATE TEMP VIEW visits_without_poi AS SELECT * FROM (VALUES "
            + ",".join(
                f"('synthetic-trip-{i}', 'synthetic-area-{i}')" for i in range(12)
            )
            + ") AS v(TRAVEL_ID, VISIT_AREA_ID)"
        )
        no_poi = Source(
            "east", "VL", Path("/synthetic/raw"), "trips", "visits_without_poi"
        )
        no_poi_rows = compute_scope(con, "east:VL", [no_poi])
        no_poi_status = {row["metric"]: row["status"] for row in no_poi_rows}
        self.assertEqual(
            no_poi_status["poi_visit_frequency"], "unavailable_missing_or_incomplete_POI_ID"
        )
        self.assertEqual(
            no_poi_status["single_visit_pois"], "unavailable_missing_or_incomplete_POI_ID"
        )
        self.assertEqual(
            no_poi_status["visitors_per_poi"], "unavailable_missing_or_incomplete_POI_ID"
        )
        missing_traveler_link = Source(
            "east", "VL", Path("/synthetic/raw"), None, "visits_without_poi"
        )
        missing_link_rows = compute_scope(con, "east:VL", [missing_traveler_link])
        missing_link_status = {row["metric"]: row["status"] for row in missing_link_rows}
        self.assertEqual(
            missing_link_status["ambiguous_trip_traveler_mappings"],
            "unavailable_trip_traveler_link_missing",
        )
        con.close()

    def test_capital_only_cli_writes_aggregates_for_synthetic_csvs(self) -> None:
        RESULTS_ROOT.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix="recommendation-fit-raw-") as raw_temp:
            raw_root = Path(raw_temp)
            tl_root = raw_root / "capital" / "TL"
            vl_root = raw_root / "capital" / "VL"
            tl_root.mkdir(parents=True)
            vl_root.mkdir(parents=True)
            for split_root, prefix in ((tl_root, "tl"), (vl_root, "vl")):
                with (split_root / "TN_TRAVEL_synthetic.csv").open(
                    "w", newline="", encoding="utf-8"
                ) as stream:
                    writer = csv.writer(stream)
                    writer.writerow(("TRAVEL_ID", "TRAVELER_ID"))
                    for i in range(12):
                        writer.writerow((f"{prefix}-trip-{i}", f"{prefix}-traveler-{i}"))
                with (split_root / "TN_VISIT_AREA_INFO_synthetic.csv").open(
                    "w", newline="", encoding="utf-8"
                ) as stream:
                    writer = csv.writer(stream)
                    writer.writerow(
                        (
                            "TRAVEL_ID",
                            "VISIT_AREA_ID",
                            "POI_ID",
                            "DGSTFN",
                            "REVISIT_INTENTION",
                            "RCMDTN_INTENTION",
                        )
                    )
                    for i in range(12):
                        writer.writerow(
                            (f"{prefix}-trip-{i}", f"area-{i}", f"poi-{i}", 4, 3, 5)
                        )

            with TemporaryDirectory(prefix="recommendation-fit-out-", dir=RESULTS_ROOT) as out_temp:
                output = Path(out_temp) / "readiness-capital"
                stdout = StringIO()
                stderr = StringIO()
                args = [
                    "--raw-root",
                    str(raw_root),
                    "--input",
                    f"capital:TL={tl_root}",
                    "--input",
                    f"capital:VL={vl_root}",
                    "--output",
                    str(output),
                    "--confirm-approved",
                    "--confirm-terms",
                    "--confirm-poi-candidate",
                ]
                with redirect_stderr(stderr), redirect_stdout(stdout):
                    exit_code = main(args)
                self.assertEqual(exit_code, 0, stderr.getvalue())
                self.assertTrue((output / "recommendation_fit.csv").is_file())
                aggregate = (output / "recommendation_fit.csv").read_text(encoding="utf-8")
                metadata = (output / "run_metadata.json").read_text(encoding="utf-8")
                self.assertIn("capital:TL", aggregate)
                self.assertIn("poi_id_vs_visit_area_id", aggregate)
                self.assertNotIn("tl-traveler-", aggregate)
                self.assertNotIn("tl-trip-", aggregate)
                self.assertNotIn("poi-", aggregate)
                for artifact in (aggregate, metadata):
                    self.assertNotIn("tl-traveler-", artifact)
                    self.assertNotIn("tl-trip-", artifact)
                    self.assertNotIn("area-", artifact)
                    self.assertNotIn("vl-traveler-", artifact)
                    self.assertNotIn("vl-trip-", artifact)
                    self.assertNotIn("poi-", artifact)
                public_rows = list(csv.DictReader(aggregate.splitlines()))
                self.assertTrue(
                    all(row["count"] in {"", "0", "<10", "10+"} for row in public_rows)
                )
                self.assertTrue(
                    all(
                        not row["rate"]
                        or row["rate"]
                        in {
                            "n/a",
                            "0-<10%",
                            "<10/suppressed",
                            "<10%",
                            "10-<25%",
                            "25-<50%",
                            "50-<75%",
                            "75-<90%",
                            "90-100%",
                        }
                        for row in public_rows
                    )
                )
                self.assertNotRegex(aggregate, r"(?<![A-Za-z_])\d+\.\d+")


if __name__ == "__main__":
    unittest.main()
