"""Synthetic ZIP-only coverage for privacy-safe travel-log archive metadata."""

from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

EDA_DIR = Path(__file__).resolve().parents[1] / "scripts" / "eda"
sys.path.insert(0, str(EDA_DIR))

from inspect_travel_log_archives import (  # noqa: E402
    RESULTS_ROOT,
    ArchiveBlocked,
    checked_infos,
    main,
    safe_member_name,
)


class TravelLogArchiveMetadataTests(unittest.TestCase):
    def test_sbl_json_archive_serializes_structure_but_not_keys_values_or_names(self) -> None:
        RESULTS_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="synthetic-sbl-archive-") as temp:
            raw_root = Path(temp) / "raw"
            raw_root.mkdir()
            region_root = raw_root / "2023-travel-log-west"
            region_root.mkdir()
            archive_path = region_root / "private-sbl-name.zip"
            with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for index in range(12):
                    archive.writestr(
                        f"private-json-path-{index}/private-member-{index}.json",
                        json.dumps(
                            {
                                "PRIVATE_KEY_SENTINEL": f"PRIVATE_VALUE_SENTINEL_{index}",
                                "kind": "synthetic",
                            }
                        ),
                    )
            with tempfile.TemporaryDirectory(
                prefix="synthetic-archive-output-", dir=RESULTS_ROOT
            ) as parent:
                output = Path(parent) / "result"
                relative_output = output.relative_to(Path.cwd())
                code = main(
                    [
                        "--raw-root", str(raw_root),
                        "--region", "west",
                        "--archive", f"SbL={archive_path}",
                        "--output", str(relative_output),
                        "--confirm-approved",
                        "--confirm-terms",
                    ]
                )
                self.assertEqual(code, 0)
                csv_path = output / "archive_metadata.csv"
                metadata_path = output / "run_metadata.json"
                serialized = csv_path.read_text(encoding="utf-8") + metadata_path.read_text(
                    encoding="utf-8"
                )
                self.assertIn("json_root_type", serialized)
                self.assertIn("json_top_level_key_count_band", serialized)
                self.assertIn("10+", serialized)
                for sentinel in (
                    "PRIVATE_KEY_SENTINEL",
                    "PRIVATE_VALUE_SENTINEL",
                    "private-json-path",
                    "private-member",
                    "private-sbl-name",
                ):
                    self.assertNotIn(sentinel, serialized)
                with csv_path.open(encoding="utf-8", newline="") as stream:
                    rows = list(csv.DictReader(stream))
                self.assertTrue(rows)
                self.assertTrue(all(row["region"] == "west" for row in rows))

    def test_archive_path_and_symlink_members_are_rejected(self) -> None:
        with self.assertRaises(ArchiveBlocked):
            safe_member_name("../private.json")
        with self.assertRaises(ArchiveBlocked):
            safe_member_name("/absolute/private.json")
        with tempfile.TemporaryDirectory(prefix="synthetic-zip-symlink-") as temp:
            archive_path = Path(temp) / "symlink.zip"
            link = zipfile.ZipInfo("safe-looking-member.json")
            link.create_system = 3
            link.external_attr = (0o120777 << 16)
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr(link, "{}")
            with zipfile.ZipFile(archive_path) as archive:
                with self.assertRaises(ArchiveBlocked):
                    checked_infos(archive, 1)

    def test_cli_rejects_archive_outside_raw_root_without_disclosing_path(self) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-archive-guard-") as temp:
            base = Path(temp)
            raw_root = base / "raw"
            raw_root.mkdir()
            outside = base / "private-archive.zip"
            with zipfile.ZipFile(outside, "w") as archive:
                archive.writestr("synthetic.json", b'{"synthetic": true}')
            RESULTS_ROOT.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(
                prefix="synthetic-archive-output-", dir=RESULTS_ROOT
            ) as parent:
                output = Path(parent) / "result"
                code = main(
                    [
                        "--raw-root", str(raw_root),
                        "--region", "west",
                        "--archive", f"SbL={outside}",
                        "--output", str(output),
                        "--confirm-approved",
                        "--confirm-terms",
                    ]
                )
                self.assertEqual(code, 2)
                self.assertFalse(output.exists())

    def test_cli_rejects_archive_from_another_region(self) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-region-archive-guard-") as temp:
            raw_root = Path(temp) / "raw"
            west_root = raw_root / "2023-travel-log-west"
            east_root = raw_root / "2023-travel-log-east"
            west_root.mkdir(parents=True)
            east_root.mkdir()
            east_archive = east_root / "synthetic-sbl.zip"
            with zipfile.ZipFile(east_archive, "w") as archive:
                archive.writestr("synthetic.json", b'{"synthetic": true}')
            RESULTS_ROOT.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(
                prefix="synthetic-archive-output-", dir=RESULTS_ROOT
            ) as parent:
                output = Path(parent) / "result"
                code = main(
                    [
                        "--raw-root", str(raw_root),
                        "--region", "west",
                        "--archive", f"SbL={east_archive}",
                        "--output", str(output),
                        "--confirm-approved",
                        "--confirm-terms",
                    ]
                )
                self.assertEqual(code, 2)
                self.assertFalse(output.exists())

    def test_cli_rejects_photo_archive_roles(self) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-photo-role-") as temp:
            root = Path(temp)
            raw_root = root / "raw"
            raw_root.mkdir()
            archive = raw_root / "synthetic.zip"
            with zipfile.ZipFile(archive, "w") as stream:
                stream.writestr("synthetic.json", b"{}")
            with self.assertRaises(SystemExit):
                main(
                    [
                        "--raw-root", str(raw_root),
                        "--region", "west",
                        "--archive", f"TS_photo={archive}",
                        "--output", "results/eda/travel-log-2023/smoke-photo-role",
                        "--confirm-approved",
                        "--confirm-terms",
                    ]
                )


if __name__ == "__main__":
    unittest.main()
