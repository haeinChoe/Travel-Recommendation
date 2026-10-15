"""Private alternate-screen review of the existing Issue #4 matched-pair sample.

Pair evidence and individual decisions exist in process memory only. This
module never sends data over a network or writes a row-level review artifact.
Run it only in a private terminal without session recording.
"""

from __future__ import annotations

import argparse
import csv
import curses
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
import signal
import sys
import tempfile
import termios
import threading
import time
import tty
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import analyze_poi_catalog_identity as identity
import analyze_poi_catalog_scenarios as scenarios
import analyze_poi_source_readiness as readiness
import evaluate_popularity as shared
from poi_identity_contract import SourcePoi, match_source_poi, normalize_exact

LABELS = ("MATCH", "NO_MATCH", "UNCERTAIN")
RESULTS_ROOT = identity.REPO_ROOT / "results" / "experiments" / "poi-match-audit"
EXPECTED_SAMPLE_SIZE = 160
LOAD_TIMEOUT_SECONDS = 900


@dataclass(frozen=True)
class ReviewPair:
    # No source or catalog identifier, coordinate, or row label is retained.
    source_name: str
    source_address: str
    source_type: str
    catalog_name: str
    catalog_address: str
    catalog_type: str
    method: str


def _master_evidence(master_path: Path, observed_ids: set[str],
                     deadline: float | None = None,
                     progress: Callable[[int | None], None] | None = None) -> tuple[
        set[str], dict[str, tuple[str, str, str, str, str]], dict[str, str]]:
    """Match readiness._read_master semantics, plus optional type, in one scan."""
    records: dict[str, set[tuple[str, str, str, str, str]]] = defaultdict(set)
    values: dict[str, set[tuple[str, str, str]]] = defaultdict(set)
    try:
        if progress is not None:
            progress(None)
        with master_path.open("r", encoding=shared._csv_encoding(master_path), newline="") as stream:
            reader = csv.reader(stream)
            header = next(reader, None)
            if header is None:
                raise ValueError("CSV header missing")
            columns: dict[str, int] = {}
            for index, field in enumerate(header):
                key = field.strip().casefold()
                if key in columns:
                    raise ValueError("duplicate CSV header")
                columns[key] = index
            missing = {field.casefold() for field in readiness.FIELDS} - columns.keys()
            if missing:
                raise ValueError("required CSV column missing")

            def cell(row: list[str], field: str) -> str | None:
                index = columns.get(field.casefold())
                value = row[index] if index is not None and index < len(row) else None
                return value if value is not None and value.strip() else None

            for row_number, row in enumerate(reader, 1):
                if deadline is not None and row_number % 5000 == 0 and time.monotonic() > deadline:
                    raise TimeoutError("bounded sample loading timeout")
                if progress is not None and row_number % 100_000 == 0:
                    progress(row_number)
                source_id = cell(row, "poi_id")
                if source_id not in observed_ids:
                    continue
                records[source_id].add(tuple(
                    normalize_exact(cell(row, field))
                    for field in ("poi_nm", "road_nm_addr", "sgg_cd", "x_coord", "y_coord")
                ))
                values[source_id].add(tuple(cell(row, field) or ""
                                            for field in ("asort_lclasdc", "asort_mlsfcdc", "asort_sdasdc")))
    except (OSError, UnicodeError, csv.Error) as exc:
        raise ValueError("POI master scan failed safely") from exc
    stable = {key: next(iter(items)) for key, items in records.items() if len(items) == 1}
    categories: dict[str, str] = {}
    for source_id in observed_ids:
        variants = values.get(source_id, set())
        if len(variants) == 1:
            categories[source_id] = " / ".join(
                f"L{position}={value}" for position, value in enumerate(next(iter(variants)), 1)
                if value) or "[not supplied]"
        elif len(variants) > 1:
            categories[source_id] = "[conflicting category codes]"
        else:
            categories[source_id] = "[not supplied]"
    return set(records), stable, categories


def _audit_split_ids(spec: shared.InputSpec, progress: Callable[[str, int | None], None],
                     deadline: float | None = None) -> tuple[set[str], set[str]]:
    """Read travel and visit CSVs once, keeping only IDs needed by the audit."""
    files = shared.csv_files(spec.root)
    by_role: dict[str, list[Path]] = {name: [] for name in shared.TABLES.values()}
    for path in files:
        role = shared.table_role(path)
        if role:
            by_role[role].append(path)
    if not by_role["travel"]:
        raise ValueError("required travel table is missing")
    owners_by_trip: dict[str, set[str]] = defaultdict(set)
    travel_ids: set[str] = set()

    def open_rows(path: Path, required: set[str]):
        stream = path.open("r", encoding=shared._csv_encoding(path), newline="")
        reader = csv.reader(stream)
        header = next(reader, None)
        if header is None:
            stream.close()
            raise ValueError("CSV header missing")
        columns: dict[str, int] = {}
        for index, field in enumerate(header):
            key = field.strip().casefold()
            if key in columns:
                stream.close()
                raise ValueError("duplicate CSV header")
            columns[key] = index
        missing = required - columns.keys()
        if missing:
            stream.close()
            raise ValueError("required CSV column missing")
        return stream, columns, reader

    def value(row: list[str], columns: dict[str, int], field: str) -> str | None:
        index = columns.get(field.casefold())
        cell = row[index] if index is not None and index < len(row) else ""
        return cell if cell and cell.strip() else None

    try:
        progress("travel_scan_started", None)
        for path in by_role["travel"]:
            stream, header, reader = open_rows(path, {"travel_id", "traveler_id"})
            with stream:
                for row_number, row in enumerate(reader, 1):
                    if row_number % 5000 == 0 and deadline is not None and time.monotonic() > deadline:
                        raise TimeoutError("bounded sample loading timeout")
                    if row_number % 100_000 == 0:
                        progress("travel_rows_scanned", row_number)
                    trip = value(row, header, "travel_id")
                    traveler = value(row, header, "traveler_id")
                    if trip is not None:
                        travel_ids.add(trip)
                        if traveler is not None:
                            owners_by_trip[trip].add(traveler)
        owners = {trip: next(iter(users)) if len(users) == 1 else None
                  for trip, users in owners_by_trip.items()}
        item_ids: set[str] = set()
        progress("visit_scan_started", None)
        for path in by_role["visits"]:
            stream, header, reader = open_rows(path, {"travel_id"})
            with stream:
                for row_number, row in enumerate(reader, 1):
                    if row_number % 5000 == 0 and deadline is not None and time.monotonic() > deadline:
                        raise TimeoutError("bounded sample loading timeout")
                    if row_number % 100_000 == 0:
                        progress("visit_rows_scanned", row_number)
                    trip = value(row, header, "travel_id")
                    item = value(row, header, "poi_id")
                    if trip is not None and owners.get(trip) is not None and item is not None:
                        item_ids.add(item)
    except (OSError, UnicodeError, csv.Error) as exc:
        raise ValueError("split scan failed safely") from exc
    return travel_ids, item_ids


def build_sample(catalog: list, specs: list[shared.InputSpec],
                 masters: dict[str, Path], snapshot_id: str,
                 deadline: float | None = None) -> list[ReviewPair]:
    """Rebuild the exact region × TL/VL sample, without exporting its keys."""
    by_role = {(spec.region, spec.role): spec for spec in specs}
    by_name: dict[str, list] = defaultdict(list)
    by_content_id = {item.content_id: item for item in catalog}
    for item in catalog:
        by_name[normalize_exact(item.title)].append(item)
    started = time.monotonic()
    progress_lock = threading.Lock()

    def progress(region: str, role: str, stage: str, rows: int | None = None) -> None:
        with progress_lock:
            elapsed = int(time.monotonic() - started)
            row_marker = f"; rows_scanned={rows}" if rows is not None else ""
            print(f"Load {region}/{role}: {stage}{row_marker}; elapsed_seconds={elapsed}", flush=True)

    def one_region(region: str) -> list[ReviewPair]:
        if deadline is not None and time.monotonic() > deadline:
            raise TimeoutError("bounded sample loading timeout")
        role_ids: dict[str, tuple[set[str], set[str]]] = {}
        for role in ("TL", "VL"):
            role_ids[role] = _audit_split_ids(
                by_role[(region, role)],
                lambda stage, rows, r=region, s=role: progress(r, s, stage, rows),
                deadline,
            )
            progress(region, role, "split_scanned")
        if role_ids["TL"][0] & role_ids["VL"][0]:
            raise ValueError("TL/VL trip overlap")
        source_ids = role_ids["TL"][1] | role_ids["VL"][1]
        master_keys, stable, categories = _master_evidence(
            masters[region], source_ids, deadline,
            lambda rows, r=region: progress(r, "catalog", "master_rows_scanned", rows),
        )
        progress(region, "catalog", "master_scanned")
        matched: dict[str, tuple[str, object]] = {}
        for source_id in source_ids:
            if source_id not in stable or source_id not in master_keys:
                continue
            name, address, *_ = stable[source_id]
            result = match_source_poi(SourcePoi(region, source_id, name, address),
                                      by_name.get(normalize_exact(name), []),
                                      snapshot_version=snapshot_id)
            if result.status == "MATCHED" and result.canonical_id:
                item = by_content_id.get(result.canonical_id)
                if item is not None:
                    matched[source_id] = (result.method, item)
        selected: list[str] = []
        for role in ("TL", "VL"):
            matched_ids = role_ids[role][1] & matched.keys()
            sample = scenarios.deterministic_audit_sample(matched_ids, region=region, split=role)
            if len(sample) != scenarios.AUDIT_MAX_PER_STRATUM:
                raise ValueError("approved sample stratum size changed")
            selected.extend(sample)
        pairs: list[ReviewPair] = []
        for source_id in selected:
            if source_id not in matched or source_id not in stable:
                raise ValueError("approved sample identity changed")
            method, item = matched[source_id]
            name, address, *_ = stable[source_id]
            pairs.append(ReviewPair(
                source_name=name, source_address=address,
                source_type=categories[source_id],
                catalog_name=item.title or "", catalog_address=item.road_address or "",
                catalog_type=item.content_type or "[not supplied]", method=method,
            ))
        progress(region, "sample", "sample_ready")
        return pairs

    pairs: list[ReviewPair] = []
    with ThreadPoolExecutor(max_workers=min(4, len(shared.REGIONS))) as executor:
        futures = {executor.submit(one_region, region): region for region in shared.REGIONS}
        collected: dict[str, list[ReviewPair]] = {}
        for future in as_completed(futures):
            region = futures[future]
            collected[region] = future.result()
    for region in shared.REGIONS:
        pairs.extend(collected[region])
    if len(pairs) != EXPECTED_SAMPLE_SIZE:
        raise ValueError("approved sample denominator changed")
    return pairs


def _write_ephemeral_evidence(pairs: list[ReviewPair], directory: Path) -> Path:
    """Materialize only adjudication fields in a private temporary directory."""
    if len(pairs) != EXPECTED_SAMPLE_SIZE:
        raise ValueError("approved sample denominator changed")
    os.chmod(directory, 0o700)
    path = directory / "evidence.jsonl"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            for ordinal, pair in enumerate(pairs, 1):
                json.dump({
                    "ordinal": ordinal,
                    "method": pair.method,
                    "source_name": pair.source_name,
                    "source_address": pair.source_address,
                    "source_type": pair.source_type,
                    "catalog_name": pair.catalog_name,
                    "catalog_address": pair.catalog_address,
                    "catalog_type": pair.catalog_type,
                }, stream, ensure_ascii=False, sort_keys=True)
                stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return path


def _read_ephemeral_evidence(path: Path) -> list[ReviewPair]:
    """Load the private evidence file without exposing its contents."""
    pairs: list[ReviewPair] = []
    expected = {"ordinal", "method", "source_name", "source_address", "source_type",
                "catalog_name", "catalog_address", "catalog_type"}
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            item = json.loads(line)
            if set(item) != expected or item["ordinal"] != len(pairs) + 1:
                raise ValueError("ephemeral evidence integrity check failed")
            pairs.append(ReviewPair(
                source_name=item["source_name"], source_address=item["source_address"],
                source_type=item["source_type"], catalog_name=item["catalog_name"],
                catalog_address=item["catalog_address"], catalog_type=item["catalog_type"],
                method=item["method"],
            ))
            if len(pairs) > EXPECTED_SAMPLE_SIZE:
                raise ValueError("ephemeral evidence integrity check failed")
    if len(pairs) != EXPECTED_SAMPLE_SIZE:
        raise ValueError("ephemeral evidence integrity check failed")
    return pairs


def review_ephemeral_sample(pairs: list[ReviewPair], output: Path,
                            ui: Callable[[list[ReviewPair], Callable[[str, str], None]], bool] | None = None,
                            adjudicator_role: str = "author") -> bool:
    """Review through a private evidence file and remove it on every exit path."""
    temporary_name: str | None = None
    evidence_path: Path | None = None
    try:
        with tempfile.TemporaryDirectory(prefix="issue4-poi-review-") as temporary_directory:
            temporary_name = temporary_directory
            evidence_path = _write_ephemeral_evidence(pairs, Path(temporary_directory))
            evidence_pairs = _read_ephemeral_evidence(evidence_path)
            return review_and_save(evidence_pairs, output, ui or _review_window,
                                   adjudicator_role=adjudicator_role)
    finally:
        # Cleanup is repeated explicitly so cancellation and ordinary exceptions
        # remove the file before TemporaryDirectory removes its private parent.
        if evidence_path is not None:
            evidence_path.unlink(missing_ok=True)
        if evidence_path is not None and evidence_path.exists():
            raise ValueError("temporary evidence cleanup verification failed")
        if temporary_name is not None and Path(temporary_name).exists():
            raise ValueError("temporary evidence cleanup verification failed")


def _open_private_tty() -> tuple[int, bytes, bytes, bytes]:
    """Check terminfo alternate-screen support without reading data rows."""
    fd = os.open("/dev/tty", os.O_RDWR | os.O_NOCTTY)
    try:
        if not os.isatty(fd):
            raise ValueError("private terminal unavailable")
        curses.setupterm(fd=fd)
        enter, leave, clear = (curses.tigetstr(name) for name in ("smcup", "rmcup", "clear"))
        if not enter or not leave or not clear:
            raise ValueError("terminal alternate screen unavailable")
        return fd, enter, leave, clear
    except BaseException:
        os.close(fd)
        raise


def _check_local_tty() -> None:
    fd, *_ = _open_private_tty()
    try:
        size = os.get_terminal_size(fd)
        if size.columns < 80 or size.lines < 18:
            raise ValueError("private terminal too small")
    finally:
        os.close(fd)


def _safe_text(value: str) -> str:
    """Keep source-controlled escapes/control bytes out of terminal commands."""
    return "".join(" " if unicodedata.category(char).startswith("C") else char
                   for char in value).strip() or "[not supplied]"


def _pair_screen(pair: ReviewPair, position: int, total: int, width: int) -> bytes:
    lines = [f"Private POI match audit — pair {position}/{total}",
             "Press 1 MATCH | 2 NO_MATCH | 3 UNCERTAIN | q cancel",
             "Then press SPACE to confirm this pair", "",
             "Source name: " + _safe_text(pair.source_name),
             "Source address: " + _safe_text(pair.source_address),
             "Source type codes (unmapped): " + _safe_text(pair.source_type), "",
             "Catalog name: " + _safe_text(pair.catalog_name),
             "Catalog address (generic addr1): " + _safe_text(pair.catalog_address),
             "Catalog contentTypeId: " + _safe_text(pair.catalog_type), "",
             "Method: " + _safe_text(pair.method)]
    return ("\r\n".join(line[:width] for line in lines) + "\r\n").encode("utf-8")


def _loading_timeout(_signum: int, _frame: object) -> None:
    raise TimeoutError("bounded sample loading timeout")


def _review_window(pairs: list[ReviewPair], submit: Callable[[str, str], None]) -> bool:
    """Render exactly one pair at a time to /dev/tty, not stdout/stderr."""
    fd, enter, leave, clear = _open_private_tty()
    original = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        os.write(fd, enter + b"\x1b[?25l")
        for index, pair in enumerate(pairs):
            size = os.get_terminal_size(fd)
            if size.columns < 80 or size.lines < 18:
                return False
            width = min(100, size.columns - 1)
            os.write(fd, clear + _pair_screen(pair, index + 1, len(pairs), width))
            selected: str | None = None
            while True:
                key = os.read(fd, 1)
                if key in (b"\x03", b"\x1b", b"q", b"Q", b""):
                    return False
                if selected is None and key in (b"1", b"2", b"3"):
                    selected = LABELS[int(key) - 1]
                    os.write(fd, ("\r\nSelected " + selected + "; press SPACE to confirm.\r\n").encode("ascii"))
                elif selected is not None and key == b" ":
                    submit(pair.method, selected)
                    # Ignore any queued repeat keys before drawing the next pair.
                    termios.tcflush(fd, termios.TCIFLUSH)
                    break
        return True
    finally:
        # Clear the final pair before restoring the normal host pane screen.
        try:
            os.write(fd, clear + b"\x1b[?25h" + leave)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, original)
            os.close(fd)


def review_and_save(pairs: list[ReviewPair], output: Path,
                    ui: Callable[[list[ReviewPair], Callable[[str, str], None]], bool] = _review_window,
                    adjudicator_role: str = "author",
                    ) -> bool:
    """Write only one aggregate after every pair is reviewed; never checkpoint."""
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    reviewed = 0

    def submit(method: str, label: str) -> None:
        nonlocal reviewed
        if label not in LABELS or method not in {pair.method for pair in pairs} or reviewed >= len(pairs):
            raise ValueError("invalid review decision")
        counts[method][label] += 1
        reviewed += 1

    completed = ui(pairs, submit)
    if not completed:
        return False
    if reviewed != len(pairs) or len(pairs) != EXPECTED_SAMPLE_SIZE:
        raise ValueError("incomplete review")
    if adjudicator_role not in ("author", "independent"):
        raise ValueError("invalid adjudicator role")
    if output.exists() or output.is_symlink() or shared.has_symlink_component(output.absolute()):
        raise ValueError("result destination unavailable")
    payload: dict[str, object] = {
        "reviewed_count": reviewed,
        "labels": {label: sum(group[label] for group in counts.values()) for label in LABELS},
        "by_method": {method: {"reviewed_count": sum(group.values()),
                               "labels": {label: group[label] for label in LABELS}}
                      for method, group in sorted(counts.items())},
        "adjudicator_role": adjudicator_role,
    }
    output.mkdir(parents=True, mode=0o700)
    temporary = output / ".aggregate.tmp"
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, output / "aggregate.json")
    finally:
        temporary.unlink(missing_ok=True)
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-id", required=True)
    parser.add_argument("--sync-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--adjudicator-role", choices=("author", "independent"), default="author")
    args = parser.parse_args(argv)
    try:
        run_id = identity._run_id(args.run_id)
        snapshot_id = identity._run_id(args.snapshot_id)
        sync_id = identity._run_id(args.sync_id)
        output = RESULTS_ROOT / run_id
        if output.exists() or output.is_symlink() or shared.has_symlink_component(output.absolute()):
            raise ValueError("result destination unavailable")
        _check_local_tty()
        previous_alarm = signal.signal(signal.SIGALRM, _loading_timeout)
        signal.setitimer(signal.ITIMER_REAL, LOAD_TIMEOUT_SECONDS)
        try:
            load_deadline = time.monotonic() + LOAD_TIMEOUT_SECONDS
            print("Preflight: existing snapshot validation started", flush=True)
            catalog, catalog_manifest = identity._load_catalog(snapshot_id)
            print("Preflight: catalog snapshot validated", flush=True)
            sync_manifest = identity._validate_sync(catalog, sync_id)
            print("Preflight: sync snapshot validated", flush=True)
            # _source_specs validates approval, provenance, region and TL/VL
            # bindings before build_sample opens actual AI Hub rows.
            def role_progress(region: str, role: str, stage: str) -> None:
                print(f"Preflight {region}/{role}: {stage}", flush=True)

            specs, masters = identity._source_specs(run_id, progress=role_progress)
            print("Preflight: AI Hub roles validated; bounded sample scan starting", flush=True)
            pairs = build_sample(catalog, specs, masters, snapshot_id, deadline=load_deadline)
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous_alarm)
        completed = review_ephemeral_sample(pairs, output,
                                            adjudicator_role=args.adjudicator_role)
        if completed:
            print("Manual sample audit completed; aggregate only; temporary evidence deleted.")
        else:
            print("Manual sample audit cancelled; no result saved; temporary evidence deleted.")
        return 0
    except TimeoutError:
        print("Manual sample audit stopped safely: bounded loading timeout; no review output.", file=sys.stderr)
        return 1
    except (KeyboardInterrupt, Exception):
        # Input paths, TUI content and library exception messages can contain
        # source data. Never write an exception, traceback or URL to the pane.
        print("Manual sample audit stopped safely; no row-level output was written.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
