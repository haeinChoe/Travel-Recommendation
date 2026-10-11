"""Independent synthetic-only safety tests for the popularity baseline CLI.

Tests verify safety behaviors defined in GitHub Issue #29:
1. Explicit confirmation required before any input/data read.
2. Rejection of raw-root escapes and symlink inputs.
3. Rejection of duplicate role mappings and unpaired TL/VL roles.
4. Rejection of invalid run IDs before input access.
5. Protection of output path and artifact overwrite behavior.
6. Privacy protection (no raw paths or identifiers leaked in outputs).

Tests are resilient to incidental error wording and use synthetic fixtures exclusively.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import os
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
LOCAL_SCRIPT_PATH = REPO_ROOT / "scripts" / "recommendation" / "evaluate_popularity.py"
ENV_SCRIPT_PATH = os.environ.get("POPULARITY_SCRIPT_PATH")
TARGET_SCRIPT_PATH = (
    Path(ENV_SCRIPT_PATH).resolve() if ENV_SCRIPT_PATH else LOCAL_SCRIPT_PATH
)

MODULE_AVAILABLE = TARGET_SCRIPT_PATH.is_file()

if MODULE_AVAILABLE:
    spec = importlib.util.spec_from_file_location("evaluate_popularity", TARGET_SCRIPT_PATH)
    if spec and spec.loader:
        evaluate_popularity = importlib.util.module_from_spec(spec)
        sys.modules["evaluate_popularity"] = evaluate_popularity
        spec.loader.exec_module(evaluate_popularity)
        main = evaluate_popularity.main
        parse_input_spec = evaluate_popularity.parse_input_spec
        has_symlink_component = evaluate_popularity.has_symlink_component
        within = evaluate_popularity.within
        _write_artifacts = evaluate_popularity._write_artifacts
        RESULTS_ROOT = evaluate_popularity.RESULTS_ROOT
    else:
        MODULE_AVAILABLE = False


def write_csv(path: Path, headers: list[str], rows: list[tuple[str, ...]]) -> None:
    """Helper to write synthetic CSV fixtures safely."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(headers)
        writer.writerows(rows)


def make_synthetic_region_split(
    root: Path, region: str = "capital"
) -> tuple[Path, Path]:
    """Create minimal synthetic TL and VL directories with synthetic records."""
    tl_dir = root / region / "TL_csv"
    vl_dir = root / region / "VL_csv"

    # Minimal travel records
    write_csv(
        tl_dir / "TN_TRAVEL.csv",
        ["TRAVEL_ID", "TRAVELER_ID"],
        [("synthetic-trip-1", "synthetic-user-1")] * 10,
    )
    # Minimal visit records
    write_csv(
        tl_dir / "TN_VISIT_AREA_INFO.csv",
        ["TRAVEL_ID", "POI_ID", "VISIT_AREA_ID"],
        [("synthetic-trip-1", "synthetic-poi-1", "synthetic-area-1")] * 10,
    )

    write_csv(
        vl_dir / "TN_TRAVEL.csv",
        ["TRAVEL_ID", "TRAVELER_ID"],
        [("synthetic-val-trip-1", "synthetic-user-1")],
    )
    write_csv(
        vl_dir / "TN_VISIT_AREA_INFO.csv",
        ["TRAVEL_ID", "POI_ID", "VISIT_AREA_ID"],
        [("synthetic-val-trip-1", "synthetic-poi-1", "synthetic-area-1")],
    )

    return tl_dir, vl_dir


@unittest.skipUnless(
    MODULE_AVAILABLE,
    f"Target CLI script is not available at {TARGET_SCRIPT_PATH} in this worktree",
)
class PopularityCliSafetyTests(unittest.TestCase):
    REQUIRED_CONFIRMATIONS = [
        "--confirm-approved",
        "--confirm-terms",
        "--confirm-poi-candidate",
    ]

    def test_explicit_confirmation_required_before_any_input_access(self) -> None:
        """Any missing confirmation flag must stop execution before touching inputs."""
        for missing in self.REQUIRED_CONFIRMATIONS:
            with self.subTest(missing=missing):
                provided_confirmations = [
                    flag for flag in self.REQUIRED_CONFIRMATIONS if flag != missing
                ]
                args = [
                    "--input",
                    "capital:TL=/must/not/be/accessed/TL_csv",
                    *provided_confirmations,
                ]
                stderr_buf = StringIO()
                with (
                    redirect_stderr(stderr_buf),
                    patch(
                        "evaluate_popularity._read_split",
                        side_effect=AssertionError("Input read occurred before confirmation!"),
                    ) as mock_read,
                    patch(
                        "evaluate_popularity.csv_files",
                        side_effect=AssertionError("Directory scanned before confirmation!"),
                    ) as mock_scan,
                ):
                    exit_code = main(args)
                    self.assertNotEqual(
                        exit_code, 0, "CLI must reject command with missing confirmation"
                    )
                    self.assertEqual(
                        exit_code, 2, "Safety checks must return exit code 2"
                    )
                    mock_read.assert_not_called()
                    mock_scan.assert_not_called()
                    self.assertTrue(
                        len(stderr_buf.getvalue().strip()) > 0,
                        "Stderr must describe the missing confirmation",
                    )

    def test_all_confirmations_missing_fails_immediately(self) -> None:
        """When none of the confirmation flags are passed, input access must be aborted."""
        args = ["--input", "capital:TL=/must/not/be/accessed/TL_csv"]
        stderr_buf = StringIO()
        with (
            redirect_stderr(stderr_buf),
            patch(
                "evaluate_popularity._read_split",
                side_effect=AssertionError("Input read occurred before confirmation!"),
            ) as mock_read,
            patch(
                "evaluate_popularity.csv_files",
                side_effect=AssertionError("Directory scanned before confirmation!"),
            ) as mock_scan,
        ):
            exit_code = main(args)
            self.assertEqual(exit_code, 2)
            mock_read.assert_not_called()
            mock_scan.assert_not_called()

    def test_invalid_run_ids_rejected_before_input_access(self) -> None:
        """Run ID must be strictly validated before any input reads occur."""
        invalid_run_ids = [
            "../escape",
            "run/with/slash",
            "run with space",
            "run*asterisk",
            "run$dollar",
            ".hidden_run",
            "_leading_underscore",
            "-leading_dash",
            "",
            "a" * 81,  # exceeds maximum 80 characters
        ]
        with TemporaryDirectory(prefix="test-run-id-") as tmp:
            raw_root = Path(tmp) / "raw"
            tl, vl = make_synthetic_region_split(raw_root)
            for bad_id in invalid_run_ids:
                with self.subTest(bad_id=bad_id):
                    # Use --run-id=value so leading dashes are parsed as option values rather than flag names
                    args = [
                        "--raw-root", str(raw_root),
                        "--input", f"capital:TL={tl}",
                        "--input", f"capital:VL={vl}",
                        f"--run-id={bad_id}",
                        *self.REQUIRED_CONFIRMATIONS,
                    ]
                    stderr_buf = StringIO()
                    with (
                        redirect_stderr(stderr_buf),
                        patch(
                            "evaluate_popularity._read_split",
                            side_effect=AssertionError("Input read occurred with invalid run-id!"),
                        ) as mock_read,
                    ):
                        try:
                            exit_code = main(args)
                        except SystemExit as exc:
                            exit_code = exc.code
                        self.assertNotEqual(exit_code, 0)
                        self.assertEqual(exit_code, 2)
                        mock_read.assert_not_called()
                        self.assertTrue(len(stderr_buf.getvalue().strip()) > 0)

    def test_raw_root_escapes_rejected(self) -> None:
        """Inputs outside --raw-root must be rejected."""
        with TemporaryDirectory(prefix="test-escape-") as tmp:
            root = Path(tmp)
            raw_root = root / "raw"
            tl, vl = make_synthetic_region_split(raw_root)
            outside_dir = root / "outside" / "TL_csv"
            outside_dir.mkdir(parents=True)

            # 1. Direct path outside raw-root
            args_outside = [
                "--raw-root", str(raw_root),
                "--input", f"capital:TL={outside_dir}",
                "--input", f"capital:VL={vl}",
                *self.REQUIRED_CONFIRMATIONS,
            ]
            stderr_buf = StringIO()
            with redirect_stderr(stderr_buf):
                self.assertNotEqual(main(args_outside), 0)

            # 2. Parent directory traversal escaping raw-root
            args_traversal = [
                "--raw-root", str(raw_root),
                "--input", f"capital:TL={raw_root / '..' / 'outside' / 'TL_csv'}",
                "--input", f"capital:VL={vl}",
                *self.REQUIRED_CONFIRMATIONS,
            ]
            stderr_buf = StringIO()
            with redirect_stderr(stderr_buf):
                self.assertNotEqual(main(args_traversal), 0)

    def test_symlink_inputs_and_components_rejected(self) -> None:
        """Symlinks at any position in input paths or raw-root must be rejected."""
        with TemporaryDirectory(prefix="test-symlink-") as tmp:
            root = Path(tmp)
            raw_root = root / "raw"
            tl, vl = make_synthetic_region_split(raw_root)

            # 1. Input directory is a symlink
            symlink_tl = root / "symlink-TL_csv"
            try:
                symlink_tl.symlink_to(tl, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"Symlink creation unsupported: {type(exc).__name__}")

            args_symlink_input = [
                "--raw-root", str(raw_root),
                "--input", f"capital:TL={symlink_tl}",
                "--input", f"capital:VL={vl}",
                *self.REQUIRED_CONFIRMATIONS,
            ]
            stderr_buf = StringIO()
            with redirect_stderr(stderr_buf):
                self.assertNotEqual(main(args_symlink_input), 0)

            # 2. Input path contains a symlink component before parent traversal
            symlink_component = symlink_tl / ".." / "capital" / "TL_csv"
            self.assertTrue(
                has_symlink_component(symlink_component),
                "has_symlink_component must detect symlink in path chain",
            )
            args_symlink_component = [
                "--raw-root", str(raw_root),
                "--input", f"capital:TL={symlink_component}",
                "--input", f"capital:VL={vl}",
                *self.REQUIRED_CONFIRMATIONS,
            ]
            stderr_buf = StringIO()
            with redirect_stderr(stderr_buf):
                self.assertNotEqual(main(args_symlink_component), 0)

            # 3. raw-root itself is a symlink
            raw_link = root / "raw-link"
            raw_link.symlink_to(raw_root, target_is_directory=True)
            args_symlink_raw_root = [
                "--raw-root", str(raw_link),
                "--input", f"capital:TL={tl}",
                "--input", f"capital:VL={vl}",
                *self.REQUIRED_CONFIRMATIONS,
            ]
            stderr_buf = StringIO()
            with redirect_stderr(stderr_buf):
                self.assertNotEqual(main(args_symlink_raw_root), 0)

    def test_duplicate_role_mappings_rejected(self) -> None:
        """Duplicate role mapping for the same region must be rejected."""
        with TemporaryDirectory(prefix="test-roles-") as tmp:
            raw_root = Path(tmp) / "raw"
            tl, vl = make_synthetic_region_split(raw_root)
            tl_alt = raw_root / "capital" / "alt" / "TL_csv"
            tl_alt.mkdir(parents=True)

            # Duplicate TL role for capital region
            args_duplicate = [
                "--raw-root", str(raw_root),
                "--input", f"capital:TL={tl}",
                "--input", f"capital:TL={tl_alt}",
                "--input", f"capital:VL={vl}",
                *self.REQUIRED_CONFIRMATIONS,
            ]
            stderr_buf = StringIO()
            with redirect_stderr(stderr_buf):
                exit_code = main(args_duplicate)
                self.assertNotEqual(exit_code, 0)
                self.assertEqual(exit_code, 2)

    def test_unpaired_role_rejected(self) -> None:
        """Each specified region must have exactly one TL and one VL role."""
        with TemporaryDirectory(prefix="test-unpaired-") as tmp:
            raw_root = Path(tmp) / "raw"
            tl, vl = make_synthetic_region_split(raw_root)

            # Only TL provided
            args_tl_only = [
                "--raw-root", str(raw_root),
                "--input", f"capital:TL={tl}",
                *self.REQUIRED_CONFIRMATIONS,
            ]
            stderr_buf = StringIO()
            with redirect_stderr(stderr_buf):
                self.assertEqual(main(args_tl_only), 2)

            # Only VL provided
            args_vl_only = [
                "--raw-root", str(raw_root),
                "--input", f"capital:VL={vl}",
                *self.REQUIRED_CONFIRMATIONS,
            ]
            stderr_buf = StringIO()
            with redirect_stderr(stderr_buf):
                self.assertEqual(main(args_vl_only), 2)

    def test_reused_directory_across_roles_rejected(self) -> None:
        """Same underlying directory cannot be assigned to multiple roles."""
        with TemporaryDirectory(prefix="test-reused-dir-") as tmp:
            raw_root = Path(tmp) / "raw"
            tl, _ = make_synthetic_region_split(raw_root)

            # Same directory mapped to both TL and VL
            args = [
                "--raw-root", str(raw_root),
                "--input", f"capital:TL={tl}",
                "--input", f"capital:VL={tl}",
                *self.REQUIRED_CONFIRMATIONS,
            ]
            stderr_buf = StringIO()
            with redirect_stderr(stderr_buf):
                self.assertEqual(main(args), 2)

    def test_role_folder_name_must_match_convention(self) -> None:
        """Input folder name must strictly match {role}_csv."""
        with TemporaryDirectory(prefix="test-folder-name-") as tmp:
            raw_root = Path(tmp) / "raw"
            tl, vl = make_synthetic_region_split(raw_root)
            wrong_name_dir = raw_root / "capital" / "TL_wrong"
            wrong_name_dir.mkdir(parents=True)

            args = [
                "--raw-root", str(raw_root),
                "--input", f"capital:TL={wrong_name_dir}",
                "--input", f"capital:VL={vl}",
                *self.REQUIRED_CONFIRMATIONS,
            ]
            stderr_buf = StringIO()
            with redirect_stderr(stderr_buf):
                self.assertEqual(main(args), 2)

    def test_parse_input_spec_syntax_and_domain_guards(self) -> None:
        """Malformed input spec arguments must raise ArgumentTypeError."""
        invalid_specs = [
            "capital:TL",             # missing separator '='
            "=path",                  # missing label
            "unknown_region:TL=/path", # invalid region domain
            "capital:INVALID=/path",  # invalid role domain
            "capital:TL=",            # empty path
            "capitalTL=/path",        # missing colon ':'
        ]
        for spec_str in invalid_specs:
            with self.subTest(spec_str=spec_str), self.assertRaises(argparse.ArgumentTypeError):
                parse_input_spec(spec_str)

    def test_k_parameter_safety(self) -> None:
        """CLI must reject non-positive or duplicated K values."""
        invalid_k_cases = [
            ["0"],
            ["-5"],
            ["10", "10"],
            ["5", "-1", "10"],
        ]
        with TemporaryDirectory(prefix="test-k-") as tmp:
            raw_root = Path(tmp) / "raw"
            tl, vl = make_synthetic_region_split(raw_root)
            for k_args in invalid_k_cases:
                with self.subTest(k_args=k_args):
                    args = [
                        "--raw-root", str(raw_root),
                        "--input", f"capital:TL={tl}",
                        "--input", f"capital:VL={vl}",
                        "--k", *k_args,
                        *self.REQUIRED_CONFIRMATIONS,
                    ]
                    stderr_buf = StringIO()
                    with redirect_stderr(stderr_buf):
                        self.assertEqual(main(args), 2)

    def test_output_path_and_overwrite_protection(self) -> None:
        """Output directory must be protected against unauthorized overwrite and symlinks."""
        with TemporaryDirectory(prefix="test-output-") as tmp:
            root = Path(tmp)
            raw_root = root / "raw"
            tl, vl = make_synthetic_region_split(raw_root)
            isolated_results_root = root / "results" / "experiments" / "popularity-baseline"
            run_id = "test-run-overwrite-01"

            args = [
                "--raw-root", str(raw_root),
                "--input", f"capital:TL={tl}",
                "--input", f"capital:VL={vl}",
                "--run-id", run_id,
                "--k", "5",
                *self.REQUIRED_CONFIRMATIONS,
            ]

            # Run 1: initial run succeeds and writes artifacts
            with (
                patch("evaluate_popularity.RESULTS_ROOT", isolated_results_root),
                redirect_stdout(StringIO()),
                redirect_stderr(StringIO()),
            ):
                exit_code_1 = main(args)
                self.assertEqual(exit_code_1, 0, "Initial execution must succeed")

            run_dir = isolated_results_root / run_id
            self.assertTrue((run_dir / "metrics.csv").is_file())
            self.assertTrue((run_dir / "run_metadata.json").is_file())
            original_metrics_content = (run_dir / "metrics.csv").read_text(encoding="utf-8")

            # Run 2: without --overwrite, re-run must be aborted and existing files intact
            stderr_buf = StringIO()
            with (
                patch("evaluate_popularity.RESULTS_ROOT", isolated_results_root),
                redirect_stdout(StringIO()),
                redirect_stderr(stderr_buf),
            ):
                exit_code_2 = main(args)
                self.assertEqual(
                    exit_code_2, 2, "Re-run without --overwrite must exit with error code 2"
                )

            current_metrics_content = (run_dir / "metrics.csv").read_text(encoding="utf-8")
            self.assertEqual(
                original_metrics_content,
                current_metrics_content,
                "Existing output files must remain untouched when overwrite is disabled",
            )

            # Run 3: with --overwrite, re-run must succeed
            args_overwrite = [*args, "--overwrite"]
            with (
                patch("evaluate_popularity.RESULTS_ROOT", isolated_results_root),
                redirect_stdout(StringIO()),
                redirect_stderr(StringIO()),
            ):
                exit_code_3 = main(args_overwrite)
                self.assertEqual(exit_code_3, 0, "Re-run with --overwrite must succeed")

    def test_artifacts_contain_no_raw_identifiers_or_file_paths(self) -> None:
        """Outputs and logs must never leak raw entity identifiers or absolute raw paths."""
        with TemporaryDirectory(prefix="test-privacy-") as tmp:
            root = Path(tmp)
            raw_root = root / "confidential-raw-storage"
            tl, vl = make_synthetic_region_split(raw_root)
            isolated_results_root = root / "results" / "experiments" / "popularity-baseline"
            run_id = "privacy-validation-run"

            args = [
                "--raw-root", str(raw_root),
                "--input", f"capital:TL={tl}",
                "--input", f"capital:VL={vl}",
                "--run-id", run_id,
                "--k", "5",
                *self.REQUIRED_CONFIRMATIONS,
            ]
            stdout_buf, stderr_buf = StringIO(), StringIO()
            with (
                patch("evaluate_popularity.RESULTS_ROOT", isolated_results_root),
                redirect_stdout(stdout_buf),
                redirect_stderr(stderr_buf),
            ):
                self.assertEqual(main(args), 0)

            cli_output = stdout_buf.getvalue() + stderr_buf.getvalue()
            run_dir = isolated_results_root / run_id
            metrics_text = (run_dir / "metrics.csv").read_text(encoding="utf-8")
            metadata_text = (run_dir / "run_metadata.json").read_text(encoding="utf-8")

            # Check for leaked confidential strings
            private_identifiers = [
                str(raw_root),
                str(tl),
                str(vl),
                "synthetic-trip-1",
                "synthetic-user-1",
                "synthetic-poi-1",
                "synthetic-area-1",
                "synthetic-val-trip-1",
            ]
            for secret in private_identifiers:
                with self.subTest(secret=secret):
                    self.assertNotIn(
                        secret,
                        cli_output,
                        f"CLI console output must not leak identifier: {secret}",
                    )
                    self.assertNotIn(
                        secret,
                        metrics_text,
                        f"metrics.csv must not contain raw identifier: {secret}",
                    )
                    self.assertNotIn(
                        secret,
                        metadata_text,
                        f"run_metadata.json must not contain raw identifier: {secret}",
                    )

            # Metadata privacy verification
            metadata = json.loads(metadata_text)
            self.assertFalse(metadata["privacy"]["raw_paths_written"])
            self.assertFalse(metadata["privacy"]["raw_identifiers_written"])
            self.assertFalse(metadata["privacy"]["row_level_outputs"])


if __name__ == "__main__":
    unittest.main()
