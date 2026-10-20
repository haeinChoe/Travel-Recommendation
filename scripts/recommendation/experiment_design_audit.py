"""Pure checks for common recommendation-experiment design errors."""

from __future__ import annotations

from typing import Mapping

RAW_IDENTIFIER_KEYS: frozenset[str] = frozenset({
    "TRAVELER_ID",
    "TRAVEL_ID",
    "VISIT_AREA_ID",
    "POI_ID",
    "contentid",
})

POST_EVENT_VISIT_FIELDS: frozenset[str] = frozenset({
    "DGSTFN",
    "REVISIT_INTENTION",
    "RCMDTN_INTENTION",
    "REVISIT_YN",
    "VISIT_CHC_REASON_CD",
    "RESIDENCE_TIME_MIN",
    "VISIT_ORDER",
    "VISIT_START_YMD",
    "VISIT_END_YMD",
})

CATALOG_MATCH_STATUS_FILTERS: frozenset[str] = frozenset({
    "MATCHED",
    "AMBIGUOUS",
    "UNMATCHED",
    "identity_source_missing",
})


def audit_experiment_design(design: Mapping[str, object]) -> tuple[str, ...]:
    """Return deterministic blockers without reading datasets or scoring models."""
    findings: list[str] = []
    features = set(design.get("features", ()))  # type: ignore[arg-type]

    if design.get("claim") == "ranking_quality" and design.get("task") == "post_visit_satisfaction_classification":
        findings.append("post_visit_classification_is_not_ranking_evidence")
    if design.get("unvisited_label") == 0 and not design.get("negative_sampling_protocol"):
        findings.append("unvisited_items_are_unknown_without_exposure_or_sampling_protocol")
    if design.get("task") == "ranking" and set(design.get("metrics", ())) <= {"accuracy"}:  # type: ignore[arg-type]
        findings.append("ranking_requires_ranking_metrics")
    if features & POST_EVENT_VISIT_FIELDS:
        findings.append("post_event_feedback_is_unavailable_at_request_time")
    if design.get("claims_incremental_feature_value") and design.get("cohorts_comparable") is False:
        findings.append("feature_ablation_cohorts_are_not_comparable")
    if features & RAW_IDENTIFIER_KEYS:
        findings.append("raw_identifiers_are_join_keys_not_model_features")
    if (
        bool(design.get("filter_by_catalog_match_status"))
        or design.get("training_cohort_filter") in CATALOG_MATCH_STATUS_FILTERS
    ):
        findings.append("training_eligibility_must_not_depend_on_catalog_match_status")
    if design.get("split_unit") == "visit_row":
        findings.append("trip_level_split_grouping_required")

    return tuple(findings)
