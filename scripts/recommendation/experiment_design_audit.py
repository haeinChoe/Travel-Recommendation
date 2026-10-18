"""Pure checks for common recommendation-experiment design errors."""

from __future__ import annotations

from typing import Mapping


def audit_experiment_design(design: Mapping[str, object]) -> tuple[str, ...]:
    """Return deterministic blockers without reading datasets or scoring models."""
    findings: list[str] = []
    if design.get("claim") == "ranking_quality" and design.get("task") == "post_visit_satisfaction_classification":
        findings.append("post_visit_classification_is_not_ranking_evidence")
    if design.get("unvisited_label") == 0 and not design.get("negative_sampling_protocol"):
        findings.append("unvisited_items_are_unknown_without_exposure_or_sampling_protocol")
    if design.get("task") == "ranking" and set(design.get("metrics", ())) <= {"accuracy"}:
        findings.append("ranking_requires_ranking_metrics")
    if set(design.get("features", ())) & {"DGSTFN", "REVISIT_INTENTION", "RCMDTN_INTENTION"}:
        findings.append("post_event_feedback_is_unavailable_at_request_time")
    if design.get("claims_incremental_feature_value") and design.get("cohorts_comparable") is False:
        findings.append("feature_ablation_cohorts_are_not_comparable")
    return tuple(findings)
