"""Run the enhanced POI analyzer with allowlisted output and independent exit capture."""

from __future__ import annotations

import argparse
import json
import queue
import re
import signal
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

import evaluate_popularity as shared
import analyze_poi_catalog_identity as identity
from analyze_poi_catalog_enhanced import RESULTS_ROOT, RUN_STATUS_FILENAME, RunStatus

ANALYZER = Path(__file__).with_name("analyze_poi_catalog_enhanced.py")
MAX_CHILD_LINE_BYTES = 500
CHILD_READ_CHUNK_BYTES = 4096
OUTPUT_QUEUE_MAXSIZE = 128


def _patterns(regions: tuple[str, ...]) -> tuple[re.Pattern[str], ...]:
    region = "(?:" + "|".join(re.escape(value) for value in regions) + ")"
    common = (
        r"catalog_load=(?:started|complete; catalog_items=(?:0|<10|10\+))",
        r"sync_validation=(?:started|complete)",
        r"metric_aggregation=(?:started|complete; metric_rows=(?:0|<10|10\+))",
        r"sample_frame=(?:started|complete; sample_items=(?:0|<10|10\+))",
        r"aggregate_write=(?:started|complete; row_level_output=false)",
        r"enhanced_identity_complete=true; source_item_count=(?:0|<10|10\+); metrics=(?:0|<10|10\+); sample_size=(?:0|<10|10\+); raw_values_emitted=false",
        r"candidate_index_build=(?:started; catalog_items=(?:0|<10|10\+)|complete)",
        rf"preflight={region}/(?:TL|VL|Other):(?:role_provenance_validated|master_provenance_validated)",
        rf"source_split_read=(?:started:{region}/(?:TL|VL)|complete:{region}/(?:TL|VL); event_count=(?:0|<10|10\+))",
        rf"source_master_scan=(?:started:{region}; observed_items=(?:0|<10|10\+)|progress:{region}; rows_read=(?:0|<10|10\+); elapsed_seconds=\d+|complete:{region}; observed_items=(?:0|<10|10\+); elapsed_seconds=\d+)",
        rf"candidate_generation=(?:started:{region}; source_items=(?:0|<10|10\+)|(?:blocking|scoring):{region}; batch=\d+; completed_work=(?:0|<10|10\+); elapsed_seconds=\d+|progress:{region}; batch=\d+; batch_source_items=(?:0|<10|10\+); completed_source_items=(?:0|<10|10\+); candidate_support=(?:0|<10|10\+); elapsed_seconds=\d+|complete:{region}; completed_source_items=(?:0|<10|10\+); candidate_support=(?:0|<10|10\+); elapsed_seconds=\d+)",
        rf"identity_pipeline={region}: complete; distinct_source_items=(?:0|<10|10\+)",
        r"\[stopped\] enhanced identity run failed safely; phase=[a-z_]+; exception_type=[A-Za-z][A-Za-z0-9_]*; row_level_output=false",
    )
    return tuple(re.compile(rf"^{value}$") for value in common)


def sanitize_marker(line: str, *, regions: tuple[str, ...] | None = None) -> str | None:
    """Return a known safe progress marker; drop all unrecognized child output."""
    clean = line.rstrip("\r\n")
    if len(clean) > MAX_CHILD_LINE_BYTES:
        return None
    if any(pattern.fullmatch(clean) for pattern in _patterns(regions or tuple(shared.REGIONS))):
        return clean
    return None


@dataclass(frozen=True)
class SupervisorResult:
    analyzer_returncode: int
    sanitizer_error_type: str | None
    interrupted: bool = False
    caught_signal: int | None = None

    @property
    def analyzer_signal(self) -> int | None:
        if self.analyzer_returncode < 0:
            return -self.analyzer_returncode
        return self.caught_signal


def supervisor_exit_code(result: SupervisorResult) -> int:
    if result.sanitizer_error_type:
        return 3
    if result.analyzer_returncode < 0:
        return 128 + (result.analyzer_signal or signal.SIGTERM)
    if result.interrupted and result.caught_signal:
        return 128 + result.caught_signal
    return result.analyzer_returncode


def run_supervised(command: list[str], *, output: TextIO = sys.stdout,
                   errors: TextIO = sys.stderr) -> SupervisorResult:
    """Stream only allowlisted markers and retain analyzer status independently."""
    previous_sigterm = signal.getsignal(signal.SIGTERM)
    supervisor_sigterm_received = False

    def request_supervisor_stop(_signum, _frame) -> None:
        # Keep the signal handler minimal; the normal loop forwards and drains.
        nonlocal supervisor_sigterm_received
        supervisor_sigterm_received = True

    signal.signal(signal.SIGTERM, request_supervisor_stop)
    try:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   bufsize=0)
    except BaseException:
        signal.signal(signal.SIGTERM, previous_sigterm)
        raise
    lines: queue.Queue[tuple[str, str | None]] = queue.Queue(maxsize=OUTPUT_QUEUE_MAXSIZE)

    def read_stream(name: str, stream) -> None:
        pending = bytearray()
        overlong = False

        def finish_line() -> None:
            nonlocal overlong
            if not overlong:
                lines.put((name, pending.decode("utf-8", errors="replace")))
            pending.clear()
            overlong = False

        try:
            while True:
                chunk = stream.read(CHILD_READ_CHUNK_BYTES)
                if not chunk:
                    break
                start = 0
                while start < len(chunk):
                    newline = chunk.find(b"\n", start)
                    end = len(chunk) if newline < 0 else newline
                    fragment = chunk[start:end]
                    if not overlong:
                        if len(pending) + len(fragment) <= MAX_CHILD_LINE_BYTES:
                            pending.extend(fragment)
                        else:
                            pending.clear()
                            overlong = True
                    if newline < 0:
                        break
                    finish_line()
                    start = newline + 1
            if pending or overlong:
                finish_line()
        except Exception as exc:  # noqa: BLE001 - type is recorded without message
            lines.put(("reader_error", type(exc).__name__))
        finally:
            lines.put((name, None))

    threads = [threading.Thread(target=read_stream, args=(name, stream), daemon=True)
               for name, stream in (("stdout", process.stdout), ("stderr", process.stderr))]
    for thread in threads:
        thread.start()
    ended = set()
    sanitizer_error_type = None
    interrupted = False
    caught_signal = None
    forwarded_sigterm = False
    try:
        while len(ended) < 2:
            if supervisor_sigterm_received and not forwarded_sigterm:
                interrupted = True
                caught_signal = signal.SIGTERM
                forwarded_sigterm = True
                if process.poll() is None:
                    process.send_signal(signal.SIGTERM)
            try:
                name, value = lines.get(timeout=0.1)
            except queue.Empty:
                continue
            except KeyboardInterrupt:
                interrupted = True
                if process.poll() is None:
                    process.send_signal(signal.SIGINT)
                continue
            if value is None:
                ended.add(name)
                continue
            if name == "reader_error":
                sanitizer_error_type = sanitizer_error_type or value
                continue
            safe = sanitize_marker(value)
            if safe is None:
                continue
            if safe.startswith("[stopped]"):
                if ("exception_type=RunInterrupted;" in safe
                        or "exception_type=AuditInterrupted;" in safe):
                    caught_signal = signal.SIGTERM
                    interrupted = True
                elif "exception_type=KeyboardInterrupt;" in safe:
                    caught_signal = signal.SIGINT
                    interrupted = True
            try:
                target = errors if safe.startswith("[stopped]") else output
                print(safe, file=target, flush=True)
            except Exception as exc:  # noqa: BLE001 - do not disclose sink details
                sanitizer_error_type = sanitizer_error_type or type(exc).__name__
    finally:
        returncode = process.wait()
        for thread in threads:
            thread.join(timeout=1)
        process.stdout.close()
        process.stderr.close()
        signal.signal(signal.SIGTERM, previous_sigterm)

    signal_number = -returncode if returncode < 0 else caught_signal
    signal_name = signal.Signals(signal_number).name if signal_number else "none"
    print(f"[supervisor] analyzer_returncode={returncode}; analyzer_signal={signal_name}; "
          f"sanitizer_error_type={sanitizer_error_type or 'none'}; interrupted={str(interrupted).lower()}",
          file=errors, flush=True)
    return SupervisorResult(returncode, sanitizer_error_type, interrupted, caught_signal)


def persist_unhandled_signal(run_id: str, result: SupervisorResult) -> None:
    """Turn a still-running status into interrupted after an unhandled child signal."""
    if result.analyzer_returncode >= 0:
        return
    try:
        safe_run_id = identity._run_id(run_id)
        output = RESULTS_ROOT / safe_run_id
        if (output.is_symlink() or shared.has_symlink_component(output.absolute())
                or not output.is_dir()):
            return
        state_path = output / RUN_STATUS_FILENAME
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state.get("status") != "running":
            return
        checkpoint = RunStatus(output, safe_run_id)
        checkpoint.phase = state.get("phase") if isinstance(state.get("phase"), str) else "unknown"
        region = state.get("region")
        checkpoint.region = region if region in shared.REGIONS else None
        batch = state.get("batch")
        checkpoint.batch = batch if isinstance(batch, int) and batch >= 0 else None
        checkpoint.update("interrupted", signal_number=-result.analyzer_returncode)
    except Exception:  # noqa: BLE001 - supervisor status repair must not expose local details
        return


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-id", required=True)
    parser.add_argument("--sync-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--audit", action="store_true")
    parser.add_argument("--audit-method")
    parser.add_argument("--audit-primary-pair", action="store_true")
    parser.add_argument("--reuse-audit-run-id")
    parser.add_argument("--adjudicator-role", choices=("author", "independent"), default="author")
    args = parser.parse_args(argv)
    command = [sys.executable, str(ANALYZER), "--snapshot-id", args.snapshot_id,
               "--sync-id", args.sync_id, "--run-id", args.run_id]
    for flag in ("audit", "audit_primary_pair"):
        if getattr(args, flag):
            command.append("--" + flag.replace("_", "-"))
    for name in ("audit_method", "reuse_audit_run_id"):
        value = getattr(args, name)
        if value:
            command.extend(("--" + name.replace("_", "-"), value))
    if args.adjudicator_role != "author":
        command.extend(("--adjudicator-role", args.adjudicator_role))
    result = run_supervised(command)
    persist_unhandled_signal(args.run_id, result)
    return supervisor_exit_code(result)


if __name__ == "__main__":
    raise SystemExit(main())
