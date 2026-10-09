import csv
import io
import unittest

from scripts.eda.validate_travel_log_code_domains import summarize


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


if __name__ == "__main__":
    unittest.main()
