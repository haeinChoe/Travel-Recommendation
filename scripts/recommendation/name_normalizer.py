"""Location-gated name normalization utilities for POI identity matching."""

from __future__ import annotations

import re
import unicodedata

PARENTHETICAL_RE = re.compile(
    r"\([^()]*\)|\[[^\[\]]*\]|\{[^{}]*\}|【[^【】]*】|〔[^〔〕]*〕|"
    r"〈[^〈〉]*〉|《[^《》]*》|「[^「」]*」|『[^『』]*』"
)

# Common facility suffixes representing sub-points of a primary POI
FACILITY_SUFFIXES: tuple[str, ...] = (
    "공영주차장",
    "제1주차장",
    "제2주차장",
    "제3주차장",
    "제4주차장",
    "제5주차장",
    "임시주차장",
    "하부주차장",
    "상부주차장",
    "주차장",
    "탐방지원센터",
    "방문자센터",
    "종합안내소",
    "관광안내소",
    "안내소",
    "매표소",
    "관리사무소",
    "관리소",
    "출렁다리",
    "케이블카",
    "전망대",
    "선착장",
    "야영장",
    "캠핑장",
    "광장",
    "입구",
    "본점",
)

BRANCH_RE = re.compile(r"(?:[가-힣0-9a-zA-Z]+점|DT점|본점)$")

# Broad geographical / generic common nouns that should never match alone
GENERIC_STOPWORDS: frozenset[str] = frozenset({
    "서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종", "경기", "강원",
    "충북", "충남", "전북", "전남", "경북", "경남", "제주",
    "대한민국", "한국", "공원", "해수욕장", "시장", "산", "강", "바다", "호수",
    "박물관", "미술관", "사찰", "절", "카페", "식당", "호텔", "모텔", "펜션",
    "리조트", "캠핑장", "야영장", "주차장", "전망대", "입구", "안내소",
})


def normalize_punctuation_n1(text: str | None) -> str:
    """N1: Strip punctuation and normalize whitespace, case-folded."""
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKC", text).casefold()
    cleaned = "".join(" " if unicodedata.category(c).startswith("P") else c for c in normalized)
    return " ".join(cleaned.split())


def split_parenthetical_variants_n2(text: str | None) -> set[str]:
    """N2: Extract outer name and inner parenthetical alias variants."""
    if not text:
        return set()
    raw = unicodedata.normalize("NFKC", text).casefold()
    variants: set[str] = set()

    # Outer stripped name
    stripped = PARENTHETICAL_RE.sub(" ", raw)
    outer = normalize_punctuation_n1(stripped)
    if outer and outer not in GENERIC_STOPWORDS and len(outer) >= 2:
        variants.add(outer)

    # Inner parenthetical tokens
    for match in PARENTHETICAL_RE.finditer(raw):
        inner = match.group(0)[1:-1].strip()
        inner_clean = normalize_punctuation_n1(inner)
        if inner_clean and inner_clean not in GENERIC_STOPWORDS and len(inner_clean) >= 2:
            variants.add(inner_clean)

    full = normalize_punctuation_n1(raw)
    if full and full not in GENERIC_STOPWORDS and len(full) >= 2:
        variants.add(full)

    return variants


def strip_region_prefix(name: str, region_tokens: tuple[str, ...]) -> str:
    """Strip leading administrative region prefix (e.g. '서울 남산타워' -> '남산타워')."""
    clean = normalize_punctuation_n1(name)
    tokens = clean.split()
    if len(tokens) >= 2 and tokens[0] in region_tokens:
        remainder = " ".join(tokens[1:])
        if remainder and remainder not in GENERIC_STOPWORDS and len(remainder) >= 2:
            return remainder
    return clean


def strip_facility_suffix(name: str) -> str:
    """Strip facility or sub-poi suffix (e.g. '설악산국립공원 주차장' -> '설악산국립공원')."""
    clean = normalize_punctuation_n1(name)
    # Check fixed suffixes
    for suffix in FACILITY_SUFFIXES:
        clean_suffix = normalize_punctuation_n1(suffix)
        if clean.endswith(" " + clean_suffix):
            remainder = clean[:-len(" " + clean_suffix)].strip()
            if remainder and remainder not in GENERIC_STOPWORDS and len(remainder) >= 2:
                return remainder
        elif clean.endswith(clean_suffix) and len(clean) > len(clean_suffix) + 2:
            remainder = clean[:-len(clean_suffix)].strip()
            if remainder and remainder not in GENERIC_STOPWORDS and len(remainder) >= 2:
                return remainder

    # Check branch suffix (e.g. '스타벅스 강남점' -> '스타벅스')
    tokens = clean.split()
    if len(tokens) >= 2 and BRANCH_RE.match(tokens[-1]):
        remainder = " ".join(tokens[:-1])
        if remainder and remainder not in GENERIC_STOPWORDS and len(remainder) >= 2:
            return remainder

    return clean


def generate_location_gated_name_variants(
    name: str,
    sido_tokens: tuple[str, ...] = (),
    sigungu_tokens: tuple[str, ...] = (),
) -> set[str]:
    """Generate candidate name keys for matching once location evidence is satisfied."""
    variants = split_parenthetical_variants_n2(name)
    extended: set[str] = set(variants)

    region_tokens = sido_tokens + sigungu_tokens
    for v in variants:
        # Strip region prefix
        no_prefix = strip_region_prefix(v, region_tokens)
        if no_prefix:
            extended.add(no_prefix)

        # Strip facility suffix
        no_suffix = strip_facility_suffix(v)
        if no_suffix:
            extended.add(no_suffix)

        # Both prefix and suffix stripped
        both = strip_facility_suffix(no_prefix)
        if both:
            extended.add(both)

    # Discard single char or stopwords
    return {v for v in extended if v and len(v) >= 2 and v not in GENERIC_STOPWORDS}
