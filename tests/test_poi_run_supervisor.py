"""Synthetic tests for the privacy-safe analyzer supervisor."""

from __future__ import annotations

import io
import os
import signal
import sys
import json
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "recommendation"))
import poi_run_supervisor as supervisor  # noqa: E402
import analyze_poi_catalog_enhanced as enhanced  # noqa: E402
from unittest import mock  # noqa: E402


class SinkFails(io.StringIO):
    def write(self, value: str) -> int:
        raise OSError("private sink diagnostic")


class PoiRunSupervisorTests(unittest.TestCase):
    def test_shared_jeju_region_and_stopped_marker_are_retained_safely(self) -> None:
        jeju = "candidate_generation=complete:jeju-islands; completed_source_items=10+; candidate_support=10+; elapsed_seconds=44"
        stopped = "[stopped] enhanced identity run failed safely; phase=candidate_generation_scoring; exception_type=RuntimeError; row_level_output=false"
        self.assertEqual(supervisor.sanitize_marker(jeju), jeju)
        self.assertEqual(supervisor.sanitize_marker(stopped), stopped)
        self.assertIsNone(supervisor.sanitize_marker(
            "[stopped] enhanced identity run failed safely; phase=bad; exception_type=RuntimeError; "
            "row_level_output=false; private=source"))

    def test_completion_marker_accepts_only_coarse_sample_and_metric_counts(self) -> None:
        for bucket in ("0", "<10", "10+"):
            marker = ("enhanced_identity_complete=true; source_item_count=10+; "
                      f"metrics={bucket}; sample_size={bucket}; raw_values_emitted=false")
            self.assertEqual(supervisor.sanitize_marker(marker), marker)
        for exact in ("1", "9", "10"):
            marker = ("enhanced_identity_complete=true; source_item_count=10+; "
                      f"metrics=10+; sample_size={exact}; raw_values_emitted=false")
            self.assertIsNone(supervisor.sanitize_marker(marker))

    def test_analyzer_nonzero_is_independent_of_sanitizer_failure(self) -> None:
        output = SinkFails()
        errors = io.StringIO()
        command = [sys.executable, "-c",
                   "print('catalog_load=started', flush=True); raise SystemExit(7)"]
        result = supervisor.run_supervised(command, output=output, errors=errors)
        self.assertEqual(result.analyzer_returncode, 7)
        self.assertIsNone(result.analyzer_signal)
        self.assertEqual(result.sanitizer_error_type, "OSError")
        self.assertIn("analyzer_returncode=7", errors.getvalue())
        self.assertIn("sanitizer_error_type=OSError", errors.getvalue())
        self.assertNotIn("private sink diagnostic", errors.getvalue())

    def test_child_signal_is_distinct_from_normal_nonzero_exit(self) -> None:
        errors = io.StringIO()
        code = f"import os, signal; os.kill(os.getpid(), signal.{signal.Signals.SIGTERM.name})"
        result = supervisor.run_supervised([sys.executable, "-c", code],
                                           output=io.StringIO(), errors=errors)
        self.assertEqual(result.analyzer_returncode, -signal.SIGTERM)
        self.assertEqual(result.analyzer_signal, signal.SIGTERM)
        self.assertIn("analyzer_signal=SIGTERM", errors.getvalue())
        self.assertIn("sanitizer_error_type=none", errors.getvalue())

    def test_huge_unterminated_child_line_is_dropped_without_leaking_value(self) -> None:
        output, errors = io.StringIO(), io.StringIO()
        command = [sys.executable, "-c",
                   "import sys; sys.stdout.buffer.write(b'private-row-value' * 100000); "
                   "sys.stdout.flush(); print('catalog_load=started', file=sys.stderr, flush=True)"]
        result = supervisor.run_supervised(command, output=output, errors=errors)
        self.assertEqual(result.analyzer_returncode, 0)
        self.assertEqual(result.sanitizer_error_type, None)
        self.assertEqual(output.getvalue(), "catalog_load=started\n")
        self.assertNotIn("private-row-value", output.getvalue() + errors.getvalue())

    def test_high_volume_rejected_output_drains_both_pipes(self) -> None:
        output, errors = io.StringIO(), io.StringIO()
        command = [sys.executable, "-c",
                   "import os; payload=b'unapproved-output\\n'; "
                   "[(os.write(1, payload), os.write(2, payload)) for _ in range(12000)]"]
        result = supervisor.run_supervised(command, output=output, errors=errors)
        self.assertEqual(result.analyzer_returncode, 0)
        self.assertEqual(result.sanitizer_error_type, None)
        self.assertEqual(output.getvalue(), "")
        self.assertNotIn("unapproved-output", errors.getvalue())

    def test_supervisor_sigterm_is_forwarded_drained_and_waited(self) -> None:
        recommendation_dir = Path(supervisor.__file__).resolve().parent
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary) / "synthetic-run"
            child_code = (
                "import pathlib, signal, sys, time\n"
                f"sys.path.insert(0, {str(recommendation_dir)!r})\n"
                "from analyze_poi_catalog_enhanced import RunStatus\n"
                "out = pathlib.Path(sys.argv[1]); out.mkdir(mode=0o700)\n"
                "checkpoint = RunStatus(out, 'synthetic-run'); checkpoint.update()\n"
                "checkpoint.progress('candidate_generation', region='capital', batch=3, "
                "work_phase='scoring', completed_work=12)\n"
                "pathlib.Path(out, 'child.pid').write_text(str(__import__('os').getpid()))\n"
                "def stop(signum, frame):\n"
                "    checkpoint.update('interrupted', signal_number=signum)\n"
                "    print('[stopped] enhanced identity run failed safely; "
                "phase=candidate_generation; exception_type=RunInterrupted; "
                "row_level_output=false', file=sys.stderr, flush=True)\n"
                "    raise SystemExit(143)\n"
                "signal.signal(signal.SIGTERM, stop)\n"
                "print('catalog_load=started', flush=True)\n"
                "while True: time.sleep(1)\n"
            )
            driver_code = (
                "import sys\n"
                f"sys.path.insert(0, {str(recommendation_dir)!r})\n"
                "import poi_run_supervisor as supervisor\n"
                f"child = [{sys.executable!r}, '-c', {child_code!r}, {str(output_dir)!r}]\n"
                "result = supervisor.run_supervised(child)\n"
                "raise SystemExit(supervisor.supervisor_exit_code(result))\n"
            )
            driver = subprocess.Popen([sys.executable, "-c", driver_code],
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                      text=True, encoding="utf-8")
            try:
                self.assertEqual(driver.stdout.readline(), "catalog_load=started\n")
                driver.send_signal(signal.SIGTERM)
                stdout, stderr = driver.communicate(timeout=5)
            finally:
                if driver.poll() is None:
                    driver.kill()
                    driver.communicate(timeout=5)
            self.assertEqual(driver.returncode, 128 + signal.SIGTERM)
            self.assertEqual(stdout, "")
            self.assertIn("analyzer_returncode=143", stderr)
            self.assertIn("analyzer_signal=SIGTERM", stderr)
            self.assertIn("interrupted=true", stderr)
            state = json.loads((output_dir / enhanced.RUN_STATUS_FILENAME).read_text())
            self.assertEqual(state["status"], "interrupted")
            self.assertEqual(state["signal_number"], signal.SIGTERM)
            child_pid = int((output_dir / "child.pid").read_text())
            with self.assertRaises(ProcessLookupError):
                os.kill(child_pid, 0)

    def test_sigterm_during_audit_review_remains_sigterm_through_supervisor(self) -> None:
        recommendation_dir = Path(supervisor.__file__).resolve().parent
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output_root = root / "results"
            output_root.mkdir(mode=0o700)
            evidence_root = root / "private-evidence"
            evidence_root.mkdir(mode=0o700)
            ready_path = root / "review-ready"
            child_pid_path = root / "analyzer.pid"
            analyzer_code = (
                "import pathlib, sys, time\n"
                f"sys.path.insert(0, {str(recommendation_dir)!r})\n"
                "from types import SimpleNamespace\n"
                "import adjudicate_poi_candidate_sample as audit\n"
                "import analyze_poi_catalog_enhanced as analyzer\n"
                f"analyzer.RESULTS_ROOT = pathlib.Path({str(output_root)!r})\n"
                "analyzer.preflight_terminal = lambda: None\n"
                "analyzer.identity._load_catalog = lambda _snapshot: ([], {'catalog_sha256': 'synthetic'})\n"
                "analyzer.identity._validate_sync = lambda _catalog, _sync: {'sync_sha256': 'synthetic'}\n"
                "analyzer.identity._source_specs = lambda *_args, **_kwargs: ([], {})\n"
                "analyzer._source_rows = lambda *_args, **_kwargs: "
                "({}, {}, [], {}, SimpleNamespace(collision_counts=lambda: {}))\n"
                "analyzer._metrics = lambda *_args: [{'scope':'all','scenario':'A','split':'ALL',"
                "'unit':'items','metric':'coverage','value':'<10','support':'10+'}]\n"
                "observation = audit.AuditObservation('synthetic-region', 'stage2_review', "
                "'development', 'synthetic_method', 'SYNTHETIC_SOURCE', 'SYNTHETIC_ADDRESS', "
                "'synthetic', (audit.CandidateView('SYNTHETIC_CANDIDATE', 'SYNTHETIC_ADDRESS', "
                "'12'),), 1)\n"
                "support = [{'region':'synthetic-region','stratum':'stage2_review',"
                "'partition':'development','selected_count':'<10','available_support':'10+',"
                "'methods':{'synthetic_method':'10+'}}]\n"
                "analyzer._audit_observations = lambda *_args, **_kwargs: ([observation], support)\n"
                "def block_review(_observations, _submit):\n"
                f"    pathlib.Path({str(ready_path)!r}).write_text('ready')\n"
                f"    pathlib.Path({str(child_pid_path)!r}).write_text(str(__import__('os').getpid()))\n"
                "    while True: time.sleep(1)\n"
                "audit._review_window = block_review\n"
                "raise SystemExit(analyzer.main(['--snapshot-id','snapshot-v1','--sync-id',"
                "'sync-v1','--run-id','synthetic-sigterm-review','--audit']))\n"
            )
            driver_code = (
                "import sys\n"
                f"sys.path.insert(0, {str(recommendation_dir)!r})\n"
                "import poi_run_supervisor as supervisor\n"
                f"command = [{sys.executable!r}, '-c', {analyzer_code!r}]\n"
                "result = supervisor.run_supervised(command)\n"
                "raise SystemExit(supervisor.supervisor_exit_code(result))\n"
            )
            environment = dict(os.environ)
            environment["TMPDIR"] = str(evidence_root)
            driver = subprocess.Popen([sys.executable, "-c", driver_code],
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                      text=True, encoding="utf-8", env=environment)
            try:
                deadline = time.monotonic() + 10
                while not ready_path.exists() and driver.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(ready_path.exists(), "synthetic audit UI did not start")
                driver.send_signal(signal.SIGTERM)
                stdout, stderr = driver.communicate(timeout=10)
            finally:
                if driver.poll() is None:
                    driver.kill()
                    driver.communicate(timeout=5)

            self.assertEqual(driver.returncode, 128 + signal.SIGTERM)
            self.assertNotIn("SYNTHETIC_SOURCE", stdout + stderr)
            self.assertIn("exception_type=AuditInterrupted", stderr)
            self.assertIn("analyzer_returncode=143", stderr)
            self.assertIn("analyzer_signal=SIGTERM", stderr)
            self.assertIn("interrupted=true", stderr)
            run_root = output_root / "synthetic-sigterm-review"
            status = json.loads((run_root / enhanced.RUN_STATUS_FILENAME).read_text())
            self.assertEqual(status["status"], "interrupted")
            self.assertEqual(status["signal_number"], signal.SIGTERM)
            self.assertEqual(status["phase"], "audit_review")
            aggregate_checkpoint = json.loads((run_root / "aggregate_checkpoint.json").read_text())
            self.assertEqual(aggregate_checkpoint["status"], "incomplete")
            self.assertFalse((run_root / "audit").exists())
            self.assertEqual(list(evidence_root.iterdir()), [])
            child_pid = int(child_pid_path.read_text())
            with self.assertRaises(ProcessLookupError):
                os.kill(child_pid, 0)

    def test_analyzer_handled_signal_is_reported_separately_from_exit_status(self) -> None:
        errors = io.StringIO()
        command = [sys.executable, "-c",
                   "print('[stopped] enhanced identity run failed safely; phase=catalog_load; "
                   "exception_type=RunInterrupted; row_level_output=false', flush=True); "
                   "raise SystemExit(143)"]
        result = supervisor.run_supervised(command, output=io.StringIO(), errors=errors)
        self.assertEqual(result.analyzer_returncode, 143)
        self.assertEqual(result.analyzer_signal, signal.SIGTERM)
        self.assertTrue(result.interrupted)
        self.assertIn("analyzer_signal=SIGTERM", errors.getvalue())

    def test_unhandled_signal_atomically_marks_running_checkpoint_interrupted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "synthetic-run"
            output.mkdir(mode=0o700)
            checkpoint = enhanced.RunStatus(output, "synthetic-run")
            checkpoint.phase = "candidate_generation"
            checkpoint.region = "jeju-islands"
            checkpoint.batch = 9
            checkpoint.update()
            with mock.patch.object(supervisor, "RESULTS_ROOT", Path(temporary)):
                supervisor.persist_unhandled_signal(
                    "synthetic-run", supervisor.SupervisorResult(-signal.SIGKILL, None))
            state = json.loads((output / enhanced.RUN_STATUS_FILENAME).read_text(encoding="utf-8"))
            self.assertEqual(state["status"], "interrupted")
            self.assertEqual(state["phase"], "candidate_generation")
            self.assertEqual(state["region"], "jeju-islands")
            self.assertEqual(state["batch"], 9)
            self.assertEqual(state["signal_number"], signal.SIGKILL)


if __name__ == "__main__":
    unittest.main()
