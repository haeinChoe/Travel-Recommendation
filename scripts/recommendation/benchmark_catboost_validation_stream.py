"""Bounded synthetic benchmark for the CatBoost ranking evaluator.

No project datasets are opened. This compares the prior full-catalog-per-query
construction with the prepared, chunked scorer and reports timings separately
from Python allocation-peak measurements.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import tracemalloc
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.recommendation.catboost_ranking_experiment import (
    CandidateInventory,
    ExperimentConfig,
    PreparedItemCatalog,
    SamplingStrategy,
    aggregate_ranking_metrics,
    materialize_inner_train_item_features,
    prepare_feature_frame,
    sample_unobserved,
    score_inner_validation_queries,
)
from scripts.recommendation.tl_traveler_split import deterministic_traveler_group_split


class SyntheticRanker:
    def predict(self, frame: pd.DataFrame) -> list[float]:
        # Repeated category codes create deliberate deterministic score ties.
        return [
            float(int(code) % 17) + float(days) * 0.01
            for code, days in zip(
                frame["canonical_admin_sgg_code"], frame["elapsed_days"], strict=True
            )
        ]


def legacy_full_catalog_metrics(
    materialization: Any,
    query_rows: list[tuple[str, tuple[str, ...]]],
    query_features: dict[str, dict[str, Any]],
    config: ExperimentConfig,
    model: SyntheticRanker,
) -> dict[str, float]:
    features = [
        "canonical_admin_sido_code", "canonical_admin_sgg_code",
        "canonical_admin_location_status", "train_positive_interaction_count",
        "train_observed_visit_type_codes", "start_month", "elapsed_days",
    ]
    item_rows = list(materialization.item_features)
    rankings: list[tuple[tuple[str, ...], tuple[str, ...]]] = []
    for query_id, relevant in query_rows:
        rows = [
            {**{column: item[column] for column in features[:5]}, **query_features[query_id]}
            for item in item_rows
        ]
        frame = prepare_feature_frame(pd.DataFrame(rows), config)
        scores = model.predict(frame)
        ranked = tuple(
            item["item_id"] for item, _ in sorted(
                zip(item_rows, scores, strict=True),
                key=lambda pair: (-float(pair[1]), str(pair[0]["item_id"])),
            )
        )
        rankings.append((ranked, relevant))
    return aggregate_ranking_metrics(rankings, k_values=config.k_values)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog-size", type=int, default=20_000)
    parser.add_argument("--queries", type=int, default=60)
    parser.add_argument("--batch-rows", type=int, default=1_024)
    args = parser.parse_args()
    if args.catalog_size < 2 or args.queries < 1 or args.batch_rows < 1:
        parser.error("catalog-size >= 2, queries >= 1, batch-rows >= 1 required")

    trip_count = max(100, args.queries * 10)
    trip_owner = {f"synthetic-trip-{index}": f"synthetic-traveler-{index}" for index in range(trip_count)}
    partitions = deterministic_traveler_group_split(
        trip_owner, seed="synthetic-benchmark", validation_fraction=0.2
    )
    catalog_rows = [
        {
            "item_id": f"synthetic-item-{index:07d}",
            "region": "synthetic-region",
            "canonical_admin_sido_code": "11",
            "canonical_admin_sgg_code": f"{index % 17:05d}",
            "canonical_admin_location_status": "synthetic",
            "train_positive_interaction_count": 999,
            "train_observed_visit_type_codes": ["outer-value-must-be-replaced"],
        }
        for index in range(args.catalog_size)
    ]
    positives = [
        {
            "TRAVEL_ID": trip_id,
            "POI_ID": f"synthetic-item-{index % args.catalog_size:07d}",
            "observed_positive": 1,
            "source_split": "TL",
        }
        for index, trip_id in enumerate(trip_owner)
    ]
    visits = [
        {
            "TRAVEL_ID": trip_id,
            "POI_ID": f"synthetic-item-{index % args.catalog_size:07d}",
            "VISIT_AREA_TYPE_CD": f"{index % 5}",
            "source_split": "TL",
        }
        for index, trip_id in enumerate(trip_owner)
    ]
    materialization_started = time.perf_counter()
    materialization = materialize_inner_train_item_features(
        trip_owner=trip_owner,
        item_features=catalog_rows,
        positive_interactions=positives,
        visit_events=visits,
        split_seed="synthetic-benchmark",
        validation_fraction=0.2,
    )
    config = ExperimentConfig(
        ("I2_ADMINISTRATIVE_LOCATION", "I3_POPULARITY", "I4_HISTORICAL_POI", "Q4_TEMPORAL"),
        k_values=(5, 10, 20),
        popularity_transform="log1p",
    )
    catalog = PreparedItemCatalog.from_materialization(
        materialization, config, region="synthetic-region"
    )
    materialization_seconds = time.perf_counter() - materialization_started

    validation_ids = [
        trip_id for trip_id, partition in partitions.items()
        if partition == "inner-validation"
    ][:args.queries]
    query_rows = [
        (trip_id, (f"synthetic-item-{16 % args.catalog_size:07d}",))
        for index, trip_id in enumerate(validation_ids)
    ]
    query_features = {
        trip_id: {
            "region": "synthetic-region",
            "start_month": f"month-{index % 12 + 1}",
            "elapsed_days": index % 30,
        }
        for index, trip_id in enumerate(validation_ids)
    }
    model = SyntheticRanker()

    # Preserve the exact legacy sampler draw for the same candidate/positive inputs.
    inventory = CandidateInventory.from_items(
        (row["item_id"] for row in materialization.item_features),
        region="synthetic-region",
    )
    sampling_positives = {query_rows[index][1][0] for index in range(len(query_rows))}
    started = time.perf_counter()
    for index in range(len(query_rows)):
        sample_unobserved(
            inventory.items, sampling_positives,
            strategy=SamplingStrategy.UNIFORM, ratio=1, seed=index,
        )
    legacy_sampling_seconds = time.perf_counter() - started
    started = time.perf_counter()
    for index in range(len(query_rows)):
        sample_unobserved(
            inventory, sampling_positives,
            strategy=SamplingStrategy.UNIFORM, ratio=1, seed=index,
        )
    prepared_sampling_seconds = time.perf_counter() - started

    started = time.perf_counter()
    legacy_metrics = legacy_full_catalog_metrics(
        materialization, query_rows, query_features, config, model
    )
    legacy_seconds = time.perf_counter() - started
    started = time.perf_counter()
    streamed = score_inner_validation_queries(
        model, catalog, iter(query_rows), query_features=query_features,
        config=config, max_rows_per_batch=args.batch_rows,
    )
    streamed_seconds = time.perf_counter() - started
    if dict(streamed.metrics) != legacy_metrics:
        raise RuntimeError("synthetic streamed and legacy metrics diverged")

    # Separately measure Python-managed allocation peaks on one representative
    # query; this is not an RSS estimate and is not included in wall timings.
    tracemalloc.start()
    score_inner_validation_queries(
        model, catalog, iter(query_rows[:1]), query_features=query_features,
        config=config, max_rows_per_batch=args.batch_rows,
    )
    _, streamed_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    tracemalloc.start()
    legacy_full_catalog_metrics(
        materialization, query_rows[:1], query_features, config, model
    )
    _, legacy_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    print(json.dumps({
        "synthetic_only": True,
        "catalog_items": len(catalog.inventory.items),
        "inner_validation_queries": streamed.query_count,
        "scored_rows": streamed.scored_rows,
        "max_prediction_frame_rows": streamed.max_batch_rows,
        "configured_prediction_frame_row_cap": args.batch_rows,
        "prepared_catalog_resident": True,
        "materialization_and_cache_seconds": materialization_seconds,
        "legacy_uniform_sampling_seconds": legacy_sampling_seconds,
        "prepared_uniform_sampling_seconds": prepared_sampling_seconds,
        "legacy_full_frame_evaluation_seconds": legacy_seconds,
        "streamed_evaluation_seconds": streamed_seconds,
        "legacy_one_query_python_allocation_peak_bytes": legacy_peak,
        "streamed_one_query_python_allocation_peak_bytes": streamed_peak,
        "allocation_measurement": "tracemalloc Python-managed peak; not process RSS",
        "metrics_exactly_equal": True,
        "metrics": dict(streamed.metrics),
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
