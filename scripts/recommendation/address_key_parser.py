"""Deterministic structured address key parser for Korean road and lot-number addresses."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Mapping


SIDO_MAPPING: dict[str, str] = {
    "서울특별시": "서울", "서울시": "서울", "서울": "서울",
    "부산광역시": "부산", "부산시": "부산", "부산": "부산",
    "대구광역시": "대구", "대구시": "대구", "대구": "대구",
    "인천광역시": "인천", "인천시": "인천", "인천": "인천",
    "광주광역시": "광주", "광주시": "광주", "광주": "광주",
    "대전광역시": "대전", "대전시": "대전", "대전": "대전",
    "울산광역시": "울산", "울산시": "울산", "울산": "울산",
    "세종특별자치시": "세종", "세종시": "세종", "세종": "세종",
    "경기도": "경기", "경기": "경기",
    "강원특별자치도": "강원", "강원도": "강원", "강원": "강원",
    "충청북도": "충북", "충북도": "충북", "충북": "충북",
    "충청남도": "충남", "충남도": "충남", "충남": "충남",
    "전북특별자치도": "전북", "전라북도": "전북", "전북": "전북",
    "전라남도": "전남", "전남도": "전남", "전남": "전남",
    "전남광주통합특별시": "전남광주",
    "경상북도": "경북", "경북도": "경북", "경북": "경북",
    "경상남도": "경남", "경남도": "경남", "경남": "경남",
    "제주특별자치도": "제주", "제주도": "제주", "제주": "제주",
}

PARENTHETICAL_RE = re.compile(
    r"\([^()]*\)|\[[^\[\]]*\]|\{[^{}]*\}|【[^【】]*】|〔[^〔〕]*〕|"
    r"〈[^〈〉]*〉|《[^《》]*》|「[^「」]*」|『[^『』]*』"
)
DETAIL_ADDR_RE = re.compile(r"(?:\d+층|\d+호|지하\s*\d+|지상\s*\d+).*$")
ROAD_SUFFIX_RE = re.compile(r"^[가-힣0-9a-zA-Z·]+(?:로|길|거리|고개)$")
LOTNO_SUFFIX_RE = re.compile(r"^[가-힣0-9·]+(?:동|읍|면|리|가)$")
NUMBER_BON_BU_RE = re.compile(r"^(\d+)(?:-(\d+))?$")


def normalize_text_clean(text: str | None) -> str:
    if not text:
        return ""
    return " ".join(unicodedata.normalize("NFKC", text).split())


def normalize_sido(sido_text: str | None) -> str:
    clean = normalize_text_clean(sido_text)
    return SIDO_MAPPING.get(clean, clean)


def normalize_sigungu(sgg_text: str | None) -> str:
    clean = normalize_text_clean(sgg_text)
    # Remove excessive spaces inside sigungu (e.g. "수원시  장안구" -> "수원시 장안구")
    return clean


@dataclass(frozen=True)
class RoadAddressKey:
    sido: str
    sigungu: str
    road_name: str
    main_no: int
    sub_no: int = 0

    @property
    def key_full(self) -> tuple[str, str, str, int, int]:
        return (self.sido, self.sigungu, self.road_name, self.main_no, self.sub_no)

    @property
    def key_main(self) -> tuple[str, str, str, int]:
        return (self.sido, self.sigungu, self.road_name, self.main_no)


@dataclass(frozen=True)
class LotnoAddressKey:
    sido: str
    sigungu: str
    emd_ri: str
    san_flag: bool
    main_no: int
    sub_no: int = 0

    @property
    def key_full(self) -> tuple[str, str, str, bool, int, int]:
        return (self.sido, self.sigungu, self.emd_ri, self.san_flag, self.main_no, self.sub_no)

    @property
    def key_main(self) -> tuple[str, str, str, bool, int]:
        return (self.sido, self.sigungu, self.emd_ri, self.san_flag, self.main_no)


@dataclass(frozen=True)
class ParsedAddress:
    raw: str
    sido: str
    sigungu: str
    road_key: RoadAddressKey | None = None
    lotno_key: LotnoAddressKey | None = None


def parse_address_string(addr: str | None) -> ParsedAddress | None:
    if not addr or not addr.strip():
        return None
    raw = normalize_text_clean(addr)
    stripped = PARENTHETICAL_RE.sub(" ", raw)
    tokens = stripped.split()
    if len(tokens) < 3:
        return None

    sido = normalize_sido(tokens[0])
    idx = 1
    sigungu_parts: list[str] = []

    # Advance until we hit a road name or an emd_ri token
    while idx < len(tokens) and not ROAD_SUFFIX_RE.match(tokens[idx]) and not LOTNO_SUFFIX_RE.match(tokens[idx]):
        sigungu_parts.append(tokens[idx])
        idx += 1

    if idx >= len(tokens):
        return None

    sigungu = normalize_sigungu(" ".join(sigungu_parts))

    road_key: RoadAddressKey | None = None
    lotno_key: LotnoAddressKey | None = None

    # Check road address
    if ROAD_SUFFIX_RE.match(tokens[idx]):
        road_name = tokens[idx]
        num_idx = idx + 1
        if num_idx < len(tokens):
            num_clean = tokens[num_idx].rstrip(",")
            m = NUMBER_BON_BU_RE.match(num_clean)
            if m:
                main_no = int(m.group(1))
                sub_no = int(m.group(2)) if m.group(2) else 0
                road_key = RoadAddressKey(sido, sigungu, road_name, main_no, sub_no)

    # Check lotno address (or combined)
    if LOTNO_SUFFIX_RE.match(tokens[idx]):
        emd_parts = [tokens[idx]]
        curr = idx + 1
        while curr < len(tokens) and LOTNO_SUFFIX_RE.match(tokens[curr]):
            emd_parts.append(tokens[curr])
            curr += 1
        emd_ri = " ".join(emd_parts)
        san_flag = False
        if curr < len(tokens) and tokens[curr] == "산":
            san_flag = True
            curr += 1
        if curr < len(tokens):
            num_clean = tokens[curr].rstrip(",")
            m = NUMBER_BON_BU_RE.match(num_clean)
            if m:
                main_no = int(m.group(1))
                sub_no = int(m.group(2)) if m.group(2) else 0
                lotno_key = LotnoAddressKey(sido, sigungu, emd_ri, san_flag, main_no, sub_no)

    if road_key is None and lotno_key is None:
        return None

    return ParsedAddress(
        raw=raw,
        sido=sido,
        sigungu=sigungu,
        road_key=road_key,
        lotno_key=lotno_key,
    )


def match_parsed_addresses(
    addr_a: ParsedAddress | None,
    addr_b: ParsedAddress | None,
) -> str | None:
    """Compare two parsed addresses and return match quality tag if matched."""
    if addr_a is None or addr_b is None:
        return None

    # Sido must agree (or one of them is empty/unspecified)
    if addr_a.sido and addr_b.sido:
        # Check compatibility (e.g. 전남광주 includes 광주 and 전남)
        if addr_a.sido != addr_b.sido:
            if not ({addr_a.sido, addr_b.sido} <= {"광주", "전남", "전남광주"}):
                return None

    # Road key match
    if addr_a.road_key is not None and addr_b.road_key is not None:
        if addr_a.road_key.road_name == addr_b.road_key.road_name:
            if addr_a.road_key.key_full == addr_b.road_key.key_full:
                return "road_exact_full"
            if addr_a.road_key.key_main == addr_b.road_key.key_main:
                # If both have explicit differing sub-numbers (e.g. 10-1 vs 10-2), conflict
                if not (addr_a.road_key.sub_no > 0 and addr_b.road_key.sub_no > 0 and addr_a.road_key.sub_no != addr_b.road_key.sub_no):
                    return "road_exact_main"

    # Lotno key match
    if addr_a.lotno_key is not None and addr_b.lotno_key is not None:
        if addr_a.lotno_key.emd_ri == addr_b.lotno_key.emd_ri:
            if addr_a.lotno_key.key_full == addr_b.lotno_key.key_full:
                return "lotno_exact_full"
            if addr_a.lotno_key.key_main == addr_b.lotno_key.key_main:
                # If both have explicit differing sub-numbers (e.g. 10-1 vs 10-2), conflict
                if not (addr_a.lotno_key.sub_no > 0 and addr_b.lotno_key.sub_no > 0 and addr_a.lotno_key.sub_no != addr_b.lotno_key.sub_no):
                    return "lotno_exact_main"

    return None
