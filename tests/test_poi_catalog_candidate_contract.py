from __future__ import annotations

import unittest

from scripts.recommendation.poi_catalog_candidate_contract import (
    PoiRecord,
    audit_experiment_design,
    diagnose_catalog,
    eligibility_reason,
    match_source_item,
    match_summary,
    positive_coverage,
)


SYNTHETIC_REGION_MAP = {"synthetic-region": frozenset({"admin-11"})}


def synthetic_catalog_record(item_id: str, **kwargs: object) -> PoiRecord:
    kwargs.setdefault("region_codes", frozenset({"admin-11"}))
    return PoiRecord(item_id, **kwargs)


def match_synthetic_region(source: PoiRecord, catalog: list[PoiRecord], **kwargs: object):
    return match_source_item(
        source,
        catalog,
        source_region="synthetic-region",
        source_region_to_admin_codes=SYNTHETIC_REGION_MAP,
        **kwargs,
    )


class IdentityContractTests(unittest.TestCase):
    def test_catalog_diagnostic_requires_explicit_region_mapping(self) -> None:
        with self.assertRaisesRegex(TypeError, "source_region_to_admin_codes"):
            diagnose_catalog(  # type: ignore[call-arg]
                [],
                [],
                request_region="synthetic-region",
                region_admin_codes={},
                supported_content_types=frozenset(),
            )

    def test_same_mapped_region_allows_exact_identity_match(self) -> None:
        source = PoiRecord("src", name="Place", address="Road 1")
        target = PoiRecord("target", name="Place", address="Road 1",
                           region_codes=frozenset({"admin-11"}))
        result = match_source_item(
            source,
            [target],
            source_region="North Region",
            source_region_to_admin_codes={" north region ": frozenset({" ADMIN-11 "})},
        )
        self.assertEqual((result.status, result.canonical_item_id), ("MATCHED", "target"))

    def test_disjoint_catalog_region_is_rejected_before_identity(self) -> None:
        source = PoiRecord("src", name="Place", address="Road 1")
        target = PoiRecord("target", name="Place", address="Road 1",
                           region_codes=frozenset({"admin-26"}))
        result = match_source_item(
            source,
            [target],
            source_region="north-region",
            source_region_to_admin_codes={"north-region": frozenset({"admin-11"})},
        )
        self.assertEqual((result.status, result.canonical_item_id), ("UNMATCHED", None))

    def test_missing_or_unmapped_region_mapping_fails_closed(self) -> None:
        source = PoiRecord("src", name="Place", address="Road 1")
        target = PoiRecord("target", name="Place", address="Road 1",
                           region_codes=frozenset({"admin-11"}))
        for region, mapping in (
            ("north-region", {}),
            ("unknown-region", {"north-region": frozenset({"admin-11"})}),
            ("north-region", {"north-region": frozenset()}),
        ):
            with self.subTest(region=region, mapping=mapping):
                result = match_source_item(
                    source,
                    [target],
                    source_region=region,
                    source_region_to_admin_codes=mapping,
                )
                self.assertEqual((result.status, result.canonical_item_id, result.method),
                                 ("UNMATCHED", None, "region_unmapped"))

    def test_empty_catalog_region_is_ignored(self) -> None:
        source = PoiRecord("src", name="Place", address="Road 1")
        result = match_synthetic_region(source, [PoiRecord("target", name="Place", address="Road 1")])
        self.assertEqual((result.status, result.canonical_item_id), ("UNMATCHED", None))

    def test_name_and_address_is_a_deterministic_match(self) -> None:
        source = PoiRecord("src", name="Place", address="Road 1")
        catalog = [synthetic_catalog_record("target", name="Place", address="Road 1")]
        result = match_synthetic_region(source, catalog)
        self.assertEqual((result.status, result.canonical_item_id, result.method),
                         ("MATCHED", "target", "name_address"))

    def test_name_address_with_conflicting_nonblank_district_is_ambiguous(self) -> None:
        source = PoiRecord("src", name="Place", address="Road 1", district_code="A")
        catalog = [synthetic_catalog_record("target", name="Place", address="Road 1", district_code="B")]
        result = match_synthetic_region(source, catalog)
        self.assertEqual((result.status, result.canonical_item_id, result.method),
                         ("AMBIGUOUS", None, "conflicting_exact_signals"))

    def test_name_address_with_matching_district_is_a_deterministic_match(self) -> None:
        source = PoiRecord("src", name="Place", address="Road 1", district_code="A")
        catalog = [synthetic_catalog_record("target", name="Place", address="Road 1", district_code="A")]
        result = match_synthetic_region(source, catalog)
        self.assertEqual((result.status, result.canonical_item_id, result.method),
                         ("MATCHED", "target", "name_address"))

    def test_name_district_with_conflicting_nonblank_address_is_ambiguous(self) -> None:
        source = PoiRecord("src", name="Place", address="Road 1", district_code="A")
        catalog = [synthetic_catalog_record("target", name="Place", address="Road 2", district_code="A")]
        result = match_synthetic_region(source, catalog)
        self.assertEqual((result.status, result.canonical_item_id, result.method),
                         ("AMBIGUOUS", None, "conflicting_exact_signals"))

    def test_name_district_with_blank_address_remains_a_deterministic_match(self) -> None:
        source = PoiRecord("src", name="Place", district_code="A")
        catalog = [synthetic_catalog_record("target", name="Place", district_code="A")]
        result = match_synthetic_region(source, catalog)
        self.assertEqual((result.status, result.canonical_item_id, result.method),
                         ("MATCHED", "target", "name_district"))

    def test_name_alone_is_ambiguous_even_with_one_catalog_row(self) -> None:
        source = PoiRecord("src", name="Same name")
        result = match_synthetic_region(source, [synthetic_catalog_record("target", name="Same name")])
        self.assertEqual((result.status, result.canonical_item_id, result.method),
                         ("AMBIGUOUS", None, "fuzzy_or_distance_candidate"))

    def test_exact_coordinates_alone_are_diagnostic_not_identity(self) -> None:
        source = PoiRecord("src", latitude="37.5", longitude="127.0")
        result = match_synthetic_region(source, [synthetic_catalog_record("target", latitude="37.5", longitude="127.0")])
        self.assertEqual(result.status, "AMBIGUOUS")
        self.assertIsNone(result.canonical_item_id)

    def test_conflicting_exact_signals_fail_closed(self) -> None:
        source = PoiRecord("src", name="Place", address="Road 1", district_code="A")
        catalog = [
            synthetic_catalog_record("by-address", name="Place", address="Road 1", district_code="B"),
            synthetic_catalog_record("by-district", name="Place", address="Road 2", district_code="A"),
        ]
        result = match_synthetic_region(source, catalog)
        self.assertEqual((result.status, result.method), ("AMBIGUOUS", "conflicting_exact_signals"))

    def test_fuzzy_match_is_diagnostic_only(self) -> None:
        source = PoiRecord("src", name="Place")
        result = match_synthetic_region(source, [synthetic_catalog_record("target", name="Placee")], fuzzy_threshold=0.8)
        self.assertEqual((result.status, result.canonical_item_id), ("AMBIGUOUS", None))

    def test_invalid_match_thresholds_are_rejected(self) -> None:
        source = PoiRecord("src", name="Place")
        for kwargs in ({"fuzzy_threshold": 1.1}, {"distance_threshold_m": float("inf")}):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    match_synthetic_region(source, [], **kwargs)

    def test_explicit_category_type_conflict_vetoes_identity(self) -> None:
        source = PoiRecord("src", name="Place", address="Road 1", category="museum")
        target = synthetic_catalog_record("target", name="Place", address="Road 1", content_type_id="12")
        result = match_synthetic_region(
            source,
            [target],
            source_category_to_content_types={"museum": frozenset({"14"})},
        )
        self.assertEqual((result.status, result.method), ("AMBIGUOUS", "category_type_conflict"))

    def test_duplicate_catalog_identity_in_a_snapshot_is_rejected(self) -> None:
        source = PoiRecord("src", name="Place", address="Road 1")
        catalog = [synthetic_catalog_record("same", name="Place", address="Road 1"),
                   synthetic_catalog_record("same", name="Other", address="Road 2")]
        with self.assertRaisesRegex(ValueError, "catalog canonical IDs"):
            match_synthetic_region(source, catalog)

    def test_match_summary_contains_no_identifiers_and_suppresses_small_cells(self) -> None:
        results = [
            match_synthetic_region(PoiRecord(f"source-{i}", name="Place"), [])
            for i in range(9)
        ]
        summary = match_summary(results)
        self.assertEqual(summary, {"MATCHED": "0", "AMBIGUOUS": "0", "UNMATCHED": "<10"})
        self.assertNotIn("source-", repr(summary))

    def test_catalog_diagnostics_are_bucketed_and_identifier_free(self) -> None:
        result = diagnose_catalog(
            [PoiRecord("private-source", name="Place", address="Road 1")],
            [synthetic_catalog_record("private-target", name="Place", address="Road 1", content_type_id="12",
                       region_codes=frozenset({"11"}), catalog_status="active")],
            source_region_to_admin_codes={"seoul": frozenset({"11"})},
            request_region="seoul", region_admin_codes={"seoul": frozenset({"11"})},
            supported_content_types=frozenset({"12"}),
        )
        self.assertEqual(result["identity"]["MATCHED"], "<10")
        self.assertEqual(result["eligible_catalog_items"], "<10")
        self.assertNotIn("private-source", repr(result))
        self.assertNotIn("private-target", repr(result))

    def test_positive_coverage_uses_coarse_rates_and_complementary_suppression(self) -> None:
        positives = {f"positive-{i}" for i in range(20)}
        eligible = {f"positive-{i}" for i in range(10)}
        self.assertEqual(positive_coverage(positives, eligible), {
            "matched_positive": "50-<75%", "outside_positive": "50-<75%",
        })
        small_outside = {f"positive-{i}" for i in range(12)}
        self.assertEqual(positive_coverage(positives, small_outside), {
            "matched_positive": "privacy_limited", "outside_positive": "privacy_limited",
        })


class EligibilityContractTests(unittest.TestCase):
    def test_region_district_active_status_and_supported_type_are_hard_constraints(self) -> None:
        item = PoiRecord("id", content_type_id="12", region_codes=frozenset({"11"}),
                         district_codes=frozenset({"11110"}), catalog_status="active")
        rules = {"seoul": frozenset({"11"})}
        types = frozenset({"12"})
        self.assertEqual(eligibility_reason(item, request_region="seoul", region_admin_codes=rules,
                                            supported_content_types=types, request_district_code="11110"), "eligible")
        self.assertEqual(eligibility_reason(item, request_region="seoul", region_admin_codes=rules,
                                            supported_content_types=types, request_district_code="11120"),
                         "outside_request_district")
        unknown = PoiRecord("id", content_type_id="12", region_codes=frozenset({"11"}))
        self.assertEqual(eligibility_reason(unknown, request_region="seoul", region_admin_codes=rules,
                                            supported_content_types=types), "catalog_status_unknown")

    def test_observed_category_and_feedback_do_not_become_eligibility_inputs(self) -> None:
        # The API takes only request region/district and catalog policy. It has
        # no hook for observed visit category or post-event feedback.
        item = PoiRecord("id", content_type_id="12", region_codes=frozenset({"11"}), catalog_status="active")
        result = eligibility_reason(item, request_region="seoul", region_admin_codes={"seoul": frozenset({"11"})},
                                    supported_content_types=frozenset({"12"}))
        self.assertEqual(result, "eligible")


class DomainReviewSmokeTests(unittest.TestCase):
    def test_skill_domain_review_cases_are_rejected_or_reframed(self) -> None:
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
