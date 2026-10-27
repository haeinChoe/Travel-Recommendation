from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import duckdb

from scripts.recommendation.hf_amazon_benchmark import (
    REQUIRED_FILES,
    ensure_dataset_files,
    load_hf_amazon_cases,
)
from scripts.recommendation.serving_benchmark import reciprocal_rank


class HfAmazonBenchmarkTest(unittest.TestCase):
    def test_downloader_fetches_only_three_required_files_and_reuses_cache(self) -> None:
        calls: list[str] = []

        def fake_downloader(url: str, destination: Path) -> None:
            calls.append(url)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(b"fixture")

        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp)
            paths = ensure_dataset_files(
                cache_dir,
                revision="fixture-revision",
                downloader=fake_downloader,
            )
            self.assertEqual(set(paths), set(REQUIRED_FILES))
            self.assertEqual(len(calls), 3)
            self.assertTrue(all("fixture-revision" in url for url in calls))

            ensure_dataset_files(
                cache_dir,
                revision="fixture-revision",
                downloader=fake_downloader,
            )
            self.assertEqual(len(calls), 3)

    def test_parquet_loader_builds_history_candidates_and_binary_ground_truth(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            interactions_path = root / "interactions.parquet"
            test_path = root / "test.parquet"
            items_path = root / "items_text.parquet"
            self._write_fixture_parquet(
                interactions_path,
                test_path,
                items_path,
            )

            cases = load_hf_amazon_cases(
                interactions_path=interactions_path,
                test_path=test_path,
                items_text_path=items_path,
                request_count=2,
                seed=17,
                history_size=3,
                description_chars=24,
            )

            self.assertEqual(len(cases), 2)
            self.assertEqual({case["domain"] for case in cases}, {"Books", "Movies_and_TV"})
            for case in cases:
                self.assertEqual(len(case["candidates"]), 10)
                candidate_ids = [candidate["candidate_id"] for candidate in case["candidates"]]
                self.assertEqual(len(set(candidate_ids)), 10)
                self.assertIn(case["ground_truth_candidate_id"], candidate_ids)
                self.assertIn("recent positively rated/reviewed history", case["preference_text"])
                self.assertIn("next positively rated/reviewed item", case["preference_text"])
                self.assertNotIn("future-only", case["preference_text"])
                for candidate in case["candidates"]:
                    self.assertLessEqual(len(candidate["description"]), 24)

    def test_reciprocal_rank_uses_first_relevant_result(self) -> None:
        relevance = {"a": 0, "b": 1, "c": 1}
        self.assertEqual(reciprocal_rank(("a", "b", "c"), relevance), 0.5)
        self.assertEqual(reciprocal_rank(("a",), relevance), 0.0)

    @staticmethod
    def _write_fixture_parquet(
        interactions_path: Path,
        test_path: Path,
        items_path: Path,
    ) -> None:
        connection = duckdb.connect(database=":memory:")
        try:
            connection.execute(
                "CREATE TABLE interactions(user_idx INTEGER, item_idx INTEGER, pos INTEGER)"
            )
            connection.executemany(
                "INSERT INTO interactions VALUES (?, ?, ?)",
                [
                    (1, 1, 0),
                    (1, 2, 1),
                    (1, 3, 2),
                    (1, 109, 3),
                    (1, 999, 4),
                    (2, 201, 0),
                    (2, 202, 1),
                    (2, 203, 2),
                    (2, 309, 3),
                    (2, 998, 4),
                ],
            )

            connection.execute(
                """
                CREATE TABLE test(
                    user_idx INTEGER,
                    item_idx INTEGER,
                    domain VARCHAR,
                    pos INTEGER,
                    candidates INTEGER[],
                    gt_pos INTEGER
                )
                """
            )
            connection.execute(
                """
                INSERT INTO test VALUES
                (1, 109, 'Books', 3, [100,101,102,103,104,105,106,107,108,109], 9),
                (2, 309, 'Movies_and_TV', 3, [300,301,302,303,304,305,306,307,308,309], 9)
                """
            )

            connection.execute(
                "CREATE TABLE items_text(item_idx INTEGER, title VARCHAR, description VARCHAR)"
            )
            item_rows = [
                (1, "Book History One", "history one"),
                (2, "Book History Two", "history two"),
                (3, "Book History Three", "history three"),
                (201, "Movie History One", "history one"),
                (202, "Movie History Two", "history two"),
                (203, "Movie History Three", "history three"),
                (999, "Future Book", "future-only"),
                (998, "Future Movie", "future-only"),
            ]
            item_rows.extend(
                (
                    item_id,
                    f"Candidate {item_id}",
                    "candidate description that is deliberately longer than the truncation limit",
                )
                for item_id in range(100, 110)
            )
            item_rows.extend(
                (
                    item_id,
                    f"Candidate {item_id}",
                    "candidate description that is deliberately longer than the truncation limit",
                )
                for item_id in range(300, 310)
            )
            connection.executemany(
                "INSERT INTO items_text VALUES (?, ?, ?)",
                item_rows,
            )

            for table_name, destination in (
                ("interactions", interactions_path),
                ("test", test_path),
                ("items_text", items_path),
            ):
                escaped = str(destination).replace("'", "''")
                connection.execute(
                    f"COPY {table_name} TO '{escaped}' (FORMAT PARQUET)"
                )
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
