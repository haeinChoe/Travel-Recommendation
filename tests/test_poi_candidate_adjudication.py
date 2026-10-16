"""Synthetic privacy checks for the staged candidate audit UI."""

from __future__ import annotations

import contextlib
import io
import json
import os
import pty
import select
import signal
import struct
import sys
import tempfile
import termios
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "recommendation"))
import adjudicate_poi_candidate_sample as audit  # noqa: E402


class CandidateAuditPrivacyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.observations = [audit.AuditObservation(
            region="synthetic-region", stratum="stage2_review", partition="development",
            method="normalized_punctuation", source_name="PRIVATE_SOURCE_NAME",
            source_address="PRIVATE_SOURCE_ADDRESS", source_type="PRIVATE_SOURCE_TYPE",
            candidates=(audit.CandidateView("PRIVATE_CATALOG_NAME", "PRIVATE_CATALOG_ADDRESS", "12"),),
            candidate_count=1,
        ) for _ in range(4)]

    def test_complete_review_persists_aggregate_only_and_deletes_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "temp"
            root.mkdir()
            output = Path(temporary) / "result"

            def ui(observations, submit):
                for observation in observations:
                    submit(observation, "MATCH")
                return True

            with mock.patch.object(audit.tempfile, "tempdir", root):
                self.assertTrue(audit.review_ephemeral(
                    self.observations, output, ui, adjudicator_role="independent"))
            self.assertEqual(list(root.iterdir()), [])
            self.assertEqual([path.name for path in output.iterdir()], ["aggregate.json"])
            payload = json.loads((output / "aggregate.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["reviewed_count"], 4)
            self.assertEqual(payload["labels"], {"MATCH": 4, "NO_MATCH": 0, "UNCERTAIN": 0})
            self.assertEqual(set(payload), {"reviewed_count", "labels", "by_method_stratum_partition",
                                            "adjudicator_role", "privacy"})
            encoded = json.dumps(payload)
            for value in ("PRIVATE_SOURCE_NAME", "PRIVATE_SOURCE_ADDRESS", "PRIVATE_SOURCE_TYPE",
                          "PRIVATE_CATALOG_NAME", "PRIVATE_CATALOG_ADDRESS"):
                self.assertNotIn(value, encoded)

    def test_cancel_and_exception_leave_no_output_or_ephemeral_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "temp"
            root.mkdir()
            output = Path(temporary) / "result"
            with mock.patch.object(audit.tempfile, "tempdir", root):
                self.assertFalse(audit.review_ephemeral(self.observations, output, lambda *_: False))
                self.assertEqual(list(root.iterdir()), [])

                def fail(*_):
                    raise RuntimeError("PRIVATE_SOURCE_NAME")

                with self.assertRaisesRegex(RuntimeError, "PRIVATE_SOURCE_NAME"):
                    audit.review_ephemeral(self.observations, output, fail)
                self.assertEqual(list(root.iterdir()), [])
            self.assertFalse(output.exists())

    def test_sigterm_is_handled_and_removes_ephemeral_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "temp"
            root.mkdir()
            output = Path(temporary) / "result"
            prior_sigterm_handler = signal.getsignal(signal.SIGTERM)

            def terminate(*_):
                self.assertEqual(len(list(root.iterdir())), 1)
                os.kill(os.getpid(), signal.SIGTERM)

            with mock.patch.object(audit.tempfile, "tempdir", root):
                with self.assertRaises(audit.AuditInterrupted) as caught:
                    audit.review_ephemeral(self.observations, output, terminate)
            self.assertEqual(caught.exception.signal_number, signal.SIGTERM)
            self.assertEqual(list(root.iterdir()), [])
            self.assertFalse(output.exists())
            self.assertEqual(signal.getsignal(signal.SIGTERM), prior_sigterm_handler)

    def test_sigterm_during_handler_installation_restores_prior_handler(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "temp"
            root.mkdir()
            output = Path(temporary) / "result"
            prior_sigterm_handler = signal.getsignal(signal.SIGTERM)
            real_signal = signal.signal
            termination_sent = False

            def install_then_terminate(signum, handler):
                nonlocal termination_sent
                result = real_signal(signum, handler)
                if (signum == signal.SIGTERM and handler is audit._handle_sigterm
                        and not termination_sent):
                    termination_sent = True
                    os.kill(os.getpid(), signal.SIGTERM)
                return result

            with mock.patch.object(audit.tempfile, "tempdir", root):
                with mock.patch.object(audit.signal, "signal", side_effect=install_then_terminate):
                    with self.assertRaises(audit.AuditInterrupted) as caught:
                        audit.review_ephemeral(self.observations, output)
            self.assertEqual(caught.exception.signal_number, signal.SIGTERM)
            self.assertTrue(termination_sent)
            self.assertEqual(list(root.iterdir()), [])
            self.assertFalse(output.exists())
            self.assertEqual(signal.getsignal(signal.SIGTERM), prior_sigterm_handler)

    def test_duplicate_or_unrecognized_label_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "result"

            def duplicate(observations, submit):
                submit(observations[0], "MATCH")
                submit(observations[0], "NO_MATCH")
                return True

            with self.assertRaisesRegex(ValueError, "invalid audit label"):
                audit.review_ephemeral(self.observations, output, duplicate)
            self.assertFalse(output.exists())

    def test_terminal_controls_are_removed(self) -> None:
        self.assertEqual(audit._safe_text("Place\x1b[31m\nName"), "Place [31m Name")

    def test_targeted_address_audit_explains_primary_pair_label_semantics(self) -> None:
        observation = audit.AuditObservation(
            region="synthetic-region", stratum="address_punctuation_variant_primary_pair",
            partition="development", method="punctuation_address_variant",
            source_name="PRIVATE_SOURCE_NAME", source_address="PRIVATE_SOURCE_ADDRESS",
            source_type="PRIVATE_SOURCE_TYPE",
            candidates=(audit.CandidateView("PRIVATE_CATALOG_NAME", "PRIVATE_CATALOG_ADDRESS", "12"),),
            candidate_count=3,
        )
        screen = audit._render(observation, 1, 1, 120).decode("utf-8")
        self.assertIn("single primary candidate", screen)
        self.assertIn("presented pair is the same place", screen)
        self.assertIn("Other candidates are not shown", screen)
        self.assertIn("Candidates shown: 1 of 3", screen)

    def test_conflicting_source_evidence_renders_observed_pairs_together(self) -> None:
        observation = audit.AuditObservation(
            region="synthetic-region", stratum="multi_candidate_ambiguous",
            partition="validation", method="conflicting_source_metadata",
            source_name="Museum Alpha", source_address="Address X",
            source_type="synthetic-type", candidates=(), candidate_count=2,
            source_candidate_groups=(
                audit.SourceCandidateGroup(
                    "Museum Alpha", "Address X",
                    (audit.CandidateView("Catalog Alpha", "Catalog Address X", "12"),), 1,
                    "Lot X"),
                audit.SourceCandidateGroup(
                    "Museum Beta", "Address Y",
                    (audit.CandidateView("Catalog Beta", "Catalog Address Y", "14"),), 1,
                    "Lot Y"),
            ),
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = audit._write_private_evidence([observation], Path(temporary))
            restored = audit._read_private_evidence(path)[0]

        screen = audit._render(restored, 1, 1, 120).decode("utf-8")
        self.assertIn("Source pair 1 name: Museum Alpha\r\nSource pair 1 road address: Address X\r\n"
                      "Source pair 1 lot address: Lot X", screen)
        self.assertIn("Source pair 2 name: Museum Beta\r\nSource pair 2 road address: Address Y\r\n"
                      "Source pair 2 lot address: Lot Y", screen)
        first_pair = screen.index("Source pair 1 name")
        second_pair = screen.index("Source pair 2 name")
        self.assertLess(first_pair, screen.index("Catalog Alpha"))
        self.assertLess(screen.index("Catalog Alpha"), second_pair)
        self.assertGreater(screen.index("Catalog Beta"), second_pair)
        self.assertNotIn("Source name: Museum Alpha", screen)

    def test_tui_uses_private_alternate_screen_without_stdout_capture(self) -> None:
        observation = self.observations[0]
        writes: list[bytes] = []
        keys = iter((b"1", b" "))
        stdout = io.StringIO()
        submitted = []
        with (mock.patch.object(audit, "_open_tty", return_value=(91, b"<enter>", b"<leave>", b"<clear>")),
              mock.patch.object(audit.termios, "tcgetattr", return_value=[]),
              mock.patch.object(audit.termios, "tcsetattr"),
              mock.patch.object(audit.termios, "tcflush"),
              mock.patch("adjudicate_poi_candidate_sample.tty.setraw"),
              mock.patch.object(audit.os, "get_terminal_size", return_value=os.terminal_size((100, 30))),
              mock.patch.object(audit.os, "read", side_effect=lambda *_: next(keys)),
              mock.patch.object(audit.os, "write", side_effect=lambda _fd, data: writes.append(data)),
              mock.patch.object(audit.os, "close"),
              contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stdout)):
            self.assertTrue(audit._review_window([observation], lambda item, label: submitted.append(label)))
        self.assertEqual(submitted, ["MATCH"])
        self.assertEqual(stdout.getvalue(), "")
        self.assertTrue(writes[0].startswith(b"<enter>"))
        self.assertTrue(writes[1].startswith(b"<clear>"))
        self.assertIn(b"PRIVATE_SOURCE_NAME", writes[1])
        self.assertEqual(writes[-1], b"<clear>\x1b[?25h<leave>")

    @unittest.skipUnless(hasattr(pty, "fork"), "Unix PTY required")
    def test_synthetic_candidate_pair_renders_in_alternate_screen(self) -> None:
        child, fd = pty.fork()
        if child == 0:
            try:
                os.environ["TERM"] = "xterm"
                local_fd = os.open("/dev/tty", os.O_RDWR)
                import fcntl
                fcntl.ioctl(local_fd, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 100, 0, 0))
                os.close(local_fd)
                done = audit._review_window([self.observations[0]], lambda *_: None)
                os._exit(0 if done else 2)
            except BaseException:
                os._exit(3)
        captured = bytearray()
        try:
            deadline = time.monotonic() + 5
            while b"item 1/1" not in captured and time.monotonic() < deadline:
                ready, _, _ = select.select([fd], [], [], 0.1)
                if ready:
                    captured.extend(os.read(fd, 65536))
            self.assertIn(b"item 1/1", captured)
            os.write(fd, b"1 ")
            _, status = os.waitpid(child, 0)
            self.assertEqual(os.waitstatus_to_exitcode(status), 0)
            self.assertIn(b"PRIVATE_CATALOG_NAME", captured)
            self.assertIn(b"\x1b[?1049h", captured)
        finally:
            try:
                os.kill(child, signal.SIGKILL)
            except ProcessLookupError:
                pass
            os.close(fd)


if __name__ == "__main__":
    unittest.main()
