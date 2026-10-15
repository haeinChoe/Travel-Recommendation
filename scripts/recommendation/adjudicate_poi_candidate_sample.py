"""Private local audit UI for candidate groups from the Issue #4 identity pipeline.

Only aggregate labels are written. Pair evidence and individual labels remain
in memory or in a mode-0600 temporary file and are never sent over a network.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import tempfile
import termios
import threading
import tty
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

LABELS = ("MATCH", "NO_MATCH", "UNCERTAIN")


def _handle_sigterm(signum: int, _frame: object) -> None:
    """Turn SIGTERM into a handled interruption so the evidence file is removed."""
    signal.signal(signum, signal.SIG_IGN)
    raise KeyboardInterrupt


@dataclass(frozen=True)
class CandidateView:
    title: str
    address: str
    content_type: str


@dataclass(frozen=True)
class SourceCandidateGroup:
    source_name: str
    source_address: str
    candidates: tuple[CandidateView, ...]
    candidate_count: int


@dataclass(frozen=True)
class AuditObservation:
    region: str
    stratum: str
    partition: str
    method: str
    source_name: str
    source_address: str
    source_type: str
    candidates: tuple[CandidateView, ...]
    candidate_count: int
    source_candidate_groups: tuple[SourceCandidateGroup, ...] = ()


def _write_private_evidence(observations: list[AuditObservation], directory: Path) -> Path:
    if not observations:
        raise ValueError("empty audit sample")
    os.chmod(directory, 0o700)
    path = directory / "candidate-evidence.jsonl"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            for ordinal, observation in enumerate(observations, 1):
                payload = asdict(observation)
                payload["ordinal"] = ordinal
                json.dump(payload, stream, ensure_ascii=False, sort_keys=True)
                stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return path


def _read_private_evidence(path: Path) -> list[AuditObservation]:
    result = []
    expected = {"ordinal", "region", "stratum", "partition", "method", "source_name",
                "source_address", "source_type", "candidates", "candidate_count",
                "source_candidate_groups"}
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            item = json.loads(line)
            if set(item) != expected or item["ordinal"] != len(result) + 1:
                raise ValueError("temporary evidence integrity check failed")
            candidates = tuple(CandidateView(**candidate) for candidate in item["candidates"])
            groups = tuple(SourceCandidateGroup(
                source_name=group["source_name"], source_address=group["source_address"],
                candidates=tuple(CandidateView(**candidate) for candidate in group["candidates"]),
                candidate_count=group["candidate_count"],
            ) for group in item["source_candidate_groups"])
            result.append(AuditObservation(
                region=item["region"], stratum=item["stratum"], partition=item["partition"],
                method=item["method"], source_name=item["source_name"],
                source_address=item["source_address"], source_type=item["source_type"],
                candidates=candidates, candidate_count=item["candidate_count"],
                source_candidate_groups=groups,
            ))
    return result


def _safe_text(value: str) -> str:
    return "".join(" " if unicodedata.category(char).startswith("C") else char
                   for char in value).strip() or "[not supplied]"


def _open_tty() -> tuple[int, bytes, bytes, bytes]:
    import curses
    fd = os.open("/dev/tty", os.O_RDWR | os.O_NOCTTY)
    try:
        if not os.isatty(fd):
            raise ValueError("private terminal unavailable")
        curses.setupterm(fd=fd)
        enter, leave, clear = (curses.tigetstr(value) for value in ("smcup", "rmcup", "clear"))
        if not enter or not leave or not clear:
            raise ValueError("alternate screen unavailable")
        size = os.get_terminal_size(fd)
        if size.columns < 80 or size.lines < 18:
            raise ValueError("private terminal too small")
        return fd, enter, leave, clear
    except BaseException:
        os.close(fd)
        raise


def _render(observation: AuditObservation, index: int, total: int, width: int) -> bytes:
    if observation.stratum.endswith("_primary_pair"):
        instruction = [
            "Targeted Stage 2 address-normalization review.",
            "Judge only the source and single primary candidate shown as a pair.",
            "MATCH means this presented pair is the same place; NO_MATCH means different places.",
            "UNCERTAIN means the displayed evidence is insufficient. Other candidates are not shown.",
        ]
    else:
        instruction = ["MATCH means a displayed candidate appears to be the same place.",
                       "NO_MATCH means none of the displayed candidates appears to be the same place.",
                       "UNCERTAIN means the displayed evidence is insufficient."]
    lines = [
        f"Issue #4 candidate audit — item {index}/{total} ({observation.partition})",
        f"Region: {observation.region}; stratum: {observation.stratum}; method: {observation.method}",
        *instruction,
        "Press 1 MATCH | 2 NO_MATCH | 3 UNCERTAIN; SPACE confirms; q cancels", "",
        *([] if observation.source_candidate_groups else [
            "Source name: " + _safe_text(observation.source_name),
            "Source address: " + _safe_text(observation.source_address),
        ]),
        "Source classification codes (unmapped): " + _safe_text(observation.source_type), "",
    ]
    if observation.source_candidate_groups:
        for group_position, group in enumerate(observation.source_candidate_groups, 1):
            lines.extend((
                f"Source pair {group_position} name: " + _safe_text(group.source_name),
                "Source pair " + str(group_position) + " address: " + _safe_text(group.source_address),
                f"Candidates for this source pair: {len(group.candidates)} of {group.candidate_count}",
            ))
            for position, candidate in enumerate(group.candidates, 1):
                lines.extend((
                    f"  Candidate {position}: " + _safe_text(candidate.title),
                    "    Address (generic addr1): " + _safe_text(candidate.address),
                    "    KTO contentTypeId: " + _safe_text(candidate.content_type),
                ))
            if not group.candidates:
                lines.append("  No candidate was returned for this source pair.")
            lines.append("")
    else:
        lines.append(f"Candidates shown: {len(observation.candidates)} of {observation.candidate_count}")
        for position, candidate in enumerate(observation.candidates, 1):
            lines.extend((
                f"Candidate {position}: " + _safe_text(candidate.title),
                "  Address (generic addr1): " + _safe_text(candidate.address),
                "  KTO contentTypeId: " + _safe_text(candidate.content_type),
            ))
    if not observation.candidates and not observation.source_candidate_groups:
        lines.append("No candidate was returned by this blocking rule; this does not prove absence.")
    return ("\r\n".join(line[:width] for line in lines) + "\r\n").encode("utf-8")


def _review_window(observations: list[AuditObservation],
                   submit: Callable[[AuditObservation, str], None]) -> bool:
    fd, enter, leave, clear = _open_tty()
    original = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        os.write(fd, enter + b"\x1b[?25l")
        for index, observation in enumerate(observations, 1):
            size = os.get_terminal_size(fd)
            if size.columns < 80 or size.lines < 18:
                return False
            os.write(fd, clear + _render(observation, index, len(observations), min(120, size.columns - 1)))
            selected: str | None = None
            while True:
                key = os.read(fd, 1)
                if key in (b"\x03", b"\x1b", b"q", b"Q", b""):
                    return False
                if selected is None and key in (b"1", b"2", b"3"):
                    selected = LABELS[int(key) - 1]
                    os.write(fd, ("\r\nSelected " + selected + "; press SPACE to confirm.\r\n").encode("ascii"))
                elif selected is not None and key == b" ":
                    submit(observation, selected)
                    termios.tcflush(fd, termios.TCIFLUSH)
                    break
        return True
    finally:
        try:
            os.write(fd, clear + b"\x1b[?25h" + leave)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, original)
            os.close(fd)


def review_ephemeral(observations: list[AuditObservation], output: Path,
                     ui: Callable[[list[AuditObservation], Callable[[AuditObservation, str], None]], bool] | None = None,
                     adjudicator_role: str = "author") -> bool:
    """Review one source group at a time; persist only complete aggregate labels."""
    temp_name: str | None = None
    evidence_path: Path | None = None
    labels: dict[tuple[str, str, str], dict[str, int]] = {}
    reviewed = 0
    allowed_observations: set[int] = set()
    submitted_observations: set[int] = set()
    prior_sigterm_handler: object | None = None

    def submit(observation: AuditObservation, label: str) -> None:
        nonlocal reviewed
        marker = id(observation)
        if (label not in LABELS or marker not in allowed_observations
                or marker in submitted_observations):
            raise ValueError("invalid audit label")
        submitted_observations.add(marker)
        key = (observation.method, observation.stratum, observation.partition)
        counts = labels.setdefault(key, {value: 0 for value in LABELS})
        counts[label] += 1
        reviewed += 1

    try:
        if threading.current_thread() is not threading.main_thread():
            raise RuntimeError("safe termination handling requires the main thread")
        prior_sigterm_handler = signal.getsignal(signal.SIGTERM)
        signal.signal(signal.SIGTERM, _handle_sigterm)
        with tempfile.TemporaryDirectory(prefix="issue4-candidate-audit-") as temp:
            temp_name = temp
            evidence_path = _write_private_evidence(observations, Path(temp))
            local_observations = _read_private_evidence(evidence_path)
            allowed_observations.update(id(item) for item in local_observations)
            completed = (ui or _review_window)(local_observations, submit)
        if not completed:
            return False
        if reviewed != len(observations) or adjudicator_role not in ("author", "independent"):
            raise ValueError("incomplete audit or invalid adjudicator role")
        if output.exists() or output.is_symlink():
            raise ValueError("aggregate destination unavailable")
        output.mkdir(parents=True, mode=0o700)
        aggregate = {
            "reviewed_count": reviewed,
            "labels": {label: sum(group[label] for group in labels.values()) for label in LABELS},
            "by_method_stratum_partition": {
                "|".join(key): {"reviewed_count": sum(values.values()), "labels": values}
                for key, values in sorted(labels.items())
            },
            "adjudicator_role": adjudicator_role,
            "privacy": "aggregate labels only; no row identity or evidence persisted",
        }
        temp_file = output / ".aggregate.tmp"
        fd = os.open(temp_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(aggregate, stream, ensure_ascii=False, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_file, output / "aggregate.json")
        finally:
            temp_file.unlink(missing_ok=True)
        return True
    finally:
        try:
            if evidence_path is not None:
                evidence_path.unlink(missing_ok=True)
            if evidence_path is not None and evidence_path.exists():
                raise ValueError("temporary evidence cleanup verification failed")
            if temp_name is not None and Path(temp_name).exists():
                raise ValueError("temporary evidence cleanup verification failed")
        finally:
            # Restore whenever we captured the prior disposition. SIGTERM can
            # arrive immediately after signal.signal() installs our handler but
            # before control returns to this frame.
            if prior_sigterm_handler is not None:
                signal.signal(signal.SIGTERM, prior_sigterm_handler)
