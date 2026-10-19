"""Load and validate the versioned POI catalog serving policy."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_POLICY_PATH = REPO_ROOT / "config" / "recommendation" / "poi-catalog-policy-v1.json"
EXPECTED_REGION_CODES = frozenset({
    "11", "12", "26", "27", "28", "30", "31", "36110", "41", "43",
    "44", "47", "48", "50", "51", "52",
})


@dataclass(frozen=True)
class PoiCatalogPolicy:
    version: str
    provider: str
    manual_version: str
    supported_content_type_ids: frozenset[str]
    excluded_content_type_ids: frozenset[str]
    product_region_to_ldong_regn_cd: dict[str, frozenset[str]]
    policy_sha256: str


def validate_live_region_codes(live_codes: set[str] | tuple[str, ...], policy: PoiCatalogPolicy) -> None:
    """Stop snapshot collection when the provider's current code set drifts."""
    expected = frozenset(
        code for codes in policy.product_region_to_ldong_regn_cd.values() for code in codes
    )
    if frozenset(str(code) for code in live_codes) != expected:
        raise ValueError(
            "current TourAPI legal-region codes differ from the versioned policy; refresh the official crosswalk before collecting"
        )


def load_poi_catalog_policy(path: str | Path = DEFAULT_POLICY_PATH) -> PoiCatalogPolicy:
    """Read a policy file and fail closed if its regional partition is incomplete."""
    try:
        raw = Path(path).read_bytes()
        data = json.loads(raw)
        region_map = {
            str(region): frozenset(str(code) for code in codes)
            for region, codes in data["product_region_to_ldong_regn_cd"].items()
        }
        macro_map = {
            str(region): frozenset(str(code) for code in codes)
            for region, codes in data["official_macro_regions"].items()
        }
        supported = frozenset(str(value) for value in data["supported_content_type_ids"])
        excluded = frozenset(str(value) for value in data["excluded_content_type_ids"])
        version = str(data["policy_version"])
        provider = str(data["provider"])
        manual_version = str(data["manual_version"])
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, AttributeError) as error:
        raise ValueError("versioned POI catalog policy is unavailable or malformed") from error
    flattened = [code for codes in region_map.values() for code in codes]
    macro_flattened = [code for codes in macro_map.values() for code in codes]
    if not version or not provider or not manual_version or not region_map:
        raise ValueError("versioned POI catalog policy is missing required metadata")
    if len(flattened) != len(set(flattened)) or set(flattened) != EXPECTED_REGION_CODES:
        raise ValueError("versioned POI catalog policy is not a full disjoint region partition")
    if len(macro_flattened) != len(set(macro_flattened)) or set(macro_flattened) != EXPECTED_REGION_CODES:
        raise ValueError("versioned official macro-region crosswalk is not a full disjoint partition")
    if not supported or supported & excluded or any(not value.isdigit() for value in supported | excluded):
        raise ValueError("versioned POI catalog policy content types are invalid")
    if provider != "tourapi-korservice2" or manual_version != "TourAPI-KorService2-v4.4":
        raise ValueError("versioned POI catalog policy provider contract is unsupported")
    return PoiCatalogPolicy(
        version=version,
        provider=provider,
        manual_version=manual_version,
        supported_content_type_ids=supported,
        excluded_content_type_ids=excluded,
        product_region_to_ldong_regn_cd=region_map,
        policy_sha256=hashlib.sha256(raw).hexdigest(),
    )
