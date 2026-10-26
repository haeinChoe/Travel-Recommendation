"""Cold-user CatBoost POI ranking experiment contract primitives.

This module does not read AI Hub raw data. It keeps the agreed experiment
semantics executable so later actual-data runs do not silently change labels,
candidates, feature provenance, sampling, or ranking metrics.

A sampled-unobserved row with label 0 is a training comparison row. It is not
an observed user dislike.
"""

from __future__ import annotations

import argparse
import bisect
import json
import math
import os
import random
import resource
import sys
import threading
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from functools import wraps
from enum import StrEnum
from itertools import combinations, pairwise
from pathlib import Path
from types import MappingProxyType
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.recommendation.tl_traveler_split import (
    deterministic_traveler_group_split,
    recompute_inner_train_positive_interaction_count,
    recompute_inner_train_visit_type_codes,
)

DEFAULT_K = (5, 10, 20)
DEFAULT_OBJECTIVE = "YetiRank"
OBJECTIVE_CANDIDATES = ("YetiRank", "PairLogit", "LambdaMart")
DEFAULT_NEGATIVE_RATIOS = (1, 2, 4, 8, 16)
DEFAULT_ITERATIONS = 1000
DEFAULT_EVAL_METRIC = "NDCG:top=10"
DEFAULT_POPULARITY_SMOOTHING = 1.0
DEFAULT_MIXED_UNIFORM_FRACTION = 0.5
CATBOOST_MISSING_CATEGORY = "__MISSING__"

FEATURE_GROUPS: dict[str, tuple[str, ...]] = {
    "Q1_STYLE": tuple(f"travel_style_{i}" for i in range(1, 9)),
    "Q2_MOTIVE": tuple(f"travel_motive_{i}" for i in range(1, 4)),
    "Q3_COMPANION": ("companion_status", "companion_count"),
    "Q4_TEMPORAL": ("start_month", "elapsed_days"),
    "Q5_DESTINATION_CONTEXT": ("travel_status_destination",),
    "I1_CATEGORY": (
        "source_category_l1_code",
        "source_category_l2_code",
        "source_category_l3_code",
    ),
    "I2_ADMINISTRATIVE_LOCATION": (
        "canonical_admin_sido_code",
        "canonical_admin_sgg_code",
        "canonical_admin_location_status",
    ),
    "I3_POPULARITY": ("train_positive_interaction_count",),
    "I4_HISTORICAL_POI": ("train_observed_visit_type_codes",),
    "C1_REGION": ("region",),
}
PENDING_FEATURE_GROUPS: dict[str, str] = {}
TRAIN_DERIVED_GROUPS = frozenset({"I3_POPULARITY", "I4_HISTORICAL_POI"})
CATEGORICAL_COLUMNS = frozenset({
    *(f"travel_style_{i}" for i in range(1, 9)),
    *(f"travel_motive_{i}" for i in range(1, 4)),
    "companion_status",
    "start_month",
    "travel_status_destination",
    "source_category_l1_code",
    "source_category_l2_code",
    "source_category_l3_code",
    "canonical_admin_sido_code",
    "canonical_admin_sgg_code",
    "canonical_admin_location_status",
    "train_observed_visit_type_codes",
    "region",
})


class SamplingStrategy(StrEnum):
    UNIFORM = "uniform"
    POPULARITY_WEIGHTED = "popularity-weighted"
    MIXED = "mixed"
    HARD = "hard"


@dataclass(frozen=True)
class ExperimentConfig:
    feature_groups: tuple[str, ...]
    sampling_strategy: SamplingStrategy = SamplingStrategy.UNIFORM
    negative_ratio: int = 1
    objective: str = DEFAULT_OBJECTIVE
    seed: int = 20261025
    k_values: tuple[int, ...] = DEFAULT_K
    category_depth: int = 3
    popularity_transform: str = "raw"
    iterations: int = DEFAULT_ITERATIONS
    eval_metric: str = DEFAULT_EVAL_METRIC
    popularity_smoothing: float = DEFAULT_POPULARITY_SMOOTHING
    mixed_uniform_fraction: float = DEFAULT_MIXED_UNIFORM_FRACTION

    def validate(self) -> None:
        if self.objective not in OBJECTIVE_CANDIDATES:
            raise ValueError(f"Unsupported CatBoost objective: {self.objective}")
        if self.negative_ratio <= 0:
            raise ValueError("negative_ratio must be positive")
        if not self.k_values or any(k <= 0 for k in self.k_values):
            raise ValueError("k_values must contain positive integers")
        unknown = set(self.feature_groups) - FEATURE_GROUPS.keys()
        if unknown:
            raise ValueError(f"Unknown feature groups: {sorted(unknown)}")
        pending = set(self.feature_groups) & PENDING_FEATURE_GROUPS.keys()
        if pending:
            reasons = "; ".join(PENDING_FEATURE_GROUPS[g] for g in sorted(pending))
            raise ValueError(f"Pending feature group contract: {reasons}")
        if self.category_depth not in {1, 2, 3}:
            raise ValueError("category_depth must be one of 1, 2, 3")
        if self.popularity_transform not in {"raw", "log1p"}:
            raise ValueError("popularity_transform must be raw or log1p")
        if self.iterations <= 0:
            raise ValueError("iterations must be positive")
        if self.eval_metric != DEFAULT_EVAL_METRIC:
            raise ValueError(
                f"eval_metric must stay fixed at {DEFAULT_EVAL_METRIC} during comparisons"
            )
        if not math.isfinite(self.popularity_smoothing) or self.popularity_smoothing < 0:
            raise ValueError("popularity_smoothing must be non-negative")
        if (
            not math.isfinite(self.mixed_uniform_fraction)
            or not 0 <= self.mixed_uniform_fraction <= 1
        ):
            raise ValueError("mixed_uniform_fraction must be between 0 and 1")


@dataclass(frozen=True)
class RankingMetric:
    ndcg: float
    recall: float
    mrr: float
    hit_rate: float


@dataclass(frozen=True)
class InnerTrainItemFeatures:
    """Candidate features rebuilt from one region's inner-train TL only.

    ``partition_by_trip`` contains raw keys and is intentionally in-memory only.
    ``item_features`` preserves the caller's AI Hub candidate inventory and static
    features, replacing only I3/I4 with values recomputed from inner-train rows.
    """

    partition_by_trip: Mapping[str, str]
    item_features: tuple[Mapping[str, Any], ...]
    _provenance_token: object = field(default=None, repr=False, compare=False)


_INNER_TRAIN_MATERIALIZATION_TOKEN = object()


@dataclass(frozen=True, init=False)
class CandidateInventory:
    """Sorted immutable candidate universe for one region.

    Uniform sampling from this object draws indices into the compressed
    available catalog, avoiding a full sorted catalog difference per query.
    """

    region: str
    items: tuple[str, ...]
    _item_index: Mapping[str, int] = field(repr=False, compare=False)

    @classmethod
    def from_items(cls, items: Iterable[str], *, region: str) -> CandidateInventory:
        clean_region = str(region).strip()
        if not clean_region:
            raise ValueError("Candidate inventory requires a region")
        values = tuple(items)
        if any(not isinstance(item, str) for item in values):
            raise ValueError("Candidate inventory ids must be strings")
        clean_items = tuple(sorted(set(values)))
        if not clean_items:
            raise ValueError("Candidate inventory must not be empty")
        instance = object.__new__(cls)
        object.__setattr__(instance, "region", clean_region)
        object.__setattr__(instance, "items", clean_items)
        object.__setattr__(
            instance,
            "_item_index",
            MappingProxyType({item: index for index, item in enumerate(clean_items)}),
        )
        return instance


@dataclass(frozen=True, init=False)
class PreparedItemCatalog:
    """Immutable normalized item columns derived from helper materialization.

    Query scoring reads only from this cache and the exact materialization it
    was built from. This keeps I3/I4 provenance checkable without repeating a
    Python row-by-row comparison for every validation query.
    """

    materialization: InnerTrainItemFeatures = field(repr=False, compare=False)
    region: str
    item_ids: tuple[str, ...]
    feature_columns: tuple[str, ...]
    item_columns: Mapping[str, tuple[Any, ...]] = field(repr=False, compare=False)
    inventory: CandidateInventory
    _normalization_key: tuple[Any, ...] = field(repr=False, compare=False)
    _provenance_token: object = field(default=None, repr=False, compare=False)

    @classmethod
    def from_materialization(
        cls,
        materialization: InnerTrainItemFeatures,
        config: ExperimentConfig,
        *,
        region: str,
    ) -> PreparedItemCatalog:
        if materialization._provenance_token is not _INNER_TRAIN_MATERIALIZATION_TOKEN:
            raise ValueError("Catalog features lack runner materialization provenance")
        selected = selected_feature_columns(config)
        rows = materialization.item_features
        if not rows:
            raise ValueError("Materialized candidate catalog must not be empty")
        region = str(region).strip()
        item_regions = {str(row.get("region", "")).strip() for row in rows}
        if item_regions != {region}:
            raise ValueError("Prepared candidate catalog must contain one matching region")
        # Keep the immutable feature tuples in the inventory's lexical order.
        # Scoring can then slice each cached column directly instead of building
        # and retaining a second item-id -> row-index map for the full catalog.
        rows = sorted(rows, key=lambda row: str(row.get("item_id", "")).strip())
        ids = tuple(str(row.get("item_id", "")).strip() for row in rows)
        if any(not item for item in ids) or any(left == right for left, right in pairwise(ids)):
            raise ValueError("Materialized item inventory must have unique non-empty ids")

        # Feature ownership comes from the experiment contract. Missing item
        # columns fail closed; query-context columns cannot be overridden by
        # similarly named static catalog fields.
        item_feature_columns = _item_feature_columns(config)
        missing = {
            column for column in item_feature_columns
            if any(column not in row for row in rows)
        }
        if missing:
            raise ValueError(
                f"Materialized candidate catalog missing item features: {sorted(missing)}"
            )
        normalized: dict[str, tuple[Any, ...]] = {}
        for column in item_feature_columns:
            normalized[column] = tuple(
                normalize_feature_value(column, row[column], config) for row in rows
            )
        inventory = CandidateInventory.from_items(ids, region=region)
        if inventory.items != ids:
            raise ValueError("Prepared feature columns must align with the candidate inventory")
        instance = object.__new__(cls)
        object.__setattr__(instance, "materialization", materialization)
        object.__setattr__(instance, "region", region)
        object.__setattr__(instance, "item_ids", ids)
        object.__setattr__(instance, "feature_columns", selected)
        object.__setattr__(instance, "item_columns", MappingProxyType(normalized))
        object.__setattr__(instance, "inventory", inventory)
        object.__setattr__(instance, "_normalization_key", _normalization_key(config))
        object.__setattr__(instance, "_provenance_token", _INNER_TRAIN_MATERIALIZATION_TOKEN)
        return instance


def materialize_inner_train_item_features(
    *,
    trip_owner: Mapping[str, str],
    item_features: Iterable[Mapping[str, Any]],
    positive_interactions: Iterable[Mapping[str, Any]],
    visit_events: Iterable[Mapping[str, Any]] | None,
    split_seed: str | int,
    validation_fraction: float = 0.2,
) -> InnerTrainItemFeatures:
    """Wire the #80 traveler split and I3/I4 recomputation into this runner.

    Inputs are one region at a time. ``positive_interactions`` must contain
    ``TRAVEL_ID``, ``POI_ID``, ``observed_positive=1``, and ``source_split=TL``.
    ``visit_events`` must be the corresponding TL ``TN_VISIT_AREA_INFO`` event
    rows. Any existing I3/I4 values on ``item_features`` are discarded, so
    full-TL aggregates cannot be reused in inner-validation.
    """
    partition_by_trip = deterministic_traveler_group_split(
        trip_owner, seed=split_seed, validation_fraction=validation_fraction
    )

    candidates = [dict(row) for row in item_features]
    if not candidates:
        raise ValueError("AI Hub candidate item features must not be empty")
    item_ids: list[str] = []
    regions: set[str] = set()
    for row in candidates:
        item_id = str(row.get("item_id", "")).strip()
        region = str(row.get("region", "")).strip()
        if not item_id or not region:
            raise ValueError("Candidate feature rows require item_id and region")
        item_ids.append(item_id)
        regions.add(region)
    if len(regions) != 1:
        raise ValueError("Inner-train feature materialization requires one region")
    if len(set(item_ids)) != len(item_ids):
        raise ValueError("AI Hub candidate inventory contains duplicate item ids")

    # Always replace, never trust precomputed outer-TL I3/I4 columns.
    i3 = recompute_inner_train_positive_interaction_count(
        positive_interactions, partition_by_trip, all_item_ids=item_ids
    )
    i4 = recompute_inner_train_visit_type_codes(
        visit_events, partition_by_trip, all_item_ids=item_ids
    )
    for row, item_id in zip(candidates, item_ids, strict=True):
        row["train_positive_interaction_count"] = i3[item_id]
        row["train_observed_visit_type_codes"] = tuple(i4[item_id])
        row["item_id"] = item_id
        row["region"] = next(iter(regions))

    return InnerTrainItemFeatures(
        partition_by_trip=MappingProxyType(dict(partition_by_trip)),
        item_features=tuple(MappingProxyType(row) for row in candidates),
        _provenance_token=_INNER_TRAIN_MATERIALIZATION_TOKEN,
    )


def _validate_inner_train_materialization_rows(
    frame: Any,
    *,
    materialization: InnerTrainItemFeatures,
    expected_partition: str,
    derived_columns: Sequence[str],
) -> None:
    """Bind every model row to exact helper output and its traveler split."""
    if materialization._provenance_token is not _INNER_TRAIN_MATERIALIZATION_TOKEN:
        raise ValueError("Train-derived features lack runner materialization provenance")
    required = {"item_id", "trip_id", *derived_columns}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError("Train-derived model rows require item/trip provenance columns")

    by_item = {str(row["item_id"]): row for row in materialization.item_features}
    for item_id, trip_id, *feature_values in frame[
        ["item_id", "trip_id", *derived_columns]
    ].itertuples(index=False, name=None):
        item_key = str(item_id).strip()
        trip_key = str(trip_id).strip()
        source = by_item.get(item_key)
        if source is None:
            raise ValueError("Model row is outside the materialized AI Hub candidate inventory")
        if materialization.partition_by_trip.get(trip_key) != expected_partition:
            raise ValueError("Model query does not match the materialized inner partition")
        for column, actual in zip(derived_columns, feature_values, strict=True):
            expected = source[column]
            equal = actual == expected
            if column == "train_observed_visit_type_codes" and isinstance(actual, (list, tuple)):
                equal = tuple(actual) == tuple(expected)
            if not equal:
                raise ValueError("Model row train-derived features do not match inner-train materialization")


TRAIN_DERIVED_COLUMNS = frozenset({
    column for group in TRAIN_DERIVED_GROUPS for column in FEATURE_GROUPS[group]
})


def available_feature_groups() -> tuple[str, ...]:
    return tuple(g for g in FEATURE_GROUPS if g not in PENDING_FEATURE_GROUPS)


def feature_group_combinations(
    groups: Sequence[str] | None = None,
    *,
    include_empty: bool = False,
) -> tuple[tuple[str, ...], ...]:
    selected = tuple(groups or available_feature_groups())
    unknown = set(selected) - FEATURE_GROUPS.keys()
    pending = set(selected) & PENDING_FEATURE_GROUPS.keys()
    if unknown:
        raise ValueError(f"Unknown feature groups: {sorted(unknown)}")
    if pending:
        raise ValueError("Pending feature groups cannot be searched yet")
    start = 0 if include_empty else 1
    return tuple(
        combo
        for size in range(start, len(selected) + 1)
        for combo in combinations(selected, size)
    )


def selected_feature_columns(config: ExperimentConfig) -> tuple[str, ...]:
    config.validate()
    columns: list[str] = []
    for group in config.feature_groups:
        group_columns = list(FEATURE_GROUPS[group])
        if group == "I1_CATEGORY":
            group_columns = group_columns[:config.category_depth]
        columns.extend(group_columns)
    return tuple(dict.fromkeys(columns))


def _normalization_key(config: ExperimentConfig) -> tuple[Any, ...]:
    return (
        selected_feature_columns(config),
        config.category_depth,
        config.popularity_transform,
    )


def _item_feature_columns(config: ExperimentConfig) -> tuple[str, ...]:
    item_groups = {
        "I1_CATEGORY", "I2_ADMINISTRATIVE_LOCATION", "I3_POPULARITY",
        "I4_HISTORICAL_POI", "C1_REGION",
    }
    return tuple(dict.fromkeys(
        column
        for group in config.feature_groups if group in item_groups
        for column in (
            FEATURE_GROUPS[group][:config.category_depth]
            if group == "I1_CATEGORY" else FEATURE_GROUPS[group]
        )
    ))


def _query_feature_columns(config: ExperimentConfig) -> tuple[str, ...]:
    item_columns = set(_item_feature_columns(config))
    return tuple(
        column for column in selected_feature_columns(config)
        if column not in item_columns
    )

def categorical_feature_columns(config: ExperimentConfig) -> tuple[str, ...]:
    return tuple(
        c for c in selected_feature_columns(config) if c in CATEGORICAL_COLUMNS
    )


def normalize_feature_value(
    column: str,
    value: Any,
    config: ExperimentConfig,
) -> Any:
    if column == "train_positive_interaction_count":
        numeric = 0.0 if _is_missing_value(value) else float(value)
        if numeric < 0:
            raise ValueError("Popularity count must be non-negative")
        if config.popularity_transform == "log1p":
            return math.log1p(numeric)
    if column == "train_observed_visit_type_codes":
        if _is_missing_value(value):
            return CATBOOST_MISSING_CATEGORY
        if isinstance(value, (list, tuple, set, frozenset)):
            return "|".join(sorted(
                CATBOOST_MISSING_CATEGORY if _is_missing_value(part) else str(part)
                for part in value
            ))
    if column in CATEGORICAL_COLUMNS:
        if _is_missing_value(value):
            return CATBOOST_MISSING_CATEGORY
        return str(value)
    return value


def _is_missing_value(value: Any) -> bool:
    """Recognize common null values without requiring pandas at import time."""

    if value is None:
        return True
    if value.__class__.__name__ in {"NAType", "NaTType"}:
        return True
    try:
        return math.isnan(value)
    except (TypeError, ValueError):
        return False


def filter_region_candidates(
    item_regions: Mapping[str, str],
    item_inventory: Iterable[str],
    target_region: str,
) -> tuple[str, ...]:
    """Filter the AI Hub item inventory to the request region.

    Eligibility is not restricted to items observed in the training split. The
    caller supplies the AI Hub inventory for which the configured candidate
    feature contract can be materialized; validation positives remain external
    ground truth. Do not build this inventory from train-observed items.
    """

    return tuple(sorted(
        item
        for item in set(item_inventory)
        if item_regions.get(item) == target_region
    ))


def validate_train_derived_scope(
    config: ExperimentConfig,
    source_scope: str | None,
) -> None:
    selected = set(config.feature_groups) & TRAIN_DERIVED_GROUPS
    if selected and source_scope != "inner-train":
        raise ValueError(
            "Train-derived features must be recomputed from inner-train only; "
            "full-TL aggregates would leak inner-validation interactions."
        )


def validate_ranking_group_layout(
    group_ids: Sequence[Any],
    labels: Sequence[int | float],
    *,
    require_both_labels: bool = True,
) -> None:
    """Require contiguous groups; training groups also need both binary labels."""

    if len(group_ids) != len(labels):
        raise ValueError("group_ids and labels must have the same length")
    if not group_ids:
        raise ValueError("ranking data must contain at least one row")

    closed: set[Any] = set()
    current = group_ids[0]
    current_labels: set[float] = set()

    def close_group(values: set[float]) -> None:
        if require_both_labels and not ({0.0, 1.0} <= values):
            raise ValueError(
                "Each training ranking group needs label 1 and sampled label 0"
            )

    for group, label in zip(group_ids, labels, strict=True):
        numeric = float(label)
        if numeric not in {0.0, 1.0}:
            raise ValueError("ranking labels must be binary 0/1")
        if group != current:
            close_group(current_labels)
            closed.add(current)
            if group in closed:
                raise ValueError("Rows for each ranking group must be contiguous")
            current = group
            current_labels = set()
        current_labels.add(numeric)
    close_group(current_labels)


def _weighted_without_replacement(
    items: Sequence[str],
    weights: Mapping[str, float],
    count: int,
    rng: random.Random,
) -> list[str]:
    remaining = list(items)
    chosen: list[str] = []
    for _ in range(min(count, len(remaining))):
        ws = [max(0.0, float(weights.get(item, 0.0))) for item in remaining]
        total = sum(ws)
        if total <= 0:
            item = rng.choice(remaining)
        else:
            threshold = rng.random() * total
            cumulative = 0.0
            item = remaining[-1]
            for candidate, weight in zip(remaining, ws, strict=True):
                cumulative += weight
                if cumulative >= threshold:
                    item = candidate
                    break
        chosen.append(item)
        remaining.remove(item)
    return chosen


def _available_rank_to_catalog_index(rank: int, excluded: Sequence[int]) -> int:
    """Map a zero-based rank in catalog-minus-exclusions to catalog index."""
    low = rank
    high = rank + len(excluded)
    target_count = rank + 1
    while low < high:
        mid = (low + high) // 2
        available_through_mid = mid + 1 - bisect.bisect_right(excluded, mid)
        if available_through_mid >= target_count:
            high = mid
        else:
            low = mid + 1
    return low


def sample_unobserved(
    candidate_items: Iterable[str] | CandidateInventory,
    positive_items: Iterable[str],
    *,
    strategy: SamplingStrategy,
    ratio: int,
    seed: int,
    popularity: Mapping[str, float] | None = None,
    hard_scores: Mapping[str, float] | None = None,
    statistics_scope: str | None = None,
    popularity_smoothing: float = DEFAULT_POPULARITY_SMOOTHING,
    mixed_uniform_fraction: float = DEFAULT_MIXED_UNIFORM_FRACTION,
) -> tuple[str, ...]:
    if ratio <= 0:
        raise ValueError("ratio must be positive")
    if not math.isfinite(popularity_smoothing) or popularity_smoothing < 0:
        raise ValueError("popularity_smoothing must be non-negative")
    if (
        not math.isfinite(mixed_uniform_fraction)
        or not 0 <= mixed_uniform_fraction <= 1
    ):
        raise ValueError("mixed_uniform_fraction must be between 0 and 1")
    if strategy != SamplingStrategy.UNIFORM and statistics_scope != "inner-train":
        raise ValueError(
            "Weighted or hard sampling statistics must come from inner-train only"
        )

    positives = set(positive_items)
    rng = random.Random(seed)
    if isinstance(candidate_items, CandidateInventory):
        inventory = candidate_items
        excluded = sorted(
            inventory._item_index[item]
            for item in positives
            if item in inventory._item_index
        )
        available_count = len(inventory.items) - len(excluded)
        count = min(available_count, len(positives) * ratio)
        if count == 0:
            return ()
        if strategy == SamplingStrategy.UNIFORM:
            ranks = rng.sample(range(available_count), count)
            return tuple(sorted(
                inventory.items[_available_rank_to_catalog_index(rank, excluded)]
                for rank in ranks
            ))
        available = [item for item in inventory.items if item not in positives]
    else:
        available = sorted(set(candidate_items) - positives)
        count = min(len(available), len(positives) * ratio)
        if count == 0:
            return ()
        if strategy == SamplingStrategy.UNIFORM:
            return tuple(sorted(rng.sample(available, count)))

    if strategy == SamplingStrategy.POPULARITY_WEIGHTED:
        weights = {
            item: popularity_smoothing + max(
                0.0, float((popularity or {}).get(item, 0.0))
            )
            for item in available
        }
        return tuple(sorted(_weighted_without_replacement(
            available, weights, count, rng
        )))

    if strategy == SamplingStrategy.MIXED:
        uniform_count = int(count * mixed_uniform_fraction)
        uniform = rng.sample(available, uniform_count)
        remaining = [item for item in available if item not in set(uniform)]
        weights = {
            item: popularity_smoothing + max(
                0.0, float((popularity or {}).get(item, 0.0))
            )
            for item in remaining
        }
        weighted = _weighted_without_replacement(
            remaining, weights, count - uniform_count, rng
        )
        return tuple(sorted({*uniform, *weighted}))

    if hard_scores is None:
        raise ValueError("hard sampling requires hard_scores")
    missing_scores = set(available) - set(hard_scores)
    if missing_scores:
        raise ValueError("hard sampling requires a score for every available candidate")
    ranked = sorted(
        available,
        key=lambda item: (-float(hard_scores.get(item, float("-inf"))), item),
    )
    return tuple(sorted(ranked[:count]))


def sampling_search_configs(
    feature_groups: Sequence[str],
    *,
    objective: str = DEFAULT_OBJECTIVE,
    seed: int = 20261025,
    popularity_smoothing: float = DEFAULT_POPULARITY_SMOOTHING,
    mixed_uniform_fraction: float = DEFAULT_MIXED_UNIFORM_FRACTION,
) -> tuple[ExperimentConfig, ...]:
    return tuple(
        ExperimentConfig(
            tuple(feature_groups),
            sampling_strategy=strategy,
            negative_ratio=ratio,
            objective=objective,
            seed=seed,
            popularity_smoothing=popularity_smoothing,
            mixed_uniform_fraction=mixed_uniform_fraction,
        )
        for strategy in SamplingStrategy
        for ratio in DEFAULT_NEGATIVE_RATIOS
    )


def feature_search_configs(
    *,
    sampling_strategy: SamplingStrategy,
    negative_ratio: int,
    objective: str = DEFAULT_OBJECTIVE,
    seed: int = 20261025,
    groups: Sequence[str] | None = None,
) -> tuple[ExperimentConfig, ...]:
    return tuple(
        ExperimentConfig(
            combo,
            sampling_strategy=sampling_strategy,
            negative_ratio=negative_ratio,
            objective=objective,
            seed=seed,
        )
        for combo in feature_group_combinations(groups)
    )


def objective_search_configs(
    feature_groups: Sequence[str],
    *,
    sampling_strategy: SamplingStrategy,
    negative_ratio: int,
    seed: int = 20261025,
) -> tuple[ExperimentConfig, ...]:
    return tuple(
        ExperimentConfig(
            tuple(feature_groups),
            sampling_strategy=sampling_strategy,
            negative_ratio=negative_ratio,
            objective=objective,
            seed=seed,
        )
        for objective in OBJECTIVE_CANDIDATES
    )


def ranking_metric_at_k(
    ranked_items: Sequence[str],
    relevant_items: Iterable[str],
    k: int,
) -> RankingMetric:
    if k <= 0:
        raise ValueError("k must be positive")
    relevant = set(relevant_items)
    top = list(ranked_items[:k])
    hits = [1 if item in relevant else 0 for item in top]
    hit_count = sum(hits)
    recall = hit_count / len(relevant) if relevant else 0.0
    dcg = sum(hit / math.log2(index + 2) for index, hit in enumerate(hits))
    ideal_hits = min(len(relevant), k)
    idcg = sum(1.0 / math.log2(index + 2) for index in range(ideal_hits))
    ndcg = dcg / idcg if idcg else 0.0
    first = next((index + 1 for index, hit in enumerate(hits) if hit), None)
    mrr = 1.0 / first if first else 0.0
    return RankingMetric(
        ndcg=ndcg,
        recall=recall,
        mrr=mrr,
        hit_rate=1.0 if hit_count else 0.0,
    )


def aggregate_ranking_metrics(
    query_rankings: Iterable[tuple[Sequence[str], Iterable[str]]],
    *,
    k_values: Sequence[int] = DEFAULT_K,
    profiler: Any | None = None,
) -> dict[str, float]:
    """Average query-level ranking metrics without retaining prior queries."""

    if not k_values or any(k <= 0 for k in k_values):
        raise ValueError("k_values must contain positive integers")
    names = ("ndcg", "recall", "mrr", "hit_rate")
    sums = {f"{name}@{k}": 0.0 for name in names for k in k_values}
    query_count = 0
    for ranked_items, relevant_items in query_rankings:
        query_count += 1
        # Ground truth may be a one-shot iterator. Freeze once per query so
        # each requested K sees the same relevant set.
        metric_started = time.perf_counter() if profiler is not None else 0.0
        relevant = frozenset(relevant_items)
        for k in k_values:
            metric = ranking_metric_at_k(ranked_items, relevant, k)
            for name in names:
                sums[f"{name}@{k}"] += getattr(metric, name)
        if profiler is not None:
            profiler.metric_compute_seconds += time.perf_counter() - metric_started
    if query_count == 0:
        raise ValueError("at least one validation query is required")
    return {name: value / query_count for name, value in sums.items()}


def prepare_feature_frame(frame: Any, config: ExperimentConfig) -> Any:
    """Select and normalize model columns for fit or bounded query scoring."""

    features = list(selected_feature_columns(config))
    result = frame.loc[:, features].copy()
    for column in features:
        result[column] = result[column].map(
            lambda value, c=column: normalize_feature_value(c, value, config)
        )
    return result


@dataclass(frozen=True)
class StreamingEvaluationResult:
    metrics: Mapping[str, float]
    query_count: int
    candidate_count: int
    scored_rows: int
    max_batch_rows: int


class ScoringProfiler:
    """In-memory aggregate-only instrumentation for bounded scorer profiling."""

    PROFILE_VERSION = "catboost-scoring-profile-v3"
    RSS_SAMPLE_INTERVAL_SECONDS = 0.5

    def __init__(self, *, capture_rankings: bool = False) -> None:
        self.capture_rankings = capture_rankings
        self.top_rankings: list[tuple[tuple[str, float], ...]] = []
        self.query_context_seconds: list[float] = []
        self.ground_truth_seconds: list[float] = []
        self.query_seconds: list[float] = []
        self.query_rows: list[int] = []
        self.frame_batches: list[tuple[float, int, int]] = []
        self.candidate_item_slice_seconds = 0.0
        self.query_context_broadcast_seconds = 0.0
        self.frame_container_seconds = 0.0
        self.static_item_cache_seconds = 0.0
        self.static_item_cache_bytes_estimate = 0
        self.pool_batches: list[tuple[float, int]] = []
        self.predict_batches: list[tuple[float, int]] = []
        self.top_partition_seconds = 0.0
        self.top_boundary_seconds = 0.0
        self.top_local_sort_seconds = 0.0
        self.global_merge_seconds = 0.0
        self.metric_compute_seconds = 0.0
        self.aggregate_wall_seconds = 0.0
        self.scoring_wall_seconds = 0.0
        self.scoring_user_cpu_seconds = 0.0
        self.scoring_system_cpu_seconds = 0.0
        self.scoring_sampled_peak_rss_bytes = 0
        self.scoring_after_rss_bytes = 0
        self.inference_mode = "dataframe"
        self.predict_thread_count: int | None = None
        self._rss_stop = threading.Event()
        self._rss_thread: threading.Thread | None = None
        self._scoring_started: float | None = None
        self._scoring_cpu_before: Any | None = None

    @staticmethod
    def _rss_bytes() -> int:
        try:
            with open("/proc/self/statm", encoding="ascii") as stream:
                resident_pages = int(stream.read().split()[1])
            return resident_pages * os.sysconf("SC_PAGE_SIZE")
        except (OSError, ValueError, IndexError):
            return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024)

    @staticmethod
    def _distribution(values: Sequence[float]) -> dict[str, float | int]:
        ordered = sorted(float(value) for value in values)
        if not ordered:
            return {"count": 0, "mean": 0.0, "p50": 0.0, "p95": 0.0, "max": 0.0}

        def percentile(fraction: float) -> float:
            position = (len(ordered) - 1) * fraction
            lower = int(position)
            upper = min(lower + 1, len(ordered) - 1)
            return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)

        return {
            "count": len(ordered),
            "mean": sum(ordered) / len(ordered),
            "p50": percentile(0.50),
            "p90": percentile(0.90),
            "p95": percentile(0.95),
            "p99": percentile(0.99),
            "max": ordered[-1],
        }

    def start_rss_sampling(self, *, started_at: float, cpu_before: Any) -> None:
        self._rss_stop.clear()
        self._scoring_started = started_at
        self._scoring_cpu_before = cpu_before
        self.scoring_sampled_peak_rss_bytes = self._rss_bytes()

        def sample() -> None:
            while not self._rss_stop.wait(self.RSS_SAMPLE_INTERVAL_SECONDS):
                self.scoring_sampled_peak_rss_bytes = max(
                    self.scoring_sampled_peak_rss_bytes, self._rss_bytes(),
                )

        self._rss_thread = threading.Thread(
            target=sample, name="issue82-scoring-rss-profile", daemon=True,
        )
        self._rss_thread.start()

    def stop_rss_sampling(self) -> None:
        self._rss_stop.set()
        if self._rss_thread is not None and self._rss_thread.ident is not None:
            self._rss_thread.join()
        self.scoring_after_rss_bytes = self._rss_bytes()
        self.scoring_sampled_peak_rss_bytes = max(
            self.scoring_sampled_peak_rss_bytes, self.scoring_after_rss_bytes,
        )

    @staticmethod
    def _timing_totals(values: Sequence[tuple[float, int]]) -> dict[str, float | int]:
        seconds = [entry[0] for entry in values]
        row_count = sum(entry[1] for entry in values)
        total_seconds = sum(seconds)
        return {
            "batches": len(values),
            "rows": row_count,
            "seconds": total_seconds,
            "seconds_distribution": ScoringProfiler._distribution(seconds),
            "mean_batch_seconds": total_seconds / len(values) if values else 0.0,
            "rows_per_second": row_count / total_seconds if total_seconds else 0.0,
        }

    def summary(self, *, scored_rows: int, candidate_count: int) -> dict[str, object]:
        frame_seconds = sum(row[0] for row in self.frame_batches)
        pool_seconds = sum(row[0] for row in self.pool_batches)
        predict_seconds = sum(row[0] for row in self.predict_batches)
        frame_rows = sum(row[1] for row in self.frame_batches)
        query_rates = [
            rows / seconds if seconds else 0.0
            for rows, seconds in zip(self.query_rows, self.query_seconds, strict=False)
        ]
        tracked = (
            sum(self.query_context_seconds) + sum(self.ground_truth_seconds)
            + frame_seconds + pool_seconds + predict_seconds + self.top_partition_seconds
            + self.top_boundary_seconds + self.top_local_sort_seconds
            + self.global_merge_seconds + self.metric_compute_seconds
            + self.static_item_cache_seconds
        )
        return {
            "profile_version": self.PROFILE_VERSION,
            "query_context_normalization_seconds": self._distribution(self.query_context_seconds),
            "ground_truth_preparation_seconds": self._distribution(self.ground_truth_seconds),
            "frame_build": {
                "batches": len(self.frame_batches),
                "rows": frame_rows,
                "columns": sorted({row[2] for row in self.frame_batches}),
                "seconds": frame_seconds,
                "mean_batch_seconds": frame_seconds / len(self.frame_batches) if self.frame_batches else 0.0,
                "milliseconds_per_million_rows": (
                    frame_seconds * 1_000_000_000 / frame_rows if frame_rows else 0.0
                ),
                "candidate_item_slice_seconds": self.candidate_item_slice_seconds,
                "query_context_broadcast_seconds": self.query_context_broadcast_seconds,
                "container_construction_seconds": self.frame_container_seconds,
                "static_item_cache_seconds": self.static_item_cache_seconds,
                "static_item_cache_bytes_estimate": self.static_item_cache_bytes_estimate,
            },
            "predict": self._timing_totals(self.predict_batches),
            "pool_build": self._timing_totals(self.pool_batches),
            "inference_mode": self.inference_mode,
            "predict_thread_count": self.predict_thread_count,
            "top_k": {
                "partition_seconds": self.top_partition_seconds,
                "boundary_tie_seconds": self.top_boundary_seconds,
                "local_sort_seconds": self.top_local_sort_seconds,
                "global_merge_seconds": self.global_merge_seconds,
            },
            "metric_compute_seconds": self.metric_compute_seconds,
            "aggregate_ranking_wall_seconds": self.aggregate_wall_seconds,
            "scoring_wall_seconds": self.scoring_wall_seconds,
            "unaccounted_seconds": self.scoring_wall_seconds - tracked,
            "query_elapsed_seconds": self._distribution(self.query_seconds),
            "query_rows_per_second": self._distribution(query_rates),
            "scored_rows": scored_rows,
            "candidate_count": candidate_count,
            "scoring_process_user_cpu_seconds": self.scoring_user_cpu_seconds,
            "scoring_process_system_cpu_seconds": self.scoring_system_cpu_seconds,
            "scoring_cpu_utilization": (
                (self.scoring_user_cpu_seconds + self.scoring_system_cpu_seconds)
                / self.scoring_wall_seconds if self.scoring_wall_seconds else 0.0
            ),
            "scoring_sampled_peak_rss_mib": round(
                self.scoring_sampled_peak_rss_bytes / 1024**2, 2,
            ),
            "scoring_rss_sampling_interval_ms": round(self.RSS_SAMPLE_INTERVAL_SECONDS * 1000),
            "scoring_after_rss_mib": round(self.scoring_after_rss_bytes / 1024**2, 2),
            "batch_rows_per_second": scored_rows / predict_seconds if predict_seconds else 0.0,
            "frame_rows_per_second": frame_rows / frame_seconds if frame_seconds else 0.0,
            "top_k_rankings_captured": len(self.top_rankings),
        }


def _top_scored_items(
    item_ids: Sequence[str], raw_scores: Any, limit: int,
    *, profiler: ScoringProfiler | None = None,
) -> list[tuple[str, float]]:
    """Return exact lexical-tiebroken top-K from one lexically ordered batch."""
    if limit <= 0:
        raise ValueError("Top-K limit must be positive")
    try:
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("numpy is required for bounded CatBoost scoring") from exc

    scores = np.asarray(raw_scores, dtype=np.float64)
    if scores.ndim != 1 or len(scores) != len(item_ids):
        raise ValueError("Model returned a score count that does not match the batch")
    if not np.isfinite(scores).all():
        raise ValueError("Model returned a non-finite ranking score")

    if len(item_ids) <= limit:
        positions = range(len(item_ids))
    else:
        threshold_index = len(item_ids) - limit
        partition_started = time.perf_counter() if profiler is not None else 0.0
        threshold = np.partition(scores, threshold_index)[threshold_index]
        if profiler is not None:
            profiler.top_partition_seconds += time.perf_counter() - partition_started
        boundary_started = time.perf_counter() if profiler is not None else 0.0
        above = np.flatnonzero(scores > threshold)
        tied = np.flatnonzero(scores == threshold)
        # Candidate IDs are lexically ordered, so the first boundary ties are
        # exactly the legacy (-score, item_id) order without sorting the batch.
        boundary_count = limit - len(above)
        positions = [int(index) for index in above]
        positions.extend(int(index) for index in tied[:boundary_count])
        if profiler is not None:
            profiler.top_boundary_seconds += time.perf_counter() - boundary_started

    sort_started = time.perf_counter() if profiler is not None else 0.0
    result = sorted(
        ((item_ids[index], float(scores[index])) for index in positions),
        key=lambda row: (-row[1], row[0]),
    )
    if profiler is not None:
        profiler.top_local_sort_seconds += time.perf_counter() - sort_started
    return result


def _profile_scoring_call(
    function: Callable[..., StreamingEvaluationResult],
) -> Callable[..., StreamingEvaluationResult]:
    """Guarantee profiler cleanup and final timing capture on success or failure."""

    @wraps(function)
    def wrapped(*args: Any, **kwargs: Any) -> StreamingEvaluationResult:
        profiler = kwargs.get("profiler")
        if profiler is None:
            return function(*args, **kwargs)
        call_started = time.perf_counter()
        cpu_before = resource.getrusage(resource.RUSAGE_SELF)
        profiler._scoring_started = None
        profiler._scoring_cpu_before = None
        profiler.aggregate_wall_seconds = 0.0
        try:
            return function(*args, **kwargs)
        finally:
            try:
                scoring_started = profiler._scoring_started or call_started
                cpu_start = profiler._scoring_cpu_before or cpu_before
                elapsed = time.perf_counter() - scoring_started
                if profiler.aggregate_wall_seconds == 0.0:
                    profiler.aggregate_wall_seconds = elapsed
                profiler.scoring_wall_seconds = elapsed
                cpu_after = resource.getrusage(resource.RUSAGE_SELF)
                profiler.scoring_user_cpu_seconds = cpu_after.ru_utime - cpu_start.ru_utime
                profiler.scoring_system_cpu_seconds = cpu_after.ru_stime - cpu_start.ru_stime
            finally:
                try:
                    profiler.stop_rss_sampling()
                finally:
                    profiler._scoring_started = None
                    profiler._scoring_cpu_before = None

    return wrapped


@_profile_scoring_call
def score_inner_validation_queries(
    model: Any,
    catalog: PreparedItemCatalog,
    query_ground_truth: Iterable[tuple[str, Iterable[str]]],
    *,
    query_features: Mapping[str, Mapping[str, Any]],
    config: ExperimentConfig,
    max_rows_per_batch: int = 2048,
    profiler: ScoringProfiler | None = None,
    progress_callback: Callable[[dict[str, object]], None] | None = None,
    progress_interval: int = 0,
    progress_total: int = 0,
    inference_mode: str = "dataframe",
    predict_thread_count: int | None = None,
) -> StreamingEvaluationResult:
    """Score the region inventory in bounded chunks, one query at a time.

    The catalog must come from ``materialize_inner_train_item_features`` and
    must be prepared for the same feature transform. Query IDs are checked
    against the helper's split before scoring. The row bound applies to each
    prediction frame; the immutable prepared catalog itself remains resident.
    """
    if max_rows_per_batch <= 0:
        raise ValueError("max_rows_per_batch must be positive")
    if inference_mode not in {
        "dataframe", "dataframe_cached_items", "dataframe_pool", "numpy_pool", "numpy_array",
    }:
        raise ValueError("Unsupported prediction input mode")
    if predict_thread_count is not None and predict_thread_count <= 0:
        raise ValueError("predict_thread_count must be positive when provided")
    if catalog._provenance_token is not _INNER_TRAIN_MATERIALIZATION_TOKEN:
        raise ValueError("Prepared candidate catalog lacks runner provenance")
    if catalog.materialization._provenance_token is not _INNER_TRAIN_MATERIALIZATION_TOKEN:
        raise ValueError("Candidate features lack runner materialization provenance")
    if catalog._normalization_key != _normalization_key(config):
        raise ValueError("Prepared catalog normalization does not match experiment config")
    if catalog.feature_columns != selected_feature_columns(config):
        raise ValueError("Prepared catalog feature columns do not match experiment config")
    if catalog.inventory.region != catalog.region:
        raise ValueError("Candidate inventory region does not match prepared catalog")
    if not catalog.inventory.items:
        raise ValueError("Same-region candidate inventory must not be empty")

    if profiler is not None:
        profiler.inference_mode = inference_mode
        profiler.predict_thread_count = predict_thread_count

    try:
        import pandas as pd
    except ImportError as exc:
        raise RuntimeError("pandas is required for bounded CatBoost scoring") from exc

    item_columns = set(_item_feature_columns(config))
    query_columns = _query_feature_columns(config)
    if set(catalog.item_columns) != item_columns:
        raise ValueError("Prepared catalog item columns do not match experiment contract")
    if catalog.item_ids != catalog.inventory.items:
        raise ValueError("Prepared feature columns do not align with the candidate inventory")
    categorical_columns = tuple(categorical_feature_columns(config))
    categorical_indices = tuple(
        catalog.feature_columns.index(column) for column in categorical_columns
    )
    pool_class = None
    np = None
    needs_pool = inference_mode in {"dataframe_pool", "numpy_pool"}
    if needs_pool:
        try:
            from catboost import Pool as pool_class
        except ImportError as exc:
            raise RuntimeError("CatBoost Pool is required for this prediction input mode") from exc
    if inference_mode in {"numpy_pool", "numpy_array"}:
        try:
            import numpy as np
        except ImportError as exc:
            raise RuntimeError("numpy is required for NumPy prediction input") from exc
    max_k = max(config.k_values)
    scored_rows = 0
    max_batch = 0
    query_count = 0
    scoring_started = time.perf_counter()
    cpu_before = resource.getrusage(resource.RUSAGE_SELF)
    aggregate_started = scoring_started
    if profiler is not None:
        profiler.start_rss_sampling(started_at=scoring_started, cpu_before=cpu_before)
    def scored_rankings() -> Iterable[tuple[tuple[str, ...], frozenset[str]]]:
        nonlocal scored_rows, max_batch, query_count
        static_item_frame = None
        if inference_mode == "dataframe_cached_items":
            static_columns = tuple(column for column in catalog.feature_columns if column in item_columns)
            estimated_cache_bytes = len(catalog.inventory.items) * len(static_columns) * 8
            if estimated_cache_bytes > 512 * 1024**2:
                raise ValueError("Static item cache exceeds the scorer's memory bound")
            cache_started = time.perf_counter()
            static_item_frame = pd.DataFrame(
                {column: catalog.item_columns[column] for column in static_columns},
                columns=static_columns,
            )
            if profiler is not None:
                profiler.static_item_cache_seconds += time.perf_counter() - cache_started
                profiler.static_item_cache_bytes_estimate = estimated_cache_bytes
        for query_id, relevant_items in query_ground_truth:
            query_started = time.perf_counter()
            query_key = str(query_id).strip()
            if catalog.materialization.partition_by_trip.get(query_key) != "inner-validation":
                raise ValueError("Scoring query is not in the materialized inner-validation partition")
            if query_key not in query_features:
                raise ValueError("Inner-validation query is missing authoritative context")
            source_context = query_features[query_key]
            if "region" not in source_context:
                raise ValueError("Query context region is required for same-region candidate scoring")
            if str(source_context["region"]).strip() != catalog.region:
                raise ValueError("Query context region conflicts with the prepared candidate region")
            query_count += 1
            truth_started = time.perf_counter()
            relevant = frozenset(str(item) for item in relevant_items)
            if profiler is not None:
                profiler.ground_truth_seconds.append(time.perf_counter() - truth_started)
            context_started = time.perf_counter()
            normalized_query = {
                column: normalize_feature_value(column, source_context[column], config)
                for column in query_columns if column in source_context
            }
            missing_query = set(query_columns) - set(normalized_query)
            if missing_query:
                raise ValueError(f"Query context missing selected features: {sorted(missing_query)}")
            if profiler is not None:
                profiler.query_context_seconds.append(time.perf_counter() - context_started)

            best: list[tuple[str, float]] = []
            items = catalog.inventory.items
            for start in range(0, len(items), max_rows_per_batch):
                stop = min(start + max_rows_per_batch, len(items))
                frame_started = time.perf_counter()
                item_slice_started = time.perf_counter()
                batch_ids = items[start:stop]
                item_values = {
                    column: catalog.item_columns[column][start:stop]
                    for column in catalog.feature_columns if column in item_columns
                } if static_item_frame is None else None
                static_slice = (
                    static_item_frame.iloc[start:stop]
                    if static_item_frame is not None else None
                )
                item_slice_seconds = time.perf_counter() - item_slice_started
                query_broadcast_started = time.perf_counter()
                query_values = {
                    column: [normalized_query[column]] * len(batch_ids)
                    for column in query_columns
                }
                query_broadcast_seconds = time.perf_counter() - query_broadcast_started
                container_started = time.perf_counter()
                if static_slice is not None:
                    frame = static_slice.copy(deep=False)
                    for column in query_columns:
                        frame[column] = query_values[column]
                    prediction_data = frame.loc[:, catalog.feature_columns]
                else:
                    frame_columns: dict[str, Sequence[Any]] = {
                        column: item_values[column]
                        for column in catalog.feature_columns if column in item_columns
                    }
                    frame_columns.update(query_values)
                    if inference_mode in {"numpy_pool", "numpy_array"}:
                        prediction_data = np.empty(
                            (len(batch_ids), len(catalog.feature_columns)), dtype=object,
                        )
                        for column_index, column in enumerate(catalog.feature_columns):
                            prediction_data[:, column_index] = frame_columns[column]
                    else:
                        prediction_data = pd.DataFrame(frame_columns, columns=catalog.feature_columns)
                container_seconds = time.perf_counter() - container_started
                if profiler is not None:
                    profiler.candidate_item_slice_seconds += item_slice_seconds
                    profiler.query_context_broadcast_seconds += query_broadcast_seconds
                    profiler.frame_container_seconds += container_seconds
                    profiler.frame_batches.append((time.perf_counter() - frame_started, len(batch_ids), len(catalog.feature_columns)))
                if needs_pool:
                    pool_started = time.perf_counter()
                    pool_kwargs: dict[str, Any] = {"cat_features": categorical_indices}
                    if inference_mode == "numpy_pool":
                        pool_kwargs["feature_names"] = list(catalog.feature_columns)
                    prediction_data = pool_class(prediction_data, **pool_kwargs)
                    pool_seconds = time.perf_counter() - pool_started
                    if profiler is not None:
                        profiler.pool_batches.append((pool_seconds, len(batch_ids)))
                predict_started = time.perf_counter()
                predict_kwargs = (
                    {"thread_count": predict_thread_count}
                    if predict_thread_count is not None else {}
                )
                scores = model.predict(prediction_data, **predict_kwargs)
                predict_seconds = time.perf_counter() - predict_started
                if profiler is not None:
                    profiler.predict_batches.append((predict_seconds, len(batch_ids)))
                batch_scored = _top_scored_items(batch_ids, scores, max_k, profiler=profiler)
                scored_rows += len(batch_ids)
                max_batch = max(max_batch, len(batch_ids))
                merge_started = time.perf_counter() if profiler is not None else 0.0
                best = sorted((*best, *batch_scored), key=lambda row: (-row[1], row[0]))[:max_k]
                if profiler is not None:
                    profiler.global_merge_seconds += time.perf_counter() - merge_started
            if profiler is not None:
                profiler.query_seconds.append(time.perf_counter() - query_started)
                profiler.query_rows.append(len(items))
                if profiler.capture_rankings:
                    profiler.top_rankings.append(tuple(best))
            yield tuple(item for item, _ in best), relevant
            if (
                profiler is not None and progress_callback is not None
                and progress_interval > 0
                and (
                    query_count % progress_interval == 0
                    or (progress_total > 0 and query_count == progress_total)
                )
            ):
                elapsed = time.perf_counter() - scoring_started
                frame_seconds = sum(row[0] for row in profiler.frame_batches)
                predict_seconds = sum(row[0] for row in profiler.predict_batches)
                top_k_seconds = (
                    profiler.top_partition_seconds + profiler.top_boundary_seconds
                    + profiler.top_local_sort_seconds + profiler.global_merge_seconds
                )
                query_context_seconds = sum(profiler.query_context_seconds)
                ground_truth_seconds = sum(profiler.ground_truth_seconds)
                tracked_seconds = (
                    query_context_seconds + ground_truth_seconds + frame_seconds
                    + sum(row[0] for row in profiler.pool_batches)
                    + predict_seconds + top_k_seconds + profiler.metric_compute_seconds
                    + profiler.static_item_cache_seconds
                )
                cpu_now = resource.getrusage(resource.RUSAGE_SELF)
                query_rates = [
                    rows / seconds if seconds else 0.0
                    for rows, seconds in zip(
                        profiler.query_rows, profiler.query_seconds, strict=False,
                    )
                ]
                progress_callback({
                    "queries_completed": query_count,
                    "scored_rows": scored_rows,
                    "elapsed_seconds": elapsed,
                    "current_rss_mib": round(profiler._rss_bytes() / 1024**2, 2),
                    "scoring_sampled_peak_rss_mib": round(
                        profiler.scoring_sampled_peak_rss_bytes / 1024**2, 2,
                    ),
                    "scoring_rss_sampling_interval_ms": round(
                        ScoringProfiler.RSS_SAMPLE_INTERVAL_SECONDS * 1000,
                    ),
                    "query_context_seconds": query_context_seconds,
                    "ground_truth_seconds": ground_truth_seconds,
                    "frame_seconds": frame_seconds,
                    "candidate_item_slice_seconds": profiler.candidate_item_slice_seconds,
                    "query_context_broadcast_seconds": profiler.query_context_broadcast_seconds,
                    "frame_container_seconds": profiler.frame_container_seconds,
                    "static_item_cache_seconds": profiler.static_item_cache_seconds,
                    "pool_build_seconds": sum(row[0] for row in profiler.pool_batches),
                    "predict_seconds": predict_seconds,
                    "top_k_seconds": top_k_seconds,
                    "metric_seconds": profiler.metric_compute_seconds,
                    "unaccounted_seconds": elapsed - tracked_seconds,
                    "user_cpu_seconds": cpu_now.ru_utime - cpu_before.ru_utime,
                    "system_cpu_seconds": cpu_now.ru_stime - cpu_before.ru_stime,
                    "query_elapsed_seconds": ScoringProfiler._distribution(profiler.query_seconds),
                    "query_rows_per_second": ScoringProfiler._distribution(query_rates),
                    "rows_per_second": scored_rows / elapsed if elapsed else 0.0,
                })

    metrics = aggregate_ranking_metrics(
        scored_rankings(), k_values=config.k_values, profiler=profiler,
    )
    if profiler is not None:
        profiler.aggregate_wall_seconds = time.perf_counter() - aggregate_started
    return StreamingEvaluationResult(
        metrics=MappingProxyType(metrics),
        query_count=query_count,
        candidate_count=len(catalog.inventory.items),
        scored_rows=scored_rows,
        max_batch_rows=max_batch,
    )


def catboost_model_params(config: ExperimentConfig) -> dict[str, Any]:
    config.validate()
    return {
        "loss_function": config.objective,
        "eval_metric": config.eval_metric,
        "iterations": config.iterations,
        "use_best_model": False,
        "random_seed": config.seed,
        "allow_writing_files": False,
        "verbose": False,
    }


def fit_catboost(
    train_frame: Any,
    validation_frame: Any | None = None,
    *,
    label_column: str,
    group_column: str,
    config: ExperimentConfig,
    train_derived_source_scope: str | None = None,
    inner_train_materialization: InnerTrainItemFeatures | None = None,
) -> Any:
    """Thin adapter; Issue #82 owns actual CatBoost execution and tuning."""

    config.validate()
    validate_train_derived_scope(config, train_derived_source_scope)
    features = list(selected_feature_columns(config))
    categorical = list(categorical_feature_columns(config))
    derived_features = [column for column in features if column in TRAIN_DERIVED_COLUMNS]
    required = {*features, label_column, group_column}
    missing_train = required - set(train_frame.columns)
    missing_validation = (
        required - set(validation_frame.columns)
        if validation_frame is not None
        else set()
    )
    if missing_train:
        raise ValueError(f"Training frame missing: {sorted(missing_train)}")
    if missing_validation:
        raise ValueError(f"Validation frame missing: {sorted(missing_validation)}")

    if derived_features:
        if inner_train_materialization is None:
            raise ValueError(
                "I3/I4 fitting requires output from materialize_inner_train_item_features"
            )
        _validate_inner_train_materialization_rows(
            train_frame,
            materialization=inner_train_materialization,
            expected_partition="inner-train",
            derived_columns=derived_features,
        )
        if validation_frame is not None:
            _validate_inner_train_materialization_rows(
                validation_frame,
                materialization=inner_train_materialization,
                expected_partition="inner-validation",
                derived_columns=derived_features,
            )

    try:
        from catboost import CatBoostRanker, Pool
    except ImportError as exc:
        raise RuntimeError(
            "CatBoost is not installed; execution belongs to Issue #82"
        ) from exc

    validate_ranking_group_layout(
        list(train_frame[group_column]), list(train_frame[label_column])
    )
    if validation_frame is not None:
        validate_ranking_group_layout(
            list(validation_frame[group_column]),
            list(validation_frame[label_column]),
            require_both_labels=False,
        )

    train_pool = Pool(
        prepare_feature_frame(train_frame, config),
        label=train_frame[label_column],
        group_id=train_frame[group_column],
        cat_features=categorical,
    )
    model = CatBoostRanker(**catboost_model_params(config))
    if validation_frame is None:
        # The caller can score validation queries incrementally after fitting.
        # Since best-model selection is disabled, an eval set does not affect
        # the fitted model and need not be retained in memory.
        model.fit(train_pool)
    else:
        validation_pool = Pool(
            prepare_feature_frame(validation_frame, config),
            label=validation_frame[label_column],
            group_id=validation_frame[group_column],
            cat_features=categorical,
        )
        # Keep the comparison budget fixed across objectives. The validation
        # set reports a metric but never selects a different best iteration.
        model.fit(train_pool, eval_set=validation_pool)
    return model


def default_protocol() -> dict[str, Any]:
    return {
        "problem": "cold-user contextual POI ranking",
        "candidate_universe": {
            "source": "AI Hub 2023 only",
            "development": "same-region items with the configured candidate features",
            "final": "same-region items with the configured candidate features",
            "train_unseen_items": "eligible when required features are available",
            "unseen_positive": "remains external ground truth; never injected post hoc",
        },
        "split": {
            "development": "TRAVELER_ID group split; finalized by Issue #80",
            "final_holdout": "canonical validation/VL; no tuning",
        },
        "prototype_objective": DEFAULT_OBJECTIVE,
        "objective_candidates": list(OBJECTIVE_CANDIDATES),
        "objective_comparison": {
            "iterations": DEFAULT_ITERATIONS,
            "eval_metric": DEFAULT_EVAL_METRIC,
            "use_best_model": False,
            "note": (
                "Shared prototype comparison defaults; tune only after objective "
                "comparison and document the chosen budget in Issue #82."
            ),
        },
        "sampling": {
            "strategies": [s.value for s in SamplingStrategy],
            "ratios": list(DEFAULT_NEGATIVE_RATIOS),
            "label_zero":
                "sampled-unobserved comparison row, not observed dislike",
            "statistics_scope": "inner-train only",
            "popularity_smoothing": DEFAULT_POPULARITY_SMOOTHING,
            "mixed_uniform_fraction": DEFAULT_MIXED_UNIFORM_FRACTION,
            "mixed_uniform_allocation": (
                "floor(count * fraction); remainder popularity-weighted"
            ),
            "sampling_parameter_status": "prototype defaults; compare in Issue #82",
        },
        "feature_groups": {
            group: {
                "columns": list(columns),
                "status": (
                    "pending"
                    if group in PENDING_FEATURE_GROUPS
                    else (
                        "requires-inner-train-recompute"
                        if group in TRAIN_DERIVED_GROUPS
                        else "available"
                    )
                ),
                "note": PENDING_FEATURE_GROUPS.get(group),
            }
            for group, columns in FEATURE_GROUPS.items()
        },
        "metrics": ["NDCG@K", "Recall@K", "MRR@K", "HitRate@K"],
        "k_values": list(DEFAULT_K),
        "stages": [
            "prototype-yetirank",
            "sampling-search",
            "feature-search",
            "objective-search",
            "hyperparameter-search",
            "multi-seed-confirmation",
            "untouched-vl-final-evaluation",
            "bootstrap-confidence-interval",
        ],
        "reminders": {
            "bootstrap": "Issue #83 after traveler-trip audit",
            "h3_coordinates":
                "deferred until administrative location is insufficient",
            "historical_serving":
                "recheck serving parity before production use",
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect the locked CatBoost ranking protocol without raw data"
    )
    parser.add_argument("--print-default-protocol", action="store_true")
    parser.add_argument("--write-default-protocol", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.print_default_protocol and args.write_default_protocol is None:
        build_parser().print_help()
        return 0
    payload = json.dumps(default_protocol(), ensure_ascii=False, indent=2) + "\n"
    if args.print_default_protocol:
        print(payload, end="")
    if args.write_default_protocol is not None:
        args.write_default_protocol.write_text(payload, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
