#!/usr/bin/env python3
"""Small Hugging Face sequential-recommendation fixture for serving benchmarks.

The source dataset is MIT-licensed and derived from Amazon Reviews 2023:
https://huggingface.co/datasets/sungjin-code/amazon-reviews-for-llm

Only three small parquet files are downloaded. Runtime artifacts stay under a
Git-ignored cache directory and are never committed.
"""

from __future__ import annotations

import hashlib
import os
import random
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import duckdb


DATASET_REPO = "sungjin-code/amazon-reviews-for-llm"
REQUIRED_FILES = (
    "interactions.parquet",
    "test.parquet",
    "items_text.parquet",
)

Downloader = Callable[[str, Path], None]


def default_downloader(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Travel-Recommendation/issue-90-benchmark"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60.0) as response:
            with temporary.open("wb") as output:
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()


def ensure_dataset_files(
    cache_dir: Path,
    *,
    revision: str = "main",
    downloader: Downloader = default_downloader,
) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    quoted_revision = urllib.parse.quote(revision, safe="")
    for filename in REQUIRED_FILES:
        destination = cache_dir / filename
        if not destination.exists():
            url = (
                f"https://huggingface.co/datasets/{DATASET_REPO}/resolve/"
                f"{quoted_revision}/data/{filename}?download=true"
            )
            downloader(url, destination)
        if not destination.is_file() or destination.stat().st_size == 0:
            raise RuntimeError(f"Dataset file is missing or empty: {filename}")
        paths[filename] = destination
    return paths


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def prepare_hf_amazon_fixture(
    *,
    cache_dir: Path,
    request_count: int,
    seed: int,
    history_size: int,
    description_chars: int,
    revision: str = "main",
    downloader: Downloader = default_downloader,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    paths = ensure_dataset_files(
        cache_dir,
        revision=revision,
        downloader=downloader,
    )
    cases = load_hf_amazon_cases(
        interactions_path=paths["interactions.parquet"],
        test_path=paths["test.parquet"],
        items_text_path=paths["items_text.parquet"],
        request_count=request_count,
        seed=seed,
        history_size=history_size,
        description_chars=description_chars,
    )
    metadata = {
        "source": "huggingface-amazon-reviews-for-llm",
        "dataset_repo": DATASET_REPO,
        "revision": revision,
        "request_count": len(cases),
        "candidate_count": 10,
        "history_size": history_size,
        "file_sha256": {
            filename: file_sha256(path)
            for filename, path in sorted(paths.items())
        },
    }
    return cases, metadata


def load_hf_amazon_cases(
    *,
    interactions_path: Path,
    test_path: Path,
    items_text_path: Path,
    request_count: int,
    seed: int,
    history_size: int,
    description_chars: int,
) -> list[dict[str, Any]]:
    if request_count <= 0:
        raise ValueError("request_count must be positive")
    if history_size <= 0:
        raise ValueError("history_size must be positive")
    if description_chars <= 0:
        raise ValueError("description_chars must be positive")

    connection = duckdb.connect(database=":memory:")
    try:
        interaction_rows = connection.execute(
            """
            SELECT user_idx, item_idx, pos
            FROM read_parquet(?)
            ORDER BY user_idx, pos, item_idx
            """,
            [str(interactions_path)],
        ).fetchall()
        test_rows = connection.execute(
            """
            SELECT user_idx, item_idx, domain, pos, candidates, gt_pos
            FROM read_parquet(?)
            ORDER BY user_idx, pos, item_idx
            """,
            [str(test_path)],
        ).fetchall()
        item_rows = connection.execute(
            """
            SELECT item_idx, title, description
            FROM read_parquet(?)
            """,
            [str(items_text_path)],
        ).fetchall()
    finally:
        connection.close()

    items = {
        int(item_idx): {
            "title": _compact_text(title),
            "description": _compact_text(description),
        }
        for item_idx, title, description in item_rows
    }

    history_by_user: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for user_idx, item_idx, pos in interaction_rows:
        history_by_user[int(user_idx)].append((int(pos), int(item_idx)))

    normalized_rows: list[dict[str, Any]] = []
    for user_idx, item_idx, domain, pos, candidates, gt_pos in test_rows:
        candidate_ids = tuple(int(value) for value in candidates)
        target_item = int(item_idx)
        ground_truth_position = int(gt_pos)
        if len(candidate_ids) != 10 or len(set(candidate_ids)) != 10:
            raise ValueError("Expected exactly 10 distinct candidates per test row")
        if not 0 <= ground_truth_position < len(candidate_ids):
            raise ValueError("gt_pos is outside candidate bounds")
        if candidate_ids[ground_truth_position] != target_item:
            raise ValueError("Dataset invariant failed: candidates[gt_pos] != item_idx")
        if any(candidate_id not in items for candidate_id in candidate_ids):
            raise ValueError("A candidate does not resolve in items_text.parquet")

        normalized_rows.append(
            {
                "user_idx": int(user_idx),
                "item_idx": target_item,
                "domain": str(domain),
                "pos": int(pos),
                "candidate_ids": candidate_ids,
            }
        )

    selected = _balanced_sample(normalized_rows, request_count, seed)
    cases: list[dict[str, Any]] = []
    for sample_index, row in enumerate(selected):
        user_history = [
            item_id
            for history_pos, item_id in history_by_user[row["user_idx"]]
            if history_pos < row["pos"]
        ][-history_size:]
        if not user_history:
            raise ValueError("Selected test row has no prior user history")

        history_lines = []
        for order, item_id in enumerate(user_history, start=1):
            item = items.get(item_id)
            if item is None:
                continue
            history_lines.append(
                f"{order}. {item['title']}: "
                f"{_truncate(item['description'], description_chars)}"
            )
        if not history_lines:
            raise ValueError("Selected test row has no text-resolvable prior history")

        candidates = []
        ground_truth_candidate_id = ""
        for candidate_index, item_id in enumerate(row["candidate_ids"]):
            item = items[item_id]
            candidate_id = f"candidate-{candidate_index:02d}"
            if item_id == row["item_idx"]:
                ground_truth_candidate_id = candidate_id
            candidates.append(
                {
                    "candidate_id": candidate_id,
                    "name": item["title"],
                    "description": _truncate(item["description"], description_chars),
                }
            )

        if not ground_truth_candidate_id:
            raise ValueError("Ground-truth item is not present in candidates")

        cases.append(
            {
                "request_id": f"hf-amazon-test-{sample_index:03d}",
                "preference_text": (
                    "This is a sequential recommendation task. "
                    f"The candidate domain is {row['domain']}. "
                    "The user's recent positively rated/reviewed history, oldest to newest, is:\n"
                    + "\n".join(history_lines)
                    + "\nRank all candidates by which item is most likely to be the user's "
                    "next positively rated/reviewed item. Do not assume the user has seen the "
                    "candidate items before."
                ),
                "candidates": candidates,
                "ground_truth_candidate_id": ground_truth_candidate_id,
                "domain": row["domain"],
            }
        )
    return cases


def _balanced_sample(
    rows: Sequence[Mapping[str, Any]],
    request_count: int,
    seed: int,
) -> list[dict[str, Any]]:
    if request_count > len(rows):
        raise ValueError(
            f"request_count={request_count} exceeds available test rows={len(rows)}"
        )

    by_domain: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_domain[str(row["domain"])].append(dict(row))

    rng = random.Random(seed)
    domains = sorted(by_domain)
    for domain in domains:
        rng.shuffle(by_domain[domain])

    selected: list[dict[str, Any]] = []
    while len(selected) < request_count:
        progressed = False
        for domain in domains:
            if by_domain[domain] and len(selected) < request_count:
                selected.append(by_domain[domain].pop())
                progressed = True
        if not progressed:
            break

    if len(selected) != request_count:
        raise RuntimeError("Could not select the requested number of benchmark rows")
    return selected


def _compact_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return " ".join(value.split())
    if isinstance(value, (list, tuple)):
        return " ".join(_compact_text(item) for item in value if item is not None).strip()
    return " ".join(str(value).split())


def _truncate(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 1].rstrip() + "…"
