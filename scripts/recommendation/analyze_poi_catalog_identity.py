"""Privacy-safe AI Hub to current KTO listing identity feasibility for Issue #4.

All identifiers and source metadata stay in memory. This does not infer a
2023 exposure set, operational POI status, or a product type policy.
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
import analyze_poi_source_readiness as readiness
import evaluate_popularity as shared
from poi_identity_contract import CatalogPoi, SourcePoi, match_source_poi, normalize_exact

REPO_ROOT = Path(__file__).resolve().parents[2]
CATALOG_ROOT = REPO_ROOT / "results" / "experiments" / "poi-catalog"
SYNC_ROOT = REPO_ROOT / "results" / "experiments" / "poi-sync-state"
RESULTS_ROOT = REPO_ROOT / "results" / "experiments" / "poi-catalog-identity"
ENV_BINDINGS = (
    ("capital", "CAPITAL_TL", "CAPITAL_VL"),
    ("west", "WEST_TL", "WEST_VL"),
    ("east", "EAST_TL", "EAST_VL"),
    ("jeju-islands", "JEJU_TL", "JEJU_VL"),
)


def _run_id(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", value):
        raise ValueError("invalid run id")
    return value


def _load_catalog(snapshot_id: str) -> tuple[list[CatalogPoi], dict[str, object]]:
    root = CATALOG_ROOT / _run_id(snapshot_id)
    if shared.has_symlink_component(root.absolute()) or not root.is_dir():
        raise ValueError("catalog snapshot unavailable")
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    content = (root / "catalog.jsonl").read_bytes()
    if hashlib.sha256(content).hexdigest() != manifest.get("catalog_sha256"):
        raise ValueError("catalog digest mismatch")
    records = [json.loads(line) for line in content.decode("utf-8").splitlines()]
    ids = [str(item.get("contentid") or "") for item in records]
    if (len(records) != manifest.get("total_count") or len(set(ids)) != len(ids)
            or not all(ids) or manifest.get("first_page_recheck") != "same_total_and_content_ids"):
        raise ValueError("catalog completeness check failed")
    catalog = [CatalogPoi(
        content_id=item["contentid"], title=item.get("title"),
        road_address=item.get("addr1"), area_code=item.get("lDongRegnCd"),
        district_code=item.get("lDongSignguCd"), content_type=item.get("contenttypeid"),
        listing_state="listed",
    ) for item in records]
    return catalog, manifest


def _validate_sync(catalog: list[CatalogPoi], sync_id: str) -> dict[str, object]:
    root = SYNC_ROOT / _run_id(sync_id)
    if shared.has_symlink_component(root.absolute()) or not root.is_dir():
        raise ValueError("sync-state snapshot unavailable")
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    content = (root / "sync_state.jsonl").read_bytes()
    if hashlib.sha256(content).hexdigest() != manifest.get("sync_sha256"):
        raise ValueError("sync-state digest mismatch")
    shown: set[str] = set()
    hidden: set[str] = set()
    for line in content.decode("utf-8").splitlines():
        row = json.loads(line)
        if row.get("showflag") == "1":
            shown.add(row["contentid"])
        elif row.get("showflag") == "0":
            hidden.add(row["contentid"])
        else:
            raise ValueError("unknown sync display state")
    if (len(shown) != manifest.get("shown_count")
            or len(hidden) != manifest.get("hidden_count")
            or shown & hidden
            or shown != {item.content_id for item in catalog}):
        raise ValueError("listing and display-state snapshots disagree")
    return manifest


def _source_specs(run_id: str, progress=None) -> tuple[list[shared.InputSpec], dict[str, Path]]:
    names = ("RAW_ROOT", *(name for _, tl, vl in ENV_BINDINGS for name in (tl, vl)))
    if not all(os.environ.get(name) for name in names):
        raise ValueError("required role binding unavailable")
    inputs = []
    for region, tl, vl in ENV_BINDINGS:
        inputs.extend((shared.parse_input_spec(region + ":TL=" + os.environ[tl]),
                       shared.parse_input_spec(region + ":VL=" + os.environ[vl])))
    args = argparse.Namespace(
        raw_root=Path(os.environ["RAW_ROOT"]), input=inputs,
        allow_approved_capital_filekey_folders=True,
        confirm_approved=True, confirm_terms=True, confirm_poi_candidate=True,
        run_id=run_id,
    )
    return readiness._validate_inputs(args, progress=progress)


def _metric(scope: str, split: str, unit: str, name: str,
            numerator: int, denominator: int | None = None) -> dict[str, str]:
    return {"scope": scope, "split": split, "unit": unit, "metric": name,
            "value": shared.count_bucket(numerator) if denominator is None
            else shared.rate_band(numerator, denominator),
            "support": shared.count_bucket(numerator if denominator is None else denominator)}


def diagnose(catalog: list[CatalogPoi], specs: list[shared.InputSpec],
             masters: dict[str, Path], snapshot_id: str) -> list[dict[str, str]]:
    by_name: dict[str, list[CatalogPoi]] = defaultdict(list)
    for item in catalog:
        by_name[normalize_exact(item.title)].append(item)
    by_role = {(spec.region, spec.role): spec for spec in specs}
    output: list[dict[str, str]] = []
    for region in shared.REGIONS:
        tl = shared._read_split(by_role[(region, "TL")])
        vl = shared._read_split(by_role[(region, "VL")])
        if tl.travel_ids & vl.travel_ids:
            raise ValueError("TL/VL trip overlap")
        source_ids = {event.item_id for event in tl.events + vl.events}
        master_keys, stable, _ = readiness._read_master(masters[region], source_ids)
        status: dict[str, tuple[str, str]] = {}
        for source_id in source_ids:
            if source_id in master_keys and source_id not in stable:
                status[source_id] = ("AMBIGUOUS", "conflicting_source_metadata")
            elif source_id not in stable:
                status[source_id] = ("UNMATCHED", "missing_master_metadata")
            else:
                name, address, *_ = stable[source_id]
                source = SourcePoi(region, source_id, name, address)
                result = match_source_poi(
                    source, by_name.get(normalize_exact(name), []),
                    snapshot_version=snapshot_id,
                )
                status[source_id] = (result.status, result.method)
        for role, split in (("TL", tl), ("VL", vl)):
            distinct = {event.item_id for event in split.events}
            for unit, members in (("source_items", distinct),
                                  ("positive_events", [event.item_id for event in split.events])):
                size = len(members)
                output.append(_metric(region, role, unit, "denominator", size))
                for category in ("MATCHED", "AMBIGUOUS", "UNMATCHED"):
                    output.append(_metric(region, role, unit, "identity_" + category.lower() + "_share",
                                          sum(status[item][0] == category for item in members), size))
                methods = Counter(status[item][1] for item in members)
                for method, amount in sorted(methods.items()):
                    output.append(_metric(region, role, unit, "method_" + method + "_share",
                                          amount, size))
        tl_ids = {event.item_id for event in tl.events}
        vl_size = len(vl.events)
        output.extend((
            _metric(region, "VL", "positive_events", "tl_proxy_inside_share",
                    sum(event.item_id in tl_ids for event in vl.events), vl_size),
            _metric(region, "VL", "positive_events", "tl_proxy_outside_cold_start_share",
                    sum(event.item_id not in tl_ids for event in vl.events), vl_size),
            _metric(region, "VL", "positive_events", "catalog_exact_linked_share",
                    sum(status[event.item_id][0] == "MATCHED" for event in vl.events), vl_size),
            _metric(region, "VL", "positive_events", "catalog_exact_linked_tl_cold_start_share",
                    sum(event.item_id not in tl_ids and status[event.item_id][0] == "MATCHED"
                        for event in vl.events), vl_size),
            _metric(region, "VL", "trip_units", "tl_proxy_nonempty_share",
                    len(vl.visit_trip_keys) if tl_ids else 0, len(vl.visit_trip_keys)),
            _metric(region, "VL", "trip_units", "tl_proxy_candidate_count", len(tl_ids)),
            _metric(region, "TL_VL", "trip_ids", "overlap", 0),
        ))
        print(region + ": identity aggregation complete", flush=True)
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-id", required=True)
    parser.add_argument("--sync-id", required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args(argv)
    try:
        run_id = _run_id(args.run_id)
        snapshot_id = _run_id(args.snapshot_id)
        sync_id = _run_id(args.sync_id)
        output = RESULTS_ROOT / run_id
        if output.exists() or output.is_symlink() or shared.has_symlink_component(output.absolute()):
            raise ValueError("result destination unavailable")
        catalog, manifest = _load_catalog(snapshot_id)
        sync_manifest = _validate_sync(catalog, sync_id)
        specs, masters = _source_specs(run_id)
        rows = diagnose(catalog, specs, masters, snapshot_id)
        output.mkdir(parents=True, mode=0o700)
        with (output / "metrics.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=("scope", "split", "unit", "metric", "value", "support"))
            writer.writeheader()
            writer.writerows(rows)
        metadata = {
            "dataset": "AI Hub Domestic Travel Log 2023",
            "regions": list(shared.REGIONS),
            "roles": ["TL", "VL", "Other/TN_POI_MASTER"],
            "catalog_snapshot_id": snapshot_id,
            "catalog_sha256": manifest["catalog_sha256"],
            "catalog_records": manifest["total_count"],
            "sync_snapshot_id": sync_id,
            "sync_sha256": sync_manifest["sync_sha256"],
            "display_state_provenance": "official_showflag_1_equals_public_listing",
            "code_revision": shared._git_revision(),
            "code_worktree_dirty": shared._git_dirty(),
            "code_sha256": {
                name: hashlib.sha256(path.read_bytes()).hexdigest()
                for name, path in (
                    ("analyze_poi_catalog_identity.py", Path(__file__)),
                    ("analyze_poi_source_readiness.py", Path(readiness.__file__)),
                    ("poi_identity_contract.py", REPO_ROOT / "scripts" / "recommendation" / "poi_identity_contract.py"),
                    ("evaluate_popularity.py", Path(shared.__file__)),
                )
            },
            "completed_utc": datetime.now(UTC).isoformat(timespec="seconds"),
            "protocol": "global exact normalized title plus address string; unreviewed precision",
            "candidate_status": "unresolved_no_request_context_type_policy_or_operational_state",
            "catalog_listing_time_not_2023_exposure": True,
            "negative_semantics": "unvisited_unknown_unlabeled",
            "seed": None,
            "privacy": "coarse counts/rates; no raw paths, source IDs, records, coordinates, or free text",
        }
        (output / "run_metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception:  # Exception text could contain private source or credential details.
        print("[stopped] catalog, source, split, or output validation failed safely", file=sys.stderr)
        return 2
    print("Completed privacy-safe four-region catalog identity: run-id=" + run_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
