"""Synthetic checks for focused codebook refreshes of existing profiles."""

from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

EDA_DIR = Path(__file__).resolve().parents[1] / "scripts" / "eda"
sys.path.insert(0, str(EDA_DIR))

from build_travel_log_codebook import build_spec  # noqa: E402
from profile_travel_log import RESULTS_ROOT, main  # noqa: E402
from validate_travel_log_code_domains import (  # noqa: E402
    GROUPS,
    MAPPING,
    allowed,
    mapped_csv_aliases,
)


def write_csv(path: Path, columns: list[str], rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(columns)
        writer.writerows(rows)


def make_fixture(base: Path) -> tuple[Path, Path, Path, dict]:
    region_root = base / "2023-travel-log-west"
    input_root = region_root / "eda-csv-extracted"
    other = input_root / "Other"
    tl_root = input_root / "TL_csv"
    codebook_root = tl_root
    output = base / "profile"
    output.mkdir(parents=True, exist_ok=True)

    # These first two tabular files occupied aliases before the mapped TL tables.
    write_csv(other / "a.csv", ["OTHER_VALUE"], [["fixture"]])
    (other / "b.json").write_text('{"fixture": true}\n', encoding="utf-8")
    write_csv(codebook_root / "TC_CODEA.csv", ["CD_A"], [[group] for group in sorted(GROUPS)])
    code_rows = [
        [group, value]
        for table_fields in MAPPING.values()
        for group, ranges in table_fields.values()
        for value in sorted(allowed(ranges))
    ]
    # Keep the synthetic code table valid even where several fields share a group.
    write_csv(codebook_root / "TC_CODEB.csv", ["CD_A", "CD_B"], code_rows)

    activity_fields = list(MAPPING["TN_ACTIVITY_HIS"])
    travel_fields = list(MAPPING["TN_TRAVEL"])
    activity_rows = [["1", "1", "1"] for _ in range(10)]
    travel_rows = [["1", "1"] for _ in range(10)]
    write_csv(tl_root / "TN_ACTIVITY_HIS_G.csv", activity_fields, activity_rows)
    write_csv(tl_root / "TN_TRAVEL_G.csv", travel_fields, travel_rows)

    # If traversal enters either photo directory, parsing this fake CSV would fail.
    for photo_role in ("TS_photo", "VS_photo"):
        photo = tl_root / photo_role
        photo.mkdir(parents=True)
        (photo / "TN_ACTIVITY_HIS_G.csv").write_bytes(b"not a readable CSV\x00")

    profile_tables = [
        ("table_000001.csv", "csv", ["OTHER_VALUE"]),
        ("table_000002.json", "json", []),
        ("table_000003.csv", "csv", ["CD_A"]),
        ("table_000004.csv", "csv", ["CD_A", "CD_B"]),
        ("table_000005.csv", "csv", activity_fields),
        ("table_000006.csv", "csv", travel_fields),
    ]
    legacy_sections = {
        "files_inventory": [{
            "path": "table_000001.csv", "size_bytes": 987654321,
            "sha256": "LEGACY_HASH_SENTINEL",
        }, {
            "path": "table_000002.json", "size_bytes": 987654321.5,
            "sha256": "LEGACY_FLOAT_SIZE_SENTINEL",
        }],
        "photo_summary": [{
            "ext": ".jpg", "count": 23, "total_bytes": 987654321,
            "min_bytes": 123456789, "median_bytes": 234567890, "max_bytes": 987654321,
        }],
        "other_files_summary": [{"ext": ".csv", "count": 23, "total_bytes": 987654321}],
        "tables": [
            {"table": alias, "format": fmt, "rows": 23, "columns": 3,
             "duplicate_rows": 2, "size_bytes": 987654321}
            for alias, fmt, _ in profile_tables
        ],
        "columns": [{
            "table": "table_000005.csv", "column": "ACTIVITY_TYPE_CD", "type": "VARCHAR",
            "non_null": 23, "null_count": 2, "null_rate": 0.086956,
            "distinct": 12, "min_len": 1, "avg_len": 4.25, "max_len": 12,
        }],
        "numeric_summary": [{
            "table": "table_000005.csv", "column": "ACTIVITY_TYPE_CD",
            "finite_count": 23, "negative_count": 2, "zero_count": 0,
        }],
        "categorical_values": [
            {"table": alias, "column": field, "value": "LEGACY_VALUE_SENTINEL", "count": 23}
            for alias, _, fields in profile_tables
            for field in fields
        ],
        "date_months": [{
            "table": "table_000005.csv", "column": "DATE_SENTINEL", "month": "2023-03",
            "rows": 13, "min_month": "2023-03", "max_month": "2023-12", "invalid_rows": 2,
        }],
        "relations": [{
            "left_distinct": 23, "right_distinct": 22, "shared_distinct": 8,
            "left_rows_without_match": 2, "right_rows_without_match": 0,
            "left_containment": 0.123456, "right_containment": 0.876543,
        }],
        "codebook_check": [{
            "table": "table_000005.csv", "column": "ACTIVITY_TYPE_CD", "status": "mismatch",
            "allowed_value_count": 12, "non_null_rows": 23,
            "rows_outside_codebook": 2, "distinct_outside_codebook": 1,
        }],
        "json_structure": [{
            "table": "table_000002.json", "top_level_len": 23,
            "value_types": '{"object": 23}', "element_types": '{"dict": 4, "str": 19}',
            "element_key_count_distribution": '{"1": 8, "2": 15}',
        }],
        "anomalies": [
            {"table": "table_000005.csv", "flag": "synthetic", "count": "12/23"},
            {"table": "*", "flag": "codebook_check_not_run_no_codebook_provided", "count": 0},
            {"table": "table_000005.csv", "flag": "fractional_count_fixture", "count": 23.5},
        ],
    }
    profile = {
        "run": {"min_cell_count": 10, "options": {}},
        **legacy_sections,
    }
    (output / "profile.json").write_text(json.dumps(profile), encoding="utf-8")
    (output / "run_metadata.json").write_text(
        json.dumps({"min_cell_count": 10, "options": {"codebook_provided": False}}),
        encoding="utf-8",
    )
    for name, records in legacy_sections.items():
        csv_path = output / f"{name}.csv"
        if records:
            with csv_path.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(records[0]))
                writer.writeheader()
                writer.writerows(records)
        else:
            csv_path.write_text("\n", encoding="utf-8")
    return input_root, codebook_root, output, profile


class CodebookOnlyTests(unittest.TestCase):
    def run_synthetic(self, column: str, value: str) -> tuple[dict, dict, dict[str, str]]:
        with tempfile.TemporaryDirectory(prefix="codebook-only-test-", dir=RESULTS_ROOT) as name:
            base = Path(name)
            raw_root = base / "raw"
            region_root = raw_root / "2023-travel-log-west"
            input_root, _, output, profile = make_fixture(region_root)
            spec = base / "allowlist.json"
            alias = "table_000005.csv" if column == "ACTIVITY_TYPE_CD" else "table_000006.csv"
            group = "ACT" if column == "ACTIVITY_TYPE_CD" else "MIS"
            spec.write_text(
                json.dumps({
                    "source": "Synthetic test fixture",
                    "tables": {alias: {column: ["1", "2"]}},
                    "unresolved_fields": {},
                    "column_groups": {alias: {column: group}},
                    "group_validation": {group: "valid"},
                }),
                encoding="utf-8",
            )
            # Override only the selected synthetic column while retaining a valid schema.
            table = "TN_ACTIVITY_HIS_G.csv" if column == "ACTIVITY_TYPE_CD" else "TN_TRAVEL_G.csv"
            source = input_root / "TL_csv" / table
            table_key = "TN_ACTIVITY_HIS" if column == "ACTIVITY_TYPE_CD" else "TN_TRAVEL"
            fields = list(MAPPING[table_key])
            rows = [[value] + ["1"] * (len(fields) - 1) for _ in range(10)]
            write_csv(source, fields, rows)
            code = main([
                "--raw-root", str(raw_root), "--input", str(input_root), "--output", str(output),
                "--codebook-only", "--codebook", str(spec), "--confirm-approved", "--confirm-terms",
            ])
            self.assertEqual(code, 0)
            result = json.loads((output / "profile.json").read_text(encoding="utf-8"))
            metadata = json.loads((output / "run_metadata.json").read_text(encoding="utf-8"))
            artifacts = {
                path.name: path.read_text(encoding="utf-8")
                for path in output.glob("*.csv")
            }
            self.assertEqual(
                [(row["table"], row["format"]) for row in profile["tables"]],
                [(row["table"], row["format"]) for row in result["tables"]],
            )
            return result, metadata, artifacts

    def test_documented_single_code_is_valid_and_bucketed(self) -> None:
        profile, metadata, artifacts = self.run_synthetic("ACTIVITY_TYPE_CD", "1")
        row = profile["codebook_check"][0]
        self.assertEqual(row["status"], "valid")
        self.assertEqual(row["non_null_rows_bucket"], "10+")
        self.assertEqual(row["rows_outside_codebook_bucket"], "0")
        self.assertEqual(row["allowed_value_count_bucket"], "<10")
        self.assertTrue(metadata["options"]["codebook_provided"])
        self.assertTrue(metadata["codebook_source_recorded"])
        self.assertNotIn(",10,", artifacts["codebook_check.csv"])

    def test_compound_unresolved_value_is_not_split_or_emitted(self) -> None:
        profile, _, artifacts = self.run_synthetic("TRAVEL_MISSION", "1;2")
        row = profile["codebook_check"][0]
        self.assertEqual(row["status"], "unresolved_candidate")
        self.assertEqual(row.get("rows_outside_codebook_bucket"), "10+", row)
        self.assertNotIn("1;2", artifacts["codebook_check.csv"])
        self.assertNotIn("1;2", json.dumps(profile))

    def test_complex_field_remains_unresolved_even_for_exact_code(self) -> None:
        profile, _, _ = self.run_synthetic("TRAVEL_MISSION", "1")
        self.assertEqual(profile["codebook_check"][0]["status"], "unresolved_candidate")

    def test_legacy_profile_sections_and_csvs_are_resanitized(self) -> None:
        profile, _, artifacts = self.run_synthetic("ACTIVITY_TYPE_CD", "1")
        serialized = json.dumps(profile, ensure_ascii=False, sort_keys=True)
        csv_serialized = "\n".join(artifacts.values())
        self.assertEqual(profile["tables"][4]["rows"], "10+")
        self.assertEqual(profile["tables"][4]["size_bytes"], "100MiB+")
        self.assertEqual(profile["columns"][0]["null_count"], "<10")
        self.assertEqual(profile["columns"][0]["null_rate"], "<10/suppressed")
        self.assertEqual(profile["numeric_summary"][0]["finite_count"], "<10")
        self.assertEqual(profile["other_files_summary"][0]["count"], "10+")
        self.assertEqual(profile["other_files_summary"][0]["total_bytes"], "100MiB+")
        self.assertEqual(profile["photo_summary"][0]["count"], "10+")
        self.assertEqual(profile["photo_summary"][0]["total_bytes"], "100MiB+")
        self.assertEqual(profile["categorical_values"][0]["value"], "category_001")
        self.assertEqual(profile["categorical_values"][0]["count"], "10+")
        self.assertEqual(profile["relations"][0]["shared_distinct"], "<10")
        self.assertEqual(profile["relations"][0]["left_containment"], "<10/suppressed")
        self.assertEqual(profile["date_months"][0]["month"], "period_001")
        self.assertEqual(profile["anomalies"][0]["count"], "10+/10+")
        self.assertEqual(profile["anomalies"][1]["count"], "suppressed")
        self.assertEqual(profile["json_structure"][0]["top_level_len"], "<10")
        self.assertNotIn("987654321", serialized + csv_serialized)
        self.assertNotIn("987654321.5", serialized + csv_serialized)
        self.assertNotIn("0.086956", serialized + csv_serialized)
        self.assertNotIn("0.123456", serialized + csv_serialized)
        self.assertNotIn("2023-03", serialized + csv_serialized)
        self.assertNotIn("LEGACY_VALUE_SENTINEL", serialized + csv_serialized)
        self.assertNotIn("LEGACY_HASH_SENTINEL", serialized + csv_serialized)
        self.assertNotIn("LEGACY_FLOAT_SIZE_SENTINEL", serialized + csv_serialized)
        self.assertNotIn("codebook_check_not_run_no_codebook_provided", csv_serialized)
        self.assertIn("10+", artifacts["tables.csv"])
        self.assertIn("<10/suppressed", artifacts["relations.csv"])
        self.assertIn("100MiB+", artifacts["files_inventory.csv"])
        self.assertIn("100MiB+", artifacts["photo_summary.csv"])
        self.assertIn("category_001", artifacts["categorical_values.csv"])
        for section in (
            "files_inventory", "photo_summary", "other_files_summary", "tables", "columns",
            "numeric_summary", "categorical_values", "date_months", "relations",
            "codebook_check", "json_structure", "anomalies",
        ):
            self.assertEqual(
                artifacts[f"{section}.csv"],
                pd.DataFrame(profile[section]).to_csv(index=False),
            )

    def test_mismatched_recorded_threshold_fails_before_input_scan(self) -> None:
        with tempfile.TemporaryDirectory(prefix="codebook-threshold-test-", dir=RESULTS_ROOT) as name:
            base = Path(name)
            raw_root = base / "raw"
            region_root = raw_root / "2023-travel-log-west"
            input_root, _, output, profile = make_fixture(region_root)
            spec = base / "allowlist.json"
            spec.write_text(json.dumps({
                "source": "Synthetic test fixture",
                "tables": {"table_000005.csv": {"ACTIVITY_TYPE_CD": ["1"]}},
                "unresolved_fields": {},
                "column_groups": {"table_000005.csv": {"ACTIVITY_TYPE_CD": "ACT"}},
                "group_validation": {"ACT": "valid"},
            }), encoding="utf-8")
            profile["run"]["min_cell_count"] = 20
            profile_path = output / "profile.json"
            profile_path.write_text(json.dumps(profile), encoding="utf-8")
            # If validation reached the selected input, DuckDB would fail on this fixture.
            source = input_root / "TL_csv" / "TN_ACTIVITY_HIS_G.csv"
            source.write_bytes(b"\x00 invalid synthetic CSV")
            before = {
                path.name: path.read_bytes()
                for path in output.iterdir()
                if path.is_file()
            }

            with self.assertRaisesRegex(SystemExit, "privacy threshold"):
                main([
                    "--raw-root", str(raw_root), "--input", str(input_root),
                    "--output", str(output), "--codebook-only", "--codebook", str(spec),
                    "--confirm-approved", "--confirm-terms",
                ])

            after = {
                path.name: path.read_bytes()
                for path in output.iterdir()
                if path.is_file()
            }
            self.assertEqual(before, after)

    def test_builder_preserves_historical_alias_positions_and_prunes_photo_dirs(self) -> None:
        with tempfile.TemporaryDirectory(prefix="codebook-builder-test-") as name:
            base = Path(name)
            input_root, codebook_root, output, profile = make_fixture(base)
            aliases = mapped_csv_aliases(input_root, profile)
            self.assertEqual(aliases["table_000005.csv"].name, "TN_ACTIVITY_HIS_G.csv")
            self.assertEqual(aliases["table_000006.csv"].name, "TN_TRAVEL_G.csv")
            spec = build_spec(input_root, "west", codebook_root, profile)
        self.assertIn("table_000005.csv", spec["tables"])
        self.assertIn("1", spec["tables"]["table_000005.csv"]["ACTIVITY_TYPE_CD"])
        self.assertNotIn("table_000001.csv", spec["tables"])
        self.assertNotIn("table_000002.csv", spec["tables"])
        self.assertNotIn("table_000003.csv", spec["tables"])
        self.assertNotIn("table_000004.csv", spec["tables"])
        self.assertIn("TRAVEL_MISSION", spec["unresolved_fields"]["table_000006.csv"])
        self.assertEqual(spec["group_validation"]["ACT"], "valid")


if __name__ == "__main__":
    unittest.main()
