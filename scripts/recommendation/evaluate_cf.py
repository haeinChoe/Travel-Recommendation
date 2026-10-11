"""Evaluate binary implicit User-CF or Item-CF on approved travel-log TL/VL inputs.

Input identifiers are held in memory only. Artifacts contain aggregate metrics
and safe run metadata; they never contain paths, recommendations, or row data.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import hmac
import json
import math
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable

import evaluate_popularity as shared

RESULTS_ROOT = shared.REPO_ROOT / "results" / "experiments" / "cf-baseline"
MIN_CELL = shared.MIN_CELL
USER_TIE_KEY = b"travel-recommendation-cf-user-tie-v1"
COHORTS = ("all", "seen_positive", "cold_positive", "user_history")


def _cosine(common: int, left_size: int, right_size: int) -> float:
    if not common or not left_size or not right_size:
        return 0.0
    return common / math.sqrt(left_size * right_size)


def _user_key(user: tuple[str, str]) -> bytes:
    region, user_id = user
    message = region.encode() + b"\0" + user_id.encode()
    return hmac.new(USER_TIE_KEY, message, hashlib.sha256).digest()


def _pair_counts(groups: dict[object, set[object]]) -> Counter[tuple[object, object]]:
    counts: Counter[tuple[object, object]] = Counter()
    for members in groups.values():
        ordered = sorted(members)
        for index, left in enumerate(ordered):
            for right in ordered[index + 1:]:
                counts[(left, right)] += 1
    return counts


def _neighbors(
    entities: set[object], norms: dict[object, int],
    pair_counts: Counter[tuple[object, object]], limit: int,
    tie_key,
) -> dict[object, list[tuple[object, float]]]:
    adjacency: dict[object, list[tuple[object, float]]] = {entity: [] for entity in entities}
    for (left, right), common in pair_counts.items():
        sim = _cosine(common, norms[left], norms[right])
        if sim > 0:
            adjacency[left].append((right, sim))
            adjacency[right].append((left, sim))
    return {
        entity: sorted(values, key=lambda pair: (-pair[1], tie_key(pair[0])))[:limit]
        for entity, values in adjacency.items()
    }


def build_user_model(train_events: Iterable[shared.Event], neighbors: int):
    """Return binary user histories and TL-only cosine top-N neighbors."""
    histories: dict[tuple[str, str], set[tuple[str, str]]] = defaultdict(set)
    users_by_item: dict[tuple[str, str], set[tuple[str, str]]] = defaultdict(set)
    for event in train_events:
        user = (event.region, event.user_id)
        item = event.item_key
        histories[user].add(item)
        users_by_item[item].add(user)
    pairs = _pair_counts(users_by_item)
    adjacency = _neighbors(
        set(histories), {user: len(items) for user, items in histories.items()},
        pairs, neighbors, _user_key,
    )
    return dict(histories), adjacency


def build_item_model(train_events: Iterable[shared.Event], top_n: int):
    """Return binary item vectors and TL-only cosine top-N similar items."""
    histories: dict[tuple[str, str], set[tuple[str, str]]] = defaultdict(set)
    users_by_item: dict[tuple[str, str], set[tuple[str, str]]] = defaultdict(set)
    items_by_user: dict[tuple[str, str], set[tuple[str, str]]] = defaultdict(set)
    for event in train_events:
        user = (event.region, event.user_id)
        item = event.item_key
        histories[user].add(item)
        users_by_item[item].add(user)
        items_by_user[user].add(item)
    pairs = _pair_counts(items_by_user)
    adjacency = _neighbors(
        set(users_by_item), {item: len(users) for item, users in users_by_item.items()},
        pairs, top_n, shared.stable_tie_key,
    )
    return dict(histories), adjacency


def user_scores(user, histories, adjacency) -> Counter:
    scores: Counter = Counter()
    # The target user is never a neighbor. Only positive-cosine TL neighbors count.
    for neighbor, similarity in adjacency.get(user, ()):
        if neighbor == user:
            continue
        for item in histories[neighbor]:
            scores[item] += similarity
    return scores


def item_scores(user, histories, adjacency) -> Counter:
    scores: Counter = Counter()
    for source_item in sorted(histories.get(user, ()), key=shared.stable_tie_key):
        for candidate, similarity in adjacency.get(source_item, ()):
            if candidate != source_item:
                scores[candidate] += similarity
    return scores


def rank_cf(candidates: set[tuple[str, str]], scores: Counter) -> list[tuple[str, str]]:
    # Keep the complete TL universe so top-K denominators match popularity.
    # A zero-score ordering is only the deterministic evaluation tie policy;
    # recommendation_coverage separately records whether CF had positive signal.
    return sorted(
        candidates,
        key=lambda item: (-scores.get(item, 0), shared.stable_tie_key(item)),
    )


def _metric_rows(
    model, scope, train, validation, k_values, rankings, history_users,
    recommendation_signal=None,
):
    train_items = {event.item_key for event in train.events}
    candidates_by_region: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for item in train_items:
        candidates_by_region[item[0]].add(item)
    val_by_trip = shared.group_positive_items(validation.events)
    query_data = []
    for trip, positives in val_by_trip.items():
        candidates = candidates_by_region.get(trip[0], set())
        if candidates:
            query_data.append((
                trip,
                positives,
                positives & candidates,
                rankings.get(trip, []),
                trip[:2] in history_users,
            ))

    out = []
    for cohort in COHORTS:
        selected = []
        for _trip, positives, seen, ranked, has_history in query_data:
            include = (
                cohort == "all"
                or (cohort == "seen_positive" and bool(seen))
                or (cohort == "cold_positive" and bool(positives - seen))
                or (cohort == "user_history" and has_history)
            )
            if include:
                if cohort in ("all", "user_history"):
                    relevant = positives
                elif cohort == "seen_positive":
                    relevant = seen
                else:
                    relevant = positives - seen
                selected.append((ranked, relevant))
        for metric in ("precision", "recall", "ndcg", "mrr"):
            for k in k_values:
                values = [
                    shared.ranking_metrics(ranked, relevant, (k,))[(metric, k)]
                    for ranked, relevant in selected
                ]
                hits = sum(len(set(ranked[:k]) & relevant) for ranked, relevant in selected)
                out.append(shared._metric_row(
                    model, scope, cohort, f"{metric}@{k}", k,
                    sum(values) / len(values) if values else 0.0, len(selected),
                    unavailable=not selected, support_count=hits,
                ))
        out.append(shared._metric_row(
            model, scope, cohort, "evaluation_trips", None, "count", len(selected),
            unavailable=not selected,
        ))

    total_trips = len(validation.visit_trip_keys)
    usable_trips = len(query_data)
    candidate_covered_trip_rows = sum(
        bool(candidates_by_region.get(trip[0])) for trip in validation.visit_trip_keys
    )
    recommendable = sum(
        bool(ranked) if recommendation_signal is None else recommendation_signal.get(trip, False)
        for trip, _positives, _seen, ranked, _has_history in query_data
    )
    validation_users = {(event.region, event.user_id) for event in validation.events}
    history_count = sum(user in history_users for user in validation_users)
    train_trip_users = {(r, user) for r, user, _trip in train.visit_trip_keys}
    usable_train_users = len(set(history_users) & train_trip_users)
    seen_events = sum(event.item_key in train_items for event in validation.events)
    usable_events = len(validation.events)
    valid_items = {event.item_key for event in validation.events}
    cold_items = valid_items - train_items
    cold_events = usable_events - seen_events
    for metric, numerator, denominator in (
        ("positive_coverage", seen_events, usable_events),
        ("candidate_coverage", candidate_covered_trip_rows, total_trips),
        ("evaluation_trip_coverage", usable_trips, total_trips),
        ("recommendation_coverage", recommendable, usable_trips),
        ("user_history_coverage", history_count, len(validation_users)),
        ("user_cold_start_share", len(validation_users) - history_count, len(validation_users)),
        ("train_user_history_coverage", usable_train_users, len(train_trip_users)),
        ("cold_start_item_share", len(cold_items), len(valid_items)),
        ("cold_start_event_share", cold_events, usable_events),
        ("item_identity_coverage", usable_events, validation.visit_rows),
    ):
        out.append(shared._metric_row(
            model, scope, "all", metric, None, shared.rate_band(numerator, denominator), denominator,
            unavailable=denominator == 0,
        ))
    train_trip_user_count = len(train_trip_users)
    train_catalogue_count = len({event.item_key for event in train.events})
    counts = (
        ("validation_visit_events", validation.visit_rows, validation.visit_rows),
        ("positive_events_with_item", usable_events, usable_events),
        ("missing_poi_events", validation.missing_poi_rows, validation.visit_rows),
        ("unmapped_trip_events", validation.unmapped_trip_rows, validation.visit_rows),
        ("ambiguous_trip_events", validation.ambiguous_trip_rows, validation.visit_rows),
        ("train_users_with_history", usable_train_users, usable_train_users),
        ("train_user_distinct_item_count_band", _band_distribution(train.events, by="user"), train_trip_user_count),
        ("train_item_distinct_user_count_band", _band_distribution(train.events, by="item"), train_catalogue_count),
        ("candidate_items", len(candidates_by_region.get(scope, set())) if scope != "aggregate" else len(train_items), len(train_items)),
    )
    for metric, value, support in counts:
        out.append(shared._metric_row(model, scope, "all", metric, None, "count" if isinstance(value, int) else value, support))
    return out


def _band_distribution(events, by):
    groups = defaultdict(set)
    for event in events:
        key = (event.region, event.user_id) if by == "user" else event.item_key
        value = event.item_key if by == "user" else (event.region, event.user_id)
        groups[key].add(value)
    bands = Counter(shared.count_bucket(len(values)) for values in groups.values())
    return ";".join(f"{band}:{shared.count_bucket(count)}" for band, count in sorted(bands.items())) or "0"


def _git_revision():
    return shared._git_revision()


def _git_dirty():
    return shared._git_dirty()


def _write_artifacts(output: Path, rows, metadata, overwrite):
    resolved = output.resolve()
    unsafe_path = (
        output.is_symlink()
        or shared.has_symlink_component(output.absolute())
        or not shared.within(resolved, RESULTS_ROOT.resolve())
        or resolved == RESULTS_ROOT.resolve()
    )
    if unsafe_path:
        raise ValueError("unsafe output location")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", output.name):
        raise ValueError("invalid run id")
    output.mkdir(parents=True, exist_ok=True)
    targets = [output / "metrics.csv", output / "run_metadata.json"]
    if any(p.is_symlink() or (p.exists() and not p.is_file()) for p in targets):
        raise ValueError("unsafe output file")
    if not overwrite and any(p.exists() for p in targets):
        raise ValueError("run id already exists")
    stage = output / ".stage"
    if stage.exists() or stage.is_symlink():
        raise ValueError("unsafe staging directory")
    stage.mkdir(mode=0o700)
    try:
        with (stage / "metrics.csv").open("w", newline="", encoding="utf-8") as stream:
            fields = ("model", "scope", "cohort", "metric", "k", "value", "cell_size", "status")
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        (stage / "run_metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
        for name in ("metrics.csv", "run_metadata.json"):
            os.replace(stage / name, output / name)
    finally:
        for child in stage.iterdir():
            child.unlink()
        stage.rmdir()


def build_parser():
    parser = argparse.ArgumentParser(
        description="Evaluate TL-only binary implicit collaborative filtering on approved travel-log TL/VL inputs."
    )
    parser.add_argument("--raw-root", type=Path, default=shared.RAW_ROOT)
    parser.add_argument("--input", action="append", required=True, type=shared.parse_input_spec, metavar="REGION:TL|VL=PATH")
    parser.add_argument("--model", choices=("user-cf", "item-cf"), required=True)
    parser.add_argument("--neighbors", type=int, default=30, help="top user neighbors or top similar items per history item")
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
    if not (args.confirm_approved and args.confirm_terms and args.confirm_poi_candidate):
        print("[중단] 승인, 이용 조건, POI_ID 후보 확인 옵션이 필요합니다.", file=sys.stderr)
        return 2
    if args.neighbors <= 0 or any(k <= 0 for k in args.k) or len(set(args.k)) != len(args.k):
        print("[중단] neighbors와 K는 중복 없는 양의 정수여야 합니다.", file=sys.stderr)
        return 2
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", args.run_id):
        print("[중단] run-id 형식을 확인하세요.", file=sys.stderr)
        return 2
    if shared.has_symlink_component(args.raw_root) or shared.has_symlink_component(RESULTS_ROOT.absolute()):
        print("[중단] raw/output 경로에 심볼릭 링크가 있습니다.", file=sys.stderr)
        return 2
    raw_root = Path(os.path.abspath(args.raw_root)).resolve()
    pairs = [(region, role) for region, role, _ in args.input]
    regions = sorted({region for region, _, _ in args.input})
    if len(set(pairs)) != len(pairs) or set(pairs) != {(r, role) for r in regions for role in ("TL", "VL")}:
        print("[중단] 선택 권역별 TL 및 VL 입력이 각각 한 개씩 필요합니다.", file=sys.stderr)
        return 2
    try:
        specs = []
        seen_roots = set()
        for region, role, requested in args.input:
            if shared.has_symlink_component(requested):
                raise ValueError("symlink input")
            root = Path(os.path.abspath(requested)).resolve()
            if not root.is_dir() or not shared.within(root, raw_root):
                raise ValueError("input outside raw root")
            role_ok = root.name == f"{role}_csv" or (
                args.allow_approved_capital_filekey_folders
                and shared.approved_capital_filekey_root(region, role, root)
            )
            if not role_ok or root in seen_roots:
                raise ValueError("invalid split input")
            seen_roots.add(root)
            specs.append(shared.InputSpec(region, role, root))
        started = datetime.now(UTC)
        split = {(spec.region, spec.role): shared._read_split(spec) for spec in specs}
        train = {r: split[(r, "TL")] for r in regions}
        validation = {r: split[(r, "VL")] for r in regions}
        overlap = {r: len(train[r].travel_ids & validation[r].travel_ids) for r in regions}
        if any(overlap.values()):
            summary = ", ".join(f"{r}={shared.count_bucket(n)}" for r, n in sorted(overlap.items()) if n)
            print(f"[중단] TL/VL TRAVEL_ID overlap 발견 (region=count bucket): {summary}", file=sys.stderr)
            return 2
        rows = []
        for region in regions:
            tr, va = train[region], validation[region]
            if args.model == "user-cf":
                histories, adjacency = build_user_model(tr.events, args.neighbors)
                score_fn = lambda user: user_scores(user, histories, adjacency)
            else:
                histories, adjacency = build_item_model(tr.events, args.neighbors)
                score_fn = lambda user: item_scores(user, histories, adjacency)
            candidate_set = {event.item_key for event in tr.events}
            history_users = set(histories)
            rankings = {}
            recommendation_signal = {}
            for trip in shared.group_positive_items(va.events):
                user = trip[:2]
                scores = score_fn(user)
                rankings[trip] = rank_cf(candidate_set, scores)
                recommendation_signal[trip] = any(scores.get(item, 0) > 0 for item in candidate_set)
            rows.extend(_metric_rows(
                args.model, region, tr, va, tuple(args.k), rankings, history_users,
                recommendation_signal,
            ))
        # Aggregate retains namespaced keys and combines disjoint trip units.
        tr = shared.SplitSummary(
            [e for r in regions for e in train[r].events],
            sum(train[r].visit_rows for r in regions),
            sum(train[r].missing_poi_rows for r in regions),
            sum(train[r].unmapped_trip_rows for r in regions),
            sum(train[r].ambiguous_trip_rows for r in regions),
            set().union(*(train[r].visit_trip_keys for r in regions)),
        )
        va = shared.SplitSummary(
            [e for r in regions for e in validation[r].events],
            sum(validation[r].visit_rows for r in regions),
            sum(validation[r].missing_poi_rows for r in regions),
            sum(validation[r].unmapped_trip_rows for r in regions),
            sum(validation[r].ambiguous_trip_rows for r in regions),
            set().union(*(validation[r].visit_trip_keys for r in regions)),
        )
        if args.model == "user-cf":
            histories, adjacency = build_user_model(tr.events, args.neighbors)
            score_fn = lambda user: user_scores(user, histories, adjacency)
        else:
            histories, adjacency = build_item_model(tr.events, args.neighbors)
            score_fn = lambda user: item_scores(user, histories, adjacency)
        rankings = {}
        recommendation_signal = {}
        for trip in shared.group_positive_items(va.events):
            candidate_set = {e.item_key for e in tr.events if e.region == trip[0]}
            scores = score_fn(trip[:2])
            rankings[trip] = rank_cf(candidate_set, scores)
            recommendation_signal[trip] = any(scores.get(item, 0) > 0 for item in candidate_set)
        rows.extend(_metric_rows(
            args.model, "aggregate", tr, va, tuple(args.k), rankings, set(histories),
            recommendation_signal,
        ))
        for scope, count in [*((r, overlap[r]) for r in regions), ("aggregate", sum(overlap.values()))]:
            bucket = shared.count_bucket(count)
            rows.append({
                "model": "split_integrity", "scope": scope, "cohort": "all",
                "metric": "train_validation_trip_id_overlap", "k": "",
                "value": bucket, "cell_size": bucket, "status": "observed",
            })
        metadata = {
            "dataset":{"name":"AI Hub Domestic Travel Log","version":"2023"},
            "input_roles":[{"region":r,"role":role} for r,role in sorted(pairs)],
            "code_revision": _git_revision(), "code_worktree_dirty": _git_dirty(),
            "script_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "started_utc":started.isoformat(timespec="seconds"),"finished_utc":datetime.now(UTC).isoformat(timespec="seconds"),
            "config":{"model":args.model,"k":args.k,"top_n":args.neighbors,"seed":None,"regions":regions,
                "split":{"TL":"train","VL":"validation","test_metrics":"not_generated"},
                "user_key":"(dataset_region, TRAVELER_ID)","item_key":"(dataset_region, nonblank POI_ID)",
                "positive_policy":"binary presence from observed visit events; repeated source events retained",
                "feedback_policy":"post-event feedback fields are not read or used",
                "missing_item_policy":"blank or absent POI_ID excluded; no fallback identity",
                "similarity":"cosine from binary TL-only vectors, within region",
                "scoring":"user similarity-weighted sum; item sum of per-history-item top-N cosine similarities",
                "self_exclusion":"target user excluded from user neighbors; source item excluded from item neighbors",
                "candidate_universe":"all nonblank region-scoped POI_ID items observed in TL; same universe as popularity",
                "known_tl_item_policy":"included in recommendation candidates",
                "zero_score_candidate_policy":"all TL candidates retained in metric rankings and ordered by deterministic HMAC tie break",
                "recommendation_coverage":"validation queries with at least one positive collaborative score; distinct from full candidate ranking",
                "cold_start_policy":"no positive CF signal is reported as zero recommendation coverage; cold items outside TL candidate universe",
                "popularity_fallback":False,"tie_break":"HMAC-SHA256 of namespaced candidate key; digest not serialized",
                "evaluation_unit":"(dataset_region, TRAVELER_ID, TRAVEL_ID)","ranking_metric_policy":"macro-average over candidate-covered trip units",
                "trip_id_overlap_check":{"checked_before_ranking":True,"status":"passed","count_bucket_policy":"0, <10, 10+","per_region":{r:shared.count_bucket(n) for r,n in sorted(overlap.items())},"aggregate":shared.count_bucket(sum(overlap.values())),"positive_overlap_policy":"fail before ranking"},
                "small_cell_policy":"k=10; cells under 10 suppressed; ratios coarse-banded"},
            "privacy":{"raw_paths_written":False,"raw_identifiers_written":False,"row_level_outputs":False,"minimum_cell_size":MIN_CELL,"test_metrics":False},
        }
        metadata["safe_metric_summary"] = [
            {
                key: row[key]
                for key in ("scope", "cohort", "metric", "k", "value", "cell_size", "status")
            }
            for row in rows
            if row["model"] == args.model
            and row["scope"] == "aggregate"
            and (
                row["cohort"] in {"all", "seen_positive", "user_history"}
                and (str(row["metric"]).endswith("@10") or row["k"] == "")
            )
        ]
        _write_artifacts(RESULTS_ROOT / args.run_id, rows, metadata, args.overwrite)
    except (OSError, UnicodeError, csv.Error, ValueError) as exc:
        print(f"[중단] CF baseline 실패: {type(exc).__name__}", file=sys.stderr)
        return 2
    print(f"완료: results/experiments/cf-baseline/{args.run_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
