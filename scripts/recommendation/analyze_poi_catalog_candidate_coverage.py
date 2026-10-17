"""Aggregate POI identity and candidate feasibility using approved AI Hub splits.

The four input-role labels are mapped to predeclared virtual product request
contexts. They do not represent actual historical request-time context.
Raw identifiers and source fields stay in memory; artifacts contain aggregates.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
import evaluate_popularity as shared
from analyze_candidate_choice_feasibility import diagnose_region
from poi_catalog_candidate_contract import (
    CandidateRequest,
    CatalogPoi,
    MatchResult,
    SourcePoi,
    eligibility_reason,
    match_source_item,
    normalize_text,
)
from poi_catalog_policy import load_poi_catalog_policy
from tourapi_snapshot_adapter import TourApiFieldMap, read_tourapi_snapshot_csv

REGIONS = ("capital", "west", "east", "jeju-islands")
ROLES = ("TL", "VL")
MIN_CELL = shared.MIN_CELL
SIZE_BUCKETS = ((1, 9, "1-9"), (10, 49, "10-49"), (50, 99, "50-99"),
                (100, 499, "100-499"), (500, None, "500+"))
ROLE_ENV = {
    (region, role): f"{'JEJU' if region == 'jeju-islands' else region.upper()}_{role}"
    for region in REGIONS for role in ROLES
}


def _count(value: int) -> str:
    return shared.count_bucket(value)


def _rate(num: int, den: int) -> str:
    return shared.rate_band(num, den) if den else "not_applicable"


def _size_bucket(n: int) -> str:
    for lo, hi, label in SIZE_BUCKETS:
        if n >= lo and (hi is None or n <= hi):
            return label
    return "0"


def _row(scope: str, metric: str, bucket: str, support: int) -> dict[str, str]:
    return {"scope": scope, "metric": metric, "bucket": bucket,
            "support": _count(support),
            "status": "privacy_limited" if 0 < support < MIN_CELL else "observed"}


def _read_catalog(path: Path, metadata: dict[str, object], policy) -> list[CatalogPoi]:
    snapshot = read_tourapi_snapshot_csv(
        path, snapshot_version=str(metadata.get("snapshot_version", "")),
        fields=TourApiFieldMap(), retrieved_at=str(metadata.get("retrieved_at_utc", "")),
        request_config_hash=str(metadata.get("request_config", {}).get("request_config_hash", "")),
        policy_version=policy.version,
    )
    return list(snapshot.records)


def _verify_snapshot(snapshot: Path, policy_path: Path, policy) -> dict[str, object]:
    metadata_path = snapshot.with_suffix(snapshot.suffix + ".metadata.json")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    expected_codes = set().union(*policy.product_region_to_ldong_regn_cd.values())
    if metadata.get("policy_config_sha256") != policy.policy_sha256:
        raise ValueError("snapshot policy fingerprint mismatch")
    if set(metadata.get("request_config", {}).get("region_codes", [])) != expected_codes:
        raise ValueError("snapshot legal-code set mismatch")
    if set(metadata.get("supported_content_type_ids_v1", [])) != set(policy.supported_content_type_ids):
        raise ValueError("snapshot supported-type set mismatch")
    if metadata.get("manual_version") != "4.4" or metadata.get("provider") != "tourapi-korservice2":
        raise ValueError("snapshot provider contract mismatch")
    return metadata


def _validate(args: argparse.Namespace):
    if not (args.confirm_approved and args.confirm_terms and args.confirm_poi_candidate):
        raise ValueError("required confirmations are missing")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", args.run_id):
        raise ValueError("invalid run id")
    raw_root = Path(os.path.abspath(args.raw_root)).resolve()
    if not raw_root.is_dir() or shared.has_symlink_component(Path(args.raw_root)):
        raise ValueError("raw input root unavailable")
    specs = []
    for region, role in ((r, s) for r in REGIONS for s in ROLES):
        value = args.inputs.get((region, role)) or os.environ.get(ROLE_ENV[(region, role)])
        if not value:
            raise ValueError("a role input is unavailable")
        root = Path(os.path.abspath(value)).resolve()
        if not root.is_dir() or not shared.within(root, raw_root) or shared.has_symlink_component(Path(value)):
            raise ValueError("role input failed safe validation")
        if root.name != f"{role}_csv" and not (
            region == "capital" and re.fullmatch(r"filekey-[A-Za-z0-9._-]+", root.name)
            and ((role == "TL" and root.parent.name == "extracted"
                  and root.parent.parent.name == "2023-travel-log-capital")
                 or (role == "VL" and root.parent.name == "2023-travel-log-capital"))
        ):
            raise ValueError("role folder layout mismatch")
        specs.append(shared.InputSpec(region, role, root))
    snapshot = Path(os.path.abspath(args.snapshot)).resolve()
    if shared.has_symlink_component(Path(args.snapshot)) or not snapshot.is_file():
        raise ValueError("snapshot unavailable")
    if not snapshot.with_suffix(snapshot.suffix + ".metadata.json").is_file():
        raise ValueError("snapshot metadata unavailable")
    policy = load_poi_catalog_policy(args.policy)
    metadata = _verify_snapshot(snapshot, Path(args.policy), policy)
    output = Path(args.output)
    if output.is_absolute() or not output.parts or output.parts[0] != "results":
        raise ValueError("output must be under ignored results/")
    return raw_root, specs, snapshot, policy, metadata, output


def _source_rows(spec: shared.InputSpec):
    files = [p for p in shared.csv_files(spec.root) if shared.table_role(p) == "visits"]
    grouped: dict[str, set[tuple[str, str, str, str]]] = defaultdict(set)
    positives: set[tuple[str, str]] = set()
    positives_missing_trip_id = 0
    if not files:
        return grouped, positives, positives_missing_trip_id
    for row in shared._rows(files, {"TRAVEL_ID"}, {
        "TRAVEL_ID", "POI_ID", "POI_NM", "SGG_CD", "LOTNO_ADDR", "ROAD_NM_ADDR",
    }):
        item_id = (row.get("poi_id") or "").strip()
        if item_id:
            grouped[item_id].add((row.get("poi_nm") or "", row.get("sgg_cd") or "",
                                  row.get("lotno_addr") or "", row.get("road_nm_addr") or ""))
            trip_id = (row.get("travel_id") or "").strip()
            if trip_id:
                positives.add((trip_id, item_id))
            else:
                positives_missing_trip_id += 1
    return grouped, positives, positives_missing_trip_id


def _match_sources(region: str, source_map, catalog_by_region_name, policy):
    admin_codes = {k: frozenset(v) for k, v in policy.product_region_to_ldong_regn_cd.items()}
    results: dict[str, MatchResult] = {}
    methods: Counter[str] = Counter()
    for source_id, signal_sets in source_map.items():
        if len(signal_sets) != 1:
            results[source_id] = MatchResult(source_id, "AMBIGUOUS", None, "source_signal_conflict", len(signal_sets))
            methods["source_signal_conflict"] += 1
            continue
        name, district, lot, road = next(iter(signal_sets))
        candidates = catalog_by_region_name.get((region, normalize_text(name)), []) if name else []
        # AI Hub SGG_CD and TourAPI lDongSignguCd have not been crosswalk-validated.
        # Keep the source value only for conflict detection; never use it as match evidence.
        variants = [SourcePoi(source_id, region, name=name, district_code="", address=address)
                    for address in dict.fromkeys((lot, road)) if address]
        if not variants:
            variants = [SourcePoi(source_id, region, name=name)]
        matches = [match_source_item(s, candidates, source_region_to_admin_codes=admin_codes) for s in variants]
        exact = [m for m in matches if m.status == "MATCHED"]
        ambiguous = [m for m in matches if m.status == "AMBIGUOUS"]
        ids = {m.canonical_item_id for m in exact}
        blocking = [m for m in ambiguous if m.method in {
            "conflicting_exact_signals", "name_address"
        }]
        if blocking or len(ids) > 1:
            result = MatchResult(source_id, "AMBIGUOUS", None, "conflicting_source_address_signals", max(2, len(ids)))
        elif exact:
            methods_found = {m.method for m in exact}
            result = MatchResult(source_id, "MATCHED", next(iter(ids)),
                                 next(iter(methods_found)) if len(methods_found) == 1 else "name_address", 1)
        else:
            result = matches[0]
        results[source_id] = result
        methods[result.method or "no_exact_signal"] += 1
    return results, methods


def analyze(catalog: list[CatalogPoi], split_data, source_maps, positive_maps,
            missing_trip_counts, policy):
    rows: list[dict[str, str]] = []
    admin_codes = {k: frozenset(v) for k, v in policy.product_region_to_ldong_regn_cd.items()}
    supported = frozenset(policy.supported_content_type_ids)
    snapshot_counts = Counter(item.content_type_id for item in catalog)
    rows.append({"scope": "aggregate", "metric": "snapshot_items", "bucket": str(len(catalog)),
                 "support": str(len(catalog)), "status": "observed_public_catalog_count"})
    for type_id, count in sorted(snapshot_counts.items()):
        rows.append({"scope": "aggregate", "metric": "snapshot_content_type_count", "bucket": type_id,
                     "support": str(count), "status": "observed_public_catalog_count"})

    for region in REGIONS:
        eligible: set[str] = set()
        reason_counts: Counter[str] = Counter()
        provider_type_counts: Counter[str] = Counter()
        for item in catalog:
            if admin_codes[region].intersection(item.region_codes):
                provider_type_counts[item.content_type_id] += 1
            reason = eligibility_reason(item, request_region=region, region_admin_codes=admin_codes,
                                        supported_content_types=supported)
            if not item.content_id.strip() or not item.title.strip():
                reason = "required_field_invalid"
            reason_counts[reason] += 1
            if reason == "eligible":
                eligible.add(item.content_id)
        rows.append({"scope": region, "metric": "eligible_candidates", "bucket": str(len(eligible)),
                     "support": str(len(eligible)), "status": "observed_public_catalog_count"})
        for type_id, count in sorted(provider_type_counts.items()):
            rows.append({"scope": region, "metric": "snapshot_region_content_type_count", "bucket": type_id,
                         "support": str(count), "status": "observed_public_catalog_count"})
        for reason, count in sorted(reason_counts.items()):
            rows.append(_row(region, "eligibility_reason", reason, count))
        request_counts: Counter[str] = Counter()
        role_matches = {}
        role_methods = {}
        for role in ROLES:
            split = split_data[(region, role)]
            source_map = source_maps[(region, role)]
            catalog_index: dict[tuple[str, str], list[CatalogPoi]] = defaultdict(list)
            for item in catalog:
                if admin_codes[region].intersection(item.region_codes) and item.title:
                    catalog_index[(region, normalize_text(item.title))].append(item)
            matches, method_counts = _match_sources(region, source_map, catalog_index, policy)
            role_matches[role] = matches
            role_methods[role] = method_counts
            status_counts = Counter(result.status for result in matches.values())
            for status in ("MATCHED", "AMBIGUOUS", "UNMATCHED"):
                rows.append(_row(region, f"{role}_identity_status", status, status_counts[status]))
            for method, count in sorted(method_counts.items()):
                rows.append(_row(region, f"{role}_match_method", method, count))

            # The request universe comes from the role's trip table. Region context
            # is fixed by this experiment configuration, not inferred from visits.
            virtual_requests = [CandidateRequest(request_id=trip_id, region=region)
                                for trip_id in split.travel_ids]
            request_n = len(virtual_requests)
            request_counts[role] = request_n
            nonempty = request_n if eligible else 0
            rows.append(_row(region, f"{role}_virtual_request_nonempty", _rate(nonempty, request_n), nonempty))
            rows.append(_row(region, f"{role}_virtual_candidate_size", _size_bucket(len(eligible)), request_n))

            all_positives = positive_maps[(region, role)]
            request_trip_ids = split.travel_ids
            orphan_positives = {pair for pair in all_positives if pair[0] not in request_trip_ids}
            positives = {pair for pair in all_positives if pair[0] in request_trip_ids}
            event_total = len(positives)
            matched_events = eligible_events = catalog_outside = cold = 0
            eligible_trips: set[str] = set()
            tl_canonical_ids = {
                result.canonical_item_id for result in role_matches.get("TL", {}).values()
                if result.status == "MATCHED" and result.canonical_item_id
            }
            for trip_id, item_id in positives:
                result = matches.get(item_id)
                if result and result.status == "MATCHED" and result.canonical_item_id:
                    matched_events += 1
                    if result.canonical_item_id in eligible:
                        eligible_events += 1
                        eligible_trips.add(trip_id)
                        if result.canonical_item_id not in tl_canonical_ids:
                            cold += 1
                    else:
                        catalog_outside += 1
            unresolved = event_total - matched_events
            rows.append(_row(region, f"{role}_confirmed_positive_candidate_coverage_lower_bound",
                             _rate(eligible_events, event_total), event_total))
            rows.append(_row(region, f"{role}_positive_candidate_coverage_upper_bound",
                             _rate(eligible_events + unresolved, event_total), event_total))
            rows.append(_row(region, f"{role}_confirmed_positive_request_coverage_lower_bound",
                             _rate(len(eligible_trips), request_n), len(eligible_trips)))
            rows.append(_row(region, f"{role}_positive_matched", _rate(matched_events, event_total), matched_events))
            rows.append(_row(region, f"{role}_positive_outside_candidate_share",
                             _rate(catalog_outside, event_total), catalog_outside))
            rows.append(_row(region, f"{role}_positive_unresolved_identity",
                             _rate(unresolved, event_total), unresolved))
            rows.append({"scope": region, "metric": f"{role}_catalog_outside_share",
                         "bucket": "not_estimable_from_identity_unresolved",
                         "support": "not_applicable", "status": "not_estimable"})
            rows.append(_row(region, f"{role}_cold_start_positive_share",
                             _rate(cold, eligible_events), cold))
            rows.append(_row(region, f"{role}_positive_without_request_trip", "unmatched_trip_id",
                             len(orphan_positives)))
            rows.append(_row(region, f"{role}_positive_missing_trip_id", "missing_trip_id",
                             missing_trip_counts[(region, role)]))

            # Existing Issue #60 style: candidate universe consists of TL-observed POI_IDs.
            # These metrics remain explicitly proxy-scoped and are separate from virtual catalog requests.
            if role == "VL":
                rows.extend({**r, "metric": f"proxy_{r['metric']}"}
                            for r in diagnose_region(region, split_data[(region, "TL")], split,
                                                     tuple(shared.DEFAULT_K)))
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-root", type=Path, default=shared.RAW_ROOT)
    parser.add_argument("--input", action="append", default=[], metavar="REGION:TL|VL=PATH")
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--policy", type=Path, default=REPO_ROOT / "config/recommendation/poi-catalog-policy-v1.json")
    parser.add_argument("--output", required=True, help="Git-ignored results/ relative path")
    parser.add_argument("--run-id", default=datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"))
    parser.add_argument("--confirm-approved", action="store_true")
    parser.add_argument("--confirm-terms", action="store_true")
    parser.add_argument("--confirm-poi-candidate", action="store_true")
    args = parser.parse_args(argv)
    started_utc = datetime.now(UTC).isoformat(timespec="seconds")
    try:
        parsed = {}
        for value in args.input:
            label, sep, path = value.partition("=")
            region, colon, role = label.partition(":")
            if not sep or not colon or region not in REGIONS or role not in ROLES or (region, role) in parsed:
                raise ValueError("input role invalid")
            parsed[(region, role)] = path
        args.inputs = parsed
        raw_root, specs, snapshot, policy, snapshot_meta, output = _validate(args)
        split_data = {(spec.region, spec.role): shared._read_split(spec) for spec in specs}
        for region in REGIONS:
            train, validation = split_data[(region, "TL")], split_data[(region, "VL")]
            if train.travel_ids & validation.travel_ids:
                raise ValueError("TL/VL overlap")
        source_results = {(spec.region, spec.role): _source_rows(spec) for spec in specs}
        source_maps = {key: value[0] for key, value in source_results.items()}
        positive_maps = {key: value[1] for key, value in source_results.items()}
        missing_trip_counts = {key: value[2] for key, value in source_results.items()}
        catalog = _read_catalog(snapshot, snapshot_meta, policy)
        rows = analyze(catalog, split_data, source_maps, positive_maps,
                       missing_trip_counts, policy)
        resolved = (REPO_ROOT / output).resolve()
        results_root = (REPO_ROOT / "results").resolve()
        if not shared.within(resolved, results_root) or resolved == results_root:
            raise ValueError("unsafe output")
        resolved.mkdir(parents=True, exist_ok=True)
        fields = ("scope", "metric", "bucket", "support", "status")
        with (resolved / "metrics.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader(); writer.writerows(rows)
        manifest = {
            "run_id": args.run_id,
            "dataset": {"name": "AI Hub Domestic Travel Log", "version": "2023"},
            "virtual_context": {"mapping": "input role -> same named predeclared ProductRegion",
                                "historical_request_context": False, "district": None,
                                "request_universe": "all distinct TRAVEL_ID values in TN_TRAVEL",
                                "positive_unit": "distinct nonblank (TRAVEL_ID, POI_ID) pairs from visit rows",
                                "visit_trip_ids_outside_request_universe": "reported separately",
                                "missing_visit_trip_id": "reported separately"},
            "candidate_policy_sha256": policy.policy_sha256,
            "policy_version": policy.version,
            "provider": snapshot_meta.get("provider"),
            "manual_version": snapshot_meta.get("manual_version"),
            "retrieved_at_utc": snapshot_meta.get("retrieved_at_utc"),
            "snapshot_sha256": snapshot_meta.get("snapshot_sha256"),
            "request_config_hash": snapshot_meta.get("request_config", {}).get("request_config_hash"),
            "experiment_config_sha256": hashlib.sha256(json.dumps({
                "virtual_context_mapping": {region: region for region in REGIONS},
                "request_district": None,
                "supported_content_types": sorted(policy.supported_content_type_ids),
                "identity_signals": ["normalized_name", "exact_address"],
                "coordinates_enabled": False,
                "source_district_crosswalk_enabled": False,
                "request_universe": "all distinct TRAVEL_ID values in TN_TRAVEL",
                "positive_unit": "distinct nonblank (TRAVEL_ID, POI_ID) pairs from visit rows",
                "candidate_policy_sha256": policy.policy_sha256,
                "snapshot_sha256": snapshot_meta.get("snapshot_sha256"),
            }, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
            "snapshot_version": snapshot_meta.get("snapshot_version"),
            "snapshot_item_count": snapshot_meta.get("catalog_item_count"),
            "cli_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "source_loader_sha256": hashlib.sha256(Path(shared.__file__).read_bytes()).hexdigest(),
            "input_role_map": {region: region for region in REGIONS},
            "input_fields": {
                "TN_TRAVEL": ["TRAVEL_ID"],
                "TN_VISIT_AREA_INFO": ["TRAVEL_ID", "POI_ID", "POI_NM", "SGG_CD", "LOTNO_ADDR", "ROAD_NM_ADDR"],
            },
            "started_utc": started_utc,
            "finished_utc": datetime.now(UTC).isoformat(timespec="seconds"),
            "privacy": {"raw_paths": False, "raw_ids": False, "rows": False,
                        "coordinates": False, "free_text": False, "secrets": False},
            "interpretation": {"visited": "positive", "unvisited": "unknown/unlabeled",
                                "coordinates_for_identity": False,
                                "source_category_crosswalk": "not_applied",
                                "identity_evidence": "normalized name and exact address only; district code crosswalk disabled",
                                "positive_coverage": "confirmed lower bound; ambiguous/unmatched positives are unresolved, not catalog-outside",
                                "outside_candidate": "confidently matched catalog identities that fail v1 eligibility",
                                "catalog_outside": "not estimable from unmatched or ambiguous identity results",
                                "cold_start": "eligible matched VL positives absent from the TL matched-item universe",
                                "historical_proxy": "TL-observed POI_ID candidates, reported separately"},
        }
        (resolved / "run_metadata.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception:
        print("[stopped] snapshot, input, or output validation failed safely", file=sys.stderr)
        return 2
    print(f"Completed privacy-safe POI candidate diagnostics; run-id={args.run_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
