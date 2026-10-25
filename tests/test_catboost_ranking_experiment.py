from __future__ import annotations

import importlib.util
import math
import random
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import pandas as pd

from scripts.recommendation.catboost_ranking_experiment import (
    CATBOOST_MISSING_CATEGORY,
    CandidateInventory,
    PreparedItemCatalog,
    DEFAULT_EVAL_METRIC,
    DEFAULT_ITERATIONS,
    DEFAULT_MIXED_UNIFORM_FRACTION,
    DEFAULT_OBJECTIVE,
    DEFAULT_POPULARITY_SMOOTHING,
    FEATURE_GROUPS,
    PENDING_FEATURE_GROUPS,
    ExperimentConfig,
    SamplingStrategy,
    aggregate_ranking_metrics,
    available_feature_groups,
    catboost_model_params,
    categorical_feature_columns,
    default_protocol,
    feature_group_combinations,
    feature_search_configs,
    filter_region_candidates,
    fit_catboost,
    normalize_feature_value,
    prepare_feature_frame,
    score_inner_validation_queries,
    objective_search_configs,
    ranking_metric_at_k,
    sample_unobserved,
    sampling_search_configs,
    selected_feature_columns,
    materialize_inner_train_item_features,
    validate_ranking_group_layout,
    validate_train_derived_scope,
)


class CatBoostRankingExperimentTests(unittest.TestCase):
    def test_feature_group_contract_enables_inner_train_i4_after_wiring(self) -> None:
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
        self.assertIn("I4_HISTORICAL_POI", available_feature_groups())
        self.assertEqual(PENDING_FEATURE_GROUPS, {})
        self.assertEqual(
            FEATURE_GROUPS["I2_ADMINISTRATIVE_LOCATION"],
            (
                "canonical_admin_sido_code",
                "canonical_admin_sgg_code",
                "canonical_admin_location_status",
            ),
        )
        ExperimentConfig(("I2_ADMINISTRATIVE_LOCATION",)).validate()
        ExperimentConfig(("I4_HISTORICAL_POI",)).validate()

    def test_runnable_feature_combinations_are_exhaustive(self) -> None:
        self.assertEqual(len(available_feature_groups()), 10)
        self.assertEqual(len(feature_group_combinations()), (2**10) - 1)

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

    def test_item_feature_ownership_keeps_all_i2_columns_at_every_category_depth(self) -> None:
        from scripts.recommendation.catboost_ranking_experiment import _item_feature_columns

        expected_i2 = FEATURE_GROUPS["I2_ADMINISTRATIVE_LOCATION"]
        for depth in (1, 2, 3):
            with self.subTest(depth=depth):
                config = ExperimentConfig(
                    ("I1_CATEGORY", "I2_ADMINISTRATIVE_LOCATION", "I3_POPULARITY", "I4_HISTORICAL_POI"),
                    category_depth=depth,
                )
                item_columns = _item_feature_columns(config)
                self.assertTrue(set(expected_i2) <= set(item_columns))
                self.assertEqual(
                    tuple(column for column in item_columns if column.startswith("source_category_")),
                    FEATURE_GROUPS["I1_CATEGORY"][:depth],
                )

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
        wired = ExperimentConfig(("I4_HISTORICAL_POI",))
        self.assertEqual(
            normalize_feature_value(
                "train_observed_visit_type_codes", ["13", "1"], wired
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

    def test_inner_train_materialization_replaces_outer_tl_i3_i4_and_preserves_i2(self) -> None:
        from scripts.recommendation.tl_traveler_split import (
            deterministic_traveler_group_split,
        )

        trip_owner = {f"trip-{i}": f"traveler-{i}" for i in range(10)}
        partitions = deterministic_traveler_group_split(trip_owner, seed="smoke")
        positives = [
            {
                "TRAVEL_ID": trip,
                "POI_ID": "item-a",
                "observed_positive": 1,
                "source_split": "TL",
            }
            for trip in trip_owner
        ]
        events = [
            {
                "TRAVEL_ID": trip,
                "POI_ID": "item-a",
                "VISIT_AREA_TYPE_CD": "1" if partition == "inner-train" else "3",
                "source_split": "TL",
            }
            for trip, partition in partitions.items()
        ]
        source_candidates = [
            {
                "item_id": "item-a",
                "region": "capital",
                "canonical_admin_sido_code": "11",
                "canonical_admin_sgg_code": "11010",
                "canonical_admin_location_status": "direct",
                "source_category_l1_code": "category-a",
                "source_category_l2_code": "category-a1",
                "source_category_l3_code": "leaf-a11",
                "train_positive_interaction_count": 999,
                "train_observed_visit_type_codes": ["13"],
            },
            {
                "item_id": "item-b",
                "region": "capital",
                "canonical_admin_sido_code": "11",
                "canonical_admin_sgg_code": "11020",
                "canonical_admin_location_status": "direct",
                "source_category_l1_code": "category-b",
                "source_category_l2_code": "category-b1",
                "source_category_l3_code": "leaf-b11",
                "train_positive_interaction_count": 999,
                "train_observed_visit_type_codes": ["13"],
            },
        ]
        materialized = materialize_inner_train_item_features(
            trip_owner=trip_owner,
            item_features=source_candidates,
            positive_interactions=positives,
            visit_events=events,
            split_seed="smoke",
        )
        rows = {row["item_id"]: row for row in materialized.item_features}
        train_trip_count = sum(partition == "inner-train" for partition in partitions.values())
        self.assertEqual(rows["item-a"]["train_positive_interaction_count"], train_trip_count)
        self.assertEqual(rows["item-a"]["train_observed_visit_type_codes"], ("1",))
        self.assertEqual(rows["item-b"]["train_positive_interaction_count"], 0)
        self.assertEqual(rows["item-b"]["train_observed_visit_type_codes"], ())
        for item_id in rows:
            self.assertEqual(
                rows[item_id]["canonical_admin_sido_code"],
                source_candidates[0 if item_id == "item-a" else 1]["canonical_admin_sido_code"],
            )
        self.assertEqual(set(materialized.partition_by_trip.values()), {"inner-train", "inner-validation"})

    def test_inner_train_materialization_fails_closed_without_tl_visit_events(self) -> None:
        with self.assertRaisesRegex(ValueError, "I4 requires"):
            materialize_inner_train_item_features(
                trip_owner={"trip-a": "traveler-a", "trip-b": "traveler-b"},
                item_features=[{"item_id": "item-a", "region": "capital"}],
                positive_interactions=[
                    {"TRAVEL_ID": "trip-a", "POI_ID": "item-a", "observed_positive": 1, "source_split": "TL"},
                    {"TRAVEL_ID": "trip-b", "POI_ID": "item-a", "observed_positive": 1, "source_split": "TL"},
                ],
                visit_events=None,
                split_seed="smoke",
            )

    def test_fit_rejects_arbitrary_train_derived_frames_even_with_scope_string(self) -> None:
        train = pd.DataFrame({
            "item_id": ["item-a", "item-b"],
            "trip_id": ["trip-train", "trip-train"],
            "train_positive_interaction_count": [999, 999],
            "train_observed_visit_type_codes": [["13"], ["13"]],
            "label": [1, 0],
            "group": ["query-train", "query-train"],
        })
        validation = pd.DataFrame({
            "item_id": ["item-a", "item-b"],
            "trip_id": ["trip-validation", "trip-validation"],
            "train_positive_interaction_count": [999, 999],
            "train_observed_visit_type_codes": [["13"], ["13"]],
            "label": [1, 0],
            "group": ["query-validation", "query-validation"],
        })
        with self.assertRaisesRegex(ValueError, "requires output from materialize"):
            fit_catboost(
                train,
                validation,
                label_column="label",
                group_column="group",
                config=ExperimentConfig(("I3_POPULARITY", "I4_HISTORICAL_POI")),
                train_derived_source_scope="inner-train",
            )

    def test_fit_rejects_rows_that_disagree_with_helper_materialization(self) -> None:
        materialized, train, validation = self._helper_backed_fit_frames()
        train.loc[0, "train_positive_interaction_count"] = 999
        with self.assertRaisesRegex(ValueError, "do not match inner-train materialization"):
            fit_catboost(
                train,
                validation,
                label_column="label",
                group_column="group",
                config=ExperimentConfig(("I3_POPULARITY", "I4_HISTORICAL_POI")),
                train_derived_source_scope="inner-train",
                inner_train_materialization=materialized,
            )

    def test_helper_materialization_can_reach_model_fit_boundary(self) -> None:
        materialized, train, validation = self._helper_backed_fit_frames()
        with self.assertRaises(TypeError):
            materialized.item_features[0]["train_positive_interaction_count"] = 999  # type: ignore[index]
        self.assertIsInstance(materialized.item_features[0]["train_observed_visit_type_codes"], tuple)
        with self.assertRaises(AttributeError):
            materialized.item_features[0]["train_observed_visit_type_codes"].append("tamper")  # type: ignore[union-attr]

        # Legacy frames may carry equivalent list-valued I4; the immutable
        # helper snapshot stores tuples, so comparison is value-based.
        train["train_observed_visit_type_codes"] = train["train_observed_visit_type_codes"].map(list)
        validation["train_observed_visit_type_codes"] = validation["train_observed_visit_type_codes"].map(list)

        class FakePool:
            def __init__(self, *args: object, **kwargs: object) -> None:
                pass

        class FakeRanker:
            def __init__(self, **kwargs: object) -> None:
                self.tree_count_ = 0

            def fit(self, *args: object, **kwargs: object) -> None:
                self.tree_count_ = 1

        fake_catboost = SimpleNamespace(CatBoostRanker=FakeRanker, Pool=FakePool)
        config = ExperimentConfig(
            ("I2_ADMINISTRATIVE_LOCATION", "I3_POPULARITY", "I4_HISTORICAL_POI")
        )
        with patch.dict(sys.modules, {"catboost": fake_catboost}):
            model = fit_catboost(
                train,
                validation,
                label_column="label",
                group_column="group",
                config=config,
                train_derived_source_scope="inner-train",
                inner_train_materialization=materialized,
            )
        self.assertEqual(model.tree_count_, 1)

    @staticmethod
    def _helper_backed_fit_frames() -> tuple[object, pd.DataFrame, pd.DataFrame]:
        from scripts.recommendation.tl_traveler_split import (
            deterministic_traveler_group_split,
        )

        trip_owner = {"trip-a": "traveler-a", "trip-b": "traveler-b"}
        partitions = deterministic_traveler_group_split(trip_owner, seed="fit")
        materialized = materialize_inner_train_item_features(
            trip_owner=trip_owner,
            item_features=[
                {"item_id": "item-a", "region": "capital", "canonical_admin_sido_code": "11",
                 "canonical_admin_sgg_code": "11010", "canonical_admin_location_status": "direct",
                 "source_category_l1_code": "A", "source_category_l2_code": "A1", "source_category_l3_code": "A11",
                 "train_positive_interaction_count": 999, "train_observed_visit_type_codes": ["13"]},
                {"item_id": "item-b", "region": "capital", "canonical_admin_sido_code": "11",
                 "canonical_admin_sgg_code": "11020", "canonical_admin_location_status": "direct",
                 "source_category_l1_code": "B", "source_category_l2_code": "B1", "source_category_l3_code": "B11",
                 "train_positive_interaction_count": 999, "train_observed_visit_type_codes": ["13"]},
            ],
            positive_interactions=[
                {"TRAVEL_ID": trip, "POI_ID": "item-a", "observed_positive": 1, "source_split": "TL"}
                for trip in trip_owner
            ],
            visit_events=[
                {"TRAVEL_ID": trip, "POI_ID": "item-a", "VISIT_AREA_TYPE_CD": "1", "source_split": "TL"}
                for trip in trip_owner
            ],
            split_seed="fit",
        )
        items = {row["item_id"]: row for row in materialized.item_features}

        def rows_for(partition: str) -> pd.DataFrame:
            trip_id = next(trip for trip, value in partitions.items() if value == partition)
            rows = []
            for item_id, label in (("item-a", 1), ("item-b", 0)):
                item = items[item_id]
                rows.append({
                    "item_id": item_id,
                    "trip_id": trip_id,
                    "group": trip_id,
                    "label": label,
                    **{column: item[column] for column in (
                        "canonical_admin_sido_code", "canonical_admin_sgg_code",
                        "canonical_admin_location_status", "source_category_l1_code",
                        "source_category_l2_code", "train_positive_interaction_count",
                        "train_observed_visit_type_codes",
                    )},
                })
            return pd.DataFrame(rows)

        return materialized, rows_for("inner-train"), rows_for("inner-validation")

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

    def test_prepared_uniform_sampler_matches_legacy_exactly(self) -> None:
        for size in (1, 2, 3, 10, 31, 128):
            candidates = tuple(f"item-{index:04d}" for index in range(size))
            inventory = CandidateInventory.from_items(candidates, region="capital")
            positive_sets = [
                set(candidates[:size // 2]),
                set(candidates[size // 2:]),
                set(candidates[::2]),
                set(candidates[1::2]),
                {"outside-inventory", *candidates[-1:]},
                set(candidates),
                set(),
            ]
            duplicate_inventory = CandidateInventory.from_items(
                (*candidates, *candidates[:2]), region="capital"
            )
            self.assertEqual(duplicate_inventory.items, inventory.items)
            for positives in positive_sets:
                for ratio in (1, 2, 5):
                    for seed in (0, 1, 7, 20261025):
                        eligible = sorted(set(candidates) - positives)
                        count = min(len(eligible), len(positives) * ratio)
                        expected = tuple(sorted(random.Random(seed).sample(eligible, count))) if count else ()
                        actual = sample_unobserved(
                            duplicate_inventory, positives,
                            strategy=SamplingStrategy.UNIFORM,
                            ratio=ratio, seed=seed,
                        )
                        self.assertEqual(actual, expected)

    def test_streaming_catalog_scorer_matches_full_frame_and_chunks_ties(self) -> None:
        materialized, _, validation = self._helper_backed_fit_frames()
        config = ExperimentConfig(
            ("I2_ADMINISTRATIVE_LOCATION", "I3_POPULARITY", "I4_HISTORICAL_POI", "Q4_TEMPORAL"),
            k_values=(1, 2, 5),
            popularity_transform="log1p",
        )
        catalog = PreparedItemCatalog.from_materialization(
            materialized, config, region="capital"
        )
        self.assertEqual(
            catalog.item_columns["train_observed_visit_type_codes"],
            tuple("1" if row["item_id"] == "item-a" else "" for row in materialized.item_features),
        )
        query_id = str(validation.loc[0, "trip_id"])
        query_features = {query_id: {"region": "capital", "start_month": None, "elapsed_days": 4}}
        relevant = iter(("item-b", "not-in-catalog"))

        class TiedModel:
            def __init__(self) -> None:
                self.frames: list[pd.DataFrame] = []

            def predict(self, frame: pd.DataFrame) -> list[float]:
                self.frames.append(frame.copy())
                return [1.0] * len(frame)

        # Legacy full-catalog prediction uses precisely the same normalized
        # feature values, then applies the deterministic score/item-id order.
        by_item = {row["item_id"]: row for row in materialized.item_features}
        full_rows = []
        for item_id in catalog.inventory.items:
            full_rows.append({
                **{column: by_item[item_id][column] for column in (
                    "canonical_admin_sido_code", "canonical_admin_sgg_code",
                    "canonical_admin_location_status", "source_category_l1_code",
                    "source_category_l2_code", "train_positive_interaction_count",
                    "train_observed_visit_type_codes",
                )},
                **query_features[query_id],
            })
        full_frame = prepare_feature_frame(pd.DataFrame(full_rows), config)
        full_scores = TiedModel().predict(full_frame)
        full_ranking = tuple(
            item for item, _ in sorted(
                zip(catalog.inventory.items, full_scores, strict=True),
                key=lambda pair: (-pair[1], pair[0]),
            )
        )
        expected = aggregate_ranking_metrics(
            ((full_ranking, ("item-b", "not-in-catalog")),),
            k_values=config.k_values,
        )
        streamed_model = TiedModel()
        result = score_inner_validation_queries(
            streamed_model, catalog,
            ((query_id, relevant),),
            query_features=query_features, config=config,
            max_rows_per_batch=1,
        )
        self.assertEqual(dict(result.metrics), expected)
        pd.testing.assert_frame_equal(
            pd.concat(streamed_model.frames, ignore_index=True), full_frame,
            check_dtype=False,
        )
        self.assertEqual(result.query_count, 1)
        self.assertEqual(result.candidate_count, 2)
        self.assertEqual(result.scored_rows, 2)
        self.assertEqual(result.max_batch_rows, 1)

    def test_streaming_scorer_preserves_i2_at_category_depth_one_and_two(self) -> None:
        from scripts.recommendation.catboost_ranking_experiment import _item_feature_columns

        materialized, _, validation = self._helper_backed_fit_frames()
        query_id = str(validation.loc[0, "trip_id"])
        query_features = {query_id: {"region": "capital", "start_month": "month-3", "elapsed_days": 8}}
        by_item = {row["item_id"]: row for row in materialized.item_features}

        class FrameRecorder:
            def __init__(self) -> None:
                self.frames: list[pd.DataFrame] = []

            def predict(self, frame: pd.DataFrame) -> list[float]:
                self.frames.append(frame.copy())
                return [0.0] * len(frame)

        for depth in (1, 2):
            config = ExperimentConfig(
                ("I1_CATEGORY", "I2_ADMINISTRATIVE_LOCATION", "I3_POPULARITY", "I4_HISTORICAL_POI", "Q4_TEMPORAL"),
                category_depth=depth, k_values=(1, 2), popularity_transform="log1p",
            )
            catalog = PreparedItemCatalog.from_materialization(
                materialized, config, region="capital"
            )
            expected_rows = [
                {**{column: by_item[item_id][column] for column in _item_feature_columns(config)},
                 **query_features[query_id]}
                for item_id in catalog.inventory.items
            ]
            expected_frame = prepare_feature_frame(pd.DataFrame(expected_rows), config)
            recorder = FrameRecorder()
            score_inner_validation_queries(
                recorder, catalog, ((query_id, iter(("item-b",))),),
                query_features=query_features, config=config, max_rows_per_batch=1,
            )
            pd.testing.assert_frame_equal(
                pd.concat(recorder.frames, ignore_index=True), expected_frame,
                check_dtype=False,
            )
            self.assertTrue(set(FEATURE_GROUPS["I2_ADMINISTRATIVE_LOCATION"]) <= set(catalog.item_columns))
            self.assertEqual(
                tuple(column for column in catalog.item_columns if column.startswith("source_category_")),
                FEATURE_GROUPS["I1_CATEGORY"][:depth],
            )

    def test_streaming_catalog_scorer_fails_closed_for_wrong_partition_nonfinite_and_config(self) -> None:
        materialized, _, validation = self._helper_backed_fit_frames()
        config = ExperimentConfig(("I3_POPULARITY", "I4_HISTORICAL_POI"))
        catalog = PreparedItemCatalog.from_materialization(materialized, config, region="capital")
        query_id = str(validation.loc[0, "trip_id"])
        queries = ((query_id, ("item-a",)),)

        class NonfiniteModel:
            def predict(self, frame: pd.DataFrame) -> list[float]:
                return [float("nan")] * len(frame)

        with self.assertRaisesRegex(ValueError, "non-finite"):
            score_inner_validation_queries(
                NonfiniteModel(), catalog, queries,
                query_features={query_id: {"region": "capital"}}, config=config,
                max_rows_per_batch=1,
            )
        with self.assertRaisesRegex(ValueError, "normalization"):
            score_inner_validation_queries(
                NonfiniteModel(), catalog, queries,
                query_features={query_id: {"region": "capital"}},
                config=ExperimentConfig(("I3_POPULARITY", "I4_HISTORICAL_POI"), popularity_transform="log1p"),
            )
        with self.assertRaisesRegex(ValueError, "region conflicts"):
            score_inner_validation_queries(
                NonfiniteModel(), catalog, queries,
                query_features={query_id: {"region": "other-region"}}, config=config,
            )
        class NoCallModel:
            called = False

            def predict(self, frame: pd.DataFrame) -> list[float]:
                self.called = True
                return [0.0] * len(frame)

        no_call_model = NoCallModel()
        with self.assertRaisesRegex(ValueError, "region is required"):
            score_inner_validation_queries(
                no_call_model, catalog, queries,
                query_features={query_id: {}}, config=config,
            )
        self.assertFalse(no_call_model.called)
        train_trip = next(
            trip for trip, partition in materialized.partition_by_trip.items()
            if partition == "inner-train"
        )
        wrong_rows = ((train_trip, ("item-a",)),)
        with self.assertRaisesRegex(ValueError, "inner-validation"):
            score_inner_validation_queries(
                NonfiniteModel(), catalog, wrong_rows, query_features={}, config=config,
            )

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

    def test_streamed_query_metric_aggregation_matches_materialized_aggregation(self) -> None:
        query_rows = [
            (["p2", "p1", "p3", "p4"], {"p1", "p4"}),
            (["p3", "p1", "p4", "p2"], {"p2"}),
            (["p1", "p2", "p3", "p4"], set()),
        ]
        k_values = (1, 2, 5)
        expected: dict[str, float] = {}
        for name in ("ndcg", "recall", "mrr", "hit_rate"):
            for k in k_values:
                values = [
                    getattr(ranking_metric_at_k(ranked, relevant, k), name)
                    for ranked, relevant in query_rows
                ]
                expected[f"{name}@{k}"] = sum(values) / len(values)

        streamed = aggregate_ranking_metrics(
            ((ranked, iter(relevant)) for ranked, relevant in query_rows),
            k_values=k_values,
        )

        self.assertEqual(streamed, expected)

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

    @unittest.skipUnless(
        importlib.util.find_spec("catboost") is not None,
        "CatBoost is not installed in this environment",
    )
    def test_real_catboost_eval_training_and_streamed_prediction_parity(self) -> None:
        from scripts.recommendation.catboost_ranking_experiment import fit_catboost

        trip_owner = {f"synthetic-trip-{index}": f"synthetic-traveler-{index}" for index in range(10)}
        from scripts.recommendation.tl_traveler_split import deterministic_traveler_group_split
        partitions = deterministic_traveler_group_split(
            trip_owner, seed="catboost-parity", validation_fraction=0.2
        )
        item_features = [
            {
                "item_id": item_id, "region": "capital",
                "canonical_admin_sido_code": "11",
                "canonical_admin_sgg_code": sgg,
                "canonical_admin_location_status": "direct",
                "source_category_l1_code": "category-a",
                "source_category_l2_code": f"category-{item_id}",
                "source_category_l3_code": f"leaf-{item_id}",
                "train_positive_interaction_count": 999,
                "train_observed_visit_type_codes": ["outer-value"],
            }
            for item_id, sgg in (("item-a", "11010"), ("item-b", "11020"), ("item-c", "11030"))
        ]
        positive_interactions = []
        visit_events = []
        for index, trip_id in enumerate(trip_owner):
            item_id = ("item-a", "item-b", "item-c")[index % 3]
            positive_interactions.append({
                "TRAVEL_ID": trip_id, "POI_ID": item_id,
                "observed_positive": 1, "source_split": "TL",
            })
            visit_events.append({
                "TRAVEL_ID": trip_id, "POI_ID": item_id,
                "VISIT_AREA_TYPE_CD": str(index % 2), "source_split": "TL",
            })
        materialized = materialize_inner_train_item_features(
            trip_owner=trip_owner, item_features=item_features,
            positive_interactions=positive_interactions, visit_events=visit_events,
            split_seed="catboost-parity", validation_fraction=0.2,
        )
        by_item = {row["item_id"]: row for row in materialized.item_features}
        train_rows: list[dict[str, object]] = []
        validation_rows: list[dict[str, object]] = []
        query_features: dict[str, dict[str, object]] = {}
        validation_truth: list[tuple[str, tuple[str, ...]]] = []
        for index, (trip_id, partition) in enumerate(partitions.items()):
            positive_item = ("item-a", "item-b", "item-c")[index % 3]
            context = {
                "region": "capital",
                "start_month": f"month-{index % 12 + 1}",
                "elapsed_days": index + 1,
            }
            if partition == "inner-validation":
                query_features[trip_id] = context
                validation_truth.append((trip_id, (positive_item, "outside-inventory")))
            target_rows = train_rows if partition == "inner-train" else validation_rows
            for item_id in by_item:
                item = by_item[item_id]
                target_rows.append({
                    "item_id": item_id, "trip_id": trip_id, "group": trip_id,
                    "label": int(item_id == positive_item), **context,
                    **{column: item[column] for column in (
                        "canonical_admin_sido_code", "canonical_admin_sgg_code",
                        "canonical_admin_location_status", "source_category_l1_code",
                        "source_category_l2_code", "train_positive_interaction_count",
                        "train_observed_visit_type_codes",
                    )},
                })
        train = pd.DataFrame(train_rows)
        validation = pd.DataFrame(validation_rows)
        config = ExperimentConfig(
            ("I1_CATEGORY", "I2_ADMINISTRATIVE_LOCATION", "I3_POPULARITY", "I4_HISTORICAL_POI", "Q4_TEMPORAL"),
            category_depth=2, iterations=3, seed=29, popularity_transform="log1p", k_values=(1, 2, 5),
        )
        kwargs = {
            "label_column": "label", "group_column": "group", "config": config,
            "train_derived_source_scope": "inner-train",
            "inner_train_materialization": materialized,
        }
        with_eval = fit_catboost(train, validation, **kwargs)
        without_eval = fit_catboost(train, None, **kwargs)
        normalized_validation = prepare_feature_frame(validation, config)
        eval_predictions = list(with_eval.predict(normalized_validation))
        no_eval_predictions = list(without_eval.predict(normalized_validation))
        self.assertEqual(eval_predictions, no_eval_predictions)

        catalog = PreparedItemCatalog.from_materialization(
            materialized, config, region="capital"
        )
        full_query_rows = []
        full_rankings = []
        for query_id, relevant in validation_truth:
            context = query_features[query_id]
            rows = [
                {**{column: item[column] for column in (
                    "canonical_admin_sido_code", "canonical_admin_sgg_code",
                    "canonical_admin_location_status", "source_category_l1_code",
                    "source_category_l2_code", "train_positive_interaction_count",
                    "train_observed_visit_type_codes",
                )}, **context}
                for item in (by_item[item_id] for item_id in catalog.inventory.items)
            ]
            frame = prepare_feature_frame(pd.DataFrame(rows), config)
            full_query_rows.append(frame)
            scores = list(with_eval.predict(frame))
            full_rankings.append((
                tuple(item_id for item_id, _ in sorted(
                    zip(catalog.inventory.items, scores, strict=True),
                    key=lambda pair: (-float(pair[1]), pair[0]),
                )),
                relevant,
            ))
        expected_metrics = aggregate_ranking_metrics(full_rankings, k_values=config.k_values)

        class RecordingRanker:
            def __init__(self) -> None:
                self.frames: list[pd.DataFrame] = []

            def predict(self, frame: pd.DataFrame) -> list[float]:
                self.frames.append(frame.copy())
                return list(with_eval.predict(frame))

        for batch_size in (1, 100):
            recording = RecordingRanker()
            result = score_inner_validation_queries(
                recording, catalog, iter(validation_truth), query_features=query_features,
                config=config, max_rows_per_batch=batch_size,
            )
            self.assertEqual(dict(result.metrics), expected_metrics)
            self.assertEqual(result.query_count, len(validation_truth))
            self.assertLessEqual(result.max_batch_rows, batch_size)
            pd.testing.assert_frame_equal(
                pd.concat(recording.frames, ignore_index=True),
                pd.concat(full_query_rows, ignore_index=True),
                check_dtype=False,
            )

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
            "requires-inner-train-recompute",
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
