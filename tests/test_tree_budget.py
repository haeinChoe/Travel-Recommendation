"""No private rows or identities are used by these tests."""
import unittest

from scripts.recommendation.tree_budget import metric_deltas, ranking_stability, run_tree_budget_sweep
from scripts.recommendation.catboost_ranking_experiment import (
    ExperimentConfig, catboost_model_params, score_inner_validation_queries,
)


class TreeBudgetAggregatesTests(unittest.TestCase):
    def test_overlap_and_positions_are_different_and_identity_free(self):
        result = ranking_stability(
            [[('b', 2), ('a', 1)]], [[('a', 2), ('b', 1)]], (1, 2),
        )
        self.assertEqual(result['overlap@2'], 1)
        self.assertEqual(result['position_agreement@2'], 0)
        self.assertEqual(result['overlap@1'], 0)
        self.assertNotIn('a', result)

    def test_zero_reference_relative_delta_is_undefined(self):
        self.assertEqual(metric_deltas({'m': 0.1}, {'m': 0}),
                         {'m': {'absolute': 0.1, 'relative': None}})

    def test_invalid_ranges_rejected_before_catalog_access(self):
        from types import SimpleNamespace
        for budget in (True, 0, -1, 1001, 2.5):
            with self.subTest(budget=budget), self.assertRaises(ValueError):
                score_inner_validation_queries(
                    SimpleNamespace(tree_count_=1000), None, [], query_features={},
                    config=None, prediction_tree_end=budget,
                )

    def test_invalid_sweep_budgets_fail_without_data(self):
        from types import SimpleNamespace
        for budgets in ((), (100,), (1000, 1000), (0, 1000), (True, 1000), (1001, 1000)):
            with self.subTest(budgets=budgets), self.assertRaises(ValueError):
                run_tree_budget_sweep(SimpleNamespace(tree_count_=1000), None, None,
                                      query_features={}, config=None, budgets=budgets)

    def test_prefix_vs_separate_training_real_catboost(self):
        import catboost
        import numpy as np
        from catboost import CatBoostRanker, Pool
        self.assertEqual(catboost.__version__, '1.2.10')
        rng = np.random.default_rng(20261025)
        x = rng.normal(size=(256, 5))
        y = (x[:, 0] + 0.3 * x[:, 1] > 0).astype(int)
        pool = Pool(x, y, group_id=np.repeat(np.arange(32), 8))
        params = catboost_model_params(ExperimentConfig(('Q4_TEMPORAL',), seed=20261025))
        params['thread_count'] = 2
        full = CatBoostRanker(**params).fit(pool)
        np.testing.assert_array_equal(full.predict(pool), full.predict(pool, ntree_start=0, ntree_end=1000))
        for budget in (250, 500):
            separate = CatBoostRanker(**{**params, 'iterations': budget}).fit(pool)
            prefix = full.predict(pool, ntree_start=0, ntree_end=budget)
            # Automatic learning rate may depend on requested iteration count;
            # equivalence is an observed result, never a required assumption.
            delta = float(np.max(np.abs(prefix - separate.predict(pool))))
            self.assertTrue(np.isfinite(delta))
            import json
            print(json.dumps({'synthetic_only': True, 'trees': budget,
                              'max_abs_prediction_delta': delta,
                              'exact_equal': bool(np.array_equal(prefix, separate.predict(pool))),
                              'full_learning_rate': full.get_all_params()['learning_rate'],
                              'separate_learning_rate': separate.get_all_params()['learning_rate']}))
            shrunk = full.copy()
            shrunk.shrink(budget)
            np.testing.assert_array_equal(prefix, shrunk.predict(pool))
