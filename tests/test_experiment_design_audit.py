from __future__ import annotations

import unittest

from scripts.recommendation.experiment_design_audit import audit_experiment_design


class ExperimentDesignAuditTests(unittest.TestCase):
    def test_domain_review_cases_are_rejected_or_reframed(self) -> None:
        cases = (
            ({"claim": "ranking_quality", "task": "post_visit_satisfaction_classification"},
             "post_visit_classification_is_not_ranking_evidence"),
            ({"unvisited_label": 0}, "unvisited_items_are_unknown_without_exposure_or_sampling_protocol"),
            ({"task": "ranking", "metrics": ["accuracy"]}, "ranking_requires_ranking_metrics"),
            ({"features": ["DGSTFN"]}, "post_event_feedback_is_unavailable_at_request_time"),
            ({"claims_incremental_feature_value": True, "cohorts_comparable": False},
             "feature_ablation_cohorts_are_not_comparable"),
        )
        for design, expected in cases:
            with self.subTest(expected=expected):
                self.assertIn(expected, audit_experiment_design(design))


if __name__ == "__main__":
    unittest.main()
