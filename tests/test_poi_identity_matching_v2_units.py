"""Comprehensive unit tests for POI identity matching pipeline v2 (Issue #69).

Tests:
1. TourAPI v4.4 snapshot coordinates (mapx, mapy) and addr2 loading & backwards compatibility.
2. Haversine distance and Korea bounding box coordinate validation.
3. Structured address key parsing (road full/main, lotno full/main, sido normalization).
4. SGG crosswalk code compatibility and migration logic.
5. Location-gated name normalization (N1, N2, region prefix, facility suffix, containment).
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.recommendation.geo_distance import (
    haversine_distance_meters,
    is_valid_korea_wgs84,
)
from scripts.recommendation.address_key_parser import (
    parse_address_string,
    match_parsed_addresses,
    normalize_sido,
)
from scripts.recommendation.sgg_crosswalk import SggCrosswalk
from scripts.recommendation.name_normalizer import (
    normalize_punctuation_n1,
    split_parenthetical_variants_n2,
    strip_facility_suffix,
    strip_region_prefix,
    generate_location_gated_name_variants,
)
from scripts.recommendation.poi_catalog_candidate_contract import (
    CatalogPoi,
    load_tourapi_v44_snapshot_csv,
)
from scripts.recommendation.tourapi_snapshot_adapter import (
    SNAPSHOT_CSV_COLUMNS,
    TourApiFieldMap,
    adapt_tourapi_snapshot,
    normalize_tourapi_item,
)


class GeoDistanceTests(unittest.TestCase):
    def test_coordinate_validation(self) -> None:
        self.assertTrue(is_valid_korea_wgs84(37.582, 126.984))  # Seoul
        self.assertTrue(is_valid_korea_wgs84(33.499, 126.531))  # Jeju
        self.assertFalse(is_valid_korea_wgs84(0.0, 0.0))
        self.assertFalse(is_valid_korea_wgs84(None, 127.0))
        self.assertFalse(is_valid_korea_wgs84(40.0, 127.0))  # North of Korea

    def test_haversine_distance(self) -> None:
        dist_zero = haversine_distance_meters(37.5, 127.0, 37.5, 127.0)
        self.assertAlmostEqual(dist_zero, 0.0, places=3)

        # Distance between Seoul City Hall (~37.5663, 126.9779) and Gwanghwamun (~37.5759, 126.9768)
        dist = haversine_distance_meters(37.5663, 126.9779, 37.5759, 126.9768)
        self.assertTrue(900 < dist < 1200)


class AddressKeyParserTests(unittest.TestCase):
    def test_normalize_sido(self) -> None:
        self.assertEqual(normalize_sido("서울특별시"), "서울")
        self.assertEqual(normalize_sido("강원특별자치도"), "강원")
        self.assertEqual(normalize_sido("제주도"), "제주")
        self.assertEqual(normalize_sido("전북특별자치도"), "전북")
        self.assertEqual(normalize_sido("경기도"), "경기")

    def test_parse_road_address(self) -> None:
        addr = "서울특별시 종로구 북촌로 57 (가회동)"
        parsed = parse_address_string(addr)
        self.assertIsNotNone(parsed)
        self.assertIsNotNone(parsed.road_key)
        self.assertEqual(parsed.road_key.sido, "서울")
        self.assertEqual(parsed.road_key.sigungu, "종로구")
        self.assertEqual(parsed.road_key.road_name, "북촌로")
        self.assertEqual(parsed.road_key.main_no, 57)
        self.assertEqual(parsed.road_key.sub_no, 0)
        self.assertEqual(parsed.road_key.key_full, ("서울", "종로구", "북촌로", 57, 0))
        self.assertEqual(parsed.road_key.key_main, ("서울", "종로구", "북촌로", 57))

    def test_parse_lotno_address(self) -> None:
        addr = "강원도 강릉시 저동 94"
        parsed = parse_address_string(addr)
        self.assertIsNotNone(parsed)
        self.assertIsNotNone(parsed.lotno_key)
        self.assertEqual(parsed.lotno_key.sido, "강원")
        self.assertEqual(parsed.lotno_key.sigungu, "강릉시")
        self.assertEqual(parsed.lotno_key.emd_ri, "저동")
        self.assertEqual(parsed.lotno_key.main_no, 94)
        self.assertFalse(parsed.lotno_key.san_flag)

    def test_match_parsed_addresses(self) -> None:
        addr1 = parse_address_string("서울특별시 종로구 북촌로 57 (가회동)")
        addr2 = parse_address_string("서울 종로구 북촌로 57")
        # 57 vs 57: full exact match (both main_no=57, sub_no=0)
        self.assertEqual(match_parsed_addresses(addr1, addr2), "road_exact_full")

        addr3 = parse_address_string("서울 종로구 북촌로 57-1")
        # 57 vs 57-1: main exact match (sub_no omitted on one side; requires secondary evidence for promotion)
        self.assertEqual(match_parsed_addresses(addr1, addr3), "road_exact_main")

        addr4 = parse_address_string("서울 종로구 북촌로 57-2")
        # 57-1 vs 57-2: both have explicit differing sub numbers -> None (conflict)
        self.assertIsNone(match_parsed_addresses(addr3, addr4))

    def test_lotno_sub_no_conflict_blocks_main_match(self) -> None:
        addr1 = parse_address_string("강원도 강릉시 저동 94")
        addr2 = parse_address_string("강원도 강릉시 저동 94-1")
        addr3 = parse_address_string("강원도 강릉시 저동 94-2")

        # 94 vs 94-1: lotno_exact_main (sub_no omitted on one side)
        self.assertEqual(match_parsed_addresses(addr1, addr2), "lotno_exact_main")
        # 94-1 vs 94-2: both have explicit differing sub numbers -> None (conflict)
        self.assertIsNone(match_parsed_addresses(addr2, addr3))
        # 94-1 vs 94-1: lotno_exact_full
        self.assertEqual(match_parsed_addresses(addr2, addr2), "lotno_exact_full")


class SggCrosswalkTests(unittest.TestCase):
    def test_sgg_crosswalk_logic(self) -> None:
        cw = SggCrosswalk()
        # Direct same code
        self.assertTrue(cw.is_compatible("1111000000", "11", "110"))
        # Migrated Gangwon 42 -> 51
        self.assertTrue(cw.is_compatible("4211000000", "51", "110"))
        # Migrated Jeonbuk 45 -> 52
        self.assertTrue(cw.is_compatible("4511000000", "52", "110"))
        # Incompatible
        self.assertFalse(cw.is_compatible("1111000000", "41", "110"))

    def test_gwangju_jeonnam_cross_conflict_prevention(self) -> None:
        cw = SggCrosswalk()
        # Gwangju Dong-gu (29110) must match TourAPI (12, 210) but NOT (12, 110: Mokpo)
        self.assertTrue(cw.is_compatible("29110", "12", "210"))
        self.assertFalse(cw.is_compatible("29110", "12", "110"))

        # Jeonnam Mokpo (46110) must match TourAPI (12, 110) but NOT (12, 210: Gwangju Dong-gu)
        self.assertTrue(cw.is_compatible("46110", "12", "110"))
        self.assertFalse(cw.is_compatible("46110", "12", "210"))

        # Gwangju Buk-gu (29170) must match TourAPI (12, 300) but NOT (12, 170: Naju)
        self.assertTrue(cw.is_compatible("29170", "12", "300"))
        self.assertFalse(cw.is_compatible("29170", "12", "170"))

        # Jeonnam Naju (46170) must match TourAPI (12, 170) but NOT (12, 300: Gwangju Buk-gu)
        self.assertTrue(cw.is_compatible("46170", "12", "170"))
        self.assertFalse(cw.is_compatible("46170", "12", "300"))

        # 2-digit SIDO without signgu must fail-closed (cannot distinguish Gwangju vs Jeonnam)
        self.assertFalse(cw.is_compatible("29", "12", ""))
        self.assertFalse(cw.is_compatible("46", "12", ""))

    def test_sejong_special_city_mapping(self) -> None:
        cw = SggCrosswalk()
        # Sejong 5-digit 36110 matches TourAPI (36110, 36110)
        self.assertTrue(cw.is_compatible("36110", "36110", "36110"))
        # Sejong 2-digit 36 matches TourAPI (36110, 36110)
        self.assertTrue(cw.is_compatible("36", "36110", "36110"))
        # Sejong does not match Seoul (11, 110)
        self.assertFalse(cw.is_compatible("36110", "11", "110"))

    def test_sido_sigungu_code_confusion_prevention(self) -> None:
        cw = SggCrosswalk()
        # 2-digit SIDO code 36 should not match random 5-digit code unless valid
        self.assertFalse(cw.is_compatible("36", "41", "110"))
        # 5-digit 42110 (Gangwon Chuncheon) should match (51, 110) but not (42, 110) if TourAPI uses 51
        self.assertTrue(cw.is_compatible("42110", "51", "110"))
        self.assertFalse(cw.is_compatible("42110", "51", "130"))  # Wonju

    def test_general_district_city_compatibility(self) -> None:
        cw = SggCrosswalk()
        # Suwon-si: representative 41110 vs sub-districts 111, 113, 115, 117
        self.assertTrue(cw.is_compatible("41110", "41", "111"))  # Suwon-si vs Jangan-gu
        self.assertTrue(cw.is_compatible("41110", "41", "113"))  # Suwon-si vs Gwonseon-gu
        self.assertTrue(cw.is_compatible("41111", "41", "110"))  # Jangan-gu vs Suwon-si rep
        # Seongnam-si: representative 41130 vs sub-district 135 (Bundang-gu)
        self.assertTrue(cw.is_compatible("41130", "41", "135"))
        # Jeonju-si: migrated 45110 (AI Hub) vs 52111 / 52113 (TourAPI)
        self.assertTrue(cw.is_compatible("45110", "52", "111"))
        self.assertTrue(cw.is_compatible("45113", "52", "110"))
        # Changwon-si: 48120 vs 48121 (Uichang-gu)
        self.assertTrue(cw.is_compatible("48120", "48", "121"))
        # Incompatible across different cities
        self.assertFalse(cw.is_compatible("41110", "41", "131"))  # Suwon rep vs Seongnam sub-district
        self.assertFalse(cw.is_compatible("41111", "41", "135"))  # Suwon Jangan vs Seongnam Bundang

    def test_multi_csv_loading(self) -> None:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".csv", delete=False) as f1, \
             tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".csv", delete=False) as f2:
            f1.write("SGG_CD1,SGG_CD2,SIDO_NM,SGG_NM\n11,110,서울특별시,종로구\n")
            f2.write("SGG_CD1,SGG_CD2,SIDO_NM,SGG_NM\n41,110,경기도,수원시\n")
            p1, p2 = f1.name, f2.name

        try:
            cw = SggCrosswalk([p1, p2])
            self.assertIn("11110", cw.aihub_to_names)
            self.assertIn("41110", cw.aihub_to_names)
            self.assertEqual(cw.aihub_to_names["11110"], ("서울특별시", "종로구"))
            self.assertEqual(cw.aihub_to_names["41110"], ("경기도", "수원시"))
        finally:
            Path(p1).unlink(missing_ok=True)
            Path(p2).unlink(missing_ok=True)


class NameNormalizerTests(unittest.TestCase):
    def test_punctuation_n1(self) -> None:
        self.assertEqual(normalize_punctuation_n1("남산(N)서울타워!"), "남산 n 서울타워")

    def test_parenthetical_variants_n2(self) -> None:
        variants = split_parenthetical_variants_n2("경복궁(사적 제117호)")
        self.assertIn("경복궁", variants)

    def test_facility_suffix(self) -> None:
        self.assertEqual(strip_facility_suffix("설악산 주차장"), "설악산")
        self.assertEqual(strip_facility_suffix("오대산 제1주차장"), "오대산")
        self.assertEqual(strip_facility_suffix("남산 케이블카"), "남산")
        self.assertEqual(strip_facility_suffix("광안리해수욕장 관광안내소"), "광안리해수욕장")
        self.assertEqual(strip_facility_suffix("감악산 출렁다리"), "감악산")

    def test_region_prefix(self) -> None:
        self.assertEqual(strip_region_prefix("서울 남산타워", ("서울",)), "남산타워")
        self.assertEqual(strip_region_prefix("제주 성산일출봉", ("제주",)), "성산일출봉")

    def test_generic_stopwords_blocked(self) -> None:
        # Generic single words like "해수욕장", "공원" should not match alone
        variants = generate_location_gated_name_variants("해수욕장")
        self.assertNotIn("해수욕장", variants)
        self.assertNotIn("공원", variants)


class SnapshotBackwardsCompatibilityTests(unittest.TestCase):
    def test_legacy_10_column_snapshot_loads_successfully(self) -> None:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".csv", delete=False) as tf:
            tf.write("contentid,contenttypeid,title,addr1,lDongRegnCd,lDongSignguCd,lclsSystm1,lclsSystm2,lclsSystm3,modifiedtime\n")
            tf.write("12345,12,Place,Seoul Road,11,110,A,A01,A0101,20261020000000\n")
            temp_path = tf.name

        try:
            snapshot = load_tourapi_v44_snapshot_csv(temp_path)
            self.assertEqual(len(snapshot.records), 1)
            item = snapshot.records[0]
            self.assertEqual(item.content_id, "12345")
            self.assertEqual(item.title, "Place")
            self.assertEqual(item.addr2, "")
            self.assertIsNone(item.mapx)
            self.assertIsNone(item.mapy)
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_v44_13_column_snapshot_loads_coordinates_and_addr2(self) -> None:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".csv", delete=False) as tf:
            tf.write("contentid,contenttypeid,title,addr1,addr2,mapx,mapy,lDongRegnCd,lDongSignguCd,lclsSystm1,lclsSystm2,lclsSystm3,modifiedtime\n")
            tf.write("12345,12,Place,Seoul Road,Building 2F,126.984,37.582,11,110,A,A01,A0101,20261020000000\n")
            temp_path = tf.name

        try:
            snapshot = load_tourapi_v44_snapshot_csv(temp_path)
            self.assertEqual(len(snapshot.records), 1)
            item = snapshot.records[0]
            self.assertEqual(item.content_id, "12345")
            self.assertEqual(item.addr2, "Building 2F")
            self.assertEqual(item.mapx, 126.984)
            self.assertEqual(item.mapy, 37.582)
        finally:
            Path(temp_path).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
