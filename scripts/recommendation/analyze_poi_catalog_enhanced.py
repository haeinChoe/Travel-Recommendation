"""Privacy-safe enhanced identity diagnostics for Issue #4.

Stage 1 remains the existing strict rule. Stages 2 and 3 generate review-only
candidates. This script does not define product or request-time contracts.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import analyze_poi_catalog_identity as identity
import analyze_poi_catalog_scenarios as scenarios
import evaluate_popularity as shared
from adjudicate_poi_candidate_sample import (AuditObservation, CandidateView,
                                             SourceCandidateGroup, review_ephemeral)
from poi_identity_contract import (CandidateEvidence, CandidateGenerationResult,
                                   CatalogCandidateIndex, CatalogPoi, SourcePoi,
                                   normalize_exact)

RESULTS_ROOT = identity.REPO_ROOT / "results" / "experiments" / "poi-catalog-enhanced"
SAMPLE_SEED = "issue4-enhanced-audit-v1"
SAMPLE_PER_REGION_STRATUM = 6
FUZZY_CANDIDATE_DISPLAY_LIMIT = 5
PRIMARY_PAIR_AUDIT_STRATA = {
    "punctuation_address_variant": "address_punctuation_variant_primary_pair",
    "normalized_multi_rule_candidates": "normalized_multi_rule_primary_pair",
}
SOURCE_REQUIRED = {"POI_ID", "POI_NM", "ROAD_NM_ADDR"}
SOURCE_SELECTED = SOURCE_REQUIRED | {"ASORT_LCLASDC", "ASORT_MLSFCDC", "ASORT_SDASDC"}


@dataclass(frozen=True)
class SourceMetadata:
    name: str | None
    address: str | None
    source_type: str
    identity_conflicted: bool = False
    missing_master: bool = False
    missing_name: bool = False
    missing_address: bool = False
    identity_variants: tuple[tuple[str | None, str | None], ...] = ()


def _bucket(value: int) -> str:
    return shared.count_bucket(value)


def _rate(numerator: int, denominator: int) -> str:
    return shared.rate_band(numerator, denominator)


def _candidate_count_bucket(value: int) -> str:
    if value == 0:
        return "0"
    if value == 1:
        return "1"
    if value < 5:
        return "2-4"
    return "5+"


def _read_source_metadata(master_path: Path, observed_ids: set[str]) -> dict[str, SourceMetadata]:
    identities: dict[str, set[tuple[str, str]]] = defaultdict(set)
    displays: dict[str, set[tuple[str, str, str]]] = defaultdict(set)
    for row in shared._rows([master_path], SOURCE_REQUIRED, SOURCE_SELECTED):
        source_id = shared._cell(row, "poi_id")
        if source_id not in observed_ids:
            continue
        name, address = row.get("poi_nm") or "", row.get("road_nm_addr") or ""
        source_type = " / ".join(
            f"L{n}={row.get(field) or ''}" for n, field in enumerate(
                ("asort_lclasdc", "asort_mlsfcdc", "asort_sdasdc"), 1)
            if row.get(field)
        ) or "[not supplied]"
        identities[source_id].add((normalize_exact(name), normalize_exact(address)))
        displays[source_id].add((name, address, source_type))
    result: dict[str, SourceMetadata] = {}
    for source_id in observed_ids:
        keys = identities.get(source_id, set())
        if not keys:
            result[source_id] = SourceMetadata(None, None, "[no source master record]",
                                               missing_master=True, missing_name=True,
                                               missing_address=True)
            continue
        values = sorted(displays[source_id])
        names = sorted({value[0] for value in values if value[0]})
        addresses = sorted({value[1] for value in values if value[1]})
        types = sorted({value[2] for value in values if value[2]})
        variants = tuple(sorted({(name or None, address or None)
                                 for name, address, _ in values}))
        # Preserve a real source spelling when several raw variants collapse to
        # one exact normalized identity. Joining them creates a synthetic value
        # that cannot match any catalog row. Conflicting normalized identities
        # remain explicitly ambiguous and are evaluated variant by variant below.
        if len(keys) == 1:
            selected_name, selected_address = variants[0]
        else:
            # Keep one real pair for legacy display fields; the paired variants
            # below retain every observed association for candidate generation
            # and any local review.
            selected_name, selected_address = variants[0]
        result[source_id] = SourceMetadata(
            selected_name,
            selected_address,
            " / ".join(types) if len(types) == 1 else
            ("[conflicting source classification codes]" if types else "[not supplied]"),
            identity_conflicted=len(keys) > 1,
            missing_name=not bool(names), missing_address=not bool(addresses),
            identity_variants=variants if len(keys) > 1 else (),
        )
    return result


def _result_for_source(index: CatalogCandidateIndex, region: str, source_id: str,
                       metadata: SourceMetadata) -> CandidateGenerationResult:
    source = SourcePoi(region, source_id, metadata.name, metadata.address)
    if not metadata.identity_conflicted:
        return index.generate(source)
    strict = index.generate(source, source_conflicted=True).strict_result
    found: dict[tuple[str, str | None, str | None], CandidateEvidence] = {}
    stages = ("none", "stage1_exact", "stage2_normalized", "stage3_fuzzy")
    stage = "none"
    variants = metadata.identity_variants or ((metadata.name, metadata.address),)
    variant_candidate_counts = []
    for name, address in variants:
        candidate_result = index.generate(
            SourcePoi(region, source_id, name, address), retain_all_candidates=True)
        variant_candidate_counts.append((name, address, candidate_result.candidate_count))
        if stages.index(candidate_result.stage) > stages.index(stage):
            stage = candidate_result.stage
        for candidate in candidate_result.candidates:
            pair_key = (candidate.item.content_id, candidate.source_name,
                        candidate.source_address)
            previous = found.get(pair_key)
            current_score = (candidate.name_similarity, candidate.address_similarity)
            previous_score = ((previous.name_similarity, previous.address_similarity)
                              if previous else (-1.0, -1.0))
            if current_score > previous_score:
                found[pair_key] = candidate
    candidates = tuple(sorted(found.values(), key=lambda value: (
        value.name_similarity, value.address_similarity, value.item.content_id
    ), reverse=True))
    return CandidateGenerationResult("AMBIGUOUS", stage, "conflicting_source_metadata",
                                     candidates,
                                     len({candidate.item.content_id for candidate in found.values()}),
                                     "conflicting_source_metadata", strict,
                                     tuple(variant_candidate_counts))


def _identity_stratum(metadata: SourceMetadata,
                      result: CandidateGenerationResult) -> str:
    if metadata.missing_master or metadata.missing_name or metadata.missing_address:
        return "missing_metadata"
    if result.status == "MATCHED":
        return "strict_matched"
    if result.candidate_count > 1 or result.status == "AMBIGUOUS":
        return "multi_candidate_ambiguous"
    if result.stage == "stage2_normalized" and result.candidate_count == 1:
        return "stage2_normalized_review"
    if result.stage == "stage3_fuzzy" and result.candidate_count == 1:
        return "stage3_fuzzy_review"
    return "still_unmatched"


def _source_rows(specs, masters, catalog, snapshot_id):
    by_role = {(spec.region, spec.role): spec for spec in specs}
    index = CatalogCandidateIndex(catalog, snapshot_version=snapshot_id,
                                  fuzzy_display_limit=FUZZY_CANDIDATE_DISPLAY_LIMIT)
    results, metadata_by_key, events_by_role = {}, {}, {}
    role_membership: dict[tuple[str, str], set[str]] = defaultdict(set)
    for region in shared.REGIONS:
        splits = {}
        for role in ("TL", "VL"):
            print(f"source_split_read=started:{region}/{role}", flush=True)
            split = shared._read_split(by_role[(region, role)])
            splits[role] = split
            events_by_role[(region, role)] = split.events
            print(f"source_split_read=complete:{region}/{role}; "
                  f"event_count={_bucket(len(split.events))}", flush=True)
            for event in split.events:
                role_membership[(region, event.item_id)].add(role)
        if splits["TL"].travel_ids & splits["VL"].travel_ids:
            raise ValueError("TL/VL trip overlap")
        source_ids = {event.item_id for role in ("TL", "VL") for event in splits[role].events}
        source_metadata = _read_source_metadata(masters[region], source_ids)
        for source_id in source_ids:
            key = (region, source_id)
            metadata_by_key[key] = source_metadata[source_id]
            results[key] = _result_for_source(index, region, source_id, source_metadata[source_id])
        print(f"identity_pipeline={region}: complete; distinct_source_items={_bucket(len(source_ids))}", flush=True)
    return results, metadata_by_key, events_by_role, role_membership, index


def _add(rows, scope, scenario, split, unit, metric, value, support):
    rows.append({"scope": scope, "scenario": scenario, "split": split,
                 "unit": unit, "metric": metric, "value": value, "support": support})


def _catalog_inventory(rows, catalog):
    codes = sorted({item.area_code for item in catalog if item.area_code})
    for scenario, allowed in scenarios.SCENARIOS.items():
        selected = [item for item in catalog if item.content_type in allowed]
        _add(rows, "catalog_national", scenario, "CATALOG", "catalog_items", "inventory_size",
             str(len(selected)), str(len(selected)))
        for content_type in sorted(allowed):
            count = sum(item.content_type == content_type for item in selected)
            _add(rows, "catalog_national", scenario, "CATALOG", "content_type", content_type,
                 str(count), str(count))
        for code in codes:
            group = [item for item in selected if item.area_code == code]
            _add(rows, "lDongRegnCd:" + code, scenario, "CATALOG", "catalog_items", "inventory_size",
                 str(len(group)), str(len(group)))
            for content_type in sorted(allowed):
                count = sum(item.content_type == content_type for item in group)
                _add(rows, "lDongRegnCd:" + code, scenario, "CATALOG", "content_type", content_type,
                     str(count), str(count))


def _catalog_area_positive_counts(events, results, by_id, allowed):
    """Group only confirmed links by the linked catalog item's KTO analysis area."""
    counts = defaultdict(Counter)
    for event in events:
        result = results[(event.region, event.item_id)]
        if result.status != "MATCHED":
            continue
        item = by_id.get(result.candidates[0].item.content_id)
        if item is None or not item.area_code:
            continue
        status = "matched_in_scenario" if item.content_type in allowed else "matched_outside_scenario"
        counts[item.area_code][status] += 1
    return counts


def _audit_observations(results, metadata, *, audit_method: str | None = None,
                       primary_pair: bool = False):
    by_stratum: dict[tuple[str, str], list[tuple[str, CandidateGenerationResult, SourceMetadata]]] = defaultdict(list)
    for (region, source_id), result in results.items():
        if audit_method and result.method != audit_method:
            continue
        stratum = (PRIMARY_PAIR_AUDIT_STRATA[audit_method] if primary_pair
                   else _identity_stratum(metadata[(region, source_id)], result))
        by_stratum[(region, stratum)].append((source_id, result, metadata[(region, source_id)]))
    observations, support = [], []
    for (region, stratum), values in sorted(by_stratum.items()):
        ranked = sorted(values, key=lambda value: hashlib.sha256(
            f"{SAMPLE_SEED}|{region}|{stratum}|{value[0]}".encode("utf-8")).digest())
        selected = ranked[:SAMPLE_PER_REGION_STRATUM]
        for position, (_, result, source) in enumerate(selected):
            partition = "development" if position % 2 == 0 else "validation"
            evidence = result.candidates[:1] if primary_pair else result.candidates
            candidates = tuple(CandidateView(
                item.item.title or "[not supplied]", item.item.road_address or "[not supplied]",
                item.item.content_type or "[not supplied]",
            ) for item in evidence)
            candidate_groups = ()
            if source.identity_conflicted:
                counts_by_pair = {(name, address): count for name, address, count
                                  in result.source_variant_candidate_counts}
                candidate_groups = tuple(SourceCandidateGroup(
                    source_name=name or "[not supplied]",
                    source_address=address or "[not supplied]",
                    candidates=tuple(CandidateView(
                        candidate.item.title or "[not supplied]",
                        candidate.item.road_address or "[not supplied]",
                        candidate.item.content_type or "[not supplied]",
                    ) for candidate in evidence if (candidate.source_name, candidate.source_address)
                    == (name, address))[:FUZZY_CANDIDATE_DISPLAY_LIMIT],
                    candidate_count=counts_by_pair.get((name, address), 0),
                ) for name, address in source.identity_variants)
            observations.append(AuditObservation(
                region, stratum, partition, result.method,
                source.name or "[not supplied]", source.address or "[not supplied]",
                source.source_type, candidates, result.candidate_count,
                source_candidate_groups=candidate_groups,
            ))
        for partition in ("development", "validation"):
            chosen = [i for i in range(len(selected))
                      if ("development" if i % 2 == 0 else "validation") == partition]
            methods = Counter(selected[i][1].method for i in chosen)
            support.append({"region": region, "stratum": stratum, "partition": partition,
                            "selected_count": len(chosen), "available_support": _bucket(len(values)),
                            "methods": {key: _bucket(value) for key, value in sorted(methods.items())}})
    return observations, support


def _metrics(catalog, results, metadata, events_by_role, role_membership):
    rows = []
    _catalog_inventory(rows, catalog)
    by_id = {item.content_id: item for item in catalog}
    status_names = ("MATCHED", "REVIEW", "AMBIGUOUS", "UNMATCHED")
    for region in shared.REGIONS:
        keys = [key for key in results if key[0] == region]
        scopes = (
            ("all_items", keys),
            ("tl_items", [key for key in keys if "TL" in role_membership[key]]),
            ("vl_items", [key for key in keys if "VL" in role_membership[key]]),
            ("tl_vl_both", [key for key in keys if role_membership[key] == {"TL", "VL"}]),
        )
        for scope, selected in scopes:
            denominator = len(selected)
            strict = sum(results[key].strict_result.status == "MATCHED" for key in selected)
            reviewed = sum(results[key].status in {"REVIEW", "AMBIGUOUS"} for key in selected)
            recovered = sum(results[key].strict_result.status == "UNMATCHED"
                            and results[key].status in {"REVIEW", "AMBIGUOUS"} for key in selected)
            for status in status_names:
                count = sum(results[key].status == status for key in selected)
                _add(rows, region, "ALL", scope, "source_items", "enhanced_" + status.lower() + "_share",
                     _rate(count, denominator), _bucket(denominator))
            _add(rows, region, "ALL", scope, "source_items", "stage1_strict_link_share",
                 _rate(strict, denominator), _bucket(denominator))
            _add(rows, region, "ALL", scope, "source_items", "review_candidate_share",
                 _rate(reviewed, denominator), _bucket(denominator))
            _add(rows, region, "ALL", scope, "source_items", "recovered_from_stage1_unmatched_share_of_reviewed",
                 _rate(recovered, reviewed), _bucket(reviewed))
            methods = Counter(results[key].method for key in selected)
            for method, count in sorted(methods.items()):
                _add(rows, region, "ALL", scope, "matching_method", method,
                     _rate(count, denominator), _bucket(denominator))
            candidate_groups: dict[tuple[str, str], list[int]] = defaultdict(list)
            for key in selected:
                result = results[key]
                candidate_groups[(result.method, result.blocking_rule)].append(
                    result.candidate_count)
            for (method, blocking_rule), counts in sorted(candidate_groups.items()):
                group_denominator = len(counts)
                bucket_counts = Counter(_candidate_count_bucket(value) for value in counts)
                for bucket in ("0", "1", "2-4", "5+"):
                    _add(rows, region, "ALL", scope, "candidate_generation",
                         f"{method}|{blocking_rule}|candidate_count_{bucket}",
                         _rate(bucket_counts[bucket], group_denominator),
                         _bucket(group_denominator))
            for label, count in (
                ("missing_source_master", sum(metadata[key].missing_master for key in selected)),
                ("missing_source_name", sum(metadata[key].missing_name for key in selected)),
                ("missing_source_address", sum(metadata[key].missing_address for key in selected)),
                ("conflicting_source_metadata", sum(metadata[key].identity_conflicted for key in selected)),
            ):
                _add(rows, region, "ALL", scope, "source_items", label + "_share",
                     _rate(count, denominator), _bucket(denominator))
        tl_ids = {event.item_id for event in events_by_role[(region, "TL")]}
        for split in ("TL", "VL"):
            events = events_by_role[(region, split)]
            denominator = len(events)
            for scenario, allowed in scenarios.SCENARIOS.items():
                counts = Counter()
                for event in events:
                    result = results[(region, event.item_id)]
                    if result.status == "MATCHED":
                        item = by_id.get(result.candidates[0].item.content_id)
                        counts["matched_in_scope" if item and item.content_type in allowed
                               else "matched_outside_scope"] += 1
                    else:
                        counts[result.status.lower()] += 1
                for status in ("matched_in_scope", "matched_outside_scope", "review", "ambiguous", "unmatched"):
                    _add(rows, region, scenario, split, "positive_events", "identity_" + status + "_share",
                         _rate(counts[status], denominator), _bucket(denominator))
                area_counts = _catalog_area_positive_counts(events, results, by_id, allowed)
                for area_code, area_statuses in sorted(area_counts.items()):
                    for status in ("matched_in_scenario", "matched_outside_scenario"):
                        _add(rows, "lDongRegnCd:" + area_code, scenario, split, "positive_events",
                             "catalog_area_" + status + "_share",
                             _rate(area_statuses[status], denominator), _bucket(denominator))
                shown_in = shown_out = 0
                for event in events:
                    result = results[(region, event.item_id)]
                    if result.status not in {"REVIEW", "AMBIGUOUS"}:
                        continue
                    types = [candidate.item.content_type for candidate in result.candidates]
                    if any(kind in allowed for kind in types):
                        shown_in += 1
                    elif types:
                        shown_out += 1
                _add(rows, region, scenario, split, "positive_events", "review_candidates_shown_in_scope_share",
                     _rate(shown_in, denominator), _bucket(denominator))
                _add(rows, region, scenario, split, "positive_events", "review_candidates_shown_outside_scope_share",
                     _rate(shown_out, denominator), _bucket(denominator))
                if split == "VL":
                    inside = sum(event.item_id in tl_ids for event in events)
                    _add(rows, region, scenario, split, "positive_events", "tl_observed_proxy_inside_share",
                         _rate(inside, denominator), _bucket(denominator))
                    _add(rows, region, scenario, split, "positive_events", "tl_observed_proxy_outside_share",
                         _rate(denominator - inside, denominator), _bucket(denominator))
    return rows


def _add_audit_metrics(rows, aggregate_path):
    if not aggregate_path.is_file():
        return
    aggregate = json.loads(aggregate_path.read_text(encoding="utf-8"))
    total = aggregate["reviewed_count"]
    for label, amount in aggregate["labels"].items():
        _add(rows, "all_regions", "AUDIT", "ALL", "reviewed_source_items", "audit_" + label.lower() + "_share",
             _rate(amount, total), _bucket(total))
    for key, value in aggregate["by_method_stratum_partition"].items():
        method, stratum, partition = key.split("|", 2)
        denominator = value["reviewed_count"]
        for label, amount in value["labels"].items():
            _add(rows, "all_regions", "AUDIT", partition, "reviewed_source_items",
                 f"{stratum}_{method}_{label.lower()}_share", _rate(amount, denominator), _bucket(denominator))


def _validate_reusable_audit(run_id: str, snapshot_id: str, sync_id: str,
                             sample_support: list[dict]) -> Path:
    audit_run = identity._run_id(run_id)
    audit_root = RESULTS_ROOT / audit_run
    metadata_path = audit_root / "run_metadata.json"
    support_path = audit_root / "sample_support.json"
    aggregate_path = audit_root / "audit" / "aggregate.json"
    paths = (audit_root, metadata_path, support_path, aggregate_path)
    if any(path.is_symlink() or shared.has_symlink_component(path.absolute()) for path in paths):
        raise ValueError("reusable audit input unavailable")
    if not all(path.is_file() for path in (metadata_path, support_path, aggregate_path)):
        raise ValueError("reusable audit input unavailable")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    support = json.loads(support_path.read_text(encoding="utf-8"))
    if (metadata.get("catalog_snapshot_id") != snapshot_id
            or metadata.get("sync_snapshot_id") != sync_id
            or metadata.get("sample", {}).get("seed") != SAMPLE_SEED
            or support != sample_support):
        raise ValueError("reusable audit does not match this sample frame")
    aggregate = json.loads(aggregate_path.read_text(encoding="utf-8"))
    labels = aggregate.get("labels")
    groups = aggregate.get("by_method_stratum_partition")
    expected_count = sum(int(row["selected_count"]) for row in sample_support)
    if (not isinstance(aggregate.get("reviewed_count"), int)
            or not isinstance(labels, dict)
            or set(labels) != {"MATCH", "NO_MATCH", "UNCERTAIN"}
            or any(not isinstance(value, int) or value < 0 for value in labels.values())
            or sum(labels.values()) != aggregate["reviewed_count"]
            or aggregate["reviewed_count"] != expected_count
            or not isinstance(groups, dict)
            or any(not isinstance(value, dict) for value in groups.values())
            or sum(value.get("reviewed_count", -1) for value in groups.values()) != expected_count):
        raise ValueError("reusable audit aggregate invalid")
    for group in groups.values():
        group_labels = group.get("labels")
        if (not isinstance(group_labels, dict)
                or set(group_labels) != {"MATCH", "NO_MATCH", "UNCERTAIN"}
                or any(not isinstance(value, int) or value < 0 for value in group_labels.values())
                or sum(group_labels.values()) != group.get("reviewed_count")):
            raise ValueError("reusable audit aggregate invalid")
    if aggregate.get("adjudicator_role") not in {"author", "independent"}:
        raise ValueError("reusable audit role invalid")
    return aggregate_path


def _write_metrics(path: Path, rows: list[dict[str, str]]) -> None:
    fields = ("scope", "scenario", "split", "unit", "metric", "value", "support")
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-id", required=True)
    parser.add_argument("--sync-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--audit", action="store_true")
    parser.add_argument("--audit-method", choices=tuple(PRIMARY_PAIR_AUDIT_STRATA))
    parser.add_argument("--audit-primary-pair", action="store_true")
    parser.add_argument("--reuse-audit-run-id")
    parser.add_argument("--adjudicator-role", choices=("author", "independent"), default="author")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.audit and args.reuse_audit_run_id:
        parser.error("choose live audit or aggregate reuse")
    if args.audit_method and not args.audit:
        parser.error("--audit-method requires --audit")
    if args.audit_primary_pair and not args.audit_method:
        parser.error("--audit-primary-pair requires --audit-method")
    try:
        run_id = identity._run_id(args.run_id)
        snapshot_id = identity._run_id(args.snapshot_id)
        sync_id = identity._run_id(args.sync_id)
        output = RESULTS_ROOT / run_id
        if output.exists() or output.is_symlink() or shared.has_symlink_component(output.absolute()):
            raise ValueError("result destination unavailable")
        catalog, catalog_manifest = identity._load_catalog(snapshot_id)
        sync_manifest = identity._validate_sync(catalog, sync_id)
        specs, masters = identity._source_specs(run_id, progress=lambda region, role, stage:
            print(f"preflight={region}/{role}:{stage}", flush=True))
        results, metadata, events, role_membership, index = _source_rows(specs, masters, catalog, snapshot_id)
        rows = _metrics(catalog, results, metadata, events, role_membership)
        observations, sample_support = _audit_observations(
            results, metadata, audit_method=args.audit_method,
            primary_pair=args.audit_primary_pair)
        if args.audit_method and not observations:
            raise ValueError("targeted audit method has no sample support")
        output.mkdir(parents=True, mode=0o700)
        audit_source_run_id = None
        if args.audit:
            audit_dir = output / "audit"
            if not review_ephemeral(observations, audit_dir, adjudicator_role=args.adjudicator_role):
                raise ValueError("candidate audit cancelled")
            _add_audit_metrics(rows, audit_dir / "aggregate.json")
            audit_source_run_id = run_id
        elif args.reuse_audit_run_id:
            audit_path = _validate_reusable_audit(args.reuse_audit_run_id,
                                                  snapshot_id, sync_id, sample_support)
            _add_audit_metrics(rows, audit_path)
            audit_source_run_id = identity._run_id(args.reuse_audit_run_id)
        _write_metrics(output / "metrics.csv", rows)
        (output / "sample_support.json").write_text(
            json.dumps(sample_support, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        metadata_out = {
            "dataset": "AI Hub Domestic Travel Log 2023",
            "catalog_snapshot_id": snapshot_id,
            "catalog_sha256": catalog_manifest["catalog_sha256"],
            "sync_snapshot_id": sync_id,
            "sync_sha256": sync_manifest["sync_sha256"],
            "code_revision": shared._git_revision(),
            "code_worktree_dirty": shared._git_dirty(),
            "scenarios": {key: sorted(value) for key, value in scenarios.SCENARIOS.items()},
            "unit": "deduplicated (region, POI_ID) observed item; TL/VL duplicates counted once",
            "stage1": "existing unique normalized-name plus address-string rule; only automatic MATCHED status",
            "stage2": "collision-preserving NFKC/case/whitespace/punctuation name and full-address candidate keys; review only",
            "stage3": "character-trigram block and string similarity; review only, no auto-match threshold",
            "stage4_coordinates": "disabled; CRS, field meaning, ranges, and same-place distances not validated",
            "stage5_type": "source classification and KTO contentTypeId shown as support only; no validated crosswalk",
            "administrative_area": "no matching filter; SGG_CD to lDongSignguCd crosswalk unvalidated",
            "catalog_area_semantics": "KTO lDongRegnCd is analysis grouping only, not request geography",
            "sample": {"seed": SAMPLE_SEED, "maximum_per_region_stratum": SAMPLE_PER_REGION_STRATUM,
                       "partition": "alternating hash-ranked sample into development/validation",
                       "sample_size": len(observations), "source_ids_persisted": False,
                       "pair_fields_persisted": False, "per_row_labels_persisted": False},
            "audit_method_filter": args.audit_method,
            "audit_primary_pair_only": args.audit_primary_pair,
            "audit_source_run_id": audit_source_run_id,
            "catalog_name_collision_counts": index.collision_counts(),
            "positive_semantics": "observed visits are positives; unobserved items unknown; unmatched not catalog absence",
            "request_time_candidate_coverage": "unestimable_without_request_area_contract_and_validated_crosswalk",
            "completed_utc": datetime.now(UTC).isoformat(timespec="seconds"),
            "privacy": "only aggregate bands/sample support persisted; no names, addresses, IDs, coordinates, or row labels",
        }
        (output / "run_metadata.json").write_text(
            json.dumps(metadata_out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"enhanced_identity_complete=true; source_item_count={_bucket(len(results))}; "
              f"metrics={len(rows)}; sample_size={len(observations)}; raw_values_emitted=false", flush=True)
        return 0
    except (KeyboardInterrupt, Exception):
        print("[stopped] enhanced identity run failed safely; no row-level output", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
