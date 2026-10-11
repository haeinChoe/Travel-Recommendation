"""Evaluate a region-scoped popularity baseline on travel-log TL/VL inputs.

Raw identifiers are used only in memory. Public artifacts contain aggregate
metrics and safe run metadata, never recommendations or row-level records.
"""

from __future__ import annotations

import argparse
import codecs
import csv
import hashlib
import hmac
import json
import math
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parents[2]
RESULTS_ROOT = REPO_ROOT / "results" / "experiments" / "popularity-baseline"
RAW_ROOT = REPO_ROOT / "data" / "raw"
REGIONS = ("capital", "west", "east", "jeju-islands")
TABLES = {"TN_TRAVEL": "travel", "TN_VISIT_AREA_INFO": "visits"}
DEFAULT_K = (5, 10, 20)
MIN_CELL = 10
TIE_KEY = b"travel-recommendation-popularity-tie-v1"
ARTIFACTS = ("metrics.csv", "run_metadata.json")


@dataclass(frozen=True)
class InputSpec:
    region: str
    role: str
    root: Path


@dataclass(frozen=True)
class Event:
    region: str
    user_id: str
    trip_id: str
    item_id: str

    @property
    def trip_key(self) -> tuple[str, str, str]:
        return self.region, self.user_id, self.trip_id

    @property
    def item_key(self) -> tuple[str, str]:
        return self.region, self.item_id


@dataclass
class SplitSummary:
    events: list[Event]
    visit_rows: int
    missing_poi_rows: int
    unmapped_trip_rows: int
    ambiguous_trip_rows: int
    visit_trip_keys: set[tuple[str, str, str]]
    travel_ids: set[str] = field(default_factory=set)


def has_symlink_component(path: Path) -> bool:
    current = Path(path.anchor) if path.is_absolute() else Path.cwd()
    parts = path.parts[1:] if path.is_absolute() else path.parts
    for part in parts:
        if part in ("", "."):
            continue
        if part == "..":
            current = current.parent
            continue
        current /= part
        if current.is_symlink():
            return True
    return False


def within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root.resolve())
        return True
    except ValueError:
        return False


def approved_capital_filekey_root(region: str, role: str, root: Path) -> bool:
    """Recognize the approved capital export layout without exposing its local key."""
    if region != "capital" or not re.fullmatch(r"filekey-[A-Za-z0-9._-]+", root.name):
        return False
    if role == "TL":
        return root.parent.name == "extracted" and root.parent.parent.name == "2023-travel-log-capital"
    return root.parent.name == "2023-travel-log-capital"


def parse_input_spec(value: str) -> tuple[str, str, Path]:
    label, sep, raw_path = value.partition("=")
    region, colon, role = label.partition(":")
    if not sep or not colon or region not in REGIONS or role not in {"TL", "VL"} or not raw_path:
        raise argparse.ArgumentTypeError("입력 형식은 region:TL|VL=/raw/role/folder 입니다.")
    return region, role, Path(raw_path)


def csv_files(root: Path) -> list[Path]:
    found: list[Path] = []
    def traversal_error(_error: OSError) -> None:
        raise ValueError("role folder traversal failed safely")

    for current, directories, names in os.walk(root, followlinks=False, onerror=traversal_error):
        base = Path(current)
        children = [*(base / name for name in directories), *(base / name for name in names)]
        if any(path.is_symlink() for path in children):
            raise ValueError("role folder contains a symlink")
        directories.sort()
        found.extend(base / name for name in names if Path(name).suffix.casefold() == ".csv")
    return sorted(found)


def table_role(path: Path) -> str | None:
    stem = path.stem.upper()
    return next(
        (role for table, role in TABLES.items() if stem == table or stem.startswith(table + "_")),
        None,
    )


def _csv_encoding(path: Path) -> str:
    with path.open("rb") as stream:
        prefix = stream.read(4)
    if prefix.startswith(codecs.BOM_UTF8):
        return "utf-8-sig"
    if prefix.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return "utf-16"
    return "utf-8"


def _cell(row: dict[str, str | None], field: str) -> str | None:
    value = row.get(field)
    if value is None or value.strip() == "":
        return None
    return value


def _rows(
    files: Iterable[Path], required: set[str], selected: set[str]
) -> Iterable[dict[str, str | None]]:
    for path in files:
        try:
            with path.open("r", encoding=_csv_encoding(path), newline="") as stream:
                reader = csv.DictReader(stream)
                if reader.fieldnames is None:
                    raise ValueError("CSV header missing")
                normalized: dict[str, str] = {}
                for name in reader.fieldnames:
                    if name is None:
                        continue
                    key = name.strip().casefold()
                    if key in normalized:
                        raise ValueError("duplicate CSV header")
                    normalized[key] = name
                missing = {field.casefold() for field in required} - normalized.keys()
                if missing:
                    # POI_ID is intentionally optional. Other contract fields are required.
                    raise ValueError("required CSV column missing")
                fields = {field.casefold() for field in selected}
                for row in reader:
                    yield {
                        field: row.get(normalized[field.casefold()])
                        for field in fields
                        if field in normalized
                    }
        except (OSError, UnicodeError, csv.Error) as exc:
            raise ValueError("CSV input could not be read safely") from exc


def _read_travel(files: list[Path]) -> tuple[dict[str, str | None], set[str]]:
    owner_sets: dict[str, set[str]] = defaultdict(set)
    trip_values: set[str] = set()
    for row in _rows(
        files, {"TRAVEL_ID", "TRAVELER_ID"}, {"TRAVEL_ID", "TRAVELER_ID"}
    ):
        trip = _cell(row, "travel_id")
        user = _cell(row, "traveler_id")
        if trip is not None:
            trip_values.add(trip)
            if user is not None:
                owner_sets[trip].add(user)
    owners = {trip: next(iter(users)) if len(users) == 1 else None for trip, users in owner_sets.items()}
    return owners, trip_values


def _read_visits(
    region: str, files: list[Path], owners: dict[str, str | None]
) -> SplitSummary:
    events: list[Event] = []
    visit_rows = missing_poi_rows = unmapped_trip_rows = ambiguous_trip_rows = 0
    trip_keys: set[tuple[str, str, str]] = set()
    for row in _rows(files, {"TRAVEL_ID"}, {"TRAVEL_ID", "POI_ID"}):
        visit_rows += 1
        trip = _cell(row, "travel_id")
        item = _cell(row, "poi_id")
        if item is None:
            missing_poi_rows += 1
        if trip is None or trip not in owners:
            unmapped_trip_rows += 1
            continue
        user = owners[trip]
        if user is None:
            ambiguous_trip_rows += 1
            continue
        trip_key = (region, user, trip)
        trip_keys.add(trip_key)
        if item is not None:
            events.append(Event(region, user, trip, item))
    return SplitSummary(
        events, visit_rows, missing_poi_rows, unmapped_trip_rows,
        ambiguous_trip_rows, trip_keys,
    )


def _read_split(spec: InputSpec) -> SplitSummary:
    files = csv_files(spec.root)
    by_role: dict[str, list[Path]] = {name: [] for name in TABLES.values()}
    for path in files:
        role = table_role(path)
        if role:
            by_role[role].append(path)
    if not by_role["travel"]:
        raise ValueError("required travel table is missing")
    owners, travel_ids = _read_travel(by_role["travel"])
    # A missing visit table is an empty split. In particular, no POI identity is inferred.
    summary = _read_visits(spec.region, by_role["visits"], owners)
    summary.travel_ids = travel_ids
    return summary


def stable_tie_key(item: tuple[str, str]) -> bytes:
    region, item_id = item
    message = region.encode("utf-8") + b"\0" + item_id.encode("utf-8")
    return hmac.new(TIE_KEY, message, hashlib.sha256).digest()


def rank_items(
    candidates: Iterable[tuple[str, str]], counts: Counter[tuple[str, str]]
) -> list[tuple[str, str]]:
    return sorted(candidates, key=lambda item: (-counts[item], stable_tie_key(item)))


def group_positive_items(events: Iterable[Event]) -> dict[tuple[str, str, str], set[tuple[str, str]]]:
    grouped: dict[tuple[str, str, str], set[tuple[str, str]]] = defaultdict(set)
    for event in events:
        grouped[event.trip_key].add(event.item_key)
    return grouped


def ranking_metrics(
    ranked: list[tuple[str, str]], relevant: set[tuple[str, str]], k_values: tuple[int, ...]
) -> dict[tuple[str, int], float]:
    result: dict[tuple[str, int], float] = {}
    for k in k_values:
        top = ranked[:k]
        denominator = min(k, len(ranked))
        hits = [1 if item in relevant else 0 for item in top]
        precision = sum(hits) / denominator if denominator else 0.0
        recall = sum(hits) / len(relevant) if relevant else 0.0
        dcg = sum(hit / math.log2(position + 2) for position, hit in enumerate(hits))
        ideal_hits = min(len(relevant), k)
        idcg = sum(1 / math.log2(position + 2) for position in range(ideal_hits))
        ndcg = dcg / idcg if idcg else 0.0
        first = next((position + 1 for position, hit in enumerate(hits) if hit), None)
        result[("precision", k)] = precision
        result[("recall", k)] = recall
        result[("ndcg", k)] = ndcg
        result[("mrr", k)] = 1 / first if first else 0.0
    return result


def count_bucket(count: int) -> str:
    if count == 0:
        return "0"
    if count < MIN_CELL:
        return "<10"
    return "10+"


def rate_band(numerator: int, denominator: int) -> str:
    if denominator < MIN_CELL or 0 < numerator < MIN_CELL:
        return "<10/suppressed"
    if numerator == 0:
        return "0-<10%"
    ratio = numerator / denominator
    if ratio < 0.10:
        return "0-<10%"
    if ratio < 0.25:
        return "10-<25%"
    if ratio < 0.50:
        return "25-<50%"
    if ratio < 0.75:
        return "50-<75%"
    if ratio < 0.90:
        return "75-<90%"
    return "90-100%"


def _metric_row(
    model: str, scope: str, cohort: str, metric: str, k: int | None,
    value: float | str, size: int, *, unavailable: bool = False,
    support_count: int | None = None,
) -> dict[str, object]:
    if unavailable:
        public_value, status = "suppressed", "empty_cohort"
    elif size < MIN_CELL or (support_count is not None and support_count < MIN_CELL):
        public_value, status = "suppressed", "suppressed_k10"
    elif isinstance(value, float):
        public_value, status = f"{value:.6f}", "observed"
    else:
        public_value, status = value, "observed"
    return {
        "model": model,
        "scope": scope,
        "cohort": cohort,
        "metric": metric,
        "k": "" if k is None else k,
        "value": public_value,
        "cell_size": count_bucket(size),
        "status": status,
    }


def _event_metrics(
    region: str,
    scope: str,
    train: SplitSummary,
    validation: SplitSummary,
    k_values: tuple[int, ...],
    pooled_counts: Counter[tuple[str, str]] | None = None,
) -> list[dict[str, object]]:
    train_counts: Counter[tuple[str, str]] = Counter(event.item_key for event in train.events)
    candidate_by_region: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for item in train_counts:
        candidate_by_region[item[0]].add(item)
    val_by_trip = group_positive_items(validation.events)

    out: list[dict[str, object]] = []
    for model in ("region_popularity", "global_popularity_diagnostic"):
        # Items remain namespaced by dataset region in both count tables.
        # Thus pooled aggregation cannot import another region's item identity.
        counts = (
            train_counts
            if model == "region_popularity"
            else (pooled_counts if pooled_counts is not None else train_counts)
        )
        query_data: list[tuple[set[tuple[str, str]], set[tuple[str, str]], list[tuple[str, str]]]] = []
        for trip_key, positives in val_by_trip.items():
            trip_region = trip_key[0]
            candidates = candidate_by_region.get(trip_region, set())
            if not candidates:
                continue
            ranked = rank_items(candidates, counts)
            seen = positives & candidates
            cold = positives - candidates
            query_data.append((positives, seen, ranked))

        for cohort in ("all", "seen_positive", "cold_positive"):
            selected = []
            for positives, seen, ranked in query_data:
                if cohort == "all":
                    relevant = positives
                    include = True
                elif cohort == "seen_positive":
                    relevant = seen
                    include = bool(seen)
                else:
                    relevant = positives - seen
                    include = bool(relevant)
                if include:
                    selected.append((ranked, relevant))
            for metric_name in ("precision", "recall", "ndcg", "mrr"):
                for k in k_values:
                    scores = [
                        ranking_metrics(ranked, relevant, (k,))[(metric_name, k)]
                        for ranked, relevant in selected
                    ]
                    avg = sum(scores) / len(scores) if scores else 0.0
                    hit_count = sum(
                        len(set(ranked[:k]) & relevant) for ranked, relevant in selected
                    )
                    out.append(_metric_row(
                        model, scope, cohort, f"{metric_name}@{k}", k, avg,
                        len(selected), unavailable=not selected, support_count=hit_count,
                    ))
            out.append(_metric_row(
                model, scope, cohort, "evaluation_trips", None, "count",
                len(selected), unavailable=not selected,
            ))

    valid_trip_rows = len(validation.visit_trip_keys)
    candidate_trips = sum(
        bool(candidate_by_region.get(trip[0])) for trip in validation.visit_trip_keys
    )
    total_events = validation.visit_rows
    eligible_events = len(validation.events)
    seen_events = sum(event.item_key in train_counts for event in validation.events)
    cold_events = eligible_events - seen_events
    validation_items = {event.item_key for event in validation.events}
    cold_items = validation_items - set(train_counts)
    for model in ("region_popularity", "global_popularity_diagnostic"):
        for metric, numerator, denominator in (
            ("positive_coverage", seen_events, eligible_events),
            ("candidate_coverage", candidate_trips, valid_trip_rows),
            ("cold_start_item_share", len(cold_items), len(validation_items)),
            ("cold_start_event_share", cold_events, eligible_events),
            ("item_identity_coverage", eligible_events, total_events),
        ):
            out.append(_metric_row(
                model, scope, "all", metric, None,
                rate_band(numerator, denominator), denominator,
                unavailable=denominator == 0,
            ))
        for metric, count in (
            ("validation_visit_events", total_events),
            ("positive_events_with_item", eligible_events),
            ("missing_poi_events", validation.missing_poi_rows),
            ("unmapped_trip_events", validation.unmapped_trip_rows),
            ("ambiguous_trip_events", validation.ambiguous_trip_rows),
            ("candidate_items", (
                sum(len(items) for items in candidate_by_region.values())
                if scope == "aggregate"
                else len(candidate_by_region.get(region, set()))
            )),
        ):
            out.append(_metric_row(
                model, scope, "all", metric, None, "count", count,
                unavailable=False,
            ))
    return out


def _git_revision() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT,
            capture_output=True, text=True, check=True,
        )
        return result.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _git_dirty() -> bool | None:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"], cwd=REPO_ROOT,
            capture_output=True, text=True, check=True,
        )
        return bool(result.stdout.strip())
    except (OSError, subprocess.CalledProcessError):
        return None


def _write_artifacts(
    output: Path, rows: list[dict[str, object]], metadata: dict[str, object], overwrite: bool
) -> None:
    resolved = output.resolve()
    if (
        output.is_symlink() or has_symlink_component(output.absolute())
        or not within(resolved, RESULTS_ROOT.resolve()) or resolved == RESULTS_ROOT.resolve()
    ):
        raise ValueError("결과는 results/experiments/popularity-baseline/<run-id>/ 아래여야 합니다.")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", output.name):
        raise ValueError("run-id 형식을 확인하세요.")
    output.mkdir(parents=True, exist_ok=True)
    targets = [output / name for name in ARTIFACTS]
    if any(path.is_symlink() or (path.exists() and not path.is_file()) for path in targets):
        raise ValueError("결과 파일 위치가 안전하지 않습니다.")
    if not overwrite and any(path.exists() for path in targets):
        raise ValueError("기존 실행 결과가 있습니다. 새 run-id를 사용하세요.")
    stage = output / ".stage"
    if stage.exists() or stage.is_symlink():
        raise ValueError("임시 결과 경로가 이미 있습니다.")
    stage.mkdir(mode=0o700)
    try:
        with (stage / ARTIFACTS[0]).open("w", newline="", encoding="utf-8") as stream:
            fields = ("model", "scope", "cohort", "metric", "k", "value", "cell_size", "status")
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        (stage / ARTIFACTS[1]).write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        for name in ARTIFACTS:
            os.replace(stage / name, output / name)
    finally:
        for child in stage.iterdir():
            child.unlink()
        stage.rmdir()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate a privacy-safe popularity baseline on approved travel-log TL/VL inputs."
    )
    parser.add_argument("--raw-root", type=Path, default=RAW_ROOT)
    parser.add_argument("--input", action="append", required=True, type=parse_input_spec,
                        metavar="REGION:TL|VL=PATH")
    parser.add_argument("--run-id", default=datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"))
    parser.add_argument("--k", nargs="+", type=int, default=list(DEFAULT_K))
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
    if any(k <= 0 for k in args.k) or len(set(args.k)) != len(args.k):
        print("[중단] K는 중복 없는 양의 정수여야 합니다.", file=sys.stderr)
        return 2
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", args.run_id):
        print("[중단] run-id 형식을 확인하세요.", file=sys.stderr)
        return 2
    if has_symlink_component(args.raw_root) or has_symlink_component(RESULTS_ROOT.absolute()):
        print("[중단] raw/output 경로에 심볼릭 링크가 있습니다.", file=sys.stderr)
        return 2
    raw_root = Path(os.path.abspath(args.raw_root)).resolve()
    pairs = [(region, role) for region, role, _ in args.input]
    regions = sorted({region for region, _, _ in args.input})
    if len(set(pairs)) != len(pairs) or set(pairs) != {
        (region, role) for region in regions for role in ("TL", "VL")
    }:
        print("[중단] 선택 권역별 TL 및 VL 입력이 각각 한 개씩 필요합니다.", file=sys.stderr)
        return 2
    try:
        specs: list[InputSpec] = []
        roots: set[Path] = set()
        for region, role, requested in args.input:
            if has_symlink_component(requested):
                raise ValueError("입력 경로에 심볼릭 링크가 있습니다.")
            root = Path(os.path.abspath(requested)).resolve()
            if not root.is_dir() or not within(root, raw_root):
                raise ValueError("입력은 --raw-root 아래의 기존 role 폴더여야 합니다.")
            folder_matches = root.name == f"{role}_csv"
            approved_capital_layout = (
                args.allow_approved_capital_filekey_folders
                and approved_capital_filekey_root(region, role, root)
            )
            if not folder_matches and not approved_capital_layout:
                raise ValueError("입력 폴더 이름이 TL/VL role과 일치하지 않습니다.")
            if root in roots:
                raise ValueError("권역·분할 입력에 같은 폴더를 지정할 수 없습니다.")
            roots.add(root)
            specs.append(InputSpec(region, role, root))
        started = datetime.now(UTC)
        split_data = {(item.region, item.role): _read_split(item) for item in specs}
        train_by_region = {region: split_data[(region, "TL")] for region in regions}
        val_by_region = {region: split_data[(region, "VL")] for region in regions}
        overlap_counts = {
            region: len(train_by_region[region].travel_ids & val_by_region[region].travel_ids)
            for region in regions
        }
        overlapping_regions = {
            region: count for region, count in overlap_counts.items() if count > 0
        }
        if overlapping_regions:
            safe_summary = ", ".join(
                f"{region}={count_bucket(count)}"
                for region, count in sorted(overlapping_regions.items())
            )
            print(
                f"[중단] TL/VL TRAVEL_ID overlap 발견 (region=count bucket): {safe_summary}",
                file=sys.stderr,
            )
            return 2

        pooled_train_counts: Counter[tuple[str, str]] = Counter(
            event.item_key
            for region in regions
            for event in train_by_region[region].events
        )
        rows: list[dict[str, object]] = []
        for region in regions:
            rows.extend(_event_metrics(
                region, region, train_by_region[region], val_by_region[region],
                tuple(args.k), pooled_train_counts,
            ))

        # Aggregate is a micro-average over trip-level cases and event-level coverage.
        aggregate_train = SplitSummary(
            [event for region in regions for event in train_by_region[region].events],
            sum(train_by_region[r].visit_rows for r in regions),
            sum(train_by_region[r].missing_poi_rows for r in regions),
            sum(train_by_region[r].unmapped_trip_rows for r in regions),
            sum(train_by_region[r].ambiguous_trip_rows for r in regions),
            set().union(*(train_by_region[r].visit_trip_keys for r in regions)),
        )
        aggregate_val = SplitSummary(
            [event for region in regions for event in val_by_region[region].events],
            sum(val_by_region[r].visit_rows for r in regions),
            sum(val_by_region[r].missing_poi_rows for r in regions),
            sum(val_by_region[r].unmapped_trip_rows for r in regions),
            sum(val_by_region[r].ambiguous_trip_rows for r in regions),
            set().union(*(val_by_region[r].visit_trip_keys for r in regions)),
        )
        rows.extend(_event_metrics(
            "", "aggregate", aggregate_train, aggregate_val, tuple(args.k), pooled_train_counts
        ))
        for scope, count in [
            *((region, overlap_counts[region]) for region in regions),
            ("aggregate", sum(overlap_counts.values())),
        ]:
            bucket = count_bucket(count)
            rows.append({
                "model": "split_integrity",
                "scope": scope,
                "cohort": "all",
                "metric": "train_validation_trip_id_overlap",
                "k": "",
                "value": bucket,
                "cell_size": bucket,
                "status": "observed",
            })
        script_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        metadata: dict[str, object] = {
            "dataset": {"name": "AI Hub Domestic Travel Log", "version": "2023"},
            "input_roles": [{"region": region, "role": role} for region, role in sorted(pairs)],
            "code_revision": _git_revision(),
            "code_worktree_dirty": _git_dirty(),
            "script_sha256": script_hash,
            "started_utc": started.isoformat(timespec="seconds"),
            "finished_utc": datetime.now(UTC).isoformat(timespec="seconds"),
            "config": {
                "k": list(args.k),
                "seed": None,
                "regions": regions,
                "candidate_universe": "nonblank region-scoped POI_ID observed in TL",
                "user_key": "(dataset_region, TRAVELER_ID)",
                "item_key": "(dataset_region, nonblank POI_ID)",
                "evaluation_unit": "(dataset_region, TRAVELER_ID, TRAVEL_ID)",
                "split": {"TL": "train", "VL": "validation", "test_metrics": "not_generated"},
                "input_layout": (
                    "approved capital filekey folders and region role folders"
                    if args.allow_approved_capital_filekey_folders
                    else "region role folders"
                ),
                "trip_id_overlap_check": {
                    "checked_before_ranking": True,
                    "status": "passed",
                    "count_bucket_policy": "0, <10, 10+",
                    "per_region": {
                        region: count_bucket(count)
                        for region, count in sorted(overlap_counts.items())
                    },
                    "aggregate": count_bucket(sum(overlap_counts.values())),
                    "positive_overlap_policy": "fail before ranking",
                },
                "tie_break": "HMAC-SHA256 of namespaced item key; digest not serialized",
                "count_policy": "train visit events; repeated events retained",
                "positive_policy": "observed binary visit; trip metric relevance is distinct item set",
                "feedback_policy": "post-event feedback excluded",
                "missing_item_policy": "blank or absent POI_ID excluded; no fallback identity",
                "small_cell_policy": "k=10; cells under 10 suppressed; ratios coarse-banded",
                "ranking_metric_policy": "macro-average over candidate-covered trip units",
                "candidate_coverage_denominator": "all validation trip units with observed visit rows and unambiguous trip owner",
                "positive_coverage_denominator": (
                    "validation visit events with nonblank POI_ID and unambiguous trip owner"
                ),
                "cold_start_denominator": "validation events with usable POI_ID and trip owner",
                "global_diagnostic_limit": "region-scoped candidate sets make pooled and regional rankings identical by construction",
            },
            "privacy": {
                "raw_paths_written": False,
                "raw_identifiers_written": False,
                "coordinates_or_free_text_written": False,
                "row_level_outputs": False,
                "minimum_cell_size": MIN_CELL,
                "metrics": "small cells suppressed; no test metrics",
            },
            "policy": {
                "source_data_immutable": True,
                "real_data_permission": "explicit CLI confirmations required",
                "test_split": "prohibited",
                "external_transfer": False,
            },
        }
        output = RESULTS_ROOT / args.run_id
        _write_artifacts(output, rows, metadata, args.overwrite)
    except (OSError, UnicodeError, csv.Error, ValueError) as exc:
        print(f"[중단] popularity baseline 실패: {type(exc).__name__}", file=sys.stderr)
        return 2
    print(f"완료: results/experiments/popularity-baseline/{args.run_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
