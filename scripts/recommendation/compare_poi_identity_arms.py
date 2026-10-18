"""Compare visit-row vs TN_POI_MASTER metadata and regional vs global identity scope.

All raw identifiers and source fields remain in memory. Only aggregate JSON is written.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evaluate_popularity as shared
from analyze_poi_catalog_candidate_coverage import (
    REGIONS, ROLES, ROLE_ENV, _read_catalog, _source_rows, _verify_snapshot,
)
from poi_catalog_candidate_contract import (
    CatalogPoi, MatchResult, SourcePoi, eligibility_reason, match_source_item, normalize_text,
)
from poi_catalog_policy import load_poi_catalog_policy
from tourapi_snapshot_adapter import TourApiFieldMap, read_tourapi_snapshot_csv

FIELDS = ("POI_NM", "SGG_CD", "LOTNO_ADDR", "ROAD_NM_ADDR")
ARM_META = {"A": "visit", "B": "master", "C": "visit", "D": "master"}
ARM_SCOPE = {"A": "source_region", "B": "source_region", "C": "global", "D": "global"}
CANONICAL_IDENTITY_ARM = "D"


def _master_rows(root: Path) -> dict[str, set[tuple[str, str, str, str]]]:
    files = [p for p in shared.csv_files(root) if "POI_MASTER" in p.name.upper()]
    if len(files) != 1:
        raise ValueError("each region must contain exactly one TN_POI_MASTER CSV")
    grouped: dict[str, set[tuple[str, str, str, str]]] = defaultdict(set)
    for row in shared._rows(files, set(FIELDS) | {"POI_ID"}, set(FIELDS) | {"POI_ID"}):
        poi_id = (row.get("poi_id") or "").strip()
        if poi_id:
            grouped[poi_id].add(tuple(row.get(field.lower()) or "" for field in FIELDS))
    return dict(grouped)


def _catalog_index(catalog: list[CatalogPoi], policy):
    all_codes = frozenset(code for codes in policy.product_region_to_ldong_regn_cd.values()
                          for code in codes)
    regional: dict[tuple[str, str], list[CatalogPoi]] = defaultdict(list)
    global_index: dict[str, list[CatalogPoi]] = defaultdict(list)
    admin = {k: frozenset(v) for k, v in policy.product_region_to_ldong_regn_cd.items()}
    for item in catalog:
        if item.title:
            global_index[normalize_text(item.title)].append(item)
            for region, codes in admin.items():
                if codes.intersection(item.region_codes):
                    regional[(region, normalize_text(item.title))].append(item)
    return regional, global_index, all_codes


def _resolve_one(poi_id: str, signals: set[tuple[str, str, str, str]], region: str,
                 candidate_items: list[CatalogPoi], admin_codes, global_scope=False) -> MatchResult:
    if len(signals) != 1:
        return MatchResult(poi_id, "AMBIGUOUS", None, "source_signal_conflict", len(signals))
    name, _sgg, lot, road = next(iter(signals))
    # SGG_CD remains diagnostic-only because its crosswalk is not verified.
    addresses = list(dict.fromkeys(value for value in (lot, road) if value)) or [""]
    matches = [match_source_item(
        SourcePoi(poi_id, region, name=name, address=address), candidate_items,
        source_region_to_admin_codes=admin_codes,
        global_identity_scope=global_scope,
    ) for address in addresses]
    exact = [result for result in matches if result.status == "MATCHED"]
    ambiguous = [result for result in matches if result.status == "AMBIGUOUS"]
    ids = {result.canonical_item_id for result in exact}
    if any(result.method in {"conflicting_exact_signals", "name_address"} for result in ambiguous) or len(ids) > 1:
        return MatchResult(poi_id, "AMBIGUOUS", None, "conflicting_source_address_signals", max(2, len(ids)))
    if exact:
        methods = {result.method for result in exact}
        return MatchResult(poi_id, "MATCHED", next(iter(ids)),
                           next(iter(methods)) if len(methods) == 1 else "name_address", 1)
    return matches[0]


def _master_visit_diagnostics(visits, masters):
    counts = Counter()
    ids = set(visits) | set(masters)
    for poi_id in ids:
        visit_rows = visits.get(poi_id, set())
        master_rows = masters.get(poi_id, set())
        counts["visit_poi_ids"] += bool(visit_rows)
        counts["master_missing"] += bool(visit_rows and not master_rows)
        counts["master_exists_stable"] += bool(master_rows and len(master_rows) == 1)
        counts["visit_internally_inconsistent"] += bool(len(visit_rows) > 1)
        if not visit_rows or not master_rows:
            continue
        # Aggregate any visit/master signal disagreements by field; no values escape.
        for index, label in enumerate(("name_differs", "sgg_differs", "lot_address_differs", "road_address_differs")):
            if any(v[index] != m[index] for v in visit_rows for m in master_rows):
                counts[label] += 1
        if len(visit_rows) > 1 and len(master_rows) == 1:
            counts["visit_conflict_stabilized_by_master"] += 1
    output = dict(counts)
    denominator = output.get("visit_poi_ids", 0)
    output["rates_per_visit_poi_id"] = {
        key: _rate(value, denominator) for key, value in sorted(output.items())
        if key != "visit_poi_ids"
    }
    stable_denominator = output.get("master_exists_stable", 0)
    field_keys = ("name_differs", "sgg_differs", "lot_address_differs", "road_address_differs")
    output["field_mismatch_rates_per_master_stable_poi"] = {
        key: _rate(output.get(key, 0), stable_denominator) for key in field_keys
    }
    conflict_denominator = output.get("visit_internally_inconsistent", 0)
    output["conflict_stabilization_rate"] = _rate(
        output.get("visit_conflict_stabilized_by_master", 0), conflict_denominator
    )
    return output


def _cross_region_master_diagnostic(source_poi_ids, positives, region, masters_by_region):
    """Classify same-region Master misses using other regional Masters, without resolving identity."""
    local = masters_by_region[region]
    def classify(poi_id):
        if poi_id in local:
            return None
        other = [(other_region, masters_by_region[other_region][poi_id])
                 for other_region in REGIONS if other_region != region
                 and poi_id in masters_by_region[other_region]]
        if not other:
            return "absent_from_all_masters"
        if len(other) == 1:
            return "found_in_one_other_master"
        metadata = {signal for _, signals in other for signal in signals}
        return ("found_in_multiple_masters_same_metadata" if len(metadata) == 1
                else "found_in_multiple_masters_conflicting_metadata")

    categories = ("absent_from_all_masters", "found_in_one_other_master",
                  "found_in_multiple_masters_same_metadata",
                  "found_in_multiple_masters_conflicting_metadata")
    source_missing = {poi_id for poi_id in source_poi_ids if poi_id not in local}
    positive_missing = [poi_id for _, poi_id in positives if poi_id not in local]
    source_counts = Counter(classify(poi_id) for poi_id in source_missing)
    positive_counts = Counter(classify(poi_id) for poi_id in positive_missing)
    return {
        "same_region_master_present_source_poi_count": len(set(source_poi_ids) - source_missing),
        "source_poi": {"missing_in_same_region_master": len(source_missing),
                       "categories": {key: source_counts[key] for key in categories},
                       "category_rates": _rate_map({key: source_counts[key] for key in categories}, len(source_missing))},
        "observed_positive": {"missing_in_same_region_master": len(positive_missing),
                              "categories": {key: positive_counts[key] for key in categories},
                              "category_rates": _rate_map({key: positive_counts[key] for key in categories}, len(positive_missing))},
    }


def _arm_counts(region, role, sources, positives, catalog, regional_index, global_index,
                all_codes, policy, arm):
    scope, metadata = ARM_SCOPE[arm], ARM_META[arm]
    admin = {k: frozenset(v) for k, v in policy.product_region_to_ldong_regn_cd.items()}
    supported = frozenset(policy.supported_content_type_ids)
    matches = {}
    title_buckets = Counter()
    title_diag = Counter()
    for poi_id, signals in sources.items():
        if metadata == "master" and not signals:
            matches[poi_id] = MatchResult(poi_id, "UNMATCHED", None, "master_missing", 0)
            continue
        names = sorted({normalize_text(signal[0]) for signal in signals if normalize_text(signal[0])})
        global_by_id = {item.content_id: item for name in names for item in global_index.get(name, [])}
        regional_by_id = {item.content_id: item for name in names
                          for item in regional_index.get((region, name), [])}
        global_candidates = list(global_by_id.values())
        regional_candidates = list(regional_by_id.values())
        lookup = global_candidates if scope == "global" else regional_candidates
        bucket = "0" if len(lookup) == 0 else "1" if len(lookup) == 1 else "2+"
        title_buckets[bucket] += 1
        if not regional_candidates:
            title_diag[{0: "global_exact_title_absent", 1: "exact_title_exists_outside_source_region_single"}.get(
                len(global_candidates), "exact_title_exists_outside_source_region_multiple")] += 1
        if metadata == "master" and not signals:
            continue
        matches[poi_id] = _resolve_one(poi_id, signals, region, lookup, admin,
                                       global_scope=scope == "global")
    catalog_by_id = {item.content_id: item for item in catalog}
    eligible_ids = {item.content_id for item in catalog
                    if eligibility_reason(item, request_region=region,
                                          region_admin_codes=admin,
                                          supported_content_types=supported) == "eligible"
                    and item.content_id and item.title.strip()}
    positive_status = Counter()
    methods = Counter()
    contained = 0
    ineligible = Counter()
    positive_title_buckets = Counter()
    positive_global_diagnostic = Counter()
    identity_source_available = 0
    identity_source_missing = 0
    title_diagnostic_positive_denominator = 0
    for _trip, poi_id in positives:
        source_available = metadata != "master" or bool(sources.get(poi_id))
        if source_available:
            identity_source_available += 1
            title_diagnostic_positive_denominator += 1
        else:
            identity_source_missing += 1
        result = matches.get(poi_id, MatchResult(poi_id, "UNMATCHED", None, "master_missing", 0))
        signals = sources.get(poi_id, set())
        if not source_available:
            continue
        names = sorted({normalize_text(signal[0]) for signal in signals if normalize_text(signal[0])})
        global_count = len({item.content_id for name in names for item in global_index.get(name, [])})
        regional_count = len({item.content_id for name in names
                              for item in regional_index.get((region, name), [])})
        selected_count = global_count if scope == "global" else regional_count
        positive_title_buckets["0" if selected_count == 0 else "1" if selected_count == 1 else "2+"] += 1
        if regional_count == 0:
            positive_global_diagnostic["global_exact_title_absent" if global_count == 0 else
                                       "exact_title_exists_outside_source_region_single" if global_count == 1 else
                                       "exact_title_exists_outside_source_region_multiple"] += 1
        positive_status[result.status] += 1
        methods[result.method or "no_exact_signal"] += 1
        if result.status == "MATCHED" and result.canonical_item_id:
            item = catalog_by_id[result.canonical_item_id]
            reason = eligibility_reason(item, request_region=region,
                                       region_admin_codes=admin,
                                       supported_content_types=supported)
            if not item.content_id or not item.title.strip():
                reason = "required_field_invalid"
            ineligible[reason] += 1
            if result.canonical_item_id in eligible_ids:
                contained += 1
    total = len(positives)
    resolved = positive_status["MATCHED"]
    return {
        "arm": arm, "metadata": metadata, "identity_scope": scope,
        "all_positives": total, "MATCHED": positive_status["MATCHED"],
        "AMBIGUOUS": positive_status["AMBIGUOUS"], "UNMATCHED": positive_status["UNMATCHED"],
        "identity_resolution_rate": _rate(resolved, total),
        "identity_source_available": identity_source_available,
        "identity_source_missing": identity_source_missing,
        "identity_resolution_rate_all": _rate(resolved, total),
        "identity_resolution_rate_source_available": _rate(resolved, identity_source_available),
        "candidate_title_count_0_1_2plus_by_source_poi": dict(title_buckets),
        "candidate_title_count_source_poi_denominator": sum(title_buckets.values()),
        "candidate_title_count_0_1_2plus_by_positive": dict(positive_title_buckets),
        "candidate_title_count_positive_denominator": title_diagnostic_positive_denominator,
        "positives_with_identity_source": title_diagnostic_positive_denominator,
        "candidate_title_count_positive_rates": _rate_map(dict(positive_title_buckets), title_diagnostic_positive_denominator),
        "global_exact_title_diagnostic_by_positive": dict(positive_global_diagnostic),
        "global_exact_title_diagnostic_positive_denominator": title_diagnostic_positive_denominator,
        "global_exact_title_diagnostic_positive_rates": _rate_map(
            dict(positive_global_diagnostic), title_diagnostic_positive_denominator),
        "positive_match_methods": dict(methods), "identity_source_missing": identity_source_missing,
        "positive_match_method_rates": _rate_map(
            dict(methods), identity_source_available if metadata == "master" else len(positives)),
        "candidate_contained": contained, "outside_candidate": resolved - contained,
        "end_to_end_coverage": _rate(contained, total),
        "conditional_coverage": _rate(contained, resolved),
        "matched_eligibility_reasons": dict(ineligible),
        "matched_eligibility_reason_rates": _rate_map(dict(ineligible), resolved),
        "global_exact_title_diagnostic_among_same_region_no_hit": dict(title_diag),
    }


def _rate(n, d):
    return {"count": n, "denominator": d, "percent": round(n * 100 / d, 2) if d else None}


def _rate_map(counts: dict[str, int], denominator: int) -> dict[str, dict[str, int | float | None]]:
    return {key: _rate(value, denominator) for key, value in sorted(counts.items())}


def run(specs, masters_by_region, snapshot_path, policy_path, output_path):
    policy = load_poi_catalog_policy(policy_path)
    metadata = json.loads(snapshot_path.with_suffix(snapshot_path.suffix + ".metadata.json").read_text(encoding="utf-8"))
    if metadata.get("provider") != "tourapi-korservice2" or metadata.get("manual_version") != "4.4":
        raise ValueError("fixed snapshot provider contract mismatch")
    expected_codes = set().union(*policy.product_region_to_ldong_regn_cd.values())
    request_config = metadata.get("request_config", {})
    if set(request_config.get("region_codes", [])) != expected_codes:
        raise ValueError("fixed snapshot legal-code universe differs from current policy")
    if set(metadata.get("supported_content_type_ids_v1", [])) != set(policy.supported_content_type_ids):
        raise ValueError("fixed snapshot supported content types differ from current policy")
    catalog = list(read_tourapi_snapshot_csv(
        snapshot_path, snapshot_version=str(metadata.get("snapshot_version", "")),
        fields=TourApiFieldMap(), retrieved_at=str(metadata.get("retrieved_at_utc", "")),
        request_config_hash=str(metadata.get("request_config", {}).get("request_config_hash", "")),
        policy_version=policy.version).records)
    snapshot_fields = ("contentid", "contenttypeid", "title", "addr1", "lDongRegnCd",
                       "lDongSignguCd", "lclsSystm1", "lclsSystm2", "lclsSystm3", "modifiedtime")
    with snapshot_path.open("r", encoding="utf-8-sig", newline="") as stream:
        canonical_rows = [{key: (row.get(key) or "") for key in snapshot_fields}
                          for row in csv.DictReader(stream)]
    canonical_rows.sort(key=lambda row: row["contentid"])
    snapshot_fingerprint = hashlib.sha256(json.dumps(
        canonical_rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()
    if snapshot_fingerprint != metadata.get("snapshot_sha256"):
        raise ValueError("fixed snapshot canonical content fingerprint mismatch")
    regional_index, global_index, all_codes = _catalog_index(catalog, policy)
    out = {"snapshot_item_count": len(catalog), "snapshot_coordinate_fields": [],
           "snapshot_policy_fingerprint_matches_current_config": metadata.get("policy_config_sha256") == policy.policy_sha256,
           "snapshot_policy_sha256": metadata.get("policy_config_sha256"),
           "snapshot_policy_fingerprint_note": "mismatch; current versioned policy applied after verifying canonical snapshot SHA-256, provider, legal-code universe, and supported types",
           "current_policy_sha256": policy.policy_sha256,
           "coordinate_diagnostic": "not_estimable_fixed_snapshot_has_no_mapx_mapy; coordinates_for_identity=false",
           "by_region_split_arm": [], "master_visit_metadata": {},
           "cross_region_master_lookup": [],
           "weighted_TL_VL": {}, "methodology": "controlled_pipeline_comparison_not_causal_effect",
           "canonical_identity_arm": CANONICAL_IDENTITY_ARM,
           "manifest": {"dataset": "AI Hub Domestic Travel Log 2023", "splits": ["TL", "VL"],
                        "provider": metadata.get("provider"), "manual_version": metadata.get("manual_version"),
                        "snapshot_version": metadata.get("snapshot_version"),
                        "snapshot_sha256": metadata.get("snapshot_sha256"),
                        "retrieved_at_utc": metadata.get("retrieved_at_utc"),
                        "request_config_hash": metadata.get("request_config", {}).get("request_config_hash"),
                        "policy_sha256_applied": policy.policy_sha256,
                        "raw_rows_ids_paths_coordinates_emitted": False,
                        "coordinates_for_identity": False}}
    for region in REGIONS:
        visit_all: dict[str, set[tuple[str, str, str, str]]] = defaultdict(set)
        master_all: dict[str, set[tuple[str, str, str, str]]] = defaultdict(set)
        for role in ROLES:
            spec = next(s for s in specs if s.region == region and s.role == role)
            visits, positives, _ = _source_rows(spec)
            master = masters_by_region[region]
            out["cross_region_master_lookup"].append({
                "region": region, "split": role,
                **_cross_region_master_diagnostic(set(visits), positives, region, masters_by_region),
            })
            visit_master = {poi_id: master[poi_id] for poi_id in visits.keys() & master.keys()}
            out["master_visit_metadata"][f"{region}:{role}"] = _master_visit_diagnostics(visits, visit_master)
            for poi_id, signals in visits.items():
                visit_all[poi_id].update(signals)
            for poi_id, signals in visit_master.items():
                master_all[poi_id].update(signals)
            for arm in "ABCD":
                if ARM_META[arm] == "visit":
                    source_map = visits
                else:
                    positive_ids = {poi_id for _, poi_id in positives}
                    source_map = {poi_id: master[poi_id] for poi_id in positive_ids if poi_id in master}
                row = _arm_counts(region, role, source_map, positives, catalog,
                                  regional_index, global_index, all_codes, policy, arm)
                row["region"], row["split"] = region, role
                out["by_region_split_arm"].append(row)
        out["master_visit_metadata"][region + ":unique_poi_id"] = _master_visit_diagnostics(visit_all, master_all)
    for arm in "ABCD":
        totals = Counter()
        for row in out["by_region_split_arm"]:
            if row["arm"] == arm:
                for key in ("all_positives", "MATCHED", "AMBIGUOUS", "UNMATCHED", "candidate_contained", "outside_candidate",
                            "identity_source_available", "identity_source_missing", "positives_with_identity_source"):
                    totals[key] += row[key]
        totals["identity_resolution_rate"] = _rate(totals["MATCHED"], totals["all_positives"])
        totals["identity_resolution_rate_all"] = _rate(totals["MATCHED"], totals["all_positives"])
        totals["identity_resolution_rate_source_available"] = _rate(
            totals["MATCHED"], totals["identity_source_available"] or totals["all_positives"])
        totals["end_to_end_coverage"] = _rate(totals["candidate_contained"], totals["all_positives"])
        totals["conditional_coverage"] = _rate(totals["candidate_contained"], totals["MATCHED"])
        for metric in ("candidate_title_count_0_1_2plus_by_positive", "positive_match_methods",
                       "matched_eligibility_reasons", "global_exact_title_diagnostic_by_positive"):
            aggregate = Counter()
            for row in out["by_region_split_arm"]:
                if row["arm"] == arm:
                    aggregate.update(row.get(metric, {}))
            totals[metric] = dict(aggregate)
            denominator = (totals["positives_with_identity_source"] if metric in {
                "candidate_title_count_0_1_2plus_by_positive", "global_exact_title_diagnostic_by_positive",
            } else totals["identity_source_available"] if metric == "positive_match_methods" and ARM_META[arm] == "master" else
                          totals["all_positives"] if metric == "positive_match_methods" else
                          totals["MATCHED"] if metric == "matched_eligibility_reasons" else sum(aggregate.values()))
            rate_key = {
                "candidate_title_count_0_1_2plus_by_positive": "candidate_title_count_positive_rates",
                "positive_match_methods": "positive_match_method_rates",
                "matched_eligibility_reasons": "matched_eligibility_reason_rates",
                "global_exact_title_diagnostic_by_positive": "global_exact_title_diagnostic_positive_rates",
            }[metric]
            totals[rate_key] = _rate_map(dict(aggregate), denominator)
        totals["global_exact_title_diagnostic_positive_denominator"] = totals["positives_with_identity_source"]
        out["weighted_TL_VL"][arm] = dict(totals)
    cross_weighted = {}
    for unit in ("source_poi", "observed_positive"):
        missing_total = Counter()
        categories_total = Counter()
        for row in out["cross_region_master_lookup"]:
            missing_total[unit] += row[unit]["missing_in_same_region_master"]
            categories_total.update(row[unit]["categories"])
        missing_count = missing_total[unit]
        cross_weighted[unit] = {
            "missing_in_same_region_master": missing_count,
            "categories": dict(categories_total),
            "category_rates": _rate_map(dict(categories_total), missing_count),
        }
    out["cross_region_master_lookup_weighted_TL_VL"] = cross_weighted
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-root", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--policy", type=Path, default=Path(__file__).resolve().parents[2] / "config/recommendation/poi-catalog-policy-v1.json")
    parser.add_argument("--master", action="append", default=[], metavar="REGION=PATH")
    parser.add_argument("--input", action="append", default=[], metavar="REGION:TL|VL=PATH")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    raw_root = args.raw_root.resolve()
    specs = []
    parsed = {}
    for value in args.input:
        label, _, path = value.partition("="); region, _, role = label.partition(":")
        if region not in REGIONS or role not in ROLES or not path:
            raise ValueError("input role invalid")
        parsed[(region, role)] = path
    for region in REGIONS:
        for role in ROLES:
            value = parsed.get((region, role)) or os.environ.get(ROLE_ENV[(region, role)])
            if not value:
                raise ValueError("all eight TL/VL inputs are required")
            root = Path(value).resolve()
            if not shared.within(root, raw_root) or not root.is_dir():
                raise ValueError("TL/VL input failed safe validation")
            specs.append(shared.InputSpec(region, role, root))
    masters = {}
    parsed_masters = dict(value.split("=", 1) for value in args.master)
    for region in REGIONS:
        root = Path(parsed_masters[region]).resolve()
        if not shared.within(root, raw_root) or not root.is_dir():
            raise ValueError("master input failed safe validation")
        masters[region] = _master_rows(root)
    output = args.output
    if not output.is_absolute() or "results" not in output.parts:
        raise ValueError("output must be an absolute path under ignored results/")
    run(specs, masters, args.snapshot.resolve(), args.policy.resolve(), output)


if __name__ == "__main__":
    main()
