from __future__ import annotations

import unittest
from collections.abc import Mapping

from scripts.recommendation.poi_rich_feature_audit import (
    ItemHistory,
    _build_inner_train_histories,
    build_poi_rich_feature_row,
)
from scripts.recommendation.training_data_contract import (
    TripPoiPositive,
    build_trip_poi_positives,
)
from scripts.recommendation.tl_traveler_split import (
    recompute_inner_train_positive_interaction_count,
    recompute_inner_train_visit_type_codes,
)


def trip_poi(
    travel_id: str,
    poi_id: str,
    *,
    traveler_id: str = "traveler-train",
    visit_area_types: tuple[str, ...] = ("1",),
    tourism_core: bool = True,
    repeat_visit_count: int = 1,
) -> TripPoiPositive:
    return TripPoiPositive(
        region="capital",
        traveler_id=traveler_id,
        travel_id=travel_id,
        poi_id=poi_id,
        observed_positive=1,
        repeat_visit_count=repeat_visit_count,
        has_tourism_core_visit=tourism_core,
        visit_area_types=visit_area_types,
        sgg_codes=("11110",),
    )


def context(
    *,
    start_month: str | None = "03",
    companion_status: str | None = "family",
) -> dict[str, object]:
    return {
        "start_month": start_month,
        "companion_status": companion_status,
        "travel_motive_1": "1",
        "travel_style_1": "2",
    }


def build_histories(
    positives: list[TripPoiPositive],
    context_by_trip: dict[str, dict[str, object]],
    *,
    partition_by_trip: dict[str, str] | None = None,
    trip_owner: dict[str, str] | None = None,
) -> tuple[Mapping[str, Mapping[str, ItemHistory]], dict[str, object]]:
    partitions = partition_by_trip or {trip: "inner-train" for trip in context_by_trip}
    owners = trip_owner or {trip: "traveler-train" for trip in context_by_trip}
    return _build_inner_train_histories(
        positives=positives,
        partition_by_trip=partitions,
        trip_owner=owners,
        context_by_trip=context_by_trip,
        candidate_ids={"poi-a"},
    )


class PoiRichFeatureAuditTests(unittest.TestCase):
    def test_inner_validation_changes_do_not_change_train_features(self) -> None:
        train_pair = trip_poi("train-trip", "poi-a")
        validation_pair_before = trip_poi(
            "validation-trip", "poi-a", traveler_id="traveler-validation"
        )
        validation_pair_after = trip_poi(
            "validation-trip",
            "poi-b",
            traveler_id="traveler-validation",
            visit_area_types=("11",),
            tourism_core=False,
        )
        partitions = {
            "train-trip": "inner-train",
            "validation-trip": "inner-validation",
        }
        owners = {
            "train-trip": "traveler-train",
            "validation-trip": "traveler-validation",
        }
        contexts_before = {
            "train-trip": context(),
            "validation-trip": context(start_month="04", companion_status="friends"),
        }
        contexts_after = {
            "train-trip": context(),
            "validation-trip": context(start_month="12", companion_status="solo"),
        }
        interactions_before = [
            {
                "TRAVEL_ID": pair.travel_id,
                "POI_ID": pair.poi_id,
                "observed_positive": 1,
                "source_split": "TL",
            }
            for pair in (train_pair, validation_pair_before)
        ]
        interactions_after = [
            {
                "TRAVEL_ID": pair.travel_id,
                "POI_ID": pair.poi_id,
                "observed_positive": 1,
                "source_split": "TL",
            }
            for pair in (train_pair, validation_pair_after)
        ]
        visit_events_before = [
            {
                "TRAVEL_ID": pair.travel_id,
                "POI_ID": pair.poi_id,
                "VISIT_AREA_TYPE_CD": pair.visit_area_types[0],
                "source_split": "TL",
            }
            for pair in (train_pair, validation_pair_before)
        ]
        visit_events_after = [
            {
                "TRAVEL_ID": pair.travel_id,
                "POI_ID": pair.poi_id,
                "VISIT_AREA_TYPE_CD": pair.visit_area_types[0],
                "source_split": "TL",
            }
            for pair in (train_pair, validation_pair_after)
        ]

        histories_before, _ = build_histories(
            [train_pair, validation_pair_before],
            contexts_before,
            partition_by_trip=partitions,
            trip_owner=owners,
        )
        histories_after, _ = build_histories(
            [train_pair, validation_pair_after],
            contexts_after,
            partition_by_trip=partitions,
            trip_owner=owners,
        )

        def feature_row(
            histories: Mapping[str, Mapping[str, ItemHistory]],
        ) -> dict[str, object]:
            return build_poi_rich_feature_row(
                item_id="poi-a",
                static_item={
                    "canonical_admin_sido_code": "11",
                    "canonical_admin_sgg_code": "11110",
                    "canonical_admin_location_status": "resolved_single_source",
                    "source_category_l1_code": "A",
                    "source_category_l2_code": "A1",
                    "source_category_l3_code": "A101",
                },
                all_valid_history=histories["all_valid_observed"].get("poi-a"),
                tourism_core_history=histories["tourism_core"].get("poi-a"),
                baseline_i3=0,
                baseline_i4=(),
            )

        self.assertEqual(feature_row(histories_before), feature_row(histories_after))
        self.assertEqual(
            recompute_inner_train_positive_interaction_count(
                interactions_before, partitions
            ),
            recompute_inner_train_positive_interaction_count(
                interactions_after, partitions
            ),
        )
        self.assertEqual(
            recompute_inner_train_visit_type_codes(visit_events_before, partitions),
            recompute_inner_train_visit_type_codes(visit_events_after, partitions),
        )

    def test_repeated_visits_in_one_trip_make_one_trip_poi_support(self) -> None:
        visit_rows = [
            {
                "TRAVEL_ID": trip_id,
                "VISIT_AREA_ID": visit_id,
                "POI_ID": "poi-a",
                "VISIT_AREA_TYPE_CD": "11",
                "SGG_CD": "11110",
            }
            for trip_id, visit_id in (
                ("train-trip", "visit-1"),
                ("train-trip", "visit-2"),
                ("second-trip", "visit-3"),
            )
        ]
        positives, diagnostics = build_trip_poi_positives(
            visit_rows,
            region="capital",
            trip_to_traveler={
                "train-trip": "traveler-train",
                "second-trip": "traveler-train",
            },
            valid_traveler_ids={"traveler-train"},
        )

        histories, _ = build_histories(
            positives,
            {"train-trip": context(), "second-trip": context()},
        )

        self.assertEqual(len(positives), 2)
        self.assertEqual(
            {pair.travel_id: pair.repeat_visit_count for pair in positives},
            {"train-trip": 2, "second-trip": 1},
        )
        self.assertEqual(diagnostics["within_trip_repeat_extra_events"], 1)
        self.assertEqual(
            histories["all_valid_observed"]["poi-a"].distinct_trip_poi_support,
            2,
        )
        self.assertEqual(
            len(histories["all_valid_observed"]["poi-a"].traveler_ids),
            1,
        )

    def test_missing_context_field_has_null_share_not_zero_share(self) -> None:
        histories, _ = build_histories(
            [trip_poi("train-trip", "poi-a")],
            {"train-trip": context(start_month=None)},
        )

        row = build_poi_rich_feature_row(
            item_id="poi-a",
            static_item={},
            all_valid_history=histories["all_valid_observed"].get("poi-a"),
            tourism_core_history=histories["tourism_core"].get("poi-a"),
            baseline_i3=0,
            baseline_i4=(),
        )

        self.assertIsNone(row["all_valid_observed_profile_shares"]["start_month"])
        self.assertEqual(
            row["all_valid_observed_profile_support"]["start_month"]["valid_trip_poi_support"],
            0,
        )

    def test_missing_field_response_is_excluded_from_valid_denominator(self) -> None:
        histories, _ = build_histories(
            [
                trip_poi("trip-with-month", "poi-a"),
                trip_poi("trip-without-month", "poi-a"),
            ],
            {
                "trip-with-month": context(start_month="03"),
                "trip-without-month": context(start_month=None),
            },
        )

        row = build_poi_rich_feature_row(
            item_id="poi-a",
            static_item={},
            all_valid_history=histories["all_valid_observed"].get("poi-a"),
            tourism_core_history=histories["tourism_core"].get("poi-a"),
            baseline_i3=0,
            baseline_i4=(),
        )

        self.assertEqual(
            row["all_valid_observed_profile_shares"]["start_month"],
            {"03": 1.0},
        )
        self.assertEqual(
            row["all_valid_observed_profile_support"]["start_month"]["valid_trip_poi_support"],
            1,
        )

    def test_cold_item_retains_static_features_and_zero_history_support(self) -> None:
        row = build_poi_rich_feature_row(
            item_id="cold-poi",
            static_item={
                "canonical_admin_sido_code": "11",
                "canonical_admin_sgg_code": "11110",
                "source_category_l1_code": "A",
                "source_category_l2_code": None,
                "source_category_l3_code": None,
            },
            all_valid_history=None,
            tourism_core_history=None,
            baseline_i3=0,
            baseline_i4=(),
        )

        self.assertEqual(row["canonical_admin_sido_code"], "11")
        self.assertEqual(row["canonical_admin_sgg_code"], "11110")
        self.assertEqual(row["source_category_l1_code"], "A")
        self.assertFalse(row["source_category_l1_code_missing"])
        self.assertTrue(row["source_category_l2_code_missing"])
        self.assertEqual(row["all_valid_observed_trip_poi_support"], 0)
        self.assertEqual(row["tourism_core_trip_poi_support"], 0)
        self.assertIsNone(row["all_valid_observed_profile_shares"]["start_month"])

    def test_non_tourism_visit_remains_observed_outside_core_cohort(self) -> None:
        histories, summary = build_histories(
            [
                trip_poi(
                    "train-trip",
                    "poi-a",
                    visit_area_types=("11",),
                    tourism_core=False,
                )
            ],
            {"train-trip": context()},
        )

        self.assertEqual(
            histories["all_valid_observed"]["poi-a"].distinct_trip_poi_support,
            1,
        )
        self.assertEqual(histories["tourism_core"].get("poi-a", None), None)
        self.assertEqual(
            summary["visit_pair_type_counts_inner_train_in_candidate_universe"][
                "known_non_tourism_only"
            ],
            1,
        )


if __name__ == "__main__":
    unittest.main()
