"""Reconcile static administrative-location evidence for AI Hub POIs.

The model-facing value is deliberately derived from static catalogue evidence.
Visit-row evidence is accepted only as a diagnostic corroboration signal so a
held-out positive cannot create or change its own item feature.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from scripts.recommendation.address_key_parser import normalize_sido, normalize_text_clean


@dataclass(frozen=True)
class AdminArea:
    code: str
    sido_code: str
    sgg_code: str
    sido_name: str
    sgg_name: str


@dataclass(frozen=True)
class CanonicalAdminLocation:
    status: str
    sido_code: str | None
    sgg_code: str | None
    sido_name: str | None
    sgg_name: str | None
    provenance: tuple[str, ...]
    conflict_sources: tuple[str, ...]
    coordinate_status: str = "subset_validation_only_not_used"


def _clean_code(value: object) -> str:
    return "" if value is None else str(value).strip()


def _normalize_name(value: str) -> str:
    return "".join(unicodedata.normalize("NFKC", value).split()).casefold()


def build_admin_lookup(rows: Sequence[Mapping[str, str]]) -> dict[str, AdminArea]:
    """Build a strict 5-digit AI Hub TC_SGG lookup from codebook rows."""
    lookup: dict[str, AdminArea] = {}
    for row in rows:
        code = _clean_code(row.get("SGG_CD"))
        sido_code = _clean_code(row.get("SGG_CD1"))
        sgg_part = _clean_code(row.get("SGG_CD2"))
        sido_name = normalize_text_clean(row.get("SIDO_NM"))
        sgg_name = normalize_text_clean(row.get("SGG_NM"))
        if not (len(code) == 5 and len(sido_code) == 2 and len(sgg_part) == 3
                and code == sido_code + sgg_part and sido_name and sgg_name):
            continue
        area = AdminArea(code, sido_code, code, sido_name, sgg_name)
        previous = lookup.get(code)
        if previous is not None and previous != area:
            raise ValueError("TC_SGG contains conflicting administrative names")
        lookup[code] = area
    return lookup


def normalize_aihub_sgg_code(value: object, lookup: Mapping[str, AdminArea]) -> str | None:
    """Normalize a full/5-digit SGG only when its 5-digit code is in TC_SGG."""
    code = _clean_code(value)
    if len(code) in {5, 10} and code[:5] in lookup and (len(code) == 5 or code[5:] == "00000"):
        return code[:5]
    return None


def address_admin_codes(address: str | None, lookup: Mapping[str, AdminArea]) -> tuple[str, ...]:
    """Map an explicit SIDO + SGG address prefix to a unique TC_SGG code.

    Road/lot details are not required. The function accepts only exact normalized
    codebook names and returns no code for partial or ambiguous addresses.
    """
    if not address:
        return ()
    tokens = normalize_text_clean(address).split()
    if len(tokens) < 2:
        return ()
    sido = _normalize_name(normalize_sido(tokens[0]))
    if not sido:
        return ()
    found: set[str] = set()
    for area in lookup.values():
        if _normalize_name(normalize_sido(area.sido_name)) != sido:
            continue
        name = _normalize_name(area.sgg_name)
        for width in range(1, min(3, len(tokens) - 1) + 1):
            if _normalize_name(" ".join(tokens[1:1 + width])) == name:
                found.add(area.code)
    return tuple(sorted(found))


def build_admin_address_lookup(lookup: Mapping[str, AdminArea]) -> dict[tuple[str, str], tuple[str, ...]]:
    """Index exact normalized SIDO/SGG names used by address prefix matching."""
    found: dict[tuple[str, str], set[str]] = {}
    for area in lookup.values():
        sido = _normalize_name(normalize_sido(area.sido_name))
        name = _normalize_name(area.sgg_name)
        if sido and name:
            found.setdefault((sido, name), set()).add(area.code)
    return {key: tuple(sorted(codes)) for key, codes in found.items()}


def _indexed_address_admin_codes(
    address: str | None,
    lookup: Mapping[str, AdminArea],
    address_lookup: Mapping[tuple[str, str], Sequence[str]],
) -> tuple[str, ...]:
    """Semantics-equivalent address matcher using the prebuilt name index."""
    if not address:
        return ()
    tokens = normalize_text_clean(address).split()
    if len(tokens) < 2:
        return ()
    sido = _normalize_name(normalize_sido(tokens[0]))
    if not sido:
        return ()
    found: set[str] = set()
    for width in range(1, min(3, len(tokens) - 1) + 1):
        name = _normalize_name(" ".join(tokens[1:1 + width]))
        found.update(address_lookup.get((sido, name), ()))
    # Keep the same validity guard as normalize_aihub_sgg_code and the source scan.
    return tuple(sorted(code for code in found if code in lookup))


def _evidence_codes(
    source: str,
    code_values: Sequence[object],
    addresses: Sequence[str | None],
    lookup: Mapping[str, AdminArea],
    address_lookup: Mapping[tuple[str, str], Sequence[str]] | None = None,
    address_result_cache: dict[str, tuple[str, ...]] | None = None,
) -> tuple[set[str], list[str], bool]:
    codes: set[str] = set()
    provenance: list[str] = []
    ambiguous = False
    for value in code_values:
        code = normalize_aihub_sgg_code(value, lookup)
        if code:
            codes.add(code)
            provenance.append(f"{source}_sgg_code")
    for address in addresses:
        mapped = None if address_result_cache is None or address is None else address_result_cache.get(address)
        if mapped is None:
            mapped = (address_admin_codes(address, lookup) if address_lookup is None
                      else _indexed_address_admin_codes(address, lookup, address_lookup))
            if (address_result_cache is not None and address is not None
                    and address not in address_result_cache and len(address_result_cache) < 65_536):
                address_result_cache[address] = mapped
        if len(mapped) == 1:
            codes.add(mapped[0])
            provenance.append(f"{source}_address")
        elif len(mapped) > 1:
            ambiguous = True
            provenance.append(f"{source}_address_ambiguous")
    return codes, provenance, ambiguous


def resolve_canonical_admin_location(
    *,
    lookup: Mapping[str, AdminArea],
    master_sgg_codes: Sequence[object] = (),
    master_addresses: Sequence[str | None] = (),
    tourapi_admin_codes: Sequence[object] = (),
    tourapi_addresses: Sequence[str | None] = (),
    admin_address_lookup: Mapping[tuple[str, str], Sequence[str]] | None = None,
    admin_address_result_cache: dict[str, tuple[str, ...]] | None = None,
) -> CanonicalAdminLocation:
    """Resolve canonical location from static catalogue evidence only.

    Visit evidence is intentionally absent from this API. Call
    :func:`compare_visit_location` separately for privacy-safe diagnostics so
    interactions cannot change a model-facing item feature.
    """
    master, master_prov, master_ambiguous = _evidence_codes(
        "master", master_sgg_codes, master_addresses, lookup, admin_address_lookup,
        admin_address_result_cache,
    )
    tour, tour_prov, tour_ambiguous = _evidence_codes(
        "tourapi", tourapi_admin_codes, tourapi_addresses, lookup, admin_address_lookup,
        admin_address_result_cache,
    )
    static = master | tour
    provenance = tuple(sorted(set(master_prov + tour_prov)))

    conflict_sources: set[str] = set()
    if len(master) > 1:
        conflict_sources.add("master")
    if len(tour) > 1:
        conflict_sources.add("tourapi")
    if len(static) > 1:
        if master and tour and master.isdisjoint(tour):
            conflict_sources.update(("master", "tourapi"))
        elif master:
            conflict_sources.add("master")
        else:
            conflict_sources.add("tourapi")
    ambiguous = master_ambiguous or tour_ambiguous
    if conflict_sources:
        status = "conflict"
        selected = None
    elif ambiguous:
        status = "ambiguous_address"
        selected = None
    elif len(static) == 1:
        selected = next(iter(static))
        status = "resolved_multi_source" if len(master) and len(tour) else "resolved_single_source"
    else:
        status = "unavailable"
        selected = None

    area = lookup.get(selected) if selected else None
    return CanonicalAdminLocation(
        status=status,
        sido_code=area.sido_code if area else None,
        sgg_code=area.sgg_code if area else None,
        sido_name=area.sido_name if area else None,
        sgg_name=area.sgg_name if area else None,
        provenance=provenance,
        conflict_sources=tuple(sorted(conflict_sources)),
    )


def resolve_master_admin_location_indexed(
    *,
    lookup: Mapping[str, AdminArea],
    address_lookup: Mapping[tuple[str, str], Sequence[str]],
    sgg_code: object,
    addresses: Sequence[str | None],
    address_result_cache: dict[str, tuple[str, ...]] | None = None,
) -> tuple[str, str | None, str | None]:
    """Fast path for the master-only fields needed by the catalog runner.

    It applies the same code normalization, address evidence union, conflict
    precedence, and ambiguity precedence as ``resolve_canonical_admin_location``.
    Provenance fields are omitted because the runner stores only status and codes.
    """
    codes: set[str] = set()
    code = normalize_aihub_sgg_code(sgg_code, lookup)
    if code:
        codes.add(code)
    ambiguous = False
    for address in addresses:
        mapped = None if address_result_cache is None or address is None else address_result_cache.get(address)
        if mapped is None:
            mapped = _indexed_address_admin_codes(address, lookup, address_lookup)
            if (address_result_cache is not None and address is not None
                    and address not in address_result_cache and len(address_result_cache) < 65_536):
                address_result_cache[address] = mapped
        if len(mapped) == 1:
            codes.add(mapped[0])
        elif len(mapped) > 1:
            ambiguous = True
    if len(codes) > 1:
        return "conflict", None, None
    if ambiguous:
        return "ambiguous_address", None, None
    if len(codes) == 1:
        area = lookup[next(iter(codes))]
        return "resolved_single_source", area.sido_code, area.sgg_code
    return "unavailable", None, None


def compare_visit_location(
    *,
    canonical_sgg_code: str | None,
    visit_sgg_codes: Sequence[object],
    visit_addresses: Sequence[str | None],
    lookup: Mapping[str, AdminArea],
) -> str:
    """Return a privacy-safe diagnostic state without changing the feature."""
    visit, _, ambiguous = _evidence_codes("visit", visit_sgg_codes, visit_addresses, lookup)
    if ambiguous:
        return "visit_address_ambiguous"
    if not visit:
        return "no_visit_location_evidence"
    if len(visit) > 1:
        return "visit_internal_conflict"
    if not canonical_sgg_code:
        return "visit_only_unconfirmed"
    return "agrees" if visit == {canonical_sgg_code} else "conflicts_with_static"
