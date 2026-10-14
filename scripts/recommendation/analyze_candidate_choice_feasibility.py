"""Measure whether TL-only POI candidates support safe VL choice diagnostics.

This is a feasibility analysis, not a recommender. Observed visits are implicit
positives and unvisited candidates remain unlabeled. Artifacts contain only
privacy-safe aggregates and path-free run metadata.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evaluate_popularity as shared

REPO_ROOT = Path(__file__).resolve().parents[2]
RESULTS_ROOT = REPO_ROOT / "results" / "experiments" / "candidate-choice-feasibility"
ARTIFACTS = ("metrics.csv", "run_metadata.json")
SIZE_BUCKETS = ((1, 9, "1-9"), (10, 49, "10-49"), (50, 99, "50-99"),
                (100, 499, "100-499"), (500, None, "500+"))
REGION_ENV = {
    "capital": ("CAPITAL_TL", "CAPITAL_VL"),
    "west": ("WEST_TL", "WEST_VL"),
    "east": ("EAST_TL", "EAST_VL"),
    "jeju-islands": ("JEJU_TL", "JEJU_VL"),
}


def _size_bucket(size: int) -> str:
    for low, high, label in SIZE_BUCKETS:
        if size >= low and (high is None or size <= high):
            return label
    return "0"


def _density_bucket(positives: int, candidates: int) -> str:
    if candidates <= 0:
        return "not_applicable"
    density = positives / candidates
    if density == 0:
        return "0%"
    if density < 0.01:
        return "0-<1%"
    if density < 0.10:
        return "1-<10%"
    if density < 0.25:
        return "10-<25%"
    return "25%+"


def _trip_count_bucket(count: int) -> str:
    if count <= 1:
        return "1"
    if count <= 3:
        return "2-3"
    if count <= 5:
        return "4-5"
    return "6+"


def _positive_count_bucket(count: int) -> str:
    if count == 0:
        return "0"
    if count == 1:
        return "1"
    if count <= 4:
        return "2-4"
    if count <= 9:
        return "5-9"
    return "10+"


def _repeat_count_bucket(count: int) -> str:
    if count == 0:
        return "0"
    if count == 1:
        return "1"
    if count <= 4:
        return "2-4"
    return "5+"


def _safe_count(value: int) -> str:
    return shared.count_bucket(value)


def _safe_rate(numerator: int, denominator: int) -> str:
    if denominator == 0:
        return "not_applicable"
    return shared.rate_band(numerator, denominator)


def _code_fingerprints() -> dict[str, str]:
    """Fingerprint both the entry point and its modified shared loader/helper."""
    return {
        "analyze_candidate_choice_feasibility.py": hashlib.sha256(
            Path(__file__).read_bytes()
        ).hexdigest(),
        "evaluate_popularity.py": hashlib.sha256(
            Path(shared.__file__).read_bytes()
        ).hexdigest(),
    }


def _summary_row(region: str, metric: str, value: str, support: int) -> dict[str, object]:
    return {
        "scope": region,
        "metric": metric,
        "bucket": value,
        "support": _safe_count(support),
        "status": "privacy_limited" if 0 < support < shared.MIN_CELL else "observed",
    }


def _choice_set_status(candidate_count: int, positives: set[tuple[str, str]],
                       candidates: set[tuple[str, str]]) -> str:
    if not candidates:
        return "empty_candidate"
    if candidate_count < 2:
        return "insufficient_candidate_support"
    inside = positives & candidates
    outside = positives - candidates
    if inside and outside:
        return "positive_outside_candidate_universe"
    if outside and not inside:
        return "cold_start_only"
    if inside:
        return "evaluable"
    return "no_observed_positive"


def _candidate_support_status(candidate_count: int) -> str:
    if candidate_count == 0:
        return "empty_candidate"
    if candidate_count < 2:
        return "insufficient_candidate_support"
    return "rankable_candidate_support"


def _positive_coverage_status(positives: set[tuple[str, str]],
                              candidates: set[tuple[str, str]]) -> str:
    if not positives:
        return "no_usable_positive"
    inside = positives & candidates
    outside = positives - candidates
    if inside and outside:
        return "positive_outside_candidate_universe"
    if outside:
        return "cold_start_only"
    return "all_positives_in_candidate_universe"


def candidate_universe(train: shared.SplitSummary) -> set[tuple[str, str]]:
    """Build region-scoped item candidates from observed TL events only."""
    return {event.item_key for event in train.events}


def _validate_split_pair(train: shared.SplitSummary, validation: shared.SplitSummary) -> None:
    if train.travel_ids & validation.travel_ids:
        raise ValueError("TL/VL trip overlap detected; no metrics were generated")


def diagnose_region(
    region: str,
    train: shared.SplitSummary,
    validation: shared.SplitSummary,
    k_values: tuple[int, ...] = shared.DEFAULT_K,
) -> list[dict[str, object]]:
    """Return safe aggregates for one explicit region TL/VL role pair."""
    candidates = candidate_universe(train)
    train_counts: Counter[tuple[str, str]] = Counter(event.item_key for event in train.events)
    positives_by_trip = shared.group_positive_items(validation.events)
    trip_keys = sorted(validation.visit_trip_keys)
    statuses: Counter[str] = Counter()
    candidate_support_statuses: Counter[str] = Counter()
    positive_coverage_statuses: Counter[str] = Counter()
    size_support: Counter[str] = Counter()
    density_support: Counter[str] = Counter()
    candidate_covered = 0
    trips_with_positive = 0
    trip_rank_data: list[tuple[list[tuple[str, str]], set[tuple[str, str]]]] = []
    seen_rank_data: list[tuple[list[tuple[str, str]], set[tuple[str, str]]]] = []

    for trip_key in trip_keys:
        trip_candidates = {item for item in candidates if item[0] == trip_key[0]}
        positives = positives_by_trip.get(trip_key, set())
        if positives:
            trips_with_positive += 1
        status = _choice_set_status(len(trip_candidates), positives, trip_candidates)
        statuses[status] += 1
        candidate_support_statuses[_candidate_support_status(len(trip_candidates))] += 1
        positive_coverage_statuses[_positive_coverage_status(positives, trip_candidates)] += 1
        if trip_candidates:
            candidate_covered += 1
            size_support[_size_bucket(len(trip_candidates))] += 1
            inside = positives & trip_candidates
            density_support[_density_bucket(len(inside), len(trip_candidates))] += 1
            ranked = shared.rank_items(trip_candidates, train_counts) if len(trip_candidates) >= 2 else []
            if positives and len(trip_candidates) >= 2:
                trip_rank_data.append((ranked, positives))
            if inside and len(trip_candidates) >= 2:
                seen_rank_data.append((ranked, inside))

    rows = [
        _summary_row(region, "candidate_items", _safe_count(len(candidates)), len(candidates)),
        _summary_row(region, "validation_trip_units", _safe_count(len(trip_keys)), len(trip_keys)),
        _summary_row(region, "trip_candidate_coverage", _safe_rate(candidate_covered, len(trip_keys)), len(trip_keys)),
        _summary_row(region, "trips_with_usable_positive", _safe_rate(trips_with_positive, len(trip_keys)), len(trip_keys)),
        _summary_row(region, "positive_event_coverage", _safe_rate(
            sum(event.item_key in candidates for event in validation.events), len(validation.events)
        ), len(validation.events)),
        _summary_row(region, "cold_start_positive_event_share", _safe_rate(
            sum(event.item_key not in candidates for event in validation.events), len(validation.events)
        ), len(validation.events)),
        _summary_row(region, "tl_vl_trip_id_overlap", _safe_count(
            len(train.travel_ids & validation.travel_ids)
        ), len(train.travel_ids & validation.travel_ids)),
        _summary_row(region, "tl_vl_traveler_overlap", _safe_count(
            len({key[1] for key in train.visit_trip_keys} & {key[1] for key in validation.visit_trip_keys})
        ), len({key[1] for key in train.visit_trip_keys} & {key[1] for key in validation.visit_trip_keys})),
    ]
    for bucket, count in sorted(size_support.items()):
        rows.append(_summary_row(region, "candidate_size_trip_distribution", bucket, count))
    for bucket, count in sorted(density_support.items()):
        rows.append(_summary_row(region, "candidate_positive_density_trip_distribution", bucket, count))
    for status, count in sorted(statuses.items()):
        rows.append(_summary_row(region, "choice_set_status", status, count))
    for status, count in sorted(candidate_support_statuses.items()):
        rows.append(_summary_row(region, "candidate_support_status", status, count))
    for status, count in sorted(positive_coverage_statuses.items()):
        rows.append(_summary_row(region, "positive_coverage_status", status, count))

    rows.extend(_structural_diagnostics(region, "tl", train))
    rows.extend(_structural_diagnostics(region, "vl", validation))

    for cohort, data in (("all_observed_positive", trip_rank_data),
                         ("in_candidate_positive", seen_rank_data)):
        for metric in ("recall", "ndcg", "mrr"):
            for k in k_values:
                scores = [shared.ranking_metrics(ranked, relevant, (k,))[(metric, k)]
                          for ranked, relevant in data]
                hit_support = sum(len(set(ranked[:k]) & relevant) for ranked, relevant in data)
                average = sum(scores) / len(scores) if scores else 0.0
                output = shared._metric_row(
                    "region_popularity_protocol_check", region, cohort,
                    f"{metric}@{k}", k, average, len(data),
                    unavailable=not data, support_count=hit_support,
                )
                rows.append({
                    "scope": output["scope"],
                    "metric": f"{cohort}:{output['metric']}",
                    "bucket": output["value"],
                    "support": output["cell_size"],
                    "status": output["status"],
                })
    return rows


def _structural_diagnostics(
    region: str, role: str, split: shared.SplitSummary
) -> list[dict[str, object]]:
    """Summarize traveler trip counts, distinct positives, and repeated events safely."""
    all_trip_keys = split.travel_trip_keys if split.travel_trip_keys is not None else split.visit_trip_keys
    trips_per_traveler: Counter[tuple[str, str]] = Counter(
        (trip_region, user_id) for trip_region, user_id, _trip_id in all_trip_keys
    )
    positives_by_trip = shared.group_positive_items(split.events)
    events_per_trip: Counter[tuple[str, str, str]] = Counter(event.trip_key for event in split.events)
    repeats_per_trip = {
        trip_key: event_count - len(positives_by_trip.get(trip_key, set()))
        for trip_key, event_count in events_per_trip.items()
    }
    rows: list[dict[str, object]] = []
    for bucket, support in sorted(Counter(_trip_count_bucket(count) for count in trips_per_traveler.values()).items()):
        rows.append(_summary_row(region, f"{role}_distinct_trips_per_traveler_distribution", bucket, support))
    positive_counts = [len(positives_by_trip.get(key, set())) for key in all_trip_keys]
    for bucket, support in sorted(Counter(_positive_count_bucket(count) for count in positive_counts).items()):
        rows.append(_summary_row(region, f"{role}_distinct_positive_pois_per_trip_distribution", bucket, support))
    repeat_counts = [repeats_per_trip.get(key, 0) for key in all_trip_keys]
    for bucket, support in sorted(Counter(_repeat_count_bucket(count) for count in repeat_counts).items()):
        rows.append(_summary_row(region, f"{role}_repeated_visit_events_per_trip_distribution", bucket, support))
    total_repeated = sum(repeats_per_trip.values())
    rows.append(_summary_row(
        region, f"{role}_repeated_visit_event_share",
        _safe_rate(total_repeated, len(split.events)), len(split.events),
    ))
    rows.append(_summary_row(
        region, f"{role}_trips_with_repeated_visits_share",
        _safe_rate(sum(count > 0 for count in repeats_per_trip.values()), len(all_trip_keys)),
        len(all_trip_keys),
    ))
    rows.append(_summary_row(
        region, f"{role}_missing_poi_event_share",
        _safe_rate(split.missing_poi_rows, split.visit_rows), split.visit_rows,
    ))
    return rows


def _validate_inputs(args: argparse.Namespace) -> tuple[list[shared.InputSpec], list[str]]:
    if not (args.confirm_approved and args.confirm_terms and args.confirm_poi_candidate):
        raise ValueError("approval, terms, and provisional POI candidate confirmations are required")
    if any(k <= 0 for k in args.k) or len(set(args.k)) != len(args.k):
        raise ValueError("K must contain distinct positive integers")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", args.run_id):
        raise ValueError("run ID format is invalid")
    raw_arg = Path(args.raw_root)
    if shared.has_symlink_component(raw_arg) or shared.has_symlink_component(RESULTS_ROOT.absolute()):
        raise ValueError("raw or result path contains a symlink")
    raw_root = Path(os.path.abspath(raw_arg)).resolve()
    if not raw_root.is_dir():
        raise ValueError("approved raw root is unavailable")
    pairs = [(region, role) for region, role, _ in args.input]
    regions = sorted({region for region, _, _ in args.input})
    if set(regions) != set(REGION_ENV) or len(set(pairs)) != 8 or set(pairs) != {
        (region, role) for region in regions for role in ("TL", "VL")
    }:
        raise ValueError("exactly one TL and VL input is required for each of the four regions")
    if len(args.input) != 8:
        raise ValueError("duplicate region/role input")
    specs: list[shared.InputSpec] = []
    roots: set[Path] = set()
    for region, role, requested in args.input:
        if shared.has_symlink_component(requested):
            raise ValueError("input path contains a symlink")
        root = Path(os.path.abspath(requested)).resolve()
        capital_layout = args.allow_approved_capital_filekey_folders and shared.approved_capital_filekey_root(region, role, root)
        if not root.is_dir() or not shared.within(root, raw_root):
            raise ValueError("input is not an existing directory under the approved raw root")
        if root.name != f"{role}_csv" and not capital_layout:
            raise ValueError("role layout does not match its explicit TL/VL binding")
        if root in roots:
            raise ValueError("role input folders must be distinct")
        roots.add(root)
        specs.append(shared.InputSpec(region, role, root))
    return specs, regions


def _write_artifacts(output: Path, rows: list[dict[str, object]], metadata: dict[str, object], overwrite: bool) -> None:
    resolved = output.resolve()
    if (output.is_symlink() or shared.has_symlink_component(output.absolute())
            or not shared.within(resolved, RESULTS_ROOT.resolve()) or resolved == RESULTS_ROOT.resolve()):
        raise ValueError("results must stay under the ignored candidate-choice-feasibility result directory")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", output.name):
        raise ValueError("run ID format is invalid")
    output.mkdir(parents=True, exist_ok=True)
    targets = [output / name for name in ARTIFACTS]
    if any(path.is_symlink() or (path.exists() and not path.is_file()) for path in targets):
        raise ValueError("result file destination is unsafe")
    if not overwrite and any(path.exists() for path in targets):
        raise ValueError("result already exists; choose a new run ID")
    stage = output / ".stage"
    if stage.exists() or stage.is_symlink():
        raise ValueError("temporary result destination already exists")
    stage.mkdir(mode=0o700)
    try:
        with (stage / ARTIFACTS[0]).open("w", newline="", encoding="utf-8") as stream:
            fields = ("scope", "metric", "bucket", "support", "status")
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        (stage / ARTIFACTS[1]).write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        for name in ARTIFACTS:
            os.replace(stage / name, output / name)
    finally:
        for child in stage.iterdir():
            child.unlink()
        stage.rmdir()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-root", type=Path, default=shared.RAW_ROOT)
    parser.add_argument("--input", action="append", required=True, type=shared.parse_input_spec,
                        metavar="REGION:TL|VL=PATH")
    parser.add_argument("--run-id", default=datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"))
    parser.add_argument("--k", nargs="+", type=int, default=list(shared.DEFAULT_K))
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--allow-approved-capital-filekey-folders", action="store_true")
    parser.add_argument("--confirm-approved", action="store_true")
    parser.add_argument("--confirm-terms", action="store_true")
    parser.add_argument("--confirm-poi-candidate", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        specs, regions = _validate_inputs(args)
        started = datetime.now(UTC)
        # The explicit role/layout contract is validated above before the first row read.
        split_data = {(spec.region, spec.role): shared._read_split(spec) for spec in specs}
        rows: list[dict[str, object]] = []
        for region in regions:
            train = split_data[(region, "TL")]
            validation = split_data[(region, "VL")]
            _validate_split_pair(train, validation)
            rows.extend(diagnose_region(region, train, validation, tuple(args.k)))
        code_fingerprints = _code_fingerprints()
        metadata = {
            "dataset": {"name": "AI Hub Domestic Travel Log", "version": "2023"},
            "input_roles": [{"region": region, "role": role} for region, role in sorted(
                (spec.region, spec.role) for spec in specs
            )],
            "code_revision": shared._git_revision(),
            "code_worktree_dirty": shared._git_dirty(),
            "code_sha256": code_fingerprints,
            "started_utc": started.isoformat(timespec="seconds"),
            "finished_utc": datetime.now(UTC).isoformat(timespec="seconds"),
            "config": {
                "candidate_universe": "nonblank region-scoped POI_ID observed in TL only",
                "evaluation_unit": "(dataset_region, TRAVELER_ID, TRAVEL_ID)",
                "split": {"TL": "candidate construction and popularity counts", "VL": "validation only", "test_metrics": "not generated"},
                "unvisited": "unknown/unlabeled; no true negatives constructed",
                "candidate_filter": "none; post-event destination/location and inferred preference filters excluded",
                "k": list(args.k),
                "seed": None,
                "count_suppression": "0 / <10 / 10+",
                "small_metric_support": "<10 trips or retrieved positives suppressed",
                "privacy": {"raw_paths": False, "raw_ids": False, "rows": False, "coordinates": False, "free_text": False, "candidate_lists": False},
            },
        }
        _write_artifacts(RESULTS_ROOT / args.run_id, rows, metadata, args.overwrite)
    except Exception:  # noqa: BLE001 - errors may contain machine-local source paths
        # Deliberately avoid exception text: it can contain a local path or source detail.
        print("[stopped] input, split, or output validation failed safely", file=sys.stderr)
        return 2
    print(f"Completed safe aggregate diagnostics for four regions; artifacts: metrics.csv and run_metadata.json; run-id={args.run_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
