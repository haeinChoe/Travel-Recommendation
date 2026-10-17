from __future__ import annotations

import unittest

from scripts.recommendation.poi_catalog_candidate_contract import (
    CandidateRequest,
    CatalogPoi,
    CatalogSnapshot,
    HistoricalRequestProxy,
    SourcePoi,
    derive_proxy_requests_from_observations,
    diagnose_catalog,
    diagnose_candidate_coverage,
    eligibility_reason,
    match_source_item,
    match_summary,
    positive_coverage,
)
from scripts.recommendation.experiment_design_audit import audit_experiment_design


SYNTHETIC_REGION_MAP = {"synthetic-region": frozenset({"admin-11"})}


def source(item_id: str, region: str = "synthetic-region", **kwargs: object) -> SourcePoi:
    return SourcePoi(item_id, region=region, **kwargs)


def synthetic_catalog_record(item_id: str, **kwargs: object) -> CatalogPoi:
    if "name" in kwargs and "title" not in kwargs:
        kwargs["title"] = kwargs.pop("name")
    kwargs.setdefault("region_codes", frozenset({"admin-11"}))
    return CatalogPoi(item_id, **kwargs)


def match_synthetic_region(source_item: SourcePoi, catalog: list[CatalogPoi], **kwargs: object):
    return match_source_item(
        source_item,
        catalog,
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
        source_item = SourcePoi("src", region="North Region", name="Place", address="Road 1")
        target = synthetic_catalog_record("target", title="Place", address="Road 1")
        result = match_source_item(
            source_item,
            [target],
            source_region_to_admin_codes={" north region ": frozenset({" ADMIN-11 "})},
        )
        self.assertEqual((result.status, result.canonical_item_id), ("MATCHED", "target"))

    def test_disjoint_catalog_region_is_rejected_before_identity(self) -> None:
        source_item = source("src", region="north-region", name="Place", address="Road 1")
        target = CatalogPoi("target", title="Place", address="Road 1", region_codes=frozenset({"admin-26"}))
        result = match_source_item(
            source_item,
            [target],
            source_region_to_admin_codes={"north-region": frozenset({"admin-11"})},
        )
        self.assertEqual((result.status, result.canonical_item_id), ("UNMATCHED", None))

    def test_missing_or_unmapped_region_mapping_fails_closed(self) -> None:
        target = synthetic_catalog_record("target", title="Place", address="Road 1")
        for region, mapping in (
            ("north-region", {}),
            ("unknown-region", {"north-region": frozenset({"admin-11"})}),
            ("north-region", {"north-region": frozenset()}),
        ):
            with self.subTest(region=region, mapping=mapping):
                source_item = source("src", region=region, name="Place", address="Road 1")
                result = match_source_item(
                    source_item,
                    [target],
                    source_region_to_admin_codes=mapping,
                )
                self.assertEqual((result.status, result.canonical_item_id, result.method),
                                 ("UNMATCHED", None, "region_unmapped"))

    def test_empty_catalog_region_is_ignored(self) -> None:
        source_item = source("src", name="Place", address="Road 1")
        result = match_synthetic_region(source_item, [CatalogPoi("target", title="Place", address="Road 1")])
        self.assertEqual((result.status, result.canonical_item_id), ("UNMATCHED", None))

    def test_name_and_address_is_a_deterministic_match(self) -> None:
        source_item = source("src", name="Place", address="Road 1")
        catalog = [synthetic_catalog_record("target", name="Place", address="Road 1")]
        result = match_synthetic_region(source_item, catalog)
        self.assertEqual((result.status, result.canonical_item_id, result.method),
                         ("MATCHED", "target", "name_address"))

    def test_name_address_with_conflicting_nonblank_district_is_ambiguous(self) -> None:
        source_item = source("src", name="Place", address="Road 1", district_code="A")
        catalog = [synthetic_catalog_record("target", name="Place", address="Road 1", district_code="B")]
        result = match_synthetic_region(source_item, catalog)
        self.assertEqual((result.status, result.canonical_item_id, result.method),
                         ("AMBIGUOUS", None, "conflicting_exact_signals"))

    def test_name_address_with_matching_district_is_a_deterministic_match(self) -> None:
        source_item = source("src", name="Place", address="Road 1", district_code="A")
        catalog = [synthetic_catalog_record("target", name="Place", address="Road 1", district_code="A")]
        result = match_synthetic_region(source_item, catalog)
        self.assertEqual((result.status, result.canonical_item_id, result.method),
                         ("MATCHED", "target", "name_address"))

    def test_name_district_with_conflicting_nonblank_address_is_ambiguous(self) -> None:
        source_item = source("src", name="Place", address="Road 1", district_code="A")
        catalog = [synthetic_catalog_record("target", name="Place", address="Road 2", district_code="A")]
        result = match_synthetic_region(source_item, catalog)
        self.assertEqual((result.status, result.canonical_item_id, result.method),
                         ("AMBIGUOUS", None, "conflicting_exact_signals"))

    def test_name_district_with_blank_address_remains_a_deterministic_match(self) -> None:
        source_item = source("src", name="Place", district_code="A")
        catalog = [synthetic_catalog_record("target", name="Place", district_code="A")]
        result = match_synthetic_region(source_item, catalog)
        self.assertEqual((result.status, result.canonical_item_id, result.method),
                         ("MATCHED", "target", "name_district"))

    def test_name_alone_is_ambiguous_even_with_one_catalog_row(self) -> None:
        source_item = source("src", name="Same name")
        result = match_synthetic_region(source_item, [synthetic_catalog_record("target", name="Same name")])
        self.assertEqual((result.status, result.canonical_item_id, result.method),
                         ("AMBIGUOUS", None, "fuzzy_name_candidate"))

    def test_coordinate_fields_are_absent_until_crs_semantics_are_verified(self) -> None:
        self.assertNotIn("latitude", SourcePoi.__dataclass_fields__)
        self.assertNotIn("longitude", CatalogPoi.__dataclass_fields__)

    def test_conflicting_exact_signals_fail_closed(self) -> None:
        source_item = source("src", name="Place", address="Road 1", district_code="A")
        catalog = [
            synthetic_catalog_record("by-address", name="Place", address="Road 1", district_code="B"),
            synthetic_catalog_record("by-district", name="Place", address="Road 2", district_code="A"),
        ]
        result = match_synthetic_region(source_item, catalog)
        self.assertEqual((result.status, result.method), ("AMBIGUOUS", "conflicting_exact_signals"))

    def test_fuzzy_match_is_diagnostic_only(self) -> None:
        source_item = source("src", name="Place")
        result = match_synthetic_region(source_item, [synthetic_catalog_record("target", name="Placee")], fuzzy_threshold=0.8)
        self.assertEqual((result.status, result.canonical_item_id), ("AMBIGUOUS", None))

    def test_invalid_match_thresholds_are_rejected(self) -> None:
        source_item = source("src", name="Place")
        for kwargs in ({"fuzzy_threshold": 1.1},):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    match_synthetic_region(source_item, [], **kwargs)

    def test_explicit_category_type_conflict_vetoes_identity(self) -> None:
        source_item = source("src", name="Place", address="Road 1", category="museum")
        target = synthetic_catalog_record("target", name="Place", address="Road 1", content_type_id="12")
        result = match_synthetic_region(
            source_item,
            [target],
            source_category_to_content_types={"museum": frozenset({"14"})},
        )
        self.assertEqual((result.status, result.method), ("AMBIGUOUS", "category_type_conflict"))

    def test_duplicate_catalog_identity_in_a_snapshot_is_rejected(self) -> None:
        source_item = source("src", name="Place", address="Road 1")
        catalog = [synthetic_catalog_record("same", name="Place", address="Road 1"),
                   synthetic_catalog_record("same", name="Other", address="Road 2")]
        with self.assertRaisesRegex(ValueError, "catalog canonical IDs"):
            match_synthetic_region(source_item, catalog)

    def test_match_summary_contains_no_identifiers_and_suppresses_small_cells(self) -> None:
        results = [
            match_synthetic_region(source(f"source-{i}", name="Place"), [])
            for i in range(9)
        ]
        summary = match_summary(results)
        self.assertEqual(summary, {"MATCHED": "0", "AMBIGUOUS": "0", "UNMATCHED": "<10"})
        self.assertNotIn("source-", repr(summary))

    def test_catalog_diagnostics_are_bucketed_and_identifier_free(self) -> None:
        result = diagnose_catalog(
            [SourcePoi("private-source", region="seoul", name="Place", address="Road 1")],
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
        item = CatalogPoi("id", content_type_id="12", region_codes=frozenset({"11"}),
                         district_codes=frozenset({"11110"}), catalog_status="active")
        rules = {"seoul": frozenset({"11"})}
        types = frozenset({"12"})
        self.assertEqual(eligibility_reason(item, request_region="seoul", region_admin_codes=rules,
                                            supported_content_types=types, request_district_code="11110"), "eligible")
        self.assertEqual(eligibility_reason(item, request_region="seoul", region_admin_codes=rules,
                                            supported_content_types=types, request_district_code="11120"),
                         "outside_request_district")
        unknown = CatalogPoi("id", content_type_id="12", region_codes=frozenset({"11"}))
        self.assertEqual(eligibility_reason(unknown, request_region="seoul", region_admin_codes=rules,
                                            supported_content_types=types), "catalog_status_unknown")

    def test_single_district_code_field_is_considered_for_eligibility(self) -> None:
        item = CatalogPoi(
            "id", content_type_id="12", region_codes=frozenset({"11"}),
            district_code="11110", catalog_status="active",
        )
        self.assertEqual(
            eligibility_reason(
                item, request_region="seoul", region_admin_codes={"seoul": frozenset({"11"})},
                supported_content_types=frozenset({"12"}), request_district_code=" 11110 ",
            ),
            "eligible",
        )

    def test_observed_category_and_feedback_do_not_become_eligibility_inputs(self) -> None:
        # The API takes only request region/district and catalog policy. It has
        # no hook for observed visit category or post-event feedback.
        item = CatalogPoi("id", content_type_id="12", region_codes=frozenset({"11"}), catalog_status="active")
        result = eligibility_reason(item, request_region="seoul", region_admin_codes={"seoul": frozenset({"11"})},
                                    supported_content_types=frozenset({"12"}))
        self.assertEqual(result, "eligible")


    def test_region_and_content_type_codes_normalize_on_both_sides(self) -> None:
        item = CatalogPoi(
            "id", content_type_id=" 12 ", region_codes=frozenset({" 11 "}), catalog_status=" ACTIVE "
        )
        self.assertEqual(
            eligibility_reason(
                item, request_region=" seoul ", region_admin_codes={"SEOUL": frozenset({"11"})},
                supported_content_types=frozenset({"12"}),
            ),
            "eligible",
        )


class CandidateCoverageTests(unittest.TestCase):
    def test_historical_proxy_requests_are_explicitly_derived_from_observations(self) -> None:
        requests = derive_proxy_requests_from_observations([
            SourcePoi(source_item_id="a", request_id="trip-1", region=" Region A "),
            SourcePoi(source_item_id="b", request_id="trip-1", region="region a"),
            SourcePoi(source_item_id="c", request_id="trip-2", region="region-b"),
        ])
        self.assertEqual(requests, [
            HistoricalRequestProxy(request_id="trip-1", region="regiona"),
            HistoricalRequestProxy(request_id="trip-2", region="region-b"),
        ])

    def test_request_context_rejects_mixed_regions(self) -> None:
        with self.assertRaisesRegex(ValueError, "share one region"):
            derive_proxy_requests_from_observations([
                SourcePoi(source_item_id="a", request_id="trip-1", region="a"),
                SourcePoi(source_item_id="b", request_id="trip-1", region="b"),
            ])

    def test_product_request_region_is_independent_of_observation_region(self) -> None:
        catalog = CatalogSnapshot("snapshot-v1", (
            CatalogPoi(
                "product-region-poi", title="Place", address="Road 1",
                content_type_id="12", region_codes=frozenset({"request-admin", "history-admin"}),
                catalog_status="active",
            ),
            CatalogPoi(
                "history-only-poi", title="Elsewhere", content_type_id="12",
                region_codes=frozenset({"history-admin"}), catalog_status="active",
            ),
        ))
        requests = [CandidateRequest(f"trip-{index}", "product-region") for index in range(10)]
        positives = [SourcePoi(
            f"source-poi-{index}", "historical-region", "Place", address="Road 1",
            request_id=f"trip-{index}",
        ) for index in range(10)]

        result = diagnose_candidate_coverage(
            requests, positives, catalog,
            region_admin_codes={
                "product-region": frozenset({"request-admin"}),
                "historical-region": frozenset({"history-admin"}),
            },
            supported_content_types=frozenset({"12"}),
        )

        self.assertEqual(result["candidate_size_distribution"]["1"], "10+")
        self.assertEqual(result["positive_candidate_coverage"], "90-100%")

    def test_historical_proxy_is_rejected_as_product_request_context(self) -> None:
        proxies = derive_proxy_requests_from_observations([
            SourcePoi("source", "historical-region", request_id="trip-1"),
        ])

        with self.assertRaisesRegex(TypeError, "independently supplied CandidateRequest"):
            diagnose_candidate_coverage(
                proxies, [], CatalogSnapshot("snapshot-v1", ()),
                region_admin_codes={}, supported_content_types=frozenset(),
            )

    def test_real_path_aggregates_requests_without_emitting_ids(self) -> None:
        catalog = CatalogSnapshot("snapshot-v1", (CatalogPoi(
            "private-content-id", title="Place", address="Road 1", content_type_id="12",
            region_codes=frozenset({"admin-11"}), catalog_status="active",
        ),))
        requests = [CandidateRequest(f"private-trip-{index}", "synthetic-region") for index in range(10)]
        positives = [SourcePoi(f"private-source-{index}", "synthetic-region", "Place", address="Road 1",
                               request_id=f"private-trip-{index}") for index in range(10)]
        result = diagnose_candidate_coverage(
            requests, positives, catalog,
            region_admin_codes=SYNTHETIC_REGION_MAP,
            supported_content_types=frozenset({"12"}),
        )
        self.assertEqual(result["positive_candidate_coverage"], "90-100%")
        self.assertEqual(result["nonempty_candidate_request_rate"], "90-100%")
        self.assertNotIn("private-trip", repr(result))
        self.assertNotIn("private-source", repr(result))
        self.assertNotIn("private-content", repr(result))

    def test_unresolved_positive_identity_is_excluded_from_coverage(self) -> None:
        result = diagnose_candidate_coverage(
            [CandidateRequest("trip", "synthetic-region")],
            [SourcePoi("source", "synthetic-region", "Place", request_id="trip")],
            CatalogSnapshot("snapshot-v1", ()),
            region_admin_codes=SYNTHETIC_REGION_MAP,
            supported_content_types=frozenset({"12"}),
        )
        self.assertEqual(result["positive_candidate_coverage"], "privacy_limited")
        self.assertEqual(result["identity_status"]["UNMATCHED"], "<10")
        self.assertTrue(result["unresolved_identity_excluded_from_candidate_coverage"])

    def test_duplicate_identity_with_conflicting_fields_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "conflicting observation fields"):
            diagnose_candidate_coverage(
                [CandidateRequest("trip-1", "synthetic-region")],
                [
                    SourcePoi("poi-1", "synthetic-region", "First", request_id="trip-1"),
                    SourcePoi("poi-1", "synthetic-region", "Second", request_id="trip-1"),
                ],
                CatalogSnapshot("snapshot-v1", ()),
                region_admin_codes=SYNTHETIC_REGION_MAP,
                supported_content_types=frozenset({"12"}),
            )


if __name__ == "__main__":
    unittest.main()
