from __future__ import annotations

import unittest

from scripts.recommendation.canonical_admin_location import (
    address_admin_codes,
    build_admin_lookup,
    compare_visit_location,
    normalize_aihub_sgg_code,
    resolve_canonical_admin_location,
)


LOOKUP = build_admin_lookup([
    {"SGG_CD": "11110", "SGG_CD1": "11", "SGG_CD2": "110",
     "SIDO_NM": "서울", "SGG_NM": "중구"},
    {"SGG_CD": "11140", "SGG_CD1": "11", "SGG_CD2": "140",
     "SIDO_NM": "서울", "SGG_NM": "중구"},
    {"SGG_CD": "41110", "SGG_CD1": "41", "SGG_CD2": "110",
     "SIDO_NM": "경기", "SGG_NM": "수원시 장안구"},
    {"SGG_CD": "42110", "SGG_CD1": "42", "SGG_CD2": "110",
     "SIDO_NM": "강원", "SGG_NM": "춘천시"},
])


class CanonicalAdminLocationTests(unittest.TestCase):
    def test_accepts_only_codebook_valid_five_digit_or_padded_code(self) -> None:
        self.assertEqual(normalize_aihub_sgg_code("11110", LOOKUP), "11110")
        self.assertEqual(normalize_aihub_sgg_code("1111000000", LOOKUP), "11110")
        self.assertIsNone(normalize_aihub_sgg_code("11", LOOKUP))
        self.assertIsNone(normalize_aihub_sgg_code("9999900000", LOOKUP))
        self.assertIsNone(normalize_aihub_sgg_code("1111000001", LOOKUP))
        self.assertIsNone(normalize_aihub_sgg_code("111100000000", LOOKUP))

    def test_address_requires_unique_exact_sgg_name_under_sido(self) -> None:
        self.assertEqual(address_admin_codes("서울특별시 중구 세종대로 1", LOOKUP), ("11110", "11140"))
        self.assertEqual(address_admin_codes("경기도 수원시 장안구 정조로 1", LOOKUP), ("41110",))
        self.assertEqual(address_admin_codes("강원특별자치도 춘천시 중앙로 1", LOOKUP), ("42110",))
        self.assertEqual(address_admin_codes("서울특별시 종로구 세종대로 1", LOOKUP), ())

    def test_agreeing_master_code_and_address_resolve_with_provenance(self) -> None:
        result = resolve_canonical_admin_location(
            lookup=LOOKUP,
            master_sgg_codes=("4211000000",),
            master_addresses=("강원특별자치도 춘천시 중앙로 1",),
        )
        self.assertEqual(result.status, "resolved_single_source")
        self.assertEqual(result.sgg_code, "42110")
        self.assertIn("master_sgg_code", result.provenance)
        self.assertIn("master_address", result.provenance)
        self.assertEqual(result.coordinate_status, "unverified_not_used")

    def test_conflict_and_ambiguity_fail_closed(self) -> None:
        conflict = resolve_canonical_admin_location(
            lookup=LOOKUP, master_sgg_codes=("11110",), master_addresses=("경기도 수원시 장안구 정조로 1",)
        )
        self.assertEqual(conflict.status, "conflict")
        self.assertIsNone(conflict.sgg_code)
        self.assertIn("master", conflict.conflict_sources)
        ambiguous = resolve_canonical_admin_location(
            lookup=LOOKUP, master_addresses=("서울특별시 중구 세종대로 1",)
        )
        self.assertEqual(ambiguous.status, "ambiguous_address")
        self.assertIsNone(ambiguous.sgg_code)

    def test_tourapi_is_secondary_and_must_agree(self) -> None:
        agreed = resolve_canonical_admin_location(
            lookup=LOOKUP, master_sgg_codes=("11110",), tourapi_admin_codes=("11110",)
        )
        self.assertEqual(agreed.status, "resolved_multi_source")
        self.assertEqual(agreed.sgg_code, "11110")
        conflict = resolve_canonical_admin_location(
            lookup=LOOKUP, master_sgg_codes=("11110",), tourapi_admin_codes=("41110",)
        )
        self.assertEqual(conflict.status, "conflict")
        self.assertIsNone(conflict.sgg_code)

    def test_visit_only_evidence_never_populates_static_feature(self) -> None:
        result = resolve_canonical_admin_location(
            lookup=LOOKUP, visit_sgg_codes=("11110",)
        )
        self.assertEqual(result.status, "visit_only_unconfirmed")
        self.assertIsNone(result.sgg_code)
        self.assertEqual(compare_visit_location(
            canonical_sgg_code=None, visit_sgg_codes=("11110",), visit_addresses=(), lookup=LOOKUP
        ), "visit_only_unconfirmed")
        self.assertEqual(compare_visit_location(
            canonical_sgg_code="11110", visit_sgg_codes=("41110",), visit_addresses=(), lookup=LOOKUP
        ), "conflicts_with_static")

    def test_validation_positive_cannot_change_static_feature(self) -> None:
        before = resolve_canonical_admin_location(lookup=LOOKUP, master_sgg_codes=("11110",))
        comparison = compare_visit_location(
            canonical_sgg_code=before.sgg_code,
            visit_sgg_codes=("41110",),
            visit_addresses=(),
            lookup=LOOKUP,
        )
        after = resolve_canonical_admin_location(lookup=LOOKUP, master_sgg_codes=("11110",))
        self.assertEqual(comparison, "conflicts_with_static")
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
