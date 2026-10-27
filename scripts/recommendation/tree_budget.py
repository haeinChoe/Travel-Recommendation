"""Aggregate-only prefix inference study; candidate and training contracts stay fixed."""
from __future__ import annotations

import resource
import time

from scripts.recommendation.catboost_ranking_experiment import (
    ScoringProfiler,
    score_inner_validation_queries,
)


def ranking_stability(rankings, reference, k_values):
    """Reduce memory-only item identities to overlap and position agreement."""
    if len(rankings) != len(reference):
        raise ValueError("Ranking cohorts differ")
    result = {}
    for k in k_values:
        overlaps, positions = [], []
        for actual, baseline in zip(rankings, reference, strict=True):
            left = [row[0] for row in actual[:k]]
            right = [row[0] for row in baseline[:k]]
            denominator = len(right)
            overlaps.append(len(set(left) & set(right)) / denominator if denominator else 1.0)
            positions.append(sum(a == b for a, b in zip(left, right)) / denominator
                             if denominator else 1.0)
        result[f"overlap@{k}"] = sum(overlaps) / len(overlaps) if overlaps else 1.0
        result[f"position_agreement@{k}"] = sum(positions) / len(positions) if positions else 1.0
    return result


def metric_deltas(metrics, reference):
    return {name: {
        "absolute": value - reference[name],
        "relative": (value - reference[name]) / reference[name] if reference[name] else None,
    } for name, value in metrics.items()}


def run_tree_budget_sweep(model, catalog, ground_truth, *, query_features, config,
                          budgets=(100, 250, 500, 750, 1000), batch_rows=131_072):
    """Fit once outside this function; repeat only inference on identical query order.

    ground_truth is a factory, not a one-shot iterator. Raw rankings never leave
    this function. Baseline runs first so every reported delta is within-cohort.
    """
    if not budgets or len(set(budgets)) != len(budgets) or model.tree_count_ not in budgets:
        raise ValueError("Unique budgets must include the fitted model baseline")
    if any(isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= model.tree_count_
           for n in budgets):
        raise ValueError("Invalid tree budget")
    reference_rankings = None
    reference_metrics = None
    runs = {}
    for budget in (model.tree_count_, *(n for n in budgets if n != model.tree_count_)):
        profiler = ScoringProfiler(capture_rankings=True)
        started = time.perf_counter()
        result = score_inner_validation_queries(
            model, catalog, ground_truth(), query_features=query_features, config=config,
            max_rows_per_batch=batch_rows, profiler=profiler,
            inference_mode="dataframe_cached_items", prediction_tree_end=budget,
        )
        elapsed = time.perf_counter() - started
        if reference_rankings is None:
            reference_rankings = profiler.top_rankings
            reference_metrics = dict(result.metrics)
        runs[budget] = {
            "trees": budget, "semantics": "prefix_inference_truncation",
            "scoring_wall_seconds": elapsed,
            "process_peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
            "rows_per_second": result.scored_rows / elapsed,
            "query_count": result.query_count, "candidate_count": result.candidate_count,
            "scored_rows": result.scored_rows, "metrics": dict(result.metrics),
            "metric_deltas_vs_1000": metric_deltas(result.metrics, reference_metrics),
            "rank_stability": ranking_stability(
                profiler.top_rankings, reference_rankings, config.k_values,
            ),
            "profiler": profiler.summary(
                scored_rows=result.scored_rows, candidate_count=result.candidate_count,
            ),
        }
    return [runs[n] for n in budgets]
