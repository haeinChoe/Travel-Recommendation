"""Privacy-safe AI Hub POI source readiness for Issue #4.

This reads only approved 2023 four-region TL/VL visits/trips and Other POI
masters. It does not call TourAPI or claim TourAPI identity/eligibility coverage.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evaluate_popularity as shared
from poi_identity_contract import normalize_exact

REPO_ROOT = Path(__file__).resolve().parents[2]
RESULTS_ROOT = REPO_ROOT / "results" / "experiments" / "poi-source-readiness"
REGION_OTHER_FILEKEY = {"capital": "539782", "west": None, "east": None, "jeju-islands": None}
SKIP_DIRS = {"TS_photo", "VS_photo", "SbL", "TL_gps_data", "VL_gps_data"}
FIELDS = {"POI_ID", "POI_NM", "ROAD_NM_ADDR", "SGG_CD", "X_COORD", "Y_COORD"}


def _find_master(raw_root: Path, region: str) -> Path:
    region_root = raw_root / f"2023-travel-log-{region}"
    if not region_root.is_dir() or shared.has_symlink_component(region_root):
        raise ValueError("approved region root unavailable")
    found: list[Path] = []
    for current, dirs, files in os.walk(region_root, followlinks=False):
        here = Path(current)
        depth = len(here.relative_to(region_root).parts)
        if any((here / d).is_symlink() for d in dirs):
            raise ValueError("unsafe source directory")
        dirs[:] = [d for d in dirs if depth < 4 and d not in SKIP_DIRS]
        for name in files:
            if name.upper().startswith("TN_POI_MASTER") and name.casefold().endswith(".csv"):
                found.append(here / name)
    if len(found) != 1:
        raise ValueError("POI master role is missing or ambiguous")
    path = found[0]
    parts = path.relative_to(region_root).parts
    other_key = REGION_OTHER_FILEKEY[region]
    expected_role = f"filekey-{other_key}" in parts if other_key else "Other" in parts
    if (not expected_role or shared.has_symlink_component(path) or not path.is_file()
            or not shared.within(path.resolve(), region_root)):
        raise ValueError("POI master provenance validation failed")
    return path


def _validate_inputs(args: argparse.Namespace, progress=None) -> tuple[list[shared.InputSpec], dict[str, Path]]:
    if not (args.confirm_approved and args.confirm_terms and args.confirm_poi_candidate):
        raise ValueError("approval and source semantics must be confirmed")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", args.run_id):
        raise ValueError("invalid run ID")
    if shared.has_symlink_component(args.raw_root) or shared.has_symlink_component(RESULTS_ROOT.absolute()):
        raise ValueError("unsafe input or output path")
    raw_root = args.raw_root.resolve()
    if not raw_root.is_dir():
        raise ValueError("approved raw root unavailable")
    if len(args.input) != 8 or {(region, role) for region, role, _ in args.input} != {
        (region, role) for region in shared.REGIONS for role in ("TL", "VL")
    }:
        raise ValueError("exact four-region TL/VL role bindings required")
    specs: list[shared.InputSpec] = []
    seen: set[Path] = set()
    for region, role, requested in args.input:
        if shared.has_symlink_component(requested):
            raise ValueError("unsafe role path")
        root = requested.resolve()
        layout = root.name == f"{role}_csv" or (
            args.allow_approved_capital_filekey_folders
            and shared.approved_capital_filekey_root(region, role, root)
        )
        if (not root.is_dir() or not shared.within(root, raw_root) or not layout
                or f"2023-travel-log-{region}" not in root.parts or root in seen):
            raise ValueError("role binding conflicts with approved provenance or layout")
        _validate_role_tables(root)
        if progress is not None:
            progress(region, role, "role_provenance_validated")
        seen.add(root)
        specs.append(shared.InputSpec(region, role, root))
    masters = {}
    for region in shared.REGIONS:
        masters[region] = _find_master(raw_root, region)
        if progress is not None:
            progress(region, "Other", "master_provenance_validated")
    return specs, masters


def _validate_role_tables(root: Path) -> None:
    """Reject absent or incompatible visit/trip tables before row reads."""
    files = shared.csv_files(root)
    by_role = {name: [path for path in files if shared.table_role(path) == name]
               for name in ("travel", "visits")}
    for role, required in (("travel", {"TRAVEL_ID", "TRAVELER_ID"}),
                           ("visits", {"TRAVEL_ID", "POI_ID"})):
        if not by_role[role]:
            raise ValueError("required role table is absent")
        for path in by_role[role]:
            with path.open("r", encoding=shared._csv_encoding(path), newline="") as stream:
                header = next(csv.reader(stream), [])
            if len({value.strip().casefold() for value in header}) != len(header) or not {
                value.casefold() for value in required
            } <= {value.strip().casefold() for value in header}:
                raise ValueError("required role table schema is incompatible")


def _bucket_row(scope: str, metric: str, numerator: int, denominator: int | None = None) -> dict[str, str]:
    return {
        "scope": scope,
        "metric": metric,
        "value": shared.count_bucket(numerator) if denominator is None else shared.rate_band(numerator, denominator),
        "support": shared.count_bucket(numerator if denominator is None else denominator),
    }


def _read_master(path: Path, observed_ids: set[str]) -> tuple[set[str], dict[str, tuple[str, str, str, str, str]], int]:
    records: dict[str, set[tuple[str, str, str, str, str]]] = defaultdict(set)
    for row in shared._rows([path], FIELDS, FIELDS):
        item = shared._cell(row, "poi_id")
        if item is None or item not in observed_ids:
            continue
        records[item].add((
            normalize_exact(shared._cell(row, "poi_nm")),
            normalize_exact(shared._cell(row, "road_nm_addr")),
            normalize_exact(shared._cell(row, "sgg_cd")),
            normalize_exact(shared._cell(row, "x_coord")),
            normalize_exact(shared._cell(row, "y_coord")),
        ))
    conflicts = sum(len(values) > 1 for values in records.values())
    # Conflicted metadata is withheld from exact matching until resolved.
    stable = {key: next(iter(values)) for key, values in records.items() if len(values) == 1}
    return set(records), stable, conflicts


def diagnose_region(region: str, tl: shared.SplitSummary, vl: shared.SplitSummary,
                    master_keys: set[str], stable: dict[str, tuple[str, str, str, str, str]],
                    conflicts: int) -> list[dict[str, str]]:
    if tl.travel_ids & vl.travel_ids:
        raise ValueError("TL/VL trip overlap")
    scope = region
    rows = [
        _bucket_row(scope, "observed_distinct_source_ids_in_master", len(master_keys)),
        _bucket_row(scope, "observed_source_id_master_coverage", len(master_keys), len({event.item_id for event in tl.events + vl.events})),
        _bucket_row(scope, "observed_master_source_id_conflict_share", conflicts, len(master_keys)),
    ]
    for name, index in (("name", 0), ("road_address", 1), ("district_code", 2)):
        rows.append(_bucket_row(scope, f"stable_master_{name}_availability", sum(bool(v[index]) for v in stable.values()), len(stable)))
    rows.append(_bucket_row(scope, "stable_master_coordinate_pair_availability",
                            sum(bool(v[3]) and bool(v[4]) for v in stable.values()), len(stable)))
    for role, split in (("TL", tl), ("VL", vl)):
        rows.extend((
            _bucket_row(scope, f"{role}_usable_positive_event_share", len(split.events), split.visit_rows),
            _bucket_row(scope, f"{role}_source_id_in_master_event_share", sum(event.item_id in master_keys for event in split.events), len(split.events)),
            _bucket_row(scope, f"{role}_source_id_with_stable_master_event_share", sum(event.item_id in stable for event in split.events), len(split.events)),
        ))
    # Same VL event denominator and trip cohort as the product-catalog study.
    tl_candidates = {event.item_id for event in tl.events}
    rows.extend((
        _bucket_row(scope, "tl_observed_proxy_candidate_count", len(tl_candidates)),
        _bucket_row(scope, "tl_observed_proxy_nonempty_vl_trip_share", len(vl.visit_trip_keys) if tl_candidates else 0, len(vl.visit_trip_keys)),
        _bucket_row(scope, "tl_observed_proxy_vl_positive_coverage", sum(event.item_id in tl_candidates for event in vl.events), len(vl.events)),
        _bucket_row(scope, "tl_observed_proxy_vl_outside_positive_share", sum(event.item_id not in tl_candidates for event in vl.events), len(vl.events)),
        _bucket_row(scope, "tl_vl_trip_overlap", 0),
    ))
    return rows


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-root", type=Path, required=True)
    parser.add_argument("--input", action="append", required=True, type=shared.parse_input_spec)
    parser.add_argument("--allow-approved-capital-filekey-folders", action="store_true")
    parser.add_argument("--confirm-approved", action="store_true")
    parser.add_argument("--confirm-terms", action="store_true")
    parser.add_argument("--confirm-poi-candidate", action="store_true")
    parser.add_argument("--run-id", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        specs, masters = _validate_inputs(args)
        by_role = {(spec.region, spec.role): spec for spec in specs}
        rows: list[dict[str, str]] = []
        for region in shared.REGIONS:
            tl = shared._read_split(by_role[(region, "TL")])
            vl = shared._read_split(by_role[(region, "VL")])
            observed_ids = {event.item_id for event in tl.events + vl.events}
            keys, stable, conflicts = _read_master(masters[region], observed_ids)
            rows.extend(diagnose_region(region, tl, vl, keys, stable, conflicts))
            print(f"{region}: source-readiness aggregation complete", flush=True)
        output = RESULTS_ROOT / args.run_id
        if (output.is_symlink() or shared.has_symlink_component(output.absolute())
                or not shared.within(output.resolve(), RESULTS_ROOT.resolve()) or output.exists()):
            raise ValueError("unsafe or existing result destination")
        output.mkdir(parents=True, mode=0o700)
        with (output / "metrics.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=("scope", "metric", "value", "support"))
            writer.writeheader()
            writer.writerows(rows)
        metadata = {
            "dataset": "AI Hub Domestic Travel Log 2023",
            "regions": list(shared.REGIONS),
            "roles": ["TL", "VL", "Other/TN_POI_MASTER"],
            "code_revision": shared._git_revision(),
            "code_worktree_dirty": shared._git_dirty(),
            "code_sha256": {
                "analyze_poi_source_readiness.py": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "evaluate_popularity.py": hashlib.sha256(Path(shared.__file__).read_bytes()).hexdigest(),
            },
            "completed_utc": datetime.now(UTC).isoformat(timespec="seconds"),
            "protocol": "TL observed source IDs vs VL observed positives; Other POI master source linkage",
            "tourapi_catalog_used": False,
            "product_candidate_coverage": "unavailable",
            "seed": None,
            "privacy": "0/<10/10+ counts and coarse rates; no paths, IDs, rows, coordinates, free text, or candidate lists",
        }
        (output / "run_metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    except Exception:  # noqa: BLE001 - exception messages can contain private input details
        print("[stopped] source, split, or output validation failed safely", file=sys.stderr)
        return 2
    print(f"Completed privacy-safe four-region source readiness: run-id={args.run_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
