from __future__ import annotations

import math
import unittest

from scripts.recommendation.catboost_ranking_experiment import (
    DEFAULT_OBJECTIVE,
    FEATURE_GROUPS,
    ExperimentConfig,
    SamplingStrategy,
    available_feature_groups,
    catboost_model_params,
    categorical_feature_columns,
    default_protocol,
    feature_group_combinations,
    feature_search_configs,
    filter_region_candidates,
    normalize_feature_value,
    objective_search_configs,
    ranking_metric_at_k,
    sample_unobserved,
    sampling_search_configs,
    selected_feature_columns,
    validate_ranking_group_layout,
    validate_train_derived_scope,
)


class CatBoostRankingExperimentTests(unittest.TestCase):
    def test_feature_group_contract_and_pending_groups_fail_closed(self) -> None:
        self.assertEqual(
            set(FEATURE_GROUPS),
            {
                "Q1_STYLE",
                "Q2_MOTIVE",
                "Q3_COMPANION",
                "Q4_TEMPORAL",
                "Q5_DESTINATION_CONTEXT",
                "I1_CATEGORY",
                "I2_ADMINISTRATIVE_LOCATION",
                "I3_POPULARITY",
                "I4_HISTORICAL_POI",
                "C1_REGION",
            },
        )
        self.assertNotIn("I2_ADMINISTRATIVE_LOCATION", available_feature_groups())
        self.assertNotIn("I4_HISTORICAL_POI", available_feature_groups())
        with self.assertRaisesRegex(ValueError, "Issue #81"):
            ExperimentConfig(("I2_ADMINISTRATIVE_LOCATION",)).validate()
        with self.assertRaisesRegex(ValueError, "Issue #80"):
            ExperimentConfig(("I4_HISTORICAL_POI",)).validate()

    def test_runnable_feature_combinations_are_exhaustive(self) -> None:
        self.assertEqual(len(available_feature_groups()), 8)
        self.assertEqual(len(feature_group_combinations()), (2**8) - 1)

    def test_category_depth_and_categorical_columns(self) -> None:
        config = ExperimentConfig(
            ("Q1_STYLE", "Q3_COMPANION", "I1_CATEGORY", "I3_POPULARITY"),
            category_depth=2,
        )
        columns = selected_feature_columns(config)
        self.assertIn("source_category_l1_code", columns)
        self.assertIn("source_category_l2_code", columns)
        self.assertNotIn("source_category_l3_code", columns)
        categorical = categorical_feature_columns(config)
        self.assertIn("travel_style_1", categorical)
        self.assertIn("companion_status", categorical)
        self.assertNotIn("companion_count", categorical)
        self.assertNotIn("train_positive_interaction_count", categorical)

    def test_popularity_transform_and_historical_normalization(self) -> None:
        config = ExperimentConfig(("I3_POPULARITY",), popularity_transform="log1p")
        self.assertAlmostEqual(
            normalize_feature_value("train_positive_interaction_count", 9, config),
            math.log(10),
        )
        pending = ExperimentConfig(("I4_HISTORICAL_POI",))
        self.assertEqual(
            normalize_feature_value(
                "train_observed_visit_type_codes", ["13", "1"], pending
            ),
            "1|13",
        )

    def test_region_filter_uses_only_prequalified_inventory(self) -> None:
        regions = {
            "a": "capital",
            "b": "capital",
            "c": "east",
            "vl-only": "capital",
        }
        candidates = filter_region_candidates(regions, {"a", "c"}, "capital")
        self.assertEqual(candidates, ("a",))
        self.assertNotIn("vl-only", candidates)

    def test_uniform_sampling_is_deterministic_and_excludes_positives(self) -> None:
        candidates = {"a", "b", "c", "d", "e"}
        positives = {"a", "b"}
        first = sample_unobserved(
            candidates,
            positives,
            strategy=SamplingStrategy.UNIFORM,
            ratio=1,
            seed=7,
        )
        second = sample_unobserved(
            reversed(sorted(candidates)),
            positives,
            strategy=SamplingStrategy.UNIFORM,
            ratio=1,
            seed=7,
        )
        self.assertEqual(first, second)
        self.assertEqual(len(first), 2)
        self.assertFalse(set(first) & positives)

    def test_all_sampling_strategies_respect_boundaries(self) -> None:
        candidates = {"a", "b", "c", "d", "e", "f"}
        positives = {"a", "b"}
        popularity = {"c": 100, "d": 20, "e": 2, "f": 1}
        hard = {"c": 0.1, "d": 0.9, "e": 0.8, "f": 0.2}
        for strategy in SamplingStrategy:
            with self.subTest(strategy=strategy):
                sampled = sample_unobserved(
                    candidates,
                    positives,
                    strategy=strategy,
                    ratio=1,
                    seed=17,
                    popularity=popularity,
                    hard_scores=(
                        hard if strategy == SamplingStrategy.HARD else None
                    ),
                    statistics_scope=(
                        "inner-train"
                        if strategy != SamplingStrategy.UNIFORM
                        else None
                    ),
                )
                self.assertEqual(len(sampled), 2)
                self.assertTrue(set(sampled) <= candidates)
                self.assertFalse(set(sampled) & positives)

        hard_sample = sample_unobserved(
            candidates,
            positives,
            strategy=SamplingStrategy.HARD,
            ratio=1,
            seed=17,
            hard_scores=hard,
            statistics_scope="inner-train",
        )
        self.assertEqual(set(hard_sample), {"d", "e"})

    def test_weighted_sampling_requires_inner_train_statistics(self) -> None:
        for strategy in (
            SamplingStrategy.POPULARITY_WEIGHTED,
            SamplingStrategy.MIXED,
            SamplingStrategy.HARD,
        ):
            with self.subTest(strategy=strategy), self.assertRaisesRegex(
                ValueError, "inner-train"
            ):
                sample_unobserved(
                    {"a", "b", "c"},
                    {"a"},
                    strategy=strategy,
                    ratio=1,
                    seed=1,
                    popularity={"b": 1, "c": 2},
                    hard_scores={"b": 1, "c": 2},
                    statistics_scope="full-TL",
                )

    def test_hard_sampling_requires_complete_scores(self) -> None:
        with self.assertRaisesRegex(ValueError, "hard_scores"):
            sample_unobserved(
                {"a", "b"},
                {"a"},
                strategy=SamplingStrategy.HARD,
                ratio=1,
                seed=1,
                statistics_scope="inner-train",
            )
        with self.assertRaisesRegex(ValueError, "every available candidate"):
            sample_unobserved(
                {"a", "b", "c"},
                {"a"},
                strategy=SamplingStrategy.HARD,
                ratio=1,
                seed=1,
                hard_scores={"b": 1.0},
                statistics_scope="inner-train",
            )

    def test_stage_config_builders_keep_axes_separate(self) -> None:
        sampling = sampling_search_configs(("Q1_STYLE",))
        self.assertEqual(len(sampling), 4 * 5)
        self.assertTrue(all(c.objective == "YetiRank" for c in sampling))

        features = feature_search_configs(
            sampling_strategy=SamplingStrategy.UNIFORM,
            negative_ratio=2,
            groups=("Q1_STYLE", "Q2_MOTIVE"),
        )
        self.assertEqual(len(features), 3)

        objectives = objective_search_configs(
            ("Q1_STYLE",),
            sampling_strategy=SamplingStrategy.UNIFORM,
            negative_ratio=2,
        )
        self.assertEqual(
            [c.objective for c in objectives],
            ["YetiRank", "PairLogit", "LambdaMart"],
        )

    def test_ranking_metrics_match_known_order(self) -> None:
        metric = ranking_metric_at_k(["x", "b", "a", "z"], {"a", "b"}, 3)
        self.assertAlmostEqual(metric.recall, 1.0)
        self.assertAlmostEqual(metric.mrr, 0.5)
        self.assertEqual(metric.hit_rate, 1.0)
        expected_dcg = 1 / math.log2(3) + 1 / math.log2(4)
        expected_idcg = 1 / math.log2(2) + 1 / math.log2(3)
        self.assertAlmostEqual(metric.ndcg, expected_dcg / expected_idcg)

    def test_ranking_groups_are_contiguous_and_have_both_labels(self) -> None:
        validate_ranking_group_layout(
            ["q1", "q1", "q2", "q2"],
            [1, 0, 0, 1],
        )
        validate_ranking_group_layout(
            ["q1", "q1"],
            [0, 0],
            require_both_labels=False,
        )
        with self.assertRaisesRegex(ValueError, "contiguous"):
            validate_ranking_group_layout(
                ["q1", "q1", "q2", "q2", "q1", "q1"],
                [1, 0, 1, 0, 1, 0],
            )
        with self.assertRaisesRegex(ValueError, "label 1"):
            validate_ranking_group_layout(["q1", "q1"], [1, 1])
        with self.assertRaisesRegex(ValueError, "binary"):
            validate_ranking_group_layout(["q1", "q1"], [2, 0])

    def test_train_derived_features_require_inner_train_scope(self) -> None:
        config = ExperimentConfig(("I3_POPULARITY",))
        with self.assertRaisesRegex(ValueError, "full-TL"):
            validate_train_derived_scope(config, "full-TL")
        validate_train_derived_scope(config, "inner-train")
        validate_train_derived_scope(ExperimentConfig(("Q1_STYLE",)), None)

    def test_default_objective_is_yetirank(self) -> None:
        config = ExperimentConfig(("Q1_STYLE",))
        self.assertEqual(DEFAULT_OBJECTIVE, "YetiRank")
        self.assertEqual(catboost_model_params(config)["loss_function"], "YetiRank")
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            ExperimentConfig(("Q1_STYLE",), objective="NDCG").validate()

    def test_protocol_keeps_vl_out_of_tuning(self) -> None:
        protocol = default_protocol()
        self.assertIn("no tuning", protocol["split"]["final_holdout"])
        self.assertIn("not observed dislike", protocol["sampling"]["label_zero"])
        self.assertEqual(
            protocol["feature_groups"]["I2_ADMINISTRATIVE_LOCATION"]["status"],
            "pending",
        )
        self.assertEqual(
            protocol["feature_groups"]["I4_HISTORICAL_POI"]["status"],
            "pending",
        )


if __name__ == "__main__":
    unittest.main()
