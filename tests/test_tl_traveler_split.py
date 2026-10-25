from __future__ import annotations

import json
import unittest

from scripts.recommendation.tl_traveler_split import (
    I4SourceUnavailableError,
    audit_payload,
    deterministic_traveler_group_split,
    recompute_inner_train_positive_interaction_count,
    recompute_inner_train_visit_type_codes,
    traveler_trip_distribution,
    validate_no_traveler_overlap,
)


class TLTravelerSplitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.trip_owner = {
            "trip-a1": "traveler-a",
            "trip-b1": "traveler-b",
            "trip-b2": "traveler-b",
            "trip-c1": "traveler-c",
            "trip-c2": "traveler-c",
            "trip-c3": "traveler-c",
            "trip-d1": "traveler-d",
        }

    def test_distribution_reports_only_required_aggregate_statistics(self) -> None:
        rows = [
            {"TRAVEL_ID": trip, "TRAVELER_ID": traveler}
            for trip, traveler in self.trip_owner.items()
        ]
        aggregate, owners = traveler_trip_distribution(rows)
        self.assertEqual(aggregate["distinct_travelers"], 4)
        self.assertEqual(aggregate["distinct_trips"], 7)
        self.assertEqual(
            aggregate["traveler_trip_count"],
            {
                "one_trip_travelers": 2,
                "two_trip_travelers": 1,
                "three_or_more_trip_travelers": 1,
            },
        )
        self.assertEqual(aggregate["mean_trips_per_traveler"], 1.75)
        self.assertEqual(aggregate["median_trips_per_traveler"], 1.5)
        self.assertEqual(aggregate["max_trips_per_traveler"], 3)
        self.assertEqual(aggregate["multi_trip_traveler_share"], 0.5)
        self.assertEqual(owners, self.trip_owner)
        self.assertNotIn("traveler-a", json.dumps(aggregate))
        self.assertNotIn("trip-a1", json.dumps(aggregate))

    def test_distribution_deduplicates_trips_and_rejects_conflicting_owners(self) -> None:
        rows = [
            {"TRAVEL_ID": "trip-a", "TRAVELER_ID": "traveler-a"},
            {"TRAVEL_ID": "trip-a", "TRAVELER_ID": "traveler-a"},
        ]
        aggregate, _ = traveler_trip_distribution(rows)
        self.assertEqual(aggregate["distinct_trips"], 1)
        with self.assertRaisesRegex(ValueError, "conflicting traveler ownership"):
            traveler_trip_distribution(
                rows + [{"TRAVEL_ID": "trip-a", "TRAVELER_ID": "traveler-b"}]
            )

    def test_group_split_is_deterministic_and_has_no_traveler_overlap(self) -> None:
        first = deterministic_traveler_group_split(
            self.trip_owner, seed=41, validation_fraction=0.25
        )
        second = deterministic_traveler_group_split(
            self.trip_owner, seed=41, validation_fraction=0.25
        )
        self.assertEqual(first, second)
        self.assertEqual(validate_no_traveler_overlap(self.trip_owner, first), 0)
        self.assertEqual(set(first), set(self.trip_owner))
        for traveler in set(self.trip_owner.values()):
            partitions = {
                first[trip]
                for trip, owner in self.trip_owner.items()
                if owner == traveler
            }
            self.assertEqual(len(partitions), 1)

    def test_group_split_rejects_one_traveler_or_invalid_ratio(self) -> None:
        with self.assertRaisesRegex(ValueError, "At least two travelers"):
            deterministic_traveler_group_split(
                {"trip-a": "traveler-a"}, seed="s", validation_fraction=0.2
            )
        with self.assertRaisesRegex(ValueError, "between zero and one"):
            deterministic_traveler_group_split(
                self.trip_owner, seed="s", validation_fraction=1.0
            )

    def test_i3_uses_only_unique_inner_train_tl_interactions(self) -> None:
        partitions = {
            "trip-a1": "inner-train",
            "trip-b1": "inner-train",
            "trip-b2": "inner-validation",
            "trip-c1": "inner-validation",
        }
        base = [
            {
                "trip_id": "trip-a1",
                "item_id": "poi-x",
                "source_split": "TL",
                "observed_positive": 1,
            },
            {
                "trip_id": "trip-b1",
                "item_id": "poi-x",
                "source_split": "TL",
                "observed_positive": 1,
            },
            {
                "trip_id": "trip-b1",
                "item_id": "poi-x",
                "source_split": "TL",
                "observed_positive": 1,
            },
            {
                "trip_id": "trip-b2",
                "item_id": "poi-y",
                "source_split": "TL",
                "observed_positive": 1,
            },
        ]
        expected = {"poi-x": 2, "poi-y": 0, "poi-unseen": 0}
        self.assertEqual(
            recompute_inner_train_positive_interaction_count(
                base, partitions, all_item_ids=["poi-unseen"]
            ),
            expected,
        )
        changed_validation = base + [
            {
                "trip_id": "trip-c1",
                "item_id": "poi-x",
                "source_split": "TL",
                "observed_positive": 1,
            },
            {
                "trip_id": "trip-b2",
                "item_id": "poi-z",
                "source_split": "TL",
                "observed_positive": 1,
            },
        ]
        self.assertEqual(
            recompute_inner_train_positive_interaction_count(
                changed_validation, partitions, all_item_ids=["poi-unseen"]
            ),
            expected,
        )

    def test_i3_rejects_non_tl_or_nonpositive_rows(self) -> None:
        partitions = {"trip-a1": "inner-train"}
        with self.assertRaisesRegex(ValueError, "outer TL"):
            recompute_inner_train_positive_interaction_count(
                [
                    {
                        "trip_id": "trip-a1",
                        "item_id": "poi-x",
                        "source_split": "VL",
                        "observed_positive": 1,
                    }
                ],
                partitions,
            )
        with self.assertRaisesRegex(ValueError, "observed-positive"):
            recompute_inner_train_positive_interaction_count(
                [
                    {
                        "trip_id": "trip-a1",
                        "item_id": "poi-x",
                        "source_split": "TL",
                        "observed_positive": 0,
                    }
                ],
                partitions,
            )

    def test_i4_requires_events_and_uses_inner_train_visit_events_only(self) -> None:
        partitions = {
            "trip-a1": "inner-train",
            "trip-b1": "inner-validation",
        }
        with self.assertRaises(I4SourceUnavailableError):
            recompute_inner_train_visit_type_codes(None, partitions)

        events = [
            {
                "TRAVEL_ID": "trip-a1",
                "POI_ID": "poi-x",
                "VISIT_AREA_TYPE_CD": "1",
                "source_split": "TL",
            },
            {
                "TRAVEL_ID": "trip-a1",
                "POI_ID": "poi-x",
                "VISIT_AREA_TYPE_CD": "4",
                "source_split": "TL",
            },
            {
                "TRAVEL_ID": "trip-b1",
                "POI_ID": "poi-x",
                "VISIT_AREA_TYPE_CD": "2",
                "source_split": "TL",
            },
            {
                "TRAVEL_ID": "trip-b1",
                "POI_ID": "poi-y",
                "VISIT_AREA_TYPE_CD": "3",
                "source_split": "TL",
            },
        ]
        expected = {"poi-x": ["1", "4"], "poi-y": []}
        self.assertEqual(
            recompute_inner_train_visit_type_codes(
                events, partitions, all_item_ids=["poi-y"]
            ),
            expected,
        )
        changed_validation = events + [
            {
                "TRAVEL_ID": "trip-b1",
                "POI_ID": "poi-x",
                "VISIT_AREA_TYPE_CD": "12",
                "source_split": "TL",
            }
        ]
        self.assertEqual(
            recompute_inner_train_visit_type_codes(changed_validation, partitions),
            {"poi-x": ["1", "4"], "poi-y": []},
        )

    def test_audit_payload_contains_only_aggregate_and_split_metadata(self) -> None:
        rows = [
            {"TRAVEL_ID": trip, "TRAVELER_ID": traveler}
            for trip, traveler in self.trip_owner.items()
        ]
        payload = audit_payload(
            {
                "capital": rows,
                "west": rows,
                "east": rows,
                "jeju-islands": rows,
            },
            seed="test-seed",
            validation_fraction=0.25,
        )
        serialized = json.dumps(payload)
        for raw_value in self.trip_owner:
            self.assertNotIn(raw_value, serialized)
        for raw_value in set(self.trip_owner.values()):
            self.assertNotIn(raw_value, serialized)
        self.assertNotIn("path", serialized)
        self.assertTrue(all(
            region["inner_split"]["traveler_overlap"] == 0
            for region in payload["regions"].values()
        ))


if __name__ == "__main__":
    unittest.main()
