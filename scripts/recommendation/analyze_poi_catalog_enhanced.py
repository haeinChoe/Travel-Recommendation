"""Privacy-safe enhanced identity diagnostics for Issue #4.

Stage 1 remains the existing strict rule. Stages 2 and 3 generate review-only
candidates. This script does not define product or request-time contracts.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import signal
import sys
import tempfile
import threading
import time
import traceback
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

import analyze_poi_catalog_identity as identity
import analyze_poi_catalog_scenarios as scenarios
import evaluate_popularity as shared
from adjudicate_poi_candidate_sample import (AuditInterrupted, AuditObservation, CandidateView,
                                             SourceCandidateGroup, preflight_terminal,
                                             review_ephemeral)
from poi_identity_contract import (CandidateEvidence, CandidateGenerationResult,
                                   CatalogCandidateIndex, CatalogPoi, SourcePoi,
                                   normalize_exact)

RESULTS_ROOT = identity.REPO_ROOT / "results" / "experiments" / "poi-catalog-enhanced"
SAMPLE_SEED = "issue4-enhanced-audit-v1"
SAMPLE_PER_REGION_STRATUM = 6
FUZZY_CANDIDATE_DISPLAY_LIMIT = 5
RUN_STATUS_FILENAME = "run_status.json"
SOURCE_MASTER_PROGRESS_INTERVAL = 50_000
SOURCE_ID_CHUNK_SIZE = 32
STATUS_HEARTBEAT_SECONDS = 15
PROGRESS_MARKER_SECONDS = 15
PRIMARY_PAIR_AUDIT_STRATA = {
    "punctuation_address_variant": "address_punctuation_variant_primary_pair",
    "normalized_multi_rule_candidates": "normalized_multi_rule_primary_pair",
}
SOURCE_REQUIRED = {"POI_ID", "POI_NM", "ROAD_NM_ADDR"}
SOURCE_SELECTED = SOURCE_REQUIRED | {"LOTNO_ADDR", "ASORT_LCLASDC", "ASORT_MLSFCDC", "ASORT_SDASDC"}


@dataclass(frozen=True)
class SourceMetadata:
    name: str | None
    address: str | None
    source_type: str
    lot_address: str | None = None
    identity_conflicted: bool = False
    strict_identity_conflicted: bool = False
    missing_master: bool = False
    missing_name: bool = False
    missing_address: bool = False
    identity_variants: tuple[tuple[str | None, str | None, str | None], ...] = ()


class RunInterrupted(BaseException):
    """Raised by the signal handler so an interrupted run can checkpoint safely."""

    def __init__(self, signal_number: int = signal.SIGTERM):
        super().__init__()
        self.signal_number = signal_number


class RunStatus:
    """Atomic aggregate-only status file; row values and exception messages are excluded."""

    def __init__(self, output: Path, run_id: str):
        self.output = output
        self.run_id = run_id
        self.phase = "startup"
        self.region: str | None = None
        self.batch: int | None = None
        self.work_phase: str | None = None
        self.completed_work: str | None = None
        self.status = "running"
        self._last_write_at: float | None = None
        self._last_boundary: tuple[str, str | None, int | None] | None = None
        self._lock = threading.RLock()
        self._heartbeat_stop = threading.Event()
        self._heartbeat_thread: threading.Thread | None = None

    def progress(self, phase: str, *, region: str | None = None,
                 batch: int | None = None, work_phase: str | None = None,
                 completed_work: int | str | None = None,
                 heartbeat_seconds: int = STATUS_HEARTBEAT_SECONDS) -> bool:
        """Checkpoint phase boundaries and same-state heartbeats only."""
        with self._lock:
            self.phase, self.region, self.batch = phase, region, batch
            self.work_phase = work_phase
            self.completed_work = (_bucket(completed_work) if isinstance(completed_work, int)
                                   else completed_work)
            boundary = (phase, region, batch)
            now = time.monotonic()
            boundary_changed = boundary != self._last_boundary
            heartbeat_due = (self._last_write_at is None
                             or now - self._last_write_at >= heartbeat_seconds)
            if boundary_changed or heartbeat_due:
                self.update(self.status)
                return True
            return False

    def heartbeat(self) -> bool:
        """Persist the current coarse state even when one scoring operation is slow."""
        with self._lock:
            if self.status != "running":
                return False
            if (self._last_write_at is not None
                    and time.monotonic() - self._last_write_at < STATUS_HEARTBEAT_SECONDS):
                return False
            self.update("running")
            return True

    def start_heartbeat(self, interval_seconds: float = STATUS_HEARTBEAT_SECONDS) -> None:
        if interval_seconds <= 0:
            raise ValueError("heartbeat interval must be positive")
        with self._lock:
            if self._heartbeat_thread is not None:
                raise RuntimeError("status heartbeat already started")
            self._heartbeat_stop.clear()

            def run() -> None:
                while not self._heartbeat_stop.wait(interval_seconds):
                    try:
                        self.heartbeat()
                    except Exception:  # noqa: BLE001 - never leak local status errors
                        self._heartbeat_stop.set()

            self._heartbeat_thread = threading.Thread(
                target=run, name="poi-run-status-heartbeat", daemon=True)
            self._heartbeat_thread.start()

    def stop_heartbeat(self) -> None:
        with self._lock:
            thread = self._heartbeat_thread
            self._heartbeat_stop.set()
        if thread is not None:
            thread.join()
        with self._lock:
            self._heartbeat_thread = None

    def update(self, status: str = "running", *, exception: BaseException | None = None,
               signal_number: int | None = None) -> None:
        with self._lock:
            self.status = status
            self._write_status(status, exception=exception, signal_number=signal_number)

    def _write_status(self, status: str, *, exception: BaseException | None = None,
                      signal_number: int | None = None) -> None:
        payload: dict[str, object] = {
            "schema_version": 1, "run_id": self.run_id, "status": status,
            "phase": self.phase, "region": self.region, "batch": self.batch,
            "row_level_output": False,
        }
        if self.work_phase is not None:
            payload["work_phase"] = self.work_phase
        if self.completed_work is not None:
            payload["completed_work"] = self.completed_work
        if exception is not None:
            payload["exception_type"] = type(exception).__name__
            payload["traceback"] = [
                {"filename": Path(frame.filename).name, "line": frame.lineno}
                for frame in traceback.extract_tb(exception.__traceback__)[-12:]
            ]
        if signal_number is not None:
            payload["signal_number"] = signal_number
        target = self.output / RUN_STATUS_FILENAME
        fd, temporary = tempfile.mkstemp(prefix=".run-status-", suffix=".tmp", dir=self.output)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, separators=(",", ":"))
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
            os.chmod(target, 0o600)
            directory_fd = os.open(self.output, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            self._last_write_at = time.monotonic()
            self._last_boundary = (self.phase, self.region, self.batch)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


class ProgressThrottle:
    """Emit the first work marker immediately, then at most once per interval."""

    def __init__(self, interval_seconds: int = PROGRESS_MARKER_SECONDS):
        if interval_seconds < 1:
            raise ValueError("progress interval must be positive")
        self.interval_seconds = interval_seconds
        self.last_emitted_at: float | None = None

    def allow(self, *, now: float | None = None) -> bool:
        current = time.monotonic() if now is None else now
        if (self.last_emitted_at is None
                or current - self.last_emitted_at >= self.interval_seconds):
            self.last_emitted_at = current
            return True
        return False


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


def _read_source_metadata(master_path: Path, observed_ids: set[str], *,
                          progress: Callable[[int], None] | None = None,
                          progress_interval: int = SOURCE_MASTER_PROGRESS_INTERVAL
                          ) -> dict[str, SourceMetadata]:
    if progress_interval < 1:
        raise ValueError("progress interval must be positive")
    identities: dict[str, set[tuple[str, str, str]]] = defaultdict(set)
    displays: dict[str, set[tuple[str, str, str, str]]] = defaultdict(set)
    rows_read = 0
    last_progress = 0
    for row in shared._rows([master_path], SOURCE_REQUIRED, SOURCE_SELECTED):
        rows_read += 1
        if progress is not None and rows_read % progress_interval == 0:
            progress(rows_read)
            last_progress = rows_read
        source_id = shared._cell(row, "poi_id")
        if source_id not in observed_ids:
            continue
        name, address = row.get("poi_nm") or "", row.get("road_nm_addr") or ""
        lot_address = row.get("lotno_addr") or ""
        source_type = " / ".join(
            f"L{n}={row.get(field) or ''}" for n, field in enumerate(
                ("asort_lclasdc", "asort_mlsfcdc", "asort_sdasdc"), 1)
            if row.get(field)
        ) or "[not supplied]"
        identities[source_id].add((normalize_exact(name), normalize_exact(address),
                                   normalize_exact(lot_address)))
        displays[source_id].add((name, address, lot_address, source_type))
    if progress is not None and rows_read != last_progress:
        progress(rows_read)
    result: dict[str, SourceMetadata] = {}
    for source_id in observed_ids:
        keys = identities.get(source_id, set())
        if not keys:
            result[source_id] = SourceMetadata(None, None, "[no source master record]",
                                               lot_address=None,
                                               missing_master=True, missing_name=True,
                                               missing_address=True)
            continue
        values = sorted(displays[source_id])
        names = sorted({value[0] for value in values if value[0]})
        addresses = sorted({value[1] for value in values if value[1]})
        types = sorted({value[3] for value in values if value[3]})
        variants = tuple(sorted({(name or None, address or None, lot_address or None)
                                 for name, address, lot_address, _ in values}))
        strict_keys = {(name, address) for name, address, _ in keys}
        # Preserve a real source spelling when several raw variants collapse to
        # one exact normalized identity. Joining them creates a synthetic value
        # that cannot match any catalog row. Conflicting normalized identities
        # remain explicitly ambiguous and are evaluated variant by variant below.
        if len(keys) == 1:
            selected_name, selected_address, selected_lot_address = variants[0]
        else:
            # Keep one real tuple for legacy display fields; the variants below
            # retain each observed name/road/lot association for review.
            selected_name, selected_address, selected_lot_address = variants[0]
        result[source_id] = SourceMetadata(
            selected_name,
            selected_address,
            " / ".join(types) if len(types) == 1 else
            ("[conflicting source classification codes]" if types else "[not supplied]"),
            lot_address=selected_lot_address,
            identity_conflicted=len(keys) > 1,
            strict_identity_conflicted=len(strict_keys) > 1,
            missing_name=not bool(names), missing_address=not bool(addresses),
            identity_variants=variants if len(keys) > 1 else (),
        )
    return result


def _result_for_source(index: CatalogCandidateIndex, region: str, source_id: str,
                       metadata: SourceMetadata, *,
                       candidate_progress: Callable[[str, int], None] | None = None
                       ) -> CandidateGenerationResult:
    source = SourcePoi(region, source_id, metadata.name, metadata.address, metadata.lot_address)
    if not metadata.identity_conflicted:
        return index.generate(source, _progress=candidate_progress)
    strict = index.strict_result(source, source_conflicted=metadata.strict_identity_conflicted)
    found: dict[int, CandidateEvidence] = {}
    found_by_variant: dict[
        tuple[str | None, str | None, str | None], dict[int, CandidateEvidence]
    ] = defaultdict(dict)
    stages = ("none", "stage1_exact", "stage2_normalized", "stage3_fuzzy")
    stage = "none"
    variants = metadata.identity_variants or ((metadata.name, metadata.address, metadata.lot_address),)
    variant_candidate_counts = []
    variant_blocking_rules = set()
    variant_ambiguous = False
    candidate_id_bitmap = bytearray((len(index.content_id_ordinals) + 7) // 8)
    candidate_record_bitmap = bytearray((len(index.catalog) + 7) // 8)
    for name, address, lot_address in variants:
        candidate_result = index.generate(
            SourcePoi(region, source_id, name, address, lot_address),
            _candidate_id_bitmap=candidate_id_bitmap,
            _candidate_record_bitmap=candidate_record_bitmap,
            _progress=candidate_progress, _rank_name_first=True)
        variant_candidate_counts.append((name, address, lot_address, candidate_result.candidate_count))
        variant_blocking_rules.add(candidate_result.blocking_rule)
        variant_ambiguous |= candidate_result.status == "AMBIGUOUS"
        if stages.index(candidate_result.stage) > stages.index(stage):
            stage = candidate_result.stage
        for candidate in candidate_result.candidates:
            # Catalog record identity keeps colliding content IDs distinct. Pair
            # evidence is also retained separately for the adjudication TUI.
            record_key = id(candidate.item)
            pair_key = (candidate.source_name, candidate.source_address,
                        candidate.source_lot_address)
            previous = found.get(record_key)
            current_score = (candidate.name_similarity, candidate.address_similarity)
            previous_score = ((previous.name_similarity, previous.address_similarity)
                              if previous else (-1.0, -1.0))
            if current_score > previous_score:
                found[record_key] = candidate
            previous_pair = found_by_variant[pair_key].get(record_key)
            previous_pair_score = ((previous_pair.name_similarity, previous_pair.address_similarity)
                                   if previous_pair else (-1.0, -1.0))
            if current_score > previous_pair_score:
                found_by_variant[pair_key][record_key] = candidate
    candidates = tuple(sorted(found.values(), key=lambda value: (
        value.name_similarity, value.address_similarity, value.item.content_id
    ), reverse=True))
    variant_evidence = tuple(
        (name, address, lot_address, tuple(sorted(
            found_by_variant.get((name, address, lot_address), {}).values(),
            key=lambda value: (value.name_similarity, value.address_similarity,
                               value.item.content_id), reverse=True,
        )[:FUZZY_CANDIDATE_DISPLAY_LIMIT]))
        for name, address, lot_address in variants
    )
    candidate_id_count = sum(value.bit_count() for value in candidate_id_bitmap)
    candidate_record_count = sum(value.bit_count() for value in candidate_record_bitmap)
    status = ("AMBIGUOUS" if metadata.strict_identity_conflicted or variant_ambiguous
              or candidate_id_count > 1
              or strict.status == "AMBIGUOUS" else "REVIEW")
    return CandidateGenerationResult(status, stage, "conflicting_source_metadata",
                                     candidates,
                                     candidate_record_count,
                                     "source_conflict_variants:" + "||".join(sorted(variant_blocking_rules)), strict,
                                     tuple(variant_candidate_counts), variant_evidence)


def _candidate_progress_reporter(*, set_phase: Callable[..., None], emit: Callable[[str], None],
                                 region: str, batch: int, started: float,
                                 throttle: ProgressThrottle) -> Callable[[str, int], None]:
    def report(work_phase: str, completed: int) -> None:
        set_phase("candidate_generation", region=region, batch=batch,
                  work_phase=work_phase, completed_work=completed)
        if throttle.allow():
            emit(f"candidate_generation={work_phase}:{region}; batch={batch}; "
                 f"completed_work={_bucket(completed)}; "
                 f"elapsed_seconds={int(time.monotonic() - started)}")
    return report


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


def _source_rows(specs, masters, catalog, snapshot_id, *,
                 progress: Callable[[str], None] | None = None,
                 phase_callback: Callable[..., None] | None = None,
                 source_chunk_size: int = SOURCE_ID_CHUNK_SIZE,
                 master_progress_interval: int = SOURCE_MASTER_PROGRESS_INTERVAL):
    if source_chunk_size < 1:
        raise ValueError("source chunk size must be positive")
    emit = progress or (lambda message: print(message, flush=True))
    set_phase = phase_callback or (lambda *_args, **_kwargs: None)
    by_role = {(spec.region, spec.role): spec for spec in specs}
    set_phase("candidate_index_build")
    emit(f"candidate_index_build=started; catalog_items={_bucket(len(catalog))}")
    index = CatalogCandidateIndex(catalog, snapshot_version=snapshot_id,
                                  fuzzy_display_limit=FUZZY_CANDIDATE_DISPLAY_LIMIT)
    emit("candidate_index_build=complete")
    results, metadata_by_key, events_by_role = {}, {}, {}
    role_membership: dict[tuple[str, str], set[str]] = defaultdict(set)
    for region in shared.REGIONS:
        splits = {}
        for role in ("TL", "VL"):
            set_phase("source_split_read", region=region)
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
        set_phase("source_master_scan", region=region)
        emit(f"source_master_scan=started:{region}; observed_items={_bucket(len(source_ids))}")
        master_started = time.monotonic()

        def master_progress(rows_read: int) -> None:
            set_phase("source_master_scan", region=region)
            elapsed = int(time.monotonic() - master_started)
            emit(f"source_master_scan=progress:{region}; rows_read={_bucket(rows_read)}; "
                 f"elapsed_seconds={elapsed}")

        source_metadata = _read_source_metadata(
            masters[region], source_ids, progress=master_progress,
            progress_interval=master_progress_interval)
        emit(f"source_master_scan=complete:{region}; observed_items={_bucket(len(source_metadata))}; "
             f"elapsed_seconds={int(time.monotonic() - master_started)}")
        ordered_source_ids = sorted(source_ids)
        generation_started = time.monotonic()
        candidate_support = 0
        set_phase("candidate_generation", region=region, batch=0)
        emit(f"candidate_generation=started:{region}; source_items={_bucket(len(ordered_source_ids))}")
        score_progress_throttle = ProgressThrottle()
        for batch_number, start in enumerate(range(0, len(ordered_source_ids), source_chunk_size), 1):
            set_phase("candidate_generation", region=region, batch=batch_number)
            chunk = ordered_source_ids[start:start + source_chunk_size]
            for source_id in chunk:
                key = (region, source_id)
                metadata_by_key[key] = source_metadata[source_id]
                candidate_progress = _candidate_progress_reporter(
                    set_phase=set_phase, emit=emit, region=region, batch=batch_number,
                    started=generation_started, throttle=score_progress_throttle)
                result = _result_for_source(
                    index, region, source_id, source_metadata[source_id],
                    candidate_progress=candidate_progress)
                results[key] = result
                candidate_support += result.candidate_count
            completed = min(start + len(chunk), len(ordered_source_ids))
            emit(f"candidate_generation=progress:{region}; "
                 f"batch={batch_number}; batch_source_items={_bucket(len(chunk))}; "
                 f"completed_source_items={_bucket(completed)}; "
                 f"candidate_support={_bucket(candidate_support)}; "
                 f"elapsed_seconds={int(time.monotonic() - generation_started)}")
        emit(f"candidate_generation=complete:{region}; "
             f"completed_source_items={_bucket(len(ordered_source_ids))}; "
             f"candidate_support={_bucket(candidate_support)}; "
             f"elapsed_seconds={int(time.monotonic() - generation_started)}")
        emit(f"identity_pipeline={region}: complete; "
             f"distinct_source_items={_bucket(len(source_ids))}")
        set_phase("source_region_complete", region=region, batch=None)
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
                counts_by_pair = {(name, address, lot_address): count
                                  for name, address, lot_address, count
                                  in result.source_variant_candidate_counts}
                evidence_by_pair = {
                    (name, address, lot_address): pair_evidence
                    for name, address, lot_address, pair_evidence
                    in result.source_variant_candidate_evidence
                }
                candidate_groups = tuple(SourceCandidateGroup(
                    source_name=name or "[not supplied]",
                    source_address=address or "[not supplied]",
                    source_lot_address=lot_address or "[not supplied]",
                    candidates=tuple(CandidateView(
                        candidate.item.title or "[not supplied]",
                        candidate.item.road_address or "[not supplied]",
                        candidate.item.content_type or "[not supplied]",
                    ) for candidate in evidence_by_pair.get((name, address, lot_address), tuple(
                        candidate for candidate in evidence
                        if (candidate.source_name, candidate.source_address,
                            candidate.source_lot_address) == (name, address, lot_address)
                    )))[:FUZZY_CANDIDATE_DISPLAY_LIMIT],
                    candidate_count=counts_by_pair.get((name, address, lot_address), 0),
                ) for name, address, lot_address in source.identity_variants)
            observations.append(AuditObservation(
                region, stratum, partition, result.method,
                source.name or "[not supplied]", source.address or "[not supplied]",
                source.source_type, candidates, result.candidate_count,
                source_lot_address=source.lot_address or "[not supplied]",
                source_candidate_groups=candidate_groups,
            ))
        for partition in ("development", "validation"):
            chosen = [i for i in range(len(selected))
                      if ("development" if i % 2 == 0 else "validation") == partition]
            methods = Counter(selected[i][1].method for i in chosen)
            support.append({"region": region, "stratum": stratum, "partition": partition,
                            "selected_count": _bucket(len(chosen)),
                            "available_support": _bucket(len(values)),
                            "methods": {key: _bucket(value) for key, value in sorted(methods.items())}})
    return observations, support


def _metrics(catalog, results, metadata, events_by_role, role_membership):
    rows = []
    _catalog_inventory(rows, catalog)
    by_id = {item.content_id: item for item in catalog}
    status_names = ("MATCHED", "REVIEW", "AMBIGUOUS", "UNMATCHED")
    # Partition once. The previous implementation rescanned every identity
    # four times per region while building ALL/TL/VL/both scopes.
    keys_by_region: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for key in results:
        keys_by_region[key[0]].append(key)
    for region in shared.REGIONS:
        keys = keys_by_region[region]
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
                             sample_support: list[dict], expected_count: int) -> Path:
    audit_run = identity._run_id(run_id)
    audit_root = RESULTS_ROOT / audit_run
    metadata_path = audit_root / "run_metadata.json"
    support_path = audit_root / "sample_support.json"
    status_path = audit_root / RUN_STATUS_FILENAME
    checkpoint_path = audit_root / "aggregate_checkpoint.json"
    aggregate_path = audit_root / "audit" / "aggregate.json"
    paths = (audit_root, metadata_path, support_path, status_path,
             checkpoint_path, aggregate_path)
    if any(path.is_symlink() or shared.has_symlink_component(path.absolute()) for path in paths):
        raise ValueError("reusable audit input unavailable")
    if not all(path.is_file() for path in (metadata_path, support_path, status_path,
                                           checkpoint_path, aggregate_path)):
        raise ValueError("reusable audit input unavailable")
    run_status = json.loads(status_path.read_text(encoding="utf-8"))
    aggregate_checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    if (run_status.get("run_id") != audit_run
            or run_status.get("status") != "complete"
            or aggregate_checkpoint.get("status") != "complete"):
        raise ValueError("reusable audit source run incomplete")
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
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}-", suffix=".tmp", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
        _fsync_directory(path.parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _fsync_directory(path: Path) -> None:
    directory_fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _write_json_atomic(path: Path, value: object) -> None:
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}-", suffix=".tmp", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
        _fsync_directory(path.parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _duration_band(seconds: float | None) -> str:
    if seconds is None:
        return "not_run"
    if seconds < 60:
        return "<1m"
    if seconds < 5 * 60:
        return "1-5m"
    if seconds < 15 * 60:
        return "5-15m"
    return "15m+"


def _phase_duration_bands(elapsed: dict[str, float], active_phase: str | None,
                          active_started: float | None, now: float) -> dict[str, str]:
    values = dict(elapsed)
    if active_phase is not None and active_started is not None:
        values[active_phase] = values.get(active_phase, 0.0) + now - active_started
    source_scan = sum(values.get(name, 0.0)
                      for name in ("source_split_read", "source_master_scan"))
    requested = {
        "source_scan": source_scan,
        "candidate_generation": values.get("candidate_generation"),
        "metrics": values.get("metric_aggregation"),
        "sample_frame": values.get("sample_frame"),
        "audit_review": values.get("audit_review"),
        "audit_reuse_validation": values.get("audit_reuse_validation"),
    }
    return {name: _duration_band(seconds) for name, seconds in requested.items()}


def _write_audit_checkpoint(output: Path, rows: list[dict[str, str]],
                            observations: list[AuditObservation],
                            sample_support: list[dict]) -> None:
    """Persist only aggregate work before entering ephemeral manual review."""
    _write_metrics(output / "metrics.csv", rows)
    _write_json_atomic(output / "sample_support.json", sample_support)
    _write_json_atomic(output / "aggregate_checkpoint.json", {
        "schema_version": 1,
        "status": "incomplete",
        "phase": "audit_review",
        "metrics_rows": _bucket(len(rows)),
        "sample_size": _bucket(len(observations)),
        "sample_support_rows": _bucket(len(sample_support)),
        "row_level_output": False,
        "rerun": "use a fresh run ID; source scan, matching, and sample frame are recomputed",
    })


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
    checkpoint: RunStatus | None = None
    previous_sigterm = signal.getsignal(signal.SIGTERM)

    def interrupt_handler(signum, _frame):
        raise RunInterrupted(signum)

    try:
        if args.audit:
            preflight_terminal()
        run_id = identity._run_id(args.run_id)
        snapshot_id = identity._run_id(args.snapshot_id)
        sync_id = identity._run_id(args.sync_id)
        output = RESULTS_ROOT / run_id
        if output.exists() or output.is_symlink() or shared.has_symlink_component(output.absolute()):
            raise ValueError("result destination unavailable")
        output.mkdir(parents=True, mode=0o700)
        os.chmod(output, 0o700)
        checkpoint = RunStatus(output, run_id)
        checkpoint.update()
        checkpoint.start_heartbeat()
        signal.signal(signal.SIGTERM, interrupt_handler)
        phase_elapsed: dict[str, float] = defaultdict(float)
        active_phase: str | None = None
        active_phase_started: float | None = None

        def set_phase(value: str, *, region: str | None = None,
                      batch: int | None = None, work_phase: str | None = None,
                      completed_work: int | None = None) -> None:
            nonlocal active_phase, active_phase_started
            now = time.monotonic()
            if value != active_phase:
                if active_phase is not None and active_phase_started is not None:
                    phase_elapsed[active_phase] += now - active_phase_started
                active_phase = value
                active_phase_started = now
            checkpoint.progress(
                value, region=region, batch=batch, work_phase=work_phase,
                completed_work=completed_work,
            )

        set_phase("catalog_load")
        print("catalog_load=started", flush=True)
        catalog, catalog_manifest = identity._load_catalog(snapshot_id)
        print(f"catalog_load=complete; catalog_items={_bucket(len(catalog))}", flush=True)
        set_phase("sync_validation")
        print("sync_validation=started", flush=True)
        sync_manifest = identity._validate_sync(catalog, sync_id)
        print("sync_validation=complete", flush=True)
        set_phase("source_preflight")
        specs, masters = identity._source_specs(run_id, progress=lambda region, role, stage:
            print(f"preflight={region}/{role}:{stage}", flush=True))
        results, metadata, events, role_membership, index = _source_rows(
            specs, masters, catalog, snapshot_id,
            phase_callback=set_phase)
        set_phase("metric_aggregation")
        print("metric_aggregation=started", flush=True)
        rows = _metrics(catalog, results, metadata, events, role_membership)
        print(f"metric_aggregation=complete; metric_rows={_bucket(len(rows))}", flush=True)
        set_phase("sample_frame")
        print("sample_frame=started", flush=True)
        observations, sample_support = _audit_observations(
            results, metadata, audit_method=args.audit_method,
            primary_pair=args.audit_primary_pair)
        print(f"sample_frame=complete; sample_items={_bucket(len(observations))}", flush=True)
        if args.audit_method and not observations:
            raise ValueError("targeted audit method has no sample support")
        audit_source_run_id = None
        if args.audit:
            set_phase("audit_review")
            _write_audit_checkpoint(output, rows, observations, sample_support)
            audit_dir = output / "audit"
            if not review_ephemeral(observations, audit_dir, adjudicator_role=args.adjudicator_role):
                raise ValueError("candidate audit cancelled")
            _add_audit_metrics(rows, audit_dir / "aggregate.json")
            audit_source_run_id = run_id
        elif args.reuse_audit_run_id:
            set_phase("audit_reuse_validation")
            audit_path = _validate_reusable_audit(args.reuse_audit_run_id,
                                                  snapshot_id, sync_id, sample_support,
                                                  expected_count=len(observations))
            _add_audit_metrics(rows, audit_path)
            audit_source_run_id = identity._run_id(args.reuse_audit_run_id)
        set_phase("aggregate_write")
        print("aggregate_write=started", flush=True)
        _write_metrics(output / "metrics.csv", rows)
        _write_json_atomic(output / "sample_support.json", sample_support)
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
            "stage1": "preserved strict unique normalized-name plus address-string baseline; enhanced signal conflicts may require review",
            "stage2": "collision-preserving punctuation-to-separator and no-spacing name/address keys; review only",
            "stage3": "name token/prefix, address-piece, validated admin-component and character-trigram fallback blocks; review only, no auto-match threshold",
            "stage4_coordinates": "disabled; CRS, field meaning, ranges, and same-place distances not validated",
            "stage5_type": "source classification and KTO contentTypeId are auxiliary only; not candidate blocks or identity decisions",
            "administrative_area": "no matching filter; SGG_CD to lDongSignguCd crosswalk unvalidated",
            "catalog_area_semantics": "KTO lDongRegnCd is catalog analysis grouping; AI Hub purpose region may define an offline cohort, but membership crosswalk is unresolved and neither field is assumed as request geography",
            "sample": {"seed": SAMPLE_SEED, "maximum_per_region_stratum": SAMPLE_PER_REGION_STRATUM,
                       "partition": "alternating hash-ranked sample into development/validation",
                       "sample_size": _bucket(len(observations)), "source_ids_persisted": False,
                       "pair_fields_persisted": False, "per_row_labels_persisted": False},
            "audit_method_filter": args.audit_method,
            "audit_primary_pair_only": args.audit_primary_pair,
            "audit_source_run_id": audit_source_run_id,
            "phase_duration_bands": _phase_duration_bands(
                phase_elapsed, active_phase, active_phase_started, time.monotonic()),
            "catalog_name_collision_counts": index.collision_counts(),
            "positive_semantics": "observed visits are positives; unobserved items unknown; unmatched not catalog absence",
            "request_time_candidate_coverage": "unestimable_without_request_area_contract_and_validated_crosswalk",
            "completion_contract": "run_status.json must report complete; aggregate files without that checkpoint are incomplete",
            "completed_utc": datetime.now(UTC).isoformat(timespec="seconds"),
            "privacy": "only aggregate bands/sample support persisted; no names, addresses, IDs, coordinates, or row labels",
        }
        _write_json_atomic(output / "run_metadata.json", metadata_out)
        if args.audit:
            _write_json_atomic(output / "aggregate_checkpoint.json", {
                "schema_version": 1,
                "status": "complete",
                "phase": "complete",
                "row_level_output": False,
                "completion_contract": "run_status.json must also report complete",
            })
        set_phase("complete")
        checkpoint.update("complete")
        print("aggregate_write=complete; row_level_output=false", flush=True)
        print(f"enhanced_identity_complete=true; source_item_count={_bucket(len(results))}; "
              f"metrics={_bucket(len(rows))}; sample_size={_bucket(len(observations))}; "
              "raw_values_emitted=false", flush=True)
        return 0
    except (RunInterrupted, AuditInterrupted, KeyboardInterrupt) as exc:
        signal_number = getattr(exc, "signal_number", None)
        if checkpoint is not None:
            checkpoint.update("interrupted", exception=exc, signal_number=signal_number)
        print("[stopped] enhanced identity run failed safely; "
              f"phase={checkpoint.phase if checkpoint else 'startup'}; "
              f"exception_type={type(exc).__name__}; "
              "row_level_output=false", file=sys.stderr)
        if signal_number is not None:
            return 128 + signal_number
        return 130 if isinstance(exc, KeyboardInterrupt) else 143
    except Exception as exc:
        if checkpoint is not None:
            checkpoint.update("failed", exception=exc)
        print("[stopped] enhanced identity run failed safely; "
              f"phase={checkpoint.phase if checkpoint else 'startup'}; "
              f"exception_type={type(exc).__name__}; "
              "row_level_output=false", file=sys.stderr)
        return 2
    finally:
        if checkpoint is not None:
            checkpoint.stop_heartbeat()
        signal.signal(signal.SIGTERM, previous_sigterm)


if __name__ == "__main__":
    raise SystemExit(main())
