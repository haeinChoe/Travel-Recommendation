"""Crosswalk mapping between AI Hub TC_SGG and TourAPI legal dong codes."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Mapping, Sequence


# Known SIDO code migrations between 2023 AI Hub and 2026 TourAPI
SIDO_AIHUB_TO_TOUR: dict[str, str] = {
    "42": "51",     # Gangwon -> Gangwon Special Self-Governing Province
    "45": "52",     # Jeonbuk -> Jeonbuk Special Self-Governing Province
    "29": "12",     # Gwangju -> Jeonnam-Gwangju Integrated Special City
    "46": "12",     # Jeonnam -> Jeonnam-Gwangju Integrated Special City
    "36": "36110",  # Sejong -> Sejong Special Self-Governing City
}

SIDO_TOUR_TO_AIHUB: dict[str, set[str]] = {
    "51": {"42"},
    "52": {"45"},
    "12": {"29", "46"},
    "36110": {"36"},
}

# Explicit mapping for Gwangju (29xxx) -> TourAPI (12, signgu)
GWANGJU_AIHUB_TO_TOUR_SIGNGU: dict[str, str] = {
    "29110": "210",  # 동구
    "29140": "240",  # 서구
    "29155": "270",  # 남구
    "29170": "300",  # 북구
    "29200": "330",  # 광산구
}

# Explicit mapping for Jeonnam (46xxx) -> TourAPI (12, signgu)
JEONNAM_AIHUB_TO_TOUR_SIGNGU: dict[str, str] = {
    "46110": "110",  # 목포시
    "46130": "130",  # 여수시
    "46150": "150",  # 순천시
    "46170": "170",  # 나주시
    "46230": "190",  # 광양시 (AI Hub 46230 -> TourAPI 190)
    "46710": "710",  # 담양군
    "46720": "720",  # 곡성군
    "46730": "730",  # 구례군
    "46770": "740",  # 고흥군
    "46780": "750",  # 보성군
    "46790": "760",  # 화순군
    "46800": "770",  # 장흥군
    "46810": "780",  # 강진군
    "46820": "790",  # 해남군
    "46830": "800",  # 영암군
    "46840": "810",  # 무안군
    "46860": "820",  # 함평군
    "46870": "830",  # 영광군
    "46880": "840",  # 장성군
    "46890": "850",  # 완도군
    "46900": "860",  # 진도군
    "46910": "870",  # 신안군
}

# 4-digit prefixes (c1 + c2[:2]) for cities with non-autonomous administrative districts (일반구)
GENERAL_DISTRICT_CITY_PREFIXES: frozenset[str] = frozenset({
    "4111",  # 경기도 수원시 (41110 vs 41111/113/115/117)
    "4113",  # 경기도 성남시 (41130 vs 41131/133/135)
    "4117",  # 경기도 안양시 (41170 vs 41171/173)
    "4127",  # 경기도 안산시 (41270 vs 41271/273)
    "4128",  # 경기도 고양시 (41280 vs 41281/285/287)
    "4146",  # 경기도 용인시 (41460 vs 41461/463/465)
    "4311",  # 충청북도 청주시 (43110 vs 43111/112/113/114)
    "4413",  # 충청남도 천안시 (44130 vs 44131/133)
    "4511",  # 전라북도 전주시 (AI Hub 45110 vs 45111/113)
    "5211",  # 전북특별자치도 전주시 (TourAPI 52110 vs 52111/113)
    "4711",  # 경상북도 포항시 (47110 vs 47111/113)
    "4812",  # 경상남도 창원시 (48120 vs 48121/123/125/127/129)
})


class SggCrosswalk:
    def __init__(self, sgg_csv_paths: str | Path | Sequence[str | Path] | None = None) -> None:
        self.aihub_to_names: dict[str, tuple[str, str]] = {}
        self.names_to_aihub: dict[tuple[str, str], str] = {}
        self.aihub_to_tour: dict[str, tuple[str, str]] = {}
        self.tour_to_aihub: dict[tuple[str, str], set[str]] = {}

        if sgg_csv_paths is not None:
            if isinstance(sgg_csv_paths, (str, Path)):
                self.load_from_csv(sgg_csv_paths)
            else:
                self.load_from_csvs(sgg_csv_paths)

    def load_from_csvs(self, paths: Sequence[str | Path]) -> None:
        """Load and merge multiple TC_SGG CSV files across regions."""
        for path in paths:
            self.load_from_csv(path)

    def load_from_csv(self, path: str | Path) -> None:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"TC_SGG file not found: {p}")

        with p.open("r", encoding="utf-8-sig", errors="ignore") as f:
            reader = csv.DictReader(f)
            for row in reader:
                c1 = (row.get("SGG_CD1") or "").strip()
                c2 = (row.get("SGG_CD2") or "").strip()
                sido = (row.get("SIDO_NM") or "").strip()
                sgg = (row.get("SGG_NM") or "").strip()
                if not (c1 and c2):
                    continue

                code_5 = c1 + c2
                self.aihub_to_names[code_5] = (sido, sgg)
                self.names_to_aihub[(sido, sgg)] = code_5

                # Determine TourAPI (regn, signgu) mapping
                tour_pair = self._resolve_tour_pair(code_5, c1, c2)
                self.aihub_to_tour[code_5] = tour_pair
                self.tour_to_aihub.setdefault(tour_pair, set()).add(code_5)

    def _resolve_tour_pair(self, code_5: str, c1: str, c2: str) -> tuple[str, str]:
        """Resolve expected TourAPI (regn, signgu) pair for an AI Hub SGG code."""
        # Sejong special case
        if code_5 == "36110" or c1 == "36":
            return ("36110", "36110")

        # Gwangju special case
        if code_5 in GWANGJU_AIHUB_TO_TOUR_SIGNGU:
            return ("12", GWANGJU_AIHUB_TO_TOUR_SIGNGU[code_5])

        # Jeonnam special case
        if code_5 in JEONNAM_AIHUB_TO_TOUR_SIGNGU:
            return ("12", JEONNAM_AIHUB_TO_TOUR_SIGNGU[code_5])

        # Default mapping using migrated sido + same signgu code
        tour_regn = SIDO_AIHUB_TO_TOUR.get(c1, c1)
        return (tour_regn, c2)

    def is_compatible(self, aihub_sgg_cd: str, tourapi_regn: str, tourapi_signgu: str) -> bool:
        """Check if AI Hub SGG code is compatible with TourAPI regn & signgu codes."""
        cd_clean = aihub_sgg_cd.strip()
        if not cd_clean:
            return False

        regn_clean = tourapi_regn.strip()
        signgu_clean = tourapi_signgu.strip()

        # Handle 5-digit AI Hub SGG code
        if len(cd_clean) >= 5:
            cd_5 = cd_clean[:5]
            c1 = cd_5[:2]
            c2 = cd_5[2:]

            # Sejong special case
            if cd_5 == "36110" or c1 == "36":
                # TourAPI regn and signgu for Sejong can be "36110" or "36"
                if regn_clean in ("36110", "36"):
                    return signgu_clean in ("36110", "110", "")
                return False

            # Gwangju special case (AI Hub 29xxx)
            if cd_5 in GWANGJU_AIHUB_TO_TOUR_SIGNGU:
                expected_signgu = GWANGJU_AIHUB_TO_TOUR_SIGNGU[cd_5]
                # Must be in regn 12 and signgu must match the reallocated Gwangju district code
                return regn_clean == "12" and signgu_clean == expected_signgu

            # Jeonnam special case (AI Hub 46xxx)
            if cd_5 in JEONNAM_AIHUB_TO_TOUR_SIGNGU:
                expected_signgu = JEONNAM_AIHUB_TO_TOUR_SIGNGU[cd_5]
                # Must be in regn 12 and signgu must match the Jeonnam city/county code
                return regn_clean == "12" and signgu_clean == expected_signgu

            # Check lookup table populated from CSV
            if cd_5 in self.aihub_to_tour:
                expected_pair = self.aihub_to_tour[cd_5]
                if (regn_clean, signgu_clean) == expected_pair:
                    return True

            # General SIDO migration check
            expected_tour_regn = SIDO_AIHUB_TO_TOUR.get(c1, c1)
            if expected_tour_regn == regn_clean:
                if c2 == signgu_clean:
                    return True
                # General district city compatibility (일반구 설치 시: c2가 0으로 끝나는 대표코드 vs 1~9로 끝나는 하위구)
                if len(c2) == 3 and len(signgu_clean) == 3 and c2[:2] == signgu_clean[:2]:
                    prefix_4 = c1 + c2[:2]
                    tour_prefix_4 = regn_clean + signgu_clean[:2]
                    if prefix_4 in GENERAL_DISTRICT_CITY_PREFIXES or tour_prefix_4 in GENERAL_DISTRICT_CITY_PREFIXES:
                        if (c2.endswith("0") and signgu_clean[-1] in "123456789") or (signgu_clean.endswith("0") and c2[-1] in "123456789"):
                            return True

            return False

        # Handle 2-digit AI Hub SIDO code
        if len(cd_clean) == 2:
            c1 = cd_clean
            if c1 == "36":
                return regn_clean in ("36110", "36")
            if c1 in ("29", "46"):
                # If only sido is known, regn must be 12, and signgu_clean MUST be non-empty to distinguish Gwangju vs Jeonnam
                if regn_clean != "12" or not signgu_clean:
                    return False
                if c1 == "29":
                    return signgu_clean in GWANGJU_AIHUB_TO_TOUR_SIGNGU.values()
                else:
                    return signgu_clean in JEONNAM_AIHUB_TO_TOUR_SIGNGU.values()

            expected_tour_regn = SIDO_AIHUB_TO_TOUR.get(c1, c1)
            return expected_tour_regn == regn_clean

        return False
