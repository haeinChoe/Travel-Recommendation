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
    profile = {
        "run": {"min_cell_count": 10, "options": {}},
        "tables": [{"table": alias, "format": fmt} for alias, fmt, _ in profile_tables],
        "categorical_values": [
            {"table": alias, "column": column}
            for alias, _, columns in profile_tables
            for column in columns
        ],
        "anomalies": [{"flag": "codebook_check_not_run_no_codebook_provided"}],
    }
    (output / "profile.json").write_text(json.dumps(profile), encoding="utf-8")
    (output / "run_metadata.json").write_text(
        json.dumps({"min_cell_count": 10, "options": {"codebook_provided": False}}),
        encoding="utf-8",
    )
    return input_root, codebook_root, output, profile


class CodebookOnlyTests(unittest.TestCase):
    def run_synthetic(self, column: str, value: str) -> tuple[dict, dict, str]:
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
            artifact = (output / "codebook_check.csv").read_text(encoding="utf-8")
            self.assertEqual(profile["tables"], result["tables"])
            return result, metadata, artifact

    def test_documented_single_code_is_valid_and_bucketed(self) -> None:
        profile, metadata, artifact = self.run_synthetic("ACTIVITY_TYPE_CD", "1")
        row = profile["codebook_check"][0]
        self.assertEqual(row["status"], "valid")
        self.assertEqual(row["non_null_rows_bucket"], "10+")
        self.assertEqual(row["rows_outside_codebook_bucket"], "0")
        self.assertEqual(row["allowed_value_count_bucket"], "<10")
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

    def test_complex_field_remains_unresolved_even_for_exact_code(self) -> None:
        profile, _, _ = self.run_synthetic("TRAVEL_MISSION", "1")
        self.assertEqual(profile["codebook_check"][0]["status"], "unresolved_candidate")

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
