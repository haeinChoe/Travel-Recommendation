"""Synthetic-only checks for public EDA aggregate serialization."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

EDA_DIR = Path(__file__).resolve().parents[1] / "scripts" / "eda"
sys.path.insert(0, str(EDA_DIR))

from compare_regions import build_frames, count_bucket, sum_count_buckets  # noqa: E402
from profile_travel_log import (  # noqa: E402
    public_run_metadata,
    serialized_type,
    suppress_small_aggregate_cells,
)


class ProfilePrivacyBucketTests(unittest.TestCase):
    def test_nested_json_type_names_are_sanitized_but_csv_types_are_preserved(self) -> None:
        dynamic_type = 'STRUCT("PRIVATE_MEMBER_SENTINEL" VARCHAR, nested MAP(VARCHAR, BIGINT))'
        self.assertEqual(serialized_type(dynamic_type, "json"), "NESTED")
        self.assertEqual(serialized_type(dynamic_type, "csv"), dynamic_type)

    def test_profile_sections_publish_only_buckets_and_generalized_categories(self) -> None:
        sections = {
            "files_inventory": [
                {
                    "path": "table_000001.csv",
                    "size_bytes": 2_000_000,
                    "sha256": "secret-fingerprint",
                }
            ],
            "tables": [
                {"table": "table_000001.csv", "rows": 23, "columns": 4, "duplicate_rows": 0}
            ],
            "columns": [
                {
                    "table": "table_000001.csv", "column": "synthetic-column", "type": "VARCHAR",
                    "non_null": 21, "null_count": 2, "distinct": 13, "null_rate": 2 / 23,
                    "min_len": 1, "avg_len": 4.2, "max_len": 120,
                }
            ],
            "categorical_values": [
                {
                    "table": "table_000001.csv", "column": "synthetic-column",
                    "value": "PRIVATE_PLACE_SENTINEL", "count": 2,
                },
                {
                    "table": "table_000001.csv", "column": "synthetic-column",
                    "value": "PRIVATE_TEXT_SENTINEL", "count": 6,
                },
                {
                    "table": "table_000001.csv", "column": "synthetic-column",
                    "value": "another-private-value", "count": 13,
                },
                {
                    "table": "table_000001.csv", "column": "other-column",
                    "value": "OTHER_PRIVATE_SENTINEL", "count": 14,
                },
            ],
            "date_months": [
                {
                    "table": "table_000001.csv", "column": "synthetic-date",
                    "month": "2023-03", "rows": 13, "invalid_rows": 0,
                },
                {
                    "table": "table_000001.csv", "column": "synthetic-date",
                    "month": "__range__", "rows": None, "min_month": "2023-03",
                    "max_month": "2023-12", "invalid_rows": 0,
                },
            ],
            "relations": [
                {"left_distinct": 21, "right_distinct": 22, "shared_distinct": 20,
                 "left_rows_without_match": 1, "right_rows_without_match": 0,
                 "left_containment": 0.91, "right_containment": 0.95}
            ],
            "anomalies": [{"count": "12/23"}],
            "json_structure": [
                {
                    "top_level_len": 24,
                    "element_types": '{"dict": 19, "str": 5}',
                    "element_key_count_distribution": '{"1": 8, "2": 16}',
                }
            ],
        }

        suppress_small_aggregate_cells(sections, 10)
        serialized = json.dumps(sections, ensure_ascii=False, sort_keys=True)

        self.assertEqual(sections["tables"][0]["rows"], "10+")
        self.assertEqual(sections["tables"][0]["columns"], "<10")
        self.assertEqual(sections["columns"][0]["null_rate"], "<10/suppressed")
        self.assertEqual(sections["relations"][0]["left_containment"], "<10/suppressed")
        self.assertEqual(sections["anomalies"][0]["count"], "10+/10+")
        self.assertNotIn("sha256", sections["files_inventory"][0])
        self.assertEqual(sections["files_inventory"][0]["size_bytes"], "1-<10MiB")
        self.assertEqual(sections["date_months"][0]["month"], "period_001")
        self.assertEqual(sections["date_months"][1]["min_month"], "2020s")
        self.assertIn("category_001", serialized)
        element_types = json.loads(sections["json_structure"][0]["element_types"])
        self.assertEqual(element_types, {"dict": "<10", "str": "<10"})
        key_distribution = json.loads(
            sections["json_structure"][0]["element_key_count_distribution"]
        )
        self.assertEqual(key_distribution, {"1-9": "suppressed"})
        self.assertNotIn("PRIVATE_PLACE_SENTINEL", serialized)
        self.assertNotIn("PRIVATE_TEXT_SENTINEL", serialized)
        self.assertNotIn("OTHER_PRIVATE_SENTINEL", serialized)
        self.assertNotIn("another-private-value", serialized)
        self.assertNotIn("secret-fingerprint", serialized)
        self.assertNotIn("2023-03", serialized)
        self.assertNotIn("2023-12", serialized)

    def test_run_metadata_drops_source_and_temporary_paths(self) -> None:
        metadata = public_run_metadata(
            {
                "input": "/private/raw/source.csv",
                "codebook_source": "/private/codebook.hwp",
                "disk_free_bytes_results": 20_000_000,
                "duckdb_config": {
                    "temp_directory": "/private/results/tmp-12345",
                    "max_temp_directory_size": "200000MiB",
                },
            }
        )
        serialized = json.dumps(metadata, ensure_ascii=False, sort_keys=True)
        self.assertNotIn("/private/", serialized)
        self.assertNotIn("tmp-12345", serialized)
        self.assertNotIn("200000MiB", serialized)
        self.assertIn("100MiB+", serialized)


class ComparisonPrivacyBucketTests(unittest.TestCase):
    def test_comparison_frames_keep_count_and_rate_values_coarse(self) -> None:
        regions = {}
        for region in ("capital", "west", "east", "jeju-islands"):
            regions[region] = {
                "tables": [
                    {"table": "table_000001.csv", "status": "ok", "rows": 23, "columns": 3,
                     "duplicate_rows": 0, "names_suppressed": False, "size_bytes": 3_000_000}
                ],
                "columns": [
                    {"table": "table_000001.csv", "column": "synthetic-column", "type": "VARCHAR",
                     "null_count": 11, "null_rate": 11 / 23, "value_policy": "safe"}
                ],
                "photo_summary": [{"count": 3, "total_bytes": 2_000_000}],
                "date_months": [],
            }

        frames = build_frames(regions)
        serialized = "\n".join(frame.to_json(orient="records") for frame in frames.values())
        summary = frames["region_summary"]

        self.assertEqual(summary.loc[0, "total_rows"], "10+")
        self.assertNotIn("photo_files", summary.columns)
        self.assertNotIn("photo_size_band", summary.columns)
        self.assertNotIn("photo_files", serialized)
        self.assertNotIn("photo_size_band", serialized)
        self.assertIn("25-<50%", serialized)
        self.assertNotIn("23", serialized)
        self.assertNotIn("0.043", serialized)
        self.assertNotIn("2_000_000", serialized)
        self.assertNotIn("2000000", serialized)

    def test_invalid_exact_count_values_are_suppressed(self) -> None:
        self.assertEqual(count_bucket(9.5), "suppressed")
        self.assertEqual(count_bucket(-2), "suppressed")
        self.assertEqual(count_bucket(True), "suppressed")

    def test_suppressed_bucket_propagates_unless_10_plus_proves_lower_bound(self) -> None:
        self.assertEqual(sum_count_buckets(["<10", "suppressed"]), "suppressed")
        self.assertEqual(sum_count_buckets(["0", "suppressed"]), "suppressed")
        self.assertEqual(sum_count_buckets(["10+", "suppressed"]), "10+")


if __name__ == "__main__":
    unittest.main()
