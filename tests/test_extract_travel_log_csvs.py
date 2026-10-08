"""Synthetic-only tests for the regional CSV ZIP extractor."""

from __future__ import annotations

import hashlib
import subprocess
import sys
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

SCRIPT = Path(__file__).parents[1] / "scripts" / "eda" / "extract_travel_log_csvs.py"


def make_zip(path: Path, members: list[tuple[str, bytes]]) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, content in members:
            archive.writestr(name, content)


def make_raw_root(parent: Path, region: str = "west") -> tuple[Path, Path]:
    raw = parent / "raw"
    raw.mkdir()
    region_root = raw / f"2023-travel-log-{region}"
    region_root.mkdir()
    return raw, region_root


def run_cli(
    raw_root: Path, archive: Path, output: Path, *extra: str, region: str = "west"
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--raw-root", str(raw_root),
            "--region", region,
            "--archive", f"TL_csv={archive}",
            "--output", str(output),
            "--confirm-approved",
            "--confirm-terms",
            *extra,
        ],
        check=False,
        capture_output=True,
        text=True,
    )


class ExtractTravelLogCsvsTests(unittest.TestCase):
    def test_extracts_capital_csv_archive_under_capital_root(self) -> None:
        with TemporaryDirectory() as temp:
            raw, region_root = make_raw_root(Path(temp), "capital")
            archive = region_root / "tables.zip"
            make_zip(archive, [("tables/synthetic.csv", b"a,b\n1,2\n")])
            output = region_root / "csv-output"
            result = run_cli(raw, archive, output, region="capital")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                (output / "TL_csv/tables/synthetic.csv").read_bytes(),
                b"a,b\n1,2\n",
            )

    def test_extracts_only_csv_and_preserves_role_subpaths(self) -> None:
        with TemporaryDirectory() as temp:
            raw, region_root = make_raw_root(Path(temp))
            archive = region_root / "bundle.zip"
            make_zip(
                archive,
                [
                    ("tables/nested/synthetic.csv", b"a,b\n1,2\n"),
                    ("photos/synthetic.jpg", b"not-an-image-payload"),
                    ("metadata/synthetic.json", b'{"synthetic": true}'),
                ],
            )
            before = hashlib.sha256(archive.read_bytes()).digest()
            output = region_root / "csv-output"
            result = run_cli(raw, archive, output)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                (output / "TL_csv/tables/nested/synthetic.csv").read_bytes(),
                b"a,b\n1,2\n",
            )
            self.assertEqual(
                sorted(path.suffix for path in output.rglob("*") if path.is_file()),
                [".csv"],
            )
            self.assertNotIn("synthetic", result.stdout + result.stderr)
            self.assertEqual(hashlib.sha256(archive.read_bytes()).digest(), before)

    def test_rejects_unsafe_member_paths_without_logging_names(self) -> None:
        names = [
            "/absolute.csv",
            "../escape.csv",
            "folder/../../escape.csv",
            r"folder\backslash.csv",
            "folder/drive:C.csv",
            "/".join(["deep"] * 65 + ["file.csv"]),
        ]
        for name in names:
            with self.subTest(path_class="unsafe"):
                with TemporaryDirectory() as temp:
                    raw, region_root = make_raw_root(Path(temp))
                    archive = region_root / "bundle.zip"
                    make_zip(archive, [(name, b"synthetic")])
                    output = region_root / "output"
                    result = run_cli(raw, archive, output)
                    self.assertEqual(result.returncode, 2)
                    self.assertFalse(output.exists())
                    self.assertNotIn(name, result.stdout + result.stderr)
                    self.assertIn("blocked_or_extraction_failed", result.stderr)

    def test_rejects_casefold_duplicates_and_file_directory_conflicts(self) -> None:
        cases = [
            [("folder/table.csv", b"a"), ("FOLDER/TABLE.CSV", b"b")],
            [("folder", b"file"), ("folder/table.csv", b"child")],
        ]
        for members in cases:
            with TemporaryDirectory() as temp:
                raw, region_root = make_raw_root(Path(temp))
                archive = region_root / "bundle.zip"
                make_zip(archive, members)
                output = region_root / "output"
                result = run_cli(raw, archive, output)
                self.assertEqual(result.returncode, 2)
                self.assertFalse(output.exists())

    def test_rejects_symlink_member(self) -> None:
        with TemporaryDirectory() as temp:
            raw, region_root = make_raw_root(Path(temp))
            archive_path = region_root / "bundle.zip"
            info = zipfile.ZipInfo("synthetic.csv")
            info.create_system = 3
            info.external_attr = 0o120777 << 16
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr(info, b"synthetic")
            output = region_root / "output"
            result = run_cli(raw, archive_path, output)
            self.assertEqual(result.returncode, 2)
            self.assertFalse(output.exists())

    def test_rejects_external_archive_and_existing_output(self) -> None:
        with TemporaryDirectory() as temp:
            base = Path(temp)
            raw = base / "raw"
            raw.mkdir()
            region_root = raw / "2023-travel-log-west"
            region_root.mkdir()
            external = base / "external.zip"
            make_zip(external, [("table.csv", b"synthetic")])
            output = region_root / "output"
            result = run_cli(raw, external, output)
            self.assertEqual(result.returncode, 2)
            self.assertFalse(output.exists())
            archive = region_root / "bundle.zip"
            make_zip(archive, [("table.csv", b"synthetic")])
            output.mkdir()
            result = run_cli(raw, archive, output)
            self.assertEqual(result.returncode, 2)
            self.assertTrue(output.is_dir())

    def test_rejects_cross_region_archive_and_output(self) -> None:
        with TemporaryDirectory() as temp:
            raw = Path(temp) / "raw"
            raw.mkdir()
            west_root = raw / "2023-travel-log-west"
            east_root = raw / "2023-travel-log-east"
            west_root.mkdir()
            east_root.mkdir()
            east_archive = east_root / "east.zip"
            make_zip(east_archive, [("table.csv", b"synthetic")])

            result = run_cli(raw, east_archive, west_root / "output")

            self.assertEqual(result.returncode, 2)
            self.assertFalse((west_root / "output").exists())

            west_archive = west_root / "west.zip"
            make_zip(west_archive, [("table.csv", b"synthetic")])
            cross_region_output = east_root / "output"
            result = run_cli(raw, west_archive, cross_region_output)
            self.assertEqual(result.returncode, 2)
            self.assertFalse(cross_region_output.exists())

    def test_requires_existing_non_symlink_region_root(self) -> None:
        with TemporaryDirectory() as temp:
            raw = Path(temp) / "raw"
            raw.mkdir()
            archive = raw / "archive.zip"
            make_zip(archive, [("table.csv", b"synthetic")])
            result = run_cli(raw, archive, raw / "output")
            self.assertEqual(result.returncode, 2)

            real_root = raw / "real-region"
            real_root.mkdir()
            region_link = raw / "2023-travel-log-west"
            region_link.symlink_to(real_root, target_is_directory=True)
            linked_archive = real_root / "archive.zip"
            make_zip(linked_archive, [("table.csv", b"synthetic")])
            result = run_cli(raw, linked_archive, real_root / "output")
            self.assertEqual(result.returncode, 2)

    def test_rejects_symlink_archive_component(self) -> None:
        with TemporaryDirectory() as temp:
            raw, region_root = make_raw_root(Path(temp))
            archive = region_root / "bundle.zip"
            make_zip(archive, [("table.csv", b"synthetic")])
            link = region_root / "linked.zip"
            link.symlink_to(archive)
            output = region_root / "output"
            result = run_cli(raw, link, output)
            self.assertEqual(result.returncode, 2)
            self.assertFalse(output.exists())

    def test_crc_failure_cleans_only_new_output(self) -> None:
        with TemporaryDirectory() as temp:
            raw, region_root = make_raw_root(Path(temp))
            archive = region_root / "bundle.zip"
            make_zip(archive, [("table.csv", b"synthetic-payload")])
            contents = bytearray(archive.read_bytes())
            local_header = contents.index(b"PK\x03\x04")
            name_length = int.from_bytes(contents[local_header + 26:local_header + 28], "little")
            extra_length = int.from_bytes(contents[local_header + 28:local_header + 30], "little")
            payload_offset = local_header + 30 + name_length + extra_length
            contents[payload_offset] ^= 1
            archive.write_bytes(contents)
            output = region_root / "output"
            result = run_cli(raw, archive, output)
            self.assertEqual(result.returncode, 2)
            self.assertFalse(output.exists())

    def test_requires_confirmation_flags_and_allowed_roles(self) -> None:
        with TemporaryDirectory() as temp:
            raw, region_root = make_raw_root(Path(temp))
            archive = region_root / "bundle.zip"
            make_zip(archive, [("table.csv", b"synthetic")])
            output = region_root / "output"
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--raw-root", str(raw), "--region", "west",
                 "--archive", f"TS_photo={archive}", "--output", str(output),
                 "--confirm-approved", "--confirm-terms"],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(output.exists())
