"""Synthetic privacy checks for the private Issue #4 review tool."""

from __future__ import annotations

import json
import io
import os
import contextlib
import csv
import fcntl
import pty
import select
import signal
import struct
import termios
import time
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "recommendation"))
import adjudicate_poi_match_sample as audit  # noqa: E402


class AdjudicationPrivacyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.pairs = [audit.ReviewPair(
            source_name="PRIVATE_SOURCE_NAME", source_address="PRIVATE_SOURCE_ADDRESS",
            source_type="PRIVATE_SOURCE_TYPE", catalog_name="PRIVATE_CATALOG_NAME",
            catalog_address="PRIVATE_CATALOG_ADDRESS", catalog_type="PRIVATE_CATALOG_TYPE",
            method="unique_exact_name_address",
        ) for _ in range(audit.EXPECTED_SAMPLE_SIZE)]

    def test_completed_review_writes_aggregate_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "review"

            def ui(pairs, submit):
                for position, pair in enumerate(pairs):
                    submit(pair.method, "MATCH" if position < 150 else "UNCERTAIN")
                return True

            self.assertTrue(audit.review_and_save(self.pairs, destination, ui))
            self.assertEqual([path.name for path in destination.iterdir()], ["aggregate.json"])
            data = json.loads((destination / "aggregate.json").read_text(encoding="utf-8"))
            self.assertEqual(data["reviewed_count"], 160)
            self.assertEqual(data["labels"], {"MATCH": 150, "NO_MATCH": 0, "UNCERTAIN": 10})
            self.assertEqual(data["by_method"]["unique_exact_name_address"]["reviewed_count"], 160)
            artifact = (destination / "aggregate.json").read_text(encoding="utf-8")
            for secret in ("PRIVATE_SOURCE_NAME", "PRIVATE_SOURCE_ADDRESS", "PRIVATE_SOURCE_TYPE",
                           "PRIVATE_CATALOG_NAME", "PRIVATE_CATALOG_ADDRESS", "PRIVATE_CATALOG_TYPE"):
                self.assertNotIn(secret, artifact)
            self.assertNotIn("source_id", artifact)
            self.assertNotIn("content_id", artifact)
            self.assertNotIn("coordinate", artifact)

    def test_cancel_and_crash_leave_no_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "review"

            def cancelled(pairs, submit):
                submit(pairs[0].method, "NO_MATCH")
                return False

            self.assertFalse(audit.review_and_save(self.pairs, destination, cancelled))
            self.assertFalse(destination.exists())

            def crashed(pairs, submit):
                submit(pairs[0].method, "MATCH")
                raise RuntimeError("synthetic interruption")

            with self.assertRaises(RuntimeError):
                audit.review_and_save(self.pairs, destination, crashed)
            self.assertFalse(destination.exists())

    def test_incomplete_or_invalid_review_never_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "review"
            with self.assertRaisesRegex(ValueError, "incomplete review"):
                audit.review_and_save(self.pairs, destination,
                                      lambda pairs, submit: True)
            self.assertFalse(destination.exists())

            def invalid(pairs, submit):
                submit(pairs[0].method, "SAME")
                return True

            with self.assertRaisesRegex(ValueError, "invalid review decision"):
                audit.review_and_save(self.pairs, destination, invalid)
            self.assertFalse(destination.exists())

    def test_ephemeral_evidence_is_minimal_private_and_deleted_after_completion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "private"
            directory.mkdir(mode=0o700)
            path = audit._write_ephemeral_evidence(self.pairs, directory)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(rows), 160)
            self.assertEqual(set(rows[0]), {"ordinal", "method", "source_name", "source_address",
                                            "source_type", "catalog_name", "catalog_address",
                                            "catalog_type"})
            self.assertEqual(rows[-1]["ordinal"], 160)
            loaded = audit._read_ephemeral_evidence(path)
            self.assertEqual(loaded, self.pairs)
            destination = Path(temporary) / "aggregate"

            def complete(pairs, submit):
                for pair in pairs:
                    submit(pair.method, "UNCERTAIN")
                return True

            evidence_root = Path(temporary) / "tmp"
            evidence_root.mkdir()
            with mock.patch.object(audit.tempfile, "tempdir", evidence_root):
                self.assertTrue(audit.review_ephemeral_sample(loaded, destination, complete))
            self.assertEqual(list(evidence_root.iterdir()), [])
            self.assertEqual([p.name for p in destination.iterdir()], ["aggregate.json"])
            aggregate = (destination / "aggregate.json").read_text(encoding="utf-8")
            self.assertNotIn("PRIVATE_SOURCE_NAME", aggregate)
            self.assertNotIn("PRIVATE_CATALOG_ADDRESS", aggregate)

    def test_ephemeral_evidence_removed_on_cancel_and_exception(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            evidence_root = Path(temporary) / "tmp"
            evidence_root.mkdir()
            output = Path(temporary) / "aggregate"
            with mock.patch.object(audit.tempfile, "tempdir", evidence_root):
                self.assertFalse(audit.review_ephemeral_sample(
                    self.pairs, output, lambda pairs, submit: False))
                self.assertEqual(list(evidence_root.iterdir()), [])

                def crash(pairs, submit):
                    raise RuntimeError("PRIVATE_SOURCE_NAME")

                with self.assertRaisesRegex(RuntimeError, "PRIVATE_SOURCE_NAME"):
                    audit.review_ephemeral_sample(self.pairs, output, crash)
                self.assertEqual(list(evidence_root.iterdir()), [])
            self.assertFalse(output.exists())

    def test_input_exception_text_is_not_logged(self) -> None:
        captured = io.StringIO()
        with tempfile.TemporaryDirectory() as temporary:
            with (mock.patch.object(audit, "RESULTS_ROOT", Path(temporary)),
                  mock.patch.object(audit, "_check_local_tty"),
                  mock.patch.object(audit.identity, "_load_catalog",
                                    side_effect=ValueError("PRIVATE_SOURCE_NAME / PRIVATE_SOURCE_ADDRESS")),
                  redirect_stderr(captured)):
                code = audit.main(["--snapshot-id", "synthetic", "--sync-id", "synthetic",
                                   "--run-id", "synthetic"])
            self.assertEqual(code, 1)
            self.assertNotIn("PRIVATE_SOURCE_NAME", captured.getvalue())
            self.assertNotIn("PRIVATE_SOURCE_ADDRESS", captured.getvalue())
            self.assertEqual(list(Path(temporary).iterdir()), [])

    def test_alternate_screen_is_cleared_and_never_uses_standard_streams(self) -> None:
        first = self.pairs[0]
        second = audit.ReviewPair("SECOND_PRIVATE_NAME", "SECOND_PRIVATE_ADDRESS", "kind",
                                  "catalog", "address", "12", first.method)
        writes: list[bytes] = []
        reads = iter((b"1", b"1", b" ", b"3", b" "))
        decisions: list[tuple[str, str]] = []
        output = io.StringIO()
        with (mock.patch.object(audit, "_open_private_tty",
                                return_value=(91, b"<enter-alt>", b"<leave-alt>", b"<clear>")),
              mock.patch.object(audit.termios, "tcgetattr", return_value=[]),
              mock.patch.object(audit.termios, "tcsetattr"),
              mock.patch.object(audit.termios, "tcflush"),
              mock.patch.object(audit.tty, "setraw"),
              mock.patch.object(audit.os, "get_terminal_size", return_value=os.terminal_size((100, 30))),
              mock.patch.object(audit.os, "read", side_effect=lambda *_: next(reads)),
              mock.patch.object(audit.os, "write", side_effect=lambda fd, data: writes.append(data)),
              mock.patch.object(audit.os, "close"),
              contextlib.redirect_stdout(output), contextlib.redirect_stderr(output)):
            self.assertTrue(audit._review_window([first, second],
                                                  lambda method, label: decisions.append((method, label))))
        self.assertEqual(decisions, [(first.method, "MATCH"), (first.method, "UNCERTAIN")])
        self.assertEqual(output.getvalue(), "")
        self.assertTrue(writes[0].startswith(b"<enter-alt>"))
        self.assertTrue(writes[1].startswith(b"<clear>"))
        self.assertIn(b"Selected MATCH", writes[2])
        self.assertTrue(writes[3].startswith(b"<clear>"))
        self.assertEqual(writes[-1], b"<clear>\x1b[?25h<leave-alt>")
        self.assertNotIn(b"PRIVATE_SOURCE_NAME", writes[3])
        self.assertNotIn(b"SECOND_PRIVATE_NAME", writes[-1])

    def test_terminal_control_characters_are_neutralized(self) -> None:
        sanitized = audit._safe_text("Name\x1b[31m\nSecret")
        self.assertNotIn("\x1b", sanitized)
        self.assertNotIn("\n", sanitized)

    def test_one_pass_master_keeps_existing_match_and_sample_rule(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            master = Path(temporary) / "synthetic.csv"
            with master.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=("POI_ID", "POI_NM", "ROAD_NM_ADDR",
                                                           "SGG_CD", "X_COORD", "Y_COORD",
                                                           "ASORT_LCLASDC"))
                writer.writeheader()
                writer.writerow({"POI_ID": "source-1", "POI_NM": "Synthetic Place",
                                 "ROAD_NM_ADDR": "Synthetic Road", "SGG_CD": "R",
                                 "X_COORD": "1", "Y_COORD": "2", "ASORT_LCLASDC": "synthetic-type"})
            catalog = [audit.identity.CatalogPoi("catalog-1", "Synthetic Place",
                                                 "Synthetic Road", "R", "D", "12", "listed")]
            prior = audit.scenarios._identity_map(catalog, {"source-1"}, master,
                                                  "synthetic", "synthetic-snapshot")
            self.assertEqual(prior["source-1"][0], "MATCHED")
            specs = []
            for role, trip_id in (("TL", "trip-a"), ("VL", "trip-b")):
                root = Path(temporary) / role
                root.mkdir()
                with (root / "TN_TRAVEL.csv").open("w", encoding="utf-8", newline="") as stream:
                    writer = csv.DictWriter(stream, fieldnames=("TRAVEL_ID", "TRAVELER_ID"))
                    writer.writeheader()
                    writer.writerow({"TRAVEL_ID": trip_id, "TRAVELER_ID": "traveler"})
                with (root / "TN_VISIT_AREA_INFO.csv").open("w", encoding="utf-8", newline="") as stream:
                    writer = csv.DictWriter(stream, fieldnames=("TRAVEL_ID", "POI_ID"))
                    writer.writeheader()
                    writer.writerow({"TRAVEL_ID": trip_id, "POI_ID": "source-1"})
                specs.append(audit.shared.InputSpec("synthetic", role, root))
            captured = io.StringIO()
            with (mock.patch.object(audit.shared, "REGIONS", ("synthetic",)),
                  mock.patch.object(audit.scenarios, "AUDIT_MAX_PER_STRATUM", 1),
                  mock.patch.object(audit, "EXPECTED_SAMPLE_SIZE", 2),
                  contextlib.redirect_stdout(captured)):
                pairs = audit.build_sample(catalog, specs, {"synthetic": master}, "synthetic-snapshot")
            for spec in specs:
                reference = audit.shared._read_split(spec)
                _, item_ids = audit._audit_split_ids(spec, lambda *_: None)
                self.assertEqual(item_ids, {event.item_id for event in reference.events})
            self.assertEqual(len(pairs), 2)
            self.assertTrue(all(pair.method == prior["source-1"][1] for pair in pairs))
            self.assertEqual(pairs[0].source_type, "L1=synthetic-type")
            self.assertNotIn("Synthetic Place", captured.getvalue())
            self.assertNotIn("source-1", captured.getvalue())

    @unittest.skipUnless(hasattr(pty, "fork"), "Unix PTY required")
    def test_synthetic_pairs_in_real_alternate_screen_pty(self) -> None:
        child, fd = pty.fork()
        if child == 0:
            try:
                os.environ["TERM"] = "xterm"
                local_fd = os.open("/dev/tty", os.O_RDWR)
                fcntl.ioctl(local_fd, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 100, 0, 0))
                os.close(local_fd)
                pair = self.pairs[0]
                second = audit.ReviewPair("SECOND_PRIVATE_NAME", "SECOND_PRIVATE_ADDRESS",
                                          "kind", "catalog", "address", "12", pair.method)
                labels = []
                done = audit._review_window([pair, second], lambda _, label: labels.append(label))
                os._exit(0 if done and labels == ["MATCH", "UNCERTAIN"] else 2)
            except BaseException:
                os._exit(3)
        captured = bytearray()
        try:
            deadline = time.monotonic() + 5
            for marker, key in ((b"pair 1/2", b"1 "), (b"pair 2/2", b"3 ")):
                while marker not in captured and time.monotonic() < deadline:
                    ready, _, _ = select.select([fd], [], [], 0.1)
                    if ready:
                        captured.extend(os.read(fd, 65536))
                self.assertIn(marker, captured)
                os.write(fd, key)
            _, status = os.waitpid(child, 0)
            self.assertEqual(os.waitstatus_to_exitcode(status), 0)
            self.assertIn(b"SECOND_PRIVATE_NAME", captured)
            self.assertIn(b"\x1b[?1049h", captured)
        finally:
            try:
                os.kill(child, signal.SIGKILL)
            except ProcessLookupError:
                pass
            os.close(fd)


if __name__ == "__main__":
    unittest.main()
