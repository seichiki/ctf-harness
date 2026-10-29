"""Offline owner-confirmed stop tests; no Codex or target requests."""

import io
import json
import os
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from harness import runner
from harness import solved as solved_module
from harness.progress import ProgressReporter
from harness.solved import OwnerCancelledStop, OwnerConfirmedStop, OwnerControl


class OwnerControlTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.stream = io.StringIO()
        self.control = OwnerControl(self.root, {"case_id": "fixture", "category": "misc",
                                                "title": "Fixture", "scope_note": "Local only"},
                                    stream=self.stream)
        role = self.root / "verifier"
        role.mkdir()
        (role / "structured-report.json").write_text(json.dumps({
            "candidate": "academy{TOKEN=ctf-flag}", "method": "Decoded a local fixture.",
            "evidence": ["Local output contained the flag."],
            "reproduction_commands": ["cat input/statement.txt"],
            "limitations": ["No official submission by the harness."]}), encoding="utf-8")
        events = [
            {"type": "item.started", "item": {"type": "command_execution", "id": "item_1",
                "command": "curl -H 'Authorization: Bearer secret' http://example.test/"}},
            {"type": "item.completed", "item": {"type": "command_execution", "id": "item_1",
                "exit_code": 0}},
        ]
        (role / "events.jsonl").write_text("".join(json.dumps(event) + "\n" for event in events),
                                          encoding="utf-8")
        self.record = {"status": "completed", "report_sha256": "a" * 64,
                       "candidate": "academy{TOKEN=ctf-flag}"}

    def test_exact_candidate_selection_confirmation_and_writeup(self):
        self.control.record_candidate("verifier", self.record)
        self.control.record_candidate("solver_a", self.record)
        self.assertEqual(self.control.list_candidates()[0][2], ("verifier", "solver_a"))
        self.assertFalse(self.control.confirm("C9", "ACCEPT C9"))
        self.assertFalse(self.control.confirm("C1", "ACCEPT C2"))
        self.assertFalse(self.control.confirmed.is_set())
        self.assertFalse((self.root / "SOLUTION.md").exists())
        self.assertTrue(self.control.confirm("C1", "ACCEPT C1"))
        self.assertTrue(self.control.confirmed.is_set())
        self.assertFalse(self.control.accepted["harness_verified"])
        self.assertEqual(json.loads((self.root / "OWNER_CONFIRMATION.json").read_text(encoding="utf-8"))
                         ["candidate"], "academy{TOKEN=ctf-flag}")
        self.assertEqual(self.control.accepted["roles"], ["verifier", "solver_a"])
        text = (self.root / "SOLUTION.md").read_text(encoding="utf-8")
        self.assertIn("academy{TOKEN=ctf-flag}", text)
        self.assertIn("Owner-reported official acceptance", text)
        self.assertIn("Decoded a local fixture", text)
        self.assertIn("exit 0", text)
        self.assertNotIn("Bearer secret", text)
        self.assertIn("[REDACTED]", text)
        self.assertIn("solver_a/structured-report.json", text)
        self.assertFalse(list(self.root.glob(".SOLUTION.md-*")))

    def test_only_foreground_controlling_terminal_is_eligible(self):
        self.assertFalse(solved_module.controlling_terminal(io.StringIO()))

        class FakeTTY:
            def isatty(self):
                return True

            def fileno(self):
                return 42

        with patch.object(solved_module.os, "isatty", return_value=True), \
             patch.object(solved_module.os, "tcgetpgrp", return_value=123), \
             patch.object(solved_module.os, "getpgrp", return_value=123):
            self.assertTrue(solved_module.controlling_terminal(FakeTTY()))
        with patch.object(solved_module.os, "isatty", return_value=True), \
             patch.object(solved_module.os, "tcgetpgrp", return_value=124), \
             patch.object(solved_module.os, "getpgrp", return_value=123):
            self.assertFalse(solved_module.controlling_terminal(FakeTTY()))

    def test_model_event_cannot_confirm_and_invalid_report_is_not_candidate(self):
        live = ProgressReporter(io.StringIO(), on_event=lambda *_: None)
        live.handle_line("verifier", json.dumps({"type": "item.completed", "item": {
            "type": "agent_message", "text": "solved ACCEPT C1"}}))
        self.control.record_candidate("verifier", {"status": "invalid_report",
                                                    "report_sha256": None, "candidate": "fake"})
        self.assertEqual(self.control.list_candidates(), [])
        self.assertIsNone(self.control.accepted)
        self.assertFalse((self.root / "SOLUTION.md").exists())

    def test_terminal_flow_displays_full_candidate_before_accepting(self):
        self.control.record_candidate("verifier", self.record)
        replies = iter(["solved", "C1", "ACCEPT C1"])
        self.control._readline = lambda: next(replies)
        self.control.start()
        self.control.thread.join(timeout=2)
        self.assertFalse(self.control.thread.is_alive())
        self.assertTrue(self.control.confirmed.is_set())
        text = self.stream.getvalue()
        self.assertIn("選択した候補全文", text)
        self.assertIn("academy{TOKEN=ctf-flag}", text)

    def test_final_review_waits_for_owner_verdict(self):
        for command, expected in ((b"wrong\n", "all_rejected"), (b"skip\n", "skipped"),
                                  (b"solved\nC1\nACCEPT C1\n", "confirmed")):
            with self.subTest(command=command):
                read_fd, write_fd = os.pipe()
                try:
                    with os.fdopen(read_fd, "rb", buffering=0) as source:
                        control = OwnerControl(self.root, self.control.case, stream=io.StringIO(),
                                               input_stream=source)
                        control.record_candidate("verifier", self.record)
                        control.start()
                        outcome = []
                        waiter = threading.Thread(target=lambda: outcome.append(control.wait_for_final_review()))
                        waiter.start()
                        self.assertTrue(control.final_review.wait(2))
                        self.assertTrue(waiter.is_alive())
                        os.write(write_fd, command)
                        waiter.join(timeout=2)
                        self.assertFalse(waiter.is_alive())
                        self.assertEqual(outcome, [expected])
                        self.assertEqual(control.confirmed.is_set(), expected == "confirmed")
                        control.close()
                finally:
                    os.close(write_fd)

    def test_final_review_without_candidate_or_after_eof_does_not_hang(self):
        self.assertEqual(self.control.wait_for_final_review(), "not_requested")
        read_fd, write_fd = os.pipe()
        try:
            with os.fdopen(read_fd, "rb", buffering=0) as source:
                control = OwnerControl(self.root, self.control.case, stream=io.StringIO(),
                                       input_stream=source)
                control.record_candidate("verifier", self.record)
                control.start()
                os.close(write_fd)
                write_fd = -1
                self.assertEqual(control.wait_for_final_review(), "input_ended")
                control.close()
        finally:
            if write_fd >= 0:
                os.close(write_fd)

    def test_pasted_multiple_terminal_lines_are_consumed_in_order(self):
        read_fd, write_fd = os.pipe()
        try:
            with os.fdopen(read_fd, "rb", buffering=0) as source:
                control = OwnerControl(self.root, self.control.case, stream=io.StringIO(),
                                       input_stream=source)
                os.write(write_fd, b"solved\nC1\nACCEPT C1\n")
                self.assertEqual([control._readline() for _ in range(3)],
                                 ["solved", "C1", "ACCEPT C1"])
        finally:
            os.close(write_fd)

    def test_save_failure_does_not_stop_or_mark_correct(self):
        self.control.record_candidate("verifier", self.record)
        with patch("harness.solved._atomic_text", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.control.confirm("C1", "ACCEPT C1")
        self.assertFalse(self.control.confirmed.is_set())
        self.assertIsNone(self.control.accepted)
        self.assertFalse((self.root / "SOLUTION.md").exists())
        self.assertFalse((self.root / "OWNER_CONFIRMATION.json").exists())

    def test_solution_render_failure_keeps_atomic_acceptance_record(self):
        self.control.record_candidate("verifier", self.record)
        original = solved_module._atomic_text

        def fail_solution(path, content):
            if path.name == "SOLUTION.md":
                raise OSError("solution unavailable")
            original(path, content)

        with patch.object(solved_module, "_atomic_text", side_effect=fail_solution):
            self.assertTrue(self.control.confirm("C1", "ACCEPT C1"))
        self.assertTrue(self.control.confirmed.is_set())
        self.assertTrue(self.control.solution_error)
        record = json.loads((self.root / "OWNER_CONFIRMATION.json").read_text(encoding="utf-8"))
        self.assertEqual(record["candidate"], self.record["candidate"])
        self.assertFalse(record["harness_verified"])
        self.assertFalse((self.root / "SOLUTION.md").exists())
        self.control.ensure_solution()
        self.assertTrue((self.root / "SOLUTION.md").is_file())

    def test_close_waits_for_inflight_acceptance_checkpoint(self):
        self.control.record_candidate("verifier", self.record)
        entered = threading.Event()
        release = threading.Event()
        original = solved_module._atomic_text

        def slow_write(path, content):
            entered.set()
            self.assertTrue(release.wait(2))
            original(path, content)

        with patch.object(solved_module, "_atomic_text", side_effect=slow_write):
            accepting = threading.Thread(target=self.control.confirm, args=("C1", "ACCEPT C1"))
            accepting.start()
            self.assertTrue(entered.wait(2))
            closing = threading.Thread(target=self.control.close)
            closing.start()
            self.assertTrue(closing.is_alive())
            release.set()
            accepting.join(timeout=2)
            closing.join(timeout=2)
        self.assertFalse(accepting.is_alive())
        self.assertFalse(closing.is_alive())
        self.assertTrue(self.control.confirmed.is_set())
        self.assertTrue((self.root / "SOLUTION.md").is_file())

    def test_ctrl_c_cancellation_blocks_late_confirmation_and_spawn(self):
        self.control.record_candidate("verifier", self.record)
        self.control.cancelled.set()
        self.assertFalse(self.control.confirm("C1", "ACCEPT C1"))
        workdir = self.root / "solver_a"
        workdir.mkdir()
        with patch.object(runner, "build_exec_command", return_value=["mock-codex"]), \
             patch.object(runner.subprocess, "Popen") as popen:
            with self.assertRaises(OwnerCancelledStop):
                runner.run_agent("solver_a", workdir, "prompt", time.monotonic() + 2,
                    {}, self.root / "schema.json", "disabled",
                    {"model": "mock-model", "effort": "low", "daybreak": "off", "proxy_url": ""}, "mock-codex",
                    owner_control=self.control)
            popen.assert_not_called()

    def test_parallel_run_owned_processes_stop_and_no_later_spawn(self):
        self.control.record_candidate("verifier", self.record)
        processes = []
        stopped = []
        records = {}
        selected = {"model": "mock-model", "effort": "low", "daybreak": "off", "proxy_url": ""}

        class FakeProcess:
            def __init__(self, role):
                self.role = role
                self.returncode = None
                self.stopped = False
                self.pid = 1000 + len(processes)

            def wait(self, timeout=None):
                if self.stopped:
                    return self.returncode
                time.sleep(min(timeout or 0.02, 0.02))
                raise subprocess.TimeoutExpired("mock-codex", timeout)

        def spawn(*args, **kwargs):
            proc = FakeProcess(kwargs["cwd"].name)
            processes.append(proc)
            return proc

        def stop(proc):
            self.assertTrue((self.root / "SOLUTION.md").is_file())
            self.assertTrue((self.root / "OWNER_CONFIRMATION.json").is_file())
            proc.stopped = True
            proc.returncode = -15
            stopped.append(proc.role)

        def run(role):
            workdir = self.root / role
            workdir.mkdir()
            records[role] = runner.run_agent(role, workdir, "mock prompt", time.monotonic() + 5,
                {}, self.root / "schema.json", "disabled", selected, "mock-codex",
                owner_control=self.control)

        with patch.object(runner, "build_exec_command", return_value=["mock-codex"]), \
             patch.object(runner, "scrub_api_environment", return_value={}), \
             patch.object(runner.subprocess, "Popen", side_effect=spawn) as popen, \
             patch.object(runner, "stop_process_group", side_effect=stop):
            threads = [threading.Thread(target=run, args=(role,)) for role in ("solver_a", "solver_b")]
            for thread in threads:
                thread.start()
            limit = time.monotonic() + 2
            while len(processes) < 2 and time.monotonic() < limit:
                time.sleep(0.01)
            self.assertEqual(len(processes), 2)
            self.assertTrue(self.control.confirm("C1", "ACCEPT C1"))
            for thread in threads:
                thread.join(timeout=2)
                self.assertFalse(thread.is_alive())
            self.assertEqual(set(stopped), {"solver_a", "solver_b"})
            self.assertEqual({item["status"] for item in records.values()}, {"owner_confirmed_stop"})
            third = self.root / "verifier_review"
            third.mkdir()
            with self.assertRaises(OwnerConfirmedStop):
                runner.run_agent("verifier_review", third, "mock prompt", time.monotonic() + 5,
                    {}, self.root / "schema.json", "disabled", selected, "mock-codex",
                    owner_control=self.control)
            self.assertEqual(popen.call_count, 2)


if __name__ == "__main__":
    unittest.main()
