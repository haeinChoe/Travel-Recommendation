"""Small synthetic checks for privacy suppression and EDA path guards."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

EDA_DIR = Path(__file__).resolve().parents[1] / "scripts" / "eda"
sys.path.insert(0, str(EDA_DIR))

from profile_travel_log import has_symlink_component, main, safe_counts  # noqa: E402


class EdaSafetySmokeTests(unittest.TestCase):
    def test_safe_counts_complementary_suppression(self) -> None:
        rows = [("synthetic-small", 8), ("synthetic-public", 10), ("synthetic-large", 15)]
        self.assertEqual(
            safe_counts(rows, 10),
            [("synthetic-large", 15), ("<suppressed>", 18)],
        )

    def test_symlink_component_before_parent_traversal_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = root / "target"
            target.mkdir()
            link = root / "link"
            try:
                link.symlink_to(target, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"symlink creation is unavailable: {type(exc).__name__}")

            self.assertTrue(has_symlink_component(link / ".." / "after"))

    def test_cli_checks_lexical_input_before_path_normalization(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            raw_root = root / "raw"
            raw_root.mkdir()
            (raw_root / "dataset").mkdir()
            outside = root / "outside"
            outside.mkdir()
            link = raw_root / "link"
            try:
                link.symlink_to(outside, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"symlink creation is unavailable: {type(exc).__name__}")

            with self.assertRaises(SystemExit):
                main(
                    [
                        "--raw-root",
                        str(raw_root),
                        "--input",
                        str(link / ".." / "dataset"),
                        "--output",
                        "results/eda/travel-log-2023/smoke",
                        "--confirm-approved",
                        "--confirm-terms",
                    ]
                )


if __name__ == "__main__":
    unittest.main()
