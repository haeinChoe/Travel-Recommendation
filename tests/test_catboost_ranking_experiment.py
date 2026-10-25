from __future__ import annotations

import importlib.util
import math
import unittest

import pandas as pd

from scripts.recommendation.catboost_ranking_experiment import (
    CATBOOST_MISSING_CATEGORY,
    DEFAULT_EVAL_METRIC,
    DEFAULT_ITERATIONS,
    DEFAULT_MIXED_UNIFORM_FRACTION,
    DEFAULT_OBJECTIVE,
    DEFAULT_POPULARITY_SMOOTHING,
    FEATURE_GROUPS,
    PENDING_FEATURE_GROUPS,
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
        self.assertIn("I2_ADMINISTRATIVE_LOCATION", available_feature_groups())
        self.assertNotIn("I4_HISTORICAL_POI", available_feature_groups())
        self.assertIn("implemented and tested", PENDING_FEATURE_GROUPS["I4_HISTORICAL_POI"])
        self.assertIn("Issue #82", PENDING_FEATURE_GROUPS["I4_HISTORICAL_POI"])
        self.assertEqual(
            FEATURE_GROUPS["I2_ADMINISTRATIVE_LOCATION"],
            (
                "canonical_admin_sido_code",
                "canonical_admin_sgg_code",
                "canonical_admin_location_status",
            ),
        )
        ExperimentConfig(("I2_ADMINISTRATIVE_LOCATION",)).validate()
        with self.assertRaisesRegex(ValueError, "Issue #80"):
            ExperimentConfig(("I4_HISTORICAL_POI",)).validate()

    def test_runnable_feature_combinations_are_exhaustive(self) -> None:
        self.assertEqual(len(available_feature_groups()), 9)
        self.assertEqual(len(feature_group_combinations()), (2**9) - 1)

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

    def test_i2_columns_are_categorical_static_features(self) -> None:
        config = ExperimentConfig(("I2_ADMINISTRATIVE_LOCATION",))
        self.assertEqual(
            selected_feature_columns(config),
            (
                "canonical_admin_sido_code",
                "canonical_admin_sgg_code",
                "canonical_admin_location_status",
            ),
        )
        self.assertEqual(
            categorical_feature_columns(config),
            (
                "canonical_admin_sido_code",
                "canonical_admin_sgg_code",
                "canonical_admin_location_status",
            ),
        )

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
        self.assertEqual(
            normalize_feature_value("companion_status", None, config),
            CATBOOST_MISSING_CATEGORY,
        )
        self.assertEqual(
            normalize_feature_value("source_category_l1_code", float("nan"), config),
            CATBOOST_MISSING_CATEGORY,
        )
        self.assertEqual(
            normalize_feature_value("travel_style_1", pd.NA, config),
            CATBOOST_MISSING_CATEGORY,
        )
        self.assertEqual(
            normalize_feature_value("region", "capital", config), "capital"
        )

    def test_region_filter_includes_train_unseen_items_from_inventory(self) -> None:
        regions = {
            "a": "capital",
            "b": "capital",
            "c": "east",
            "vl-only": "capital",
        }
        candidates = filter_region_candidates(
            regions, {"a", "c", "vl-only"}, "capital"
        )
        self.assertEqual(candidates, ("a", "vl-only"))

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

    def test_sampling_parameters_are_configurable_with_prototype_defaults(self) -> None:
        candidates = {"positive", "a", "b", "c", "d", "e"}
        positives = {"positive"}
        popularity = {"a": 1, "b": 3, "c": 5, "d": 7, "e": 9}
        self.assertEqual(DEFAULT_POPULARITY_SMOOTHING, 1.0)
        self.assertEqual(DEFAULT_MIXED_UNIFORM_FRACTION, 0.5)
        uniform = sample_unobserved(
            candidates,
            positives,
            strategy=SamplingStrategy.UNIFORM,
            ratio=3,
            seed=17,
        )
        all_uniform_mixed = sample_unobserved(
            candidates,
            positives,
            strategy=SamplingStrategy.MIXED,
            ratio=3,
            seed=17,
            popularity=popularity,
            statistics_scope="inner-train",
            mixed_uniform_fraction=1.0,
        )
        self.assertEqual(all_uniform_mixed, uniform)
        all_weighted = sample_unobserved(
            candidates,
            positives,
            strategy=SamplingStrategy.MIXED,
            ratio=3,
            seed=17,
            popularity=popularity,
            statistics_scope="inner-train",
            mixed_uniform_fraction=0.0,
            popularity_smoothing=0.0,
        )
        weighted = sample_unobserved(
            candidates,
            positives,
            strategy=SamplingStrategy.POPULARITY_WEIGHTED,
            ratio=3,
            seed=17,
            popularity=popularity,
            statistics_scope="inner-train",
            popularity_smoothing=0.0,
        )
        self.assertEqual(all_weighted, weighted)
        with self.assertRaisesRegex(ValueError, "popularity_smoothing"):
            sample_unobserved(
                candidates,
                positives,
                strategy=SamplingStrategy.UNIFORM,
                ratio=1,
                seed=17,
                popularity_smoothing=-1,
            )
        with self.assertRaisesRegex(ValueError, "mixed_uniform_fraction"):
            ExperimentConfig(("Q1_STYLE",), mixed_uniform_fraction=1.1).validate()

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
        for group in ("I3_POPULARITY", "I4_HISTORICAL_POI"):
            with self.subTest(group=group):
                config = ExperimentConfig((group,))
                with self.assertRaisesRegex(ValueError, "full-TL"):
                    validate_train_derived_scope(config, "full-TL")
                validate_train_derived_scope(config, "inner-train")
        validate_train_derived_scope(ExperimentConfig(("Q1_STYLE",)), None)

    def test_default_objective_is_yetirank(self) -> None:
        config = ExperimentConfig(("Q1_STYLE",))
        self.assertEqual(DEFAULT_OBJECTIVE, "YetiRank")
        self.assertEqual(catboost_model_params(config)["loss_function"], "YetiRank")
        params = catboost_model_params(config)
        self.assertEqual(params["eval_metric"], DEFAULT_EVAL_METRIC)
        self.assertEqual(params["iterations"], DEFAULT_ITERATIONS)
        self.assertIs(params["use_best_model"], False)
        objective_configs = objective_search_configs(
            ("Q1_STYLE",),
            sampling_strategy=SamplingStrategy.UNIFORM,
            negative_ratio=1,
        )
        self.assertEqual({c.iterations for c in objective_configs}, {DEFAULT_ITERATIONS})
        self.assertEqual({c.eval_metric for c in objective_configs}, {DEFAULT_EVAL_METRIC})
        sampling_configs = sampling_search_configs(
            ("Q1_STYLE",), popularity_smoothing=0.25, mixed_uniform_fraction=0.7
        )
        self.assertEqual({c.popularity_smoothing for c in sampling_configs}, {0.25})
        self.assertEqual({c.mixed_uniform_fraction for c in sampling_configs}, {0.7})
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            ExperimentConfig(("Q1_STYLE",), objective="NDCG").validate()

    def test_protocol_keeps_vl_out_of_tuning(self) -> None:
        protocol = default_protocol()
        self.assertIn("no tuning", protocol["split"]["final_holdout"])
        self.assertIn("not observed dislike", protocol["sampling"]["label_zero"])
        self.assertEqual(
            protocol["feature_groups"]["I2_ADMINISTRATIVE_LOCATION"]["status"],
            "available",
        )
        self.assertEqual(
            protocol["candidate_universe"]["train_unseen_items"],
            "eligible when required features are available",
        )
        self.assertEqual(
            protocol["objective_comparison"]["use_best_model"], False
        )
        self.assertEqual(
            protocol["feature_groups"]["I4_HISTORICAL_POI"]["status"],
            "pending",
        )

    @unittest.skipUnless(
        importlib.util.find_spec("catboost") is not None,
        "CatBoost is not installed in this environment",
    )
    def test_catboost_synthetic_fit_accepts_nullable_categoricals(self) -> None:
        from scripts.recommendation.catboost_ranking_experiment import fit_catboost

        train_features = {
            f"travel_style_{index}": (
                [None, "1", pd.NA, "2"]
                if index == 1
                else ["a", "b", "c", "d"]
            )
            for index in range(1, 9)
        }
        validation_features = {
            f"travel_style_{index}": (
                [float("nan"), "1", "2", None]
                if index == 1
                else ["a", "b", "c", "d"]
            )
            for index in range(1, 9)
        }
        train = pd.DataFrame({
            **train_features,
            "label": [1, 0, 1, 0],
            "group": ["q1", "q1", "q2", "q2"],
        })
        validation = pd.DataFrame({
            **validation_features,
            "label": [1, 0, 0, 1],
            "group": ["q3", "q3", "q4", "q4"],
        })
        model = fit_catboost(
            train,
            validation,
            label_column="label",
            group_column="group",
            config=ExperimentConfig(("Q1_STYLE",), iterations=2),
        )
        self.assertGreater(model.tree_count_, 0)


if __name__ == "__main__":
    unittest.main()
