import csv
import io
import contextlib
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from scripts.eda.validate_travel_log_code_domains import RESULTS, main, summarize


class TravelLogCodeDomainTests(unittest.TestCase):
    def test_single_documented_code_is_valid(self):
        result = summarize(["1"] * 10, "EXPND_SE", {"1", "2", "3", "4", "5"}, True)

        self.assertEqual(result["range_status"], "valid")
        self.assertEqual(result["group_status"], "valid")
        self.assertEqual(result["range_unmatched_bucket"], "0")

    def test_composite_text_is_unresolved_and_not_written(self):
        value = "1;2"
        result = summarize([value] * 10, "EXPND_SE", {"1", "2", "3", "4", "5"}, True)
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=list(result))
        writer.writeheader()
        writer.writerow(result)

        self.assertEqual(result["range_status"], "unresolved_candidate")
        self.assertEqual(result["group_status"], "unresolved_candidate")
        self.assertEqual(result["range_unmatched_bucket"], "10+")
        self.assertNotIn(value, output.getvalue())

    def test_invalid_output_is_rejected_before_opening_inputs(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "outside-results"
            args = ["--input", "west:TL=/missing/sentinel", "--codebook", "west=/missing/sentinel",
                    "--output", str(output), "--confirm-approved", "--confirm-terms"]
            errors = io.StringIO()
            with patch.object(Path, "open", side_effect=AssertionError("input was opened")):
                with contextlib.redirect_stderr(errors):
                    status = main(args)

        self.assertEqual(status, 2)
        self.assertIn("output_path_invalid", errors.getvalue())

    def test_codebook_directory_rejects_wrong_role_before_csv_scan(self):
        with tempfile.TemporaryDirectory() as temp:
            roots = self._region_roots(Path(temp))
            for region, root in roots.items():
                target = root / "TL_csv" / (
                    "tc_codea_codes.csv" if region == "west" else "tc_codeb_codes.csv"
                )
                target.write_text("CD_A,CD_B\n", encoding="utf-8")
            books = {region: root / "TL_csv" for region, root in roots.items()}
            books["east"] = roots["east"] / "TL_csv"
            books["jeju-islands"] = roots["jeju-islands"] / "TL_csv"
            args = self._cli_args(roots, books, "wrong-role")
            errors = io.StringIO()
            with contextlib.redirect_stderr(errors):
                status = main(args)

        self.assertEqual(status, 2)
        self.assertIn("codebook_table_mapping_unavailable", errors.getvalue())
        self.assertNotIn(str(temp), errors.getvalue())

    def test_codebook_directory_rejects_wrong_region(self):
        with tempfile.TemporaryDirectory() as temp:
            roots = self._region_roots(Path(temp))
            books = {region: root / "TL_csv" for region, root in roots.items()}
            args = self._cli_args(roots, books, "wrong-region")
            args[args.index("west=" + str(books["west"]))] = "west=" + str(books["east"])
            errors = io.StringIO()
            with contextlib.redirect_stderr(errors):
                status = main(args)

        self.assertEqual(status, 2)
        self.assertIn("codebook_region_path_invalid", errors.getvalue())
        self.assertNotIn(str(temp), errors.getvalue())

    @staticmethod
    def _region_roots(base):
        roots = {}
        for region in ("west", "east", "jeju-islands"):
            root = base / f"2023-travel-log-{region}"
            for role in ("TL_csv", "VL_csv"):
                (root / role).mkdir(parents=True, exist_ok=True)
            roots[region] = root
        return roots

    @staticmethod
    def _cli_args(roots, books, run_name):
        args = []
        for region, root in roots.items():
            for role in ("TL", "VL"):
                args.extend(("--input", f"{region}:{role}={root / (role + '_csv')}"))
            args.extend(("--codebook", f"{region}={books[region]}"))
        args.extend(("--output", str(RESULTS / f"synthetic-{run_name}-{uuid.uuid4().hex}"),
                     "--confirm-approved", "--confirm-terms"))
        return args


if __name__ == "__main__":
    unittest.main()
