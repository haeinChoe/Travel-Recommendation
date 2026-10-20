from __future__ import annotations

import unittest

from scripts.recommendation.training_data_contract import (
    OBSERVATION_GRAINS,
    PRIMARY_CONTEXT_FEATURES,
    TOURISM_CORE_VISIT_AREA_TYPES,
    build_trip_poi_positives,
    check_split_trip_leakage,
    derive_companion_relation_codes,
    derive_temporal_features,
    evaluate_visit_observation,
    resolve_sgg_code_parity,
    validate_code_domain,
    validate_companions_num,
    validate_feature_contract,
)


class TrainingDataContractTests(unittest.TestCase):
    def test_three_level_observation_grains_defined(self) -> None:
        self.assertEqual(
            OBSERVATION_GRAINS["visit_event_grain"],
            ("region", "TRAVEL_ID", "VISIT_AREA_ID"),
        )
        self.assertEqual(
            OBSERVATION_GRAINS["trip_poi_grain"],
            ("region", "TRAVEL_ID", "POI_ID"),
        )
        self.assertEqual(
            OBSERVATION_GRAINS["trip_request_grain"],
            ("region", "TRAVELER_ID", "TRAVEL_ID"),
        )

    def test_eligibility_is_independent_of_tourapi_match_status(self) -> None:
        statuses = (None, "MATCHED", "AMBIGUOUS", "UNMATCHED", "identity_source_missing")
        results = [
            evaluate_visit_observation(
                region="capital",
                travel_id="T1",
                visit_area_id="V1",
                poi_id="P1",
                visit_area_type_cd="1",
                trip_exists_unique=True,
                traveler_exists_unique=True,
                catalog_match_status=status,
            )
            for status in statuses
        ]
        first = results[0]
        self.assertTrue(first.structurally_valid_visit_event)
        self.assertTrue(first.structurally_valid_trip_poi)
        self.assertEqual(first.domain_cohort, "tourism_core")
        self.assertTrue(first.is_tourism_core_positive)
        for res in results[1:]:
            self.assertEqual(res, first)

    def test_tourism_core_vs_non_tourism_separation(self) -> None:
        core_obs = evaluate_visit_observation(
            region="west",
            travel_id="T1",
            visit_area_id="V1",
            poi_id="P1",
            visit_area_type_cd="2",  # 역사/유적/종교
            trip_exists_unique=True,
            traveler_exists_unique=True,
        )
        self.assertEqual(core_obs.domain_cohort, "tourism_core")
        self.assertEqual(core_obs.exclusion_reasons, ())
        self.assertTrue(core_obs.is_tourism_core_positive)

        restaurant_obs = evaluate_visit_observation(
            region="west",
            travel_id="T1",
            visit_area_id="V2",
            poi_id="P2",
            visit_area_type_cd="11",  # 식당/카페
            trip_exists_unique=True,
            traveler_exists_unique=True,
        )
        self.assertTrue(restaurant_obs.structurally_valid_trip_poi)
        self.assertEqual(restaurant_obs.domain_cohort, "non_tourism")
        self.assertIn("non_tourism_visit_area_type", restaurant_obs.exclusion_reasons)
        self.assertFalse(restaurant_obs.is_tourism_core_positive)

        home_no_poi_obs = evaluate_visit_observation(
            region="west",
            travel_id="T1",
            visit_area_id="V3",
            poi_id=None,
            visit_area_type_cd="21",  # 집
            trip_exists_unique=True,
            traveler_exists_unique=True,
        )
        self.assertTrue(home_no_poi_obs.structurally_valid_visit_event)
        self.assertFalse(home_no_poi_obs.structurally_valid_trip_poi)
        self.assertIn("missing_poi_id", home_no_poi_obs.exclusion_reasons)
        self.assertIn("non_tourism_visit_area_type", home_no_poi_obs.exclusion_reasons)

    def test_trip_poi_grain_deduplication_and_repeat_diagnostic(self) -> None:
        visit_rows = [
            {
                "TRAVEL_ID": "T100",
                "VISIT_AREA_ID": "1",
                "POI_ID": "POI_A",
                "VISIT_AREA_TYPE_CD": "1",
                "SGG_CD": "11110",
            },
            {
                "TRAVEL_ID": "T100",
                "VISIT_AREA_ID": "2",
                "POI_ID": "POI_A",
                "VISIT_AREA_TYPE_CD": "1",
                "SGG_CD": "11110",
            },
            {
                "TRAVEL_ID": "T100",
                "VISIT_AREA_ID": "3",
                "POI_ID": "POI_B",
                "VISIT_AREA_TYPE_CD": "11",
                "SGG_CD": "11140",
            },
            {
                "TRAVEL_ID": "T100",
                "VISIT_AREA_ID": "4",
                "POI_ID": "",
                "VISIT_AREA_TYPE_CD": "21",
                "SGG_CD": "11110",
            },
        ]
        positives, diag = build_trip_poi_positives(
            visit_rows,
            region="capital",
            trip_to_traveler={"T100": "U1"},
            valid_traveler_ids={"U1"},
        )
        self.assertEqual(len(positives), 2)
        self.assertEqual(diag["total_visit_rows"], 4)
        self.assertEqual(diag["valid_visit_event_rows"], 4)
        self.assertEqual(diag["missing_poi_visit_rows"], 1)
        self.assertEqual(diag["distinct_trip_poi_positives"], 2)
        self.assertEqual(diag["tourism_core_trip_poi_positives"], 1)
        self.assertEqual(diag["within_trip_repeat_poi_pairs"], 1)
        self.assertEqual(diag["within_trip_repeat_extra_events"], 1)

        poi_a = next(p for p in positives if p.poi_id == "POI_A")
        self.assertEqual(poi_a.observed_positive, 1)
        self.assertEqual(poi_a.repeat_visit_count, 2)
        self.assertTrue(poi_a.has_tourism_core_visit)

    def test_temporal_and_code_domain_validation(self) -> None:
        valid_temp = derive_temporal_features("2023-05-10", "2023-05-12")
        self.assertTrue(valid_temp.is_valid)
        self.assertEqual(valid_temp.month, "05")
        self.assertEqual(valid_temp.elapsed_days, 2)

        inverted_temp = derive_temporal_features("2023-05-12", "2023-05-10")
        self.assertFalse(inverted_temp.is_valid)
        self.assertIsNone(inverted_temp.elapsed_days)
        self.assertEqual(inverted_temp.invalid_reason, "inverted_date_range")

        self.assertEqual(validate_code_domain("TRAVEL_STYL_1", "7"), "7")
        self.assertIsNone(validate_code_domain("TRAVEL_STYL_1", "8"))
        self.assertEqual(validate_code_domain("TRAVEL_MOTIVE_1", "10"), "10")
        self.assertIsNone(validate_code_domain("TRAVEL_MOTIVE_1", "11"))
        self.assertEqual(validate_companions_num("0"), 0)
        self.assertEqual(validate_companions_num("3"), 3)
        self.assertIsNone(validate_companions_num("-1"))

        rel = derive_companion_relation_codes([{"REL_CD": "2"}, {"REL_CD": "1"}, {"REL_CD": "99"}])
        self.assertEqual(rel, ("1", "2"))

    def test_feature_contract_and_sgg_parity(self) -> None:
        self.assertEqual(validate_feature_contract(PRIMARY_CONTEXT_FEATURES), ())
        self.assertIn(
            "raw_identifiers_are_join_keys_not_model_features",
            validate_feature_contract(["POI_ID", "region"]),
        )
        self.assertIn(
            "post_event_feedback_is_unavailable_at_request_time",
            validate_feature_contract(["DGSTFN", "region"]),
        )
        self.assertIn(
            "demographics_excluded_from_default_model_features",
            validate_feature_contract(["GENDER", "AGE_GRP"]),
        )
        self.assertIn(
            "training_eligibility_must_not_depend_on_catalog_match_status",
            validate_feature_contract(["region"], catalog_match_status_filter="MATCHED"),
        )

        # SGG parity resolution
        self.assertEqual(resolve_sgg_code_parity("11110"), ("11", "110"))
        self.assertEqual(resolve_sgg_code_parity("42110"), ("51", "110"))
        self.assertEqual(resolve_sgg_code_parity("29110"), ("12", "210"))
        self.assertEqual(resolve_sgg_code_parity("36110"), ("36110", "36110"))
        self.assertIsNone(resolve_sgg_code_parity(""))

        self.assertEqual(check_split_trip_leakage({"T1", "T2"}, {"T3"}), 0)
        self.assertEqual(check_split_trip_leakage({"T1", "T2"}, {"T2", "T3"}), 1)


if __name__ == "__main__":
    unittest.main()
