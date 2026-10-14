"""Compare Issue #4 catalog type scenarios without inventing request geography.

This is an analysis-time inventory and identity-coverage comparison. KTO
legal-dong codes group catalog rows only; AI Hub visit region is never used as
a request-time region filter. Unmatched/ambiguous observations are not claimed
to be outside the KTO catalog.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

import analyze_poi_catalog_identity as identity
import analyze_poi_source_readiness as readiness
import evaluate_popularity as shared
from poi_identity_contract import CatalogPoi, SourcePoi, match_source_poi, normalize_exact

SCENARIOS = {
    "A": frozenset({"12", "14", "15", "25", "28", "32", "38", "39"}),
    "B": frozenset({"12", "14", "15", "25", "28"}),
    "C": frozenset({"12", "14", "28"}),
}
RESULTS_ROOT = identity.REPO_ROOT / "results" / "experiments" / "poi-catalog-scenarios"
AUDIT_SEED = "issue4-match-audit-v1"
AUDIT_MAX_PER_STRATUM = 20


def positive_class(status: str, item: CatalogPoi | None,
                   supported_types: frozenset[str]) -> str:
    if status == "MATCHED" and item is not None:
        return "linked_in_scope" if item.content_type in supported_types else "linked_outside_type_scope"
    return "ambiguous" if status == "AMBIGUOUS" else "unmatched"


def deterministic_audit_sample(item_ids: set[str], *, region: str, split: str,
                               limit: int = AUDIT_MAX_PER_STRATUM,
                               seed: str = AUDIT_SEED) -> list[str]:
    """Select a reproducible bounded sample; IDs remain in memory only."""
    ranked = sorted(item_ids, key=lambda value: hashlib.sha256(
        (seed + "|" + region + "|" + split + "|" + value).encode("utf-8")).digest())
    return ranked[:limit]


def _rate(scope: str, scenario: str, split: str, metric: str,
          numerator: int, denominator: int) -> dict[str, str]:
    return {"scope": scope, "scenario": scenario, "split": split,
            "unit": "positive_events", "metric": metric,
            "value": shared.rate_band(numerator, denominator),
            "support": shared.count_bucket(denominator)}


def _public_count(scope: str, scenario: str, kind: str, metric: str,
                  amount: int) -> dict[str, str]:
    # Counts describe only the public KTO snapshot, not AI Hub observations.
    return {"scope": scope, "scenario": scenario, "split": "CATALOG",
            "unit": kind, "metric": metric, "value": str(amount),
            "support": str(amount)}


def _identity_map(catalog: list[CatalogPoi], source_ids: set[str],
                  master_path: Path, region: str, snapshot_id: str
                  ) -> dict[str, tuple[str, str, CatalogPoi | None]]:
    master_keys, stable, _ = readiness._read_master(master_path, source_ids)
    by_name: dict[str, list[CatalogPoi]] = defaultdict(list)
    by_content_id = {item.content_id: item for item in catalog}
    for item in catalog:
        by_name[normalize_exact(item.title)].append(item)
    result: dict[str, tuple[str, str, CatalogPoi | None]] = {}
    for source_id in source_ids:
        if source_id in master_keys and source_id not in stable:
            result[source_id] = ("AMBIGUOUS", "conflicting_source_metadata", None)
            continue
        if source_id not in stable:
            result[source_id] = ("UNMATCHED", "missing_master_metadata", None)
            continue
        name, address, *_ = stable[source_id]
        match = match_source_poi(SourcePoi(region, source_id, name, address),
                                 by_name.get(normalize_exact(name), []),
                                 snapshot_version=snapshot_id)
        result[source_id] = (match.status, match.method,
                             by_content_id.get(match.canonical_id) if match.canonical_id else None)
    return result


def compare(catalog: list[CatalogPoi], specs: list[shared.InputSpec],
            masters: dict[str, Path], snapshot_id: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    # Public inventory is reported nationally and by KTO legal-dong region.
    # District codes are deliberately not used: no request-code mapping exists.
    area_codes = sorted({item.area_code for item in catalog if item.area_code})
    for scenario, allowed in SCENARIOS.items():
        scoped = [item for item in catalog if item.content_type in allowed]
        rows.append(_public_count("catalog_national", scenario, "catalog_items", "inventory_size", len(scoped)))
        rows.append(_public_count("catalog_national", scenario, "catalog_items", "missing_lDongRegnCd",
                                  sum(not item.area_code for item in scoped)))
        for type_id in sorted(allowed):
            count = sum(item.content_type == type_id for item in scoped)
            rows.append(_public_count("catalog_national", scenario, "content_type", type_id, count))
        by_area: dict[str, list[CatalogPoi]] = defaultdict(list)
        for item in scoped:
            if item.area_code:
                by_area[item.area_code].append(item)
        for area_code in area_codes:
            rows.append(_public_count("lDongRegnCd:" + area_code, scenario,
                                      "catalog_items", "inventory_size",
                                      len(by_area.get(area_code, []))))
            for type_id in sorted(allowed):
                rows.append(_public_count("lDongRegnCd:" + area_code, scenario,
                                          "content_type", type_id,
                                          sum(item.content_type == type_id
                                              for item in by_area.get(area_code, []))))

    by_role = {(spec.region, spec.role): spec for spec in specs}
    audit_sample_total = 0
    for region in shared.REGIONS:
        tl = shared._read_split(by_role[(region, "TL")])
        vl = shared._read_split(by_role[(region, "VL")])
        if tl.travel_ids & vl.travel_ids:
            raise ValueError("TL/VL trip overlap")
        source_ids = {event.item_id for event in tl.events + vl.events}
        identity_map = _identity_map(catalog, source_ids, masters[region], region, snapshot_id)
        tl_ids = {event.item_id for event in tl.events}
        for split_name, split in (("TL", tl), ("VL", vl)):
            denominator = len(split.events)
            distinct_items = {event.item_id for event in split.events}
            proposed_matches = {item_id for item_id in distinct_items
                                if identity_map[item_id][0] == "MATCHED"}
            sample = deterministic_audit_sample(proposed_matches, region=region, split=split_name)
            audit_sample_total += len(sample)
            rows.extend((
                {"scope": region, "scenario": "ALL", "split": split_name,
                 "unit": "proposed_matched_pair_sample", "metric": "sample_denominator",
                 "value": shared.count_bucket(len(sample)), "support": shared.count_bucket(len(sample))},
                {"scope": region, "scenario": "ALL", "split": split_name,
                 "unit": "proposed_matched_pair_sample", "metric": "method_unique_exact_name_address",
                 "value": shared.count_bucket(len(sample)), "support": shared.count_bucket(len(sample))},
                {"scope": region, "scenario": "ALL", "split": split_name,
                 "unit": "proposed_matched_pair_sample", "metric": "adjudicated_pairs",
                 "value": "0; review pending", "support": shared.count_bucket(len(sample))},
            ))
            for scenario, allowed in SCENARIOS.items():
                classes = [positive_class(identity_map[event.item_id][0],
                                          identity_map[event.item_id][2], allowed)
                           for event in split.events]
                for name in ("linked_in_scope", "linked_outside_type_scope", "ambiguous", "unmatched"):
                    rows.append(_rate(region, scenario, split_name,
                                      "positive_" + name + "_share",
                                      sum(value == name for value in classes), denominator))
                if split_name == "VL":
                    rows.append(_rate(region, scenario, split_name,
                                      "positive_in_scope_and_TL_proxy_share",
                                      sum(value == "linked_in_scope" and event.item_id in tl_ids
                                          for value, event in zip(classes, split.events)), denominator))
                    rows.append(_rate(region, scenario, split_name,
                                      "positive_in_scope_TL_cold_start_share",
                                      sum(value == "linked_in_scope" and event.item_id not in tl_ids
                                          for value, event in zip(classes, split.events)), denominator))
                # Catalog code is attached only by a successful identity link.
                # Each code share uses the same full regional positive denominator.
                by_area = Counter(
                    identity_map[event.item_id][2].area_code
                    for value, event in zip(classes, split.events)
                    if value == "linked_in_scope" and identity_map[event.item_id][2]
                    and identity_map[event.item_id][2].area_code
                )
                for area_code in area_codes:
                    rows.append(_rate("matched_positive_lDongRegnCd:" + area_code,
                                      scenario, split_name, "positive_in_scope_share_of_all",
                                      by_area[area_code], denominator))
        print(region + ": scenario aggregation complete", flush=True)
    rows.append({"scope": "all_regions", "scenario": "ALL", "split": "TL_VL_stratified",
                 "unit": "proposed_matched_pair_sample", "metric": "selected_sample_denominator",
                 "value": str(audit_sample_total), "support": shared.count_bucket(audit_sample_total)})
    rows.append({"scope": "all_regions", "scenario": "ALL", "split": "TL_VL_stratified",
                 "unit": "proposed_matched_pair_sample", "metric": "method_unique_exact_name_address",
                 "value": str(audit_sample_total), "support": shared.count_bucket(audit_sample_total)})
    rows.append({"scope": "all_regions", "scenario": "ALL", "split": "TL_VL_stratified",
                 "unit": "proposed_matched_pair_sample", "metric": "adjudicated_pairs",
                 "value": "0; review pending", "support": shared.count_bucket(audit_sample_total)})
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-id", required=True)
    parser.add_argument("--sync-id", required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args(argv)
    try:
        run_id = identity._run_id(args.run_id)
        snapshot_id = identity._run_id(args.snapshot_id)
        sync_id = identity._run_id(args.sync_id)
        output = RESULTS_ROOT / run_id
        if output.exists() or output.is_symlink() or shared.has_symlink_component(output.absolute()):
            raise ValueError("result destination unavailable")
        catalog, catalog_manifest = identity._load_catalog(snapshot_id)
        sync_manifest = identity._validate_sync(catalog, sync_id)
        specs, masters = identity._source_specs(run_id)
        metrics = compare(catalog, specs, masters, snapshot_id)
        output.mkdir(parents=True, mode=0o700)
        with (output / "metrics.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=("scope", "scenario", "split", "unit", "metric", "value", "support"))
            writer.writeheader()
            writer.writerows(metrics)
        metadata = {
            "dataset": "AI Hub Domestic Travel Log 2023",
            "catalog_snapshot_id": snapshot_id,
            "catalog_sha256": catalog_manifest["catalog_sha256"],
            "sync_snapshot_id": sync_id,
            "sync_sha256": sync_manifest["sync_sha256"],
            "scenarios": {key: sorted(value) for key, value in SCENARIOS.items()},
            "area_semantics": "KTO_lDongRegnCd_catalog_grouping_only_not_request_or_serving_filter",
            "district_semantics": "not_analyzed_unvalidated_request_mapping",
            "identity_rule": "unique_normalized_name_and_generic_address_string; unreviewed",
            "positive_semantics": "observed visit; unvisited unknown_unlabeled",
            "unmatched_semantics": "not_linked_under_rule_not_proven_catalog_outside",
            "request_time_candidate_coverage": "unestimable_no_request_context_or_product_area_contract",
            "code_revision": shared._git_revision(),
            "code_worktree_dirty": shared._git_dirty(),
            "code_sha256": {
                name: hashlib.sha256(Path(path).read_bytes()).hexdigest()
                for name, path in (
                    ("analyze_poi_catalog_scenarios.py", __file__),
                    ("analyze_poi_catalog_identity.py", identity.__file__),
                    ("analyze_poi_source_readiness.py", readiness.__file__),
                    ("poi_identity_contract.py", Path(identity.REPO_ROOT / "scripts/recommendation/poi_identity_contract.py")),
                    ("evaluate_popularity.py", Path(shared.__file__)),
                )
            },
            "completed_utc": datetime.now(UTC).isoformat(timespec="seconds"),
            "privacy": "public catalog inventory exact; observed-data rates coarse/suppressed; no row-level fields",
            "precision_review": "not_estimated_manual_sample_unadjudicated_no_private_review_view",
            "precision_sample": {
                "method": "SHA-256 rank within region by TL/VL split among unique proposed MATCHED source items",
                "seed": AUDIT_SEED,
                "maximum_per_region_split_stratum": AUDIT_MAX_PER_STRATUM,
                "ids_or_pair_fields_persisted": False,
                "adjudication": "not_performed_in_agent_channel; no private value-view facility",
            },
        }
        (output / "run_metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    except Exception:
        print("[stopped] scenario, source, split, or output validation failed safely", file=sys.stderr)
        return 2
    print("Completed privacy-safe scenario comparison: run-id=" + run_id + ", rows=" + str(len(metrics)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
