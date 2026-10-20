"""Crosswalk mapping between AI Hub TC_SGG and TourAPI legal dong codes."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Mapping


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


class SggCrosswalk:
    def __init__(self, sgg_csv_path: str | Path | None = None) -> None:
        self.aihub_to_names: dict[str, tuple[str, str]] = {}
        self.names_to_aihub: dict[tuple[str, str], str] = {}
        self.aihub_to_tour: dict[str, tuple[str, str]] = {}
        self.tour_to_aihub: dict[tuple[str, str], set[str]] = {}
        if sgg_csv_path is not None:
            self.load_from_csv(sgg_csv_path)

    def load_from_csv(self, path: str | Path) -> None:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError("TC_SGG file not found")

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

                # Default mapping using migrated sido + same signgu code
                tour_regn = SIDO_AIHUB_TO_TOUR.get(c1, c1)
                tour_pair = (tour_regn, c2)
                self.aihub_to_tour[code_5] = tour_pair
                self.tour_to_aihub.setdefault(tour_pair, set()).add(code_5)

    def is_compatible(self, aihub_sgg_cd: str, tourapi_regn: str, tourapi_signgu: str) -> bool:
        """Check if AI Hub SGG code (5-digit or 10-digit) is compatible with TourAPI pair."""
        cd_clean = aihub_sgg_cd.strip()
        if not cd_clean:
            return False
        cd_5 = cd_clean[:5]
        regn_clean = tourapi_regn.strip()
        signgu_clean = tourapi_signgu.strip()

        # Direct 5-digit code match
        if (regn_clean, signgu_clean) in self.tour_to_aihub:
            if cd_5 in self.tour_to_aihub[(regn_clean, signgu_clean)]:
                return True

        # Check sido level compatibility
        c1 = cd_5[:2]
        expected_tour_regn = SIDO_AIHUB_TO_TOUR.get(c1, c1)
        if expected_tour_regn == regn_clean:
            # If signgu code matches directly
            if cd_5[2:] == signgu_clean:
                return True

        return False
