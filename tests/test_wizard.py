"""Offline wizard and handoff checks; fake runners never invoke Codex."""

import io
import json
import tempfile
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from harness import cli, config, runner, wizard
from harness.handoff import Handoff
from harness.progress import ProgressReporter


class WizardTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.config = config.validate({"model": "gpt-5.6-sol", "effort": "high",
                                       "daybreak": "blue", "orchestration": "single",
                                       "network_access": "off", "progress": False})
        root_patch = patch.object(runner, "ROOT", self.root)
        root_patch.start()
        self.addCleanup(root_patch.stop)
        load_patch = patch.object(wizard, "load", return_value=dict(self.config))
        load_patch.start()
        self.addCleanup(load_patch.stop)
        self.calls = []

    def test_wizard_time_limit_has_no_fifteen_minute_cap(self):
        self.assertEqual(wizard._minutes(lambda _: ""), 15)
        self.assertEqual(wizard._minutes(lambda _: "480"), 480)
        responses = iter(["0", "bad", "30"])
        with redirect_stdout(io.StringIO()):
            self.assertEqual(wizard._minutes(lambda _: next(responses)), 30)

    def fake_run(self, category, case_id, settings, switches, *args, **kwargs):
        self.calls.append((category, case_id, settings, switches, kwargs))
        path = self.root / "categories" / category / "runs" / case_id / "fake-run"
        path.mkdir(parents=True)
        (path / "result.json").write_text('{"status":"no_candidate"}', encoding="utf-8")
        (path / "HANDOFF.md").write_text("# handoff\n", encoding="utf-8")
        return path

    def wizard(self, answers, fake=None):
        replies = iter(answers)
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            result = wizard.run_wizard(root=self.root, tty=True, input_fn=lambda _: next(replies),
                                       external_runner=fake or self.fake_run)
        return result, out.getvalue(), err.getvalue()

    def test_no_arguments_routes_directly_to_new_problem_wizard(self):
        with patch.object(wizard, "run_wizard", return_value=17) as target:
            self.assertEqual(cli.main([]), 17)
        target.assert_called_once()
        self.assertEqual(wizard.run_wizard(root=self.root, tty=False), 2)

    def test_new_local_case_scaffold_files_statement_and_footer(self):
        answers = ["7", "日本語 問題", "", "Read this local puzzle.", "/end",
                   "1", "", "1", "RUN"]
        result, out, _ = self.wizard(answers)
        self.assertEqual(result, 0)
        self.assertEqual(len(self.calls), 1)
        case_id = self.calls[0][1]
        self.assertTrue(case_id.startswith("case-"))
        case = self.root / "categories" / "misc" / "cases" / case_id
        self.assertTrue((case / "input" / "files").is_dir())
        self.assertEqual((case / "input" / "statement.txt").read_text(encoding="utf-8"),
                         "Read this local puzzle.\n")
        manifest = json.loads((case / "case.json").read_text(encoding="utf-8"))
        self.assertFalse(manifest["draft"])
        self.assertEqual(manifest["title"], "日本語 問題")
        self.assertIsNone(manifest["authorized_target"])
        self.assertEqual(self.calls[0][2]["network_access"], "off")
        self.assertTrue(self.calls[0][4]["owner_confirmation"])
        self.assertFalse(self.calls[0][3]["similar_search"])
        self.assertIn(f"配布ファイル保存先：{case / 'input' / 'files'}\nEnterで完了\n", out)
        self.assertIn("配布ファイルなし", out)
        self.assertIn("引継ぎファイル：", out)
        self.assertIn("ログ保存先：", out)

    def test_cancellation_after_scaffold_leaves_draft_without_run(self):
        result, out, _ = self.wizard(["7", "Fixture", "/cancel"])
        self.assertEqual(result, 0)
        self.assertEqual(self.calls, [])
        self.assertNotIn("ログ保存先：", out)
        cases = list((self.root / "categories" / "misc" / "cases").iterdir())
        self.assertEqual(len(cases), 1)
        self.assertTrue(json.loads((cases[0] / "case.json").read_text())["draft"])
        with self.assertRaisesRegex(ValueError, "draft"):
            runner.seal_case("misc", cases[0].name)

    def test_placed_files_are_listed_and_symlinks_rejected(self):
        answers = iter(["7", "Fixture", "", "Statement", "/end", "1", "", "1", "RUN"])
        def enter(prompt):
            value = next(answers)
            if prompt == "" and value == "":
                folder = next((self.root / "categories" / "misc" / "cases").iterdir()) / "input" / "files"
                (folder / "sample.bin").write_bytes(b"fixture")
            return value
        out = io.StringIO()
        with redirect_stdout(out):
            result = wizard.run_wizard(root=self.root, tty=True, input_fn=enter,
                                       external_runner=self.fake_run)
        self.assertEqual(result, 0)
        self.assertIn('"sample.bin"', out.getvalue())
        folder = next((self.root / "categories" / "misc" / "cases").iterdir()) / "input" / "files"
        (folder / "link").symlink_to(folder / "sample.bin")
        with self.assertRaisesRegex(ValueError, "symlink|シンボリック"):
            wizard._scan_files(folder)

    def test_live_network_off_requires_explicit_one_run_enable(self):
        answers = ["1", "Web fixture", "", "Question", "/end", "2",
                   "http://example.test:1234/", "3", "2", "ENABLE", "RUN"]
        result, out, _ = self.wizard(answers)
        self.assertEqual(result, 0)
        self.assertEqual(self.calls[0][2]["network_access"], "on")
        self.assertTrue(self.calls[0][3]["similar_search"])
        self.assertEqual(self.config["network_access"], "off")
        self.assertIn("ネットワーク: on", out)

    def test_invalid_statement_and_no_run_confirmation(self):
        result, out, _ = self.wizard(["7", "Fixture", "", "TODO", "/end",
                                      "Actual statement", "/end", "1", "1", "1", "stop"])
        self.assertEqual(result, 0)
        self.assertEqual(self.calls, [])
        self.assertIn("空欄や仮の問題文", out)
        self.assertNotIn("ログ保存先：", out)

    def test_failed_run_displays_only_existing_run_paths(self):
        def broken(*args, **kwargs):
            run = self.root / "categories" / "misc" / "runs" / args[1] / "interrupted"
            run.mkdir(parents=True)
            (run / "HANDOFF.md").write_text("# saved", encoding="utf-8")
            raise OSError("mock failure")
        result, out, _ = self.wizard(["7", "Fixture", "", "Statement", "/end",
                                      "1", "1", "1", "RUN"], fake=broken)
        self.assertEqual(result, 2)
        self.assertIn("引継ぎファイル：", out)
        self.assertIn("ログ保存先：", out)

    def test_owner_confirmed_run_shows_solution_file(self):
        def solved(*args, **kwargs):
            run = self.fake_run(*args, **kwargs)
            (run / "SOLUTION.md").write_text("# recorded solution", encoding="utf-8")
            (run / "OWNER_CONFIRMATION.json").write_text('{"harness_verified":false}', encoding="utf-8")
            (run / "result.json").write_text('{"status":"user_confirmed"}', encoding="utf-8")
            (run / "candidate.txt").write_text("fixture-flag\n", encoding="utf-8")
            return run
        result, out, _ = self.wizard(["7", "Fixture", "", "Statement", "/end",
                                      "1", "1", "1", "RUN"], fake=solved)
        self.assertEqual(result, 0)
        self.assertIn("解法ファイル：", out)
        self.assertIn("正解報告：", out)
        self.assertIn("引継ぎファイル：", out)
        self.assertIn("ログ保存先：", out)

    def test_keyboard_interrupt_after_run_creation_shows_footer(self):
        def interrupted(*args, **kwargs):
            run = self.root / "categories" / "misc" / "runs" / args[1] / "interrupted"
            run.mkdir(parents=True)
            (run / "HANDOFF.md").write_text("# saved", encoding="utf-8")
            raise KeyboardInterrupt
        result, out, err = self.wizard(["7", "Fixture", "", "Statement", "/end",
                                        "1", "1", "1", "RUN"], fake=interrupted)
        self.assertEqual(result, 130)
        self.assertIn("引継ぎファイル：", out)
        self.assertIn("ログ保存先：", out)
        self.assertIn("中断", err)

    def test_eof_before_case_creation_leaves_no_case(self):
        def eof(_):
            raise EOFError
        with redirect_stdout(io.StringIO()):
            self.assertEqual(wizard.run_wizard(root=self.root, tty=True, input_fn=eof,
                                               external_runner=self.fake_run), 0)
        self.assertFalse((self.root / "categories" / "misc" / "cases").exists())
        self.assertEqual(self.calls, [])


class HandoffTests(unittest.TestCase):
    def test_checkpoints_are_atomic_bounded_and_mask_secrets(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            handoff = Handoff(root, {"case_id": "case", "category": "misc",
                                     "scope_note": "Local fixture", "authorized_target":
                                     "http://user:pass@example.test/?token=topsecret"},
                              {"model": "gpt-5.6-sol", "network_access": "off", "proxy_configured": False})
            def emit(role):
                for index in range(15):
                    handoff.event(role, f"command #item_{index} started: curl -H 'Authorization: Bearer topsecret' http://example.test/")
            threads = [threading.Thread(target=emit, args=(role,)) for role in ("solver_a", "solver_b")]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            self.assertIn("Status: in progress", handoff.path.read_text(encoding="utf-8"))
            handoff.finish("cancelled", "KeyboardInterrupt")
            content = handoff.path.read_text(encoding="utf-8")
            self.assertIn("Status: cancelled", content)
            self.assertIn("solver_a", content)
            self.assertIn("solver_b", content)
            self.assertNotIn("topsecret", content)
            self.assertNotIn("user:pass", content)
            self.assertIn("[REDACTED]", content)
            self.assertFalse(list(root.glob(".HANDOFF-*")))

    def test_optional_handoff_callback_failure_does_not_suppress_progress(self):
        output = io.StringIO()
        def broken(*_):
            raise OSError("render failed")
        reporter = ProgressReporter(output, on_event=broken)
        reporter.role_started("solver")
        self.assertIn("solver: started", output.getvalue())

    def test_jsonl_command_checkpoints_before_final_status(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            handoff = Handoff(root, {"case_id": "sample", "category": "misc",
                                     "scope_note": "Local fixture"},
                              {"model": "gpt-5.6-sol", "network_access": "off"})
            reporter = ProgressReporter(io.StringIO(), enabled=False, on_event=handoff.event)
            command = "curl -H 'Authorization: Bearer hidden' http://example.test/"
            reporter.handle_line("solver", json.dumps({"type": "item.started", "item": {
                "id": "item_1", "type": "command_execution", "command": command}}))
            interim = handoff.path.read_text(encoding="utf-8")
            self.assertIn("command #item_1 started", interim)
            self.assertNotIn("hidden", interim)
            self.assertIn("Status: in progress", interim)
            reporter.handle_line("solver", json.dumps({"type": "item.completed", "item": {
                "id": "item_1", "type": "command_execution", "exit_code": 0}}))
            reporter.role_candidate("solver", {"status": "completed", "report_sha256": "a" * 64,
                                               "candidate": "academy{TOKEN=ctf-flag_123}"})
            self.assertIn("command #item_1 completed (exit 0)",
                          handoff.path.read_text(encoding="utf-8"))
            self.assertIn("academy{TOKEN=ctf-flag_123}", handoff.path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
