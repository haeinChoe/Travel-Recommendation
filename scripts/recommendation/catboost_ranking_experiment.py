"""Cold-user CatBoost POI ranking experiment contract primitives.

This module does not read AI Hub raw data. It keeps the agreed experiment
semantics executable so later actual-data runs do not silently change labels,
candidates, feature provenance, sampling, or ranking metrics.

A sampled-unobserved row with label 0 is a training comparison row. It is not
an observed user dislike.
"""

from __future__ import annotations

import argparse
import json
import math
import random
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from itertools import combinations
from pathlib import Path
from typing import Any

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
    "I2_ADMINISTRATIVE_LOCATION": (),
    "I3_POPULARITY": ("train_positive_interaction_count",),
    "I4_HISTORICAL_POI": ("train_observed_visit_type_codes",),
    "C1_REGION": ("region",),
}
PENDING_FEATURE_GROUPS = {
    "I2_ADMINISTRATIVE_LOCATION":
        "Issue #81 must define canonical administrative-location columns.",
    "I4_HISTORICAL_POI":
        "Issue #80 must provide inner-train-safe visit-type derivation.",
}
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


def sample_unobserved(
    candidate_items: Iterable[str],
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
    available = sorted(set(candidate_items) - positives)
    count = min(len(available), len(positives) * ratio)
    if count == 0:
        return ()

    rng = random.Random(seed)
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
    validation_frame: Any,
    *,
    label_column: str,
    group_column: str,
    config: ExperimentConfig,
    train_derived_source_scope: str | None = None,
) -> Any:
    """Thin adapter; Issue #82 owns actual CatBoost execution and tuning."""

    config.validate()
    validate_train_derived_scope(config, train_derived_source_scope)
    try:
        from catboost import CatBoostRanker, Pool
    except ImportError as exc:
        raise RuntimeError(
            "CatBoost is not installed; execution belongs to Issue #82"
        ) from exc

    features = list(selected_feature_columns(config))
    categorical = list(categorical_feature_columns(config))
    required = {*features, label_column, group_column}
    missing_train = required - set(train_frame.columns)
    missing_validation = required - set(validation_frame.columns)
    if missing_train:
        raise ValueError(f"Training frame missing: {sorted(missing_train)}")
    if missing_validation:
        raise ValueError(f"Validation frame missing: {sorted(missing_validation)}")

    validate_ranking_group_layout(
        list(train_frame[group_column]), list(train_frame[label_column])
    )
    validate_ranking_group_layout(
        list(validation_frame[group_column]),
        list(validation_frame[label_column]),
        require_both_labels=False,
    )

    def prepared(frame: Any) -> Any:
        result = frame.loc[:, features].copy()
        for column in features:
            result[column] = result[column].map(
                lambda value, c=column: normalize_feature_value(c, value, config)
            )
        return result

    train_pool = Pool(
        prepared(train_frame),
        label=train_frame[label_column],
        group_id=train_frame[group_column],
        cat_features=categorical,
    )
    validation_pool = Pool(
        prepared(validation_frame),
        label=validation_frame[label_column],
        group_id=validation_frame[group_column],
        cat_features=categorical,
    )
    model = CatBoostRanker(**catboost_model_params(config))
    # Keep the comparison budget fixed across objectives. The validation set
    # reports one shared metric but never selects a different best iteration.
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
