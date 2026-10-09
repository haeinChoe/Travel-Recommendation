"""Synthetic checks for focused codebook refreshes of existing profiles."""

from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

EDA_DIR = Path(__file__).resolve().parents[1] / "scripts" / "eda"
sys.path.insert(0, str(EDA_DIR))

from build_travel_log_codebook import build_spec  # noqa: E402
from profile_travel_log import RESULTS_ROOT, main  # noqa: E402


class CodebookOnlyTests(unittest.TestCase):
    def run_synthetic(self, column: str, value: str) -> tuple[dict, dict, str]:
        with tempfile.TemporaryDirectory(prefix="codebook-only-test-", dir=RESULTS_ROOT) as name:
            base = Path(name)
            raw_root = base / "raw"
            input_root = raw_root / "dataset"
            output = base / "profile"
            input_root.mkdir(parents=True)
            output.mkdir()
            csv_path = input_root / "TN_SYNTHETIC_G.csv"
            with csv_path.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.writer(stream)
                writer.writerow([column, "SYNTHETIC_OTHER"])
                writer.writerows([[value, "fixture"] for _ in range(10)])
            spec = base / "allowlist.json"
            spec.write_text(
                json.dumps({
                    "source": "Synthetic test fixture",
                    "tables": {"table_000001.csv": {column: ["1", "2"]}},
                }),
                encoding="utf-8",
            )
            (output / "profile.json").write_text(
                json.dumps({
                    "run": {"min_cell_count": 10, "options": {}},
                    "tables": [{"kept": True}],
                    "anomalies": [{"flag": "codebook_check_not_run_no_codebook_provided"}],
                }),
                encoding="utf-8",
            )
            (output / "run_metadata.json").write_text(
                json.dumps({"min_cell_count": 10, "options": {"codebook_provided": False}}),
                encoding="utf-8",
            )
            code = main([
                "--raw-root", str(raw_root), "--input", str(input_root), "--output", str(output),
                "--codebook-only", "--codebook", str(spec), "--confirm-approved", "--confirm-terms",
            ])
            self.assertEqual(code, 0)
            profile = json.loads((output / "profile.json").read_text(encoding="utf-8"))
            metadata = json.loads((output / "run_metadata.json").read_text(encoding="utf-8"))
            artifact = (output / "codebook_check.csv").read_text(encoding="utf-8")
            return profile, metadata, artifact

    def test_documented_single_code_is_valid_and_bucketed(self) -> None:
        profile, metadata, artifact = self.run_synthetic("ACTIVITY_TYPE_CD", "1")
        row = profile["codebook_check"][0]
        self.assertEqual(row["status"], "valid")
        self.assertEqual(row["non_null_rows_bucket"], "10+")
        self.assertEqual(row["rows_outside_codebook_bucket"], "0")
        self.assertEqual(row["allowed_value_count_bucket"], "<10")
        self.assertEqual(profile["tables"], [{"kept": True}])
        self.assertTrue(metadata["options"]["codebook_provided"])
        self.assertTrue(metadata["codebook_source_recorded"])
        self.assertNotIn(",10,", artifact)

    def test_compound_unresolved_value_is_not_split_or_emitted(self) -> None:
        profile, _, artifact = self.run_synthetic("TRAVEL_MISSION", "1;2")
        row = profile["codebook_check"][0]
        self.assertEqual(row["status"], "unresolved_candidate")
        self.assertEqual(row.get("rows_outside_codebook_bucket"), "10+", row)
        self.assertNotIn("1;2", artifact)
        self.assertNotIn("1;2", json.dumps(profile))

    def test_complex_field_is_unresolved_even_when_exactly_allowed(self) -> None:
        profile, _, _ = self.run_synthetic("TRAVEL_MISSION", "1")
        self.assertEqual(profile["codebook_check"][0]["status"], "unresolved_candidate")

    def test_builder_uses_manual_ranges_and_separates_unresolved_fields(self) -> None:
        with tempfile.TemporaryDirectory(prefix="codebook-builder-test-") as name:
            base = Path(name)
            input_root = base / "2023-travel-log-west" / "input"
            codebook_root = base / "2023-travel-log-west" / "TL_csv"
            input_root.mkdir(parents=True)
            codebook_root.mkdir(parents=True)
            (input_root / "TN_ACTIVITY_HIS_G.csv").write_text(
                "ACTIVITY_TYPE_CD\n1\n", encoding="utf-8"
            )
            (input_root / "TN_TRAVEL_G.csv").write_text(
                "TRAVEL_MISSION\n1;2\n", encoding="utf-8"
            )
            (codebook_root / "TC_CODEA.csv").write_text(
                "CD_A\nACT\n", encoding="utf-8"
            )
            (codebook_root / "TC_CODEB.csv").write_text(
                "CD_A,CD_B\n" + "".join(
                    f"ACT,{value}\n" for value in [*map(str, range(1, 8)), "99"]
                ),
                encoding="utf-8",
            )
            spec = build_spec(input_root, "west", codebook_root)
        self.assertIn("table_000001.csv", spec["tables"])
        self.assertIn("1", spec["tables"]["table_000001.csv"]["ACTIVITY_TYPE_CD"])
        self.assertNotIn("table_000002.csv", spec["tables"])
        self.assertIn("TRAVEL_MISSION", spec["unresolved_fields"]["table_000002.csv"])
        self.assertEqual(spec["group_validation"]["ACT"], "valid")


if __name__ == "__main__":
    unittest.main()
