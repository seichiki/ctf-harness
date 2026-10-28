"""Offline checks for a standalone clone; no Codex model request is made."""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from harness import config, report, runner


class ConfigTests(unittest.TestCase):
    def test_public_defaults_and_local_override(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "config.toml"
            values = config.load({"model": "gpt-6-luna"}, path)
            self.assertEqual((values["effort"], values["daybreak"], values["orchestration"]),
                             ("medium", "off", "single"))
            config.save({"model": "gpt-5.6-sol", "effort": "high", "daybreak": "blue",
                         "orchestration": "multi"}, path)
            self.assertEqual(config.load(path=path)["daybreak"], "blue")
            self.assertEqual(config.load({"daybreak": "off"}, path)["daybreak"], "off")
            with self.assertRaises(FileExistsError):
                config.save(values, path)

    def test_invalid_configuration_stops(self):
        for key, value in (("model", ""), ("model", "other/provider"), ("effort", "invalid"),
                           ("daybreak", "red"), ("orchestration", "auto")):
            data = {"model": "gpt-6-luna", "effort": "medium", "daybreak": "off",
                    "orchestration": "single"}
            data[key] = value
            with self.assertRaises(ValueError):
                config.validate(data)

    def test_api_environment_is_scrubbed(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-only", "CODEX_API_KEY": "test-only",
                                     "OPENAI_BASE_URL": "https://example.invalid"}):
            env = runner.scrub_api_environment()
        for key in ("OPENAI_API_KEY", "CODEX_API_KEY", "OPENAI_BASE_URL"):
            self.assertNotIn(key, env)


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.workdir = Path("/tmp/ctf-harness-test-role")
        self.schema = self.workdir / "schema.json"
        self.base = {"model": "gpt-6-luna", "effort": "medium", "daybreak": "off",
                     "orchestration": "single"}

    def test_off_is_explicit_and_single_is_default(self):
        command = runner.build_exec_command(self.base, self.workdir, self.schema, "disabled", "fixture prompt", "codex")
        self.assertIn("--ignore-user-config", command)
        self.assertEqual(command[command.index("--cyber-access-program") + 1], "standard")
        self.assertIn("daybreak=false", command)
        self.assertIn("model_reasoning_effort=medium", command)
        self.assertIn("features.multi_agent=false", command)
        self.assertIn("web_search=disabled", command)
        self.assertEqual(command[command.index("-m") + 1], "gpt-6-luna")
        self.assertNotIn("daybreak_blue", command)
        self.assertEqual(runner.choose_switches("test", "auto", "auto"), {
            "preset": "test", "similar_search": False, "answer_reference": False,
        })

    def test_blue_multi_is_explicit_for_each_exec(self):
        selected = {"model": "gpt-5.6-sol", "effort": "high", "daybreak": "blue",
                    "orchestration": "multi"}
        command = runner.build_exec_command(selected, self.workdir, self.schema, "live", "fixture", "codex")
        self.assertEqual(command[command.index("--cyber-access-program") + 1], "daybreak_blue")
        self.assertIn("daybreak=true", command)
        self.assertIn("model_reasoning_effort=high", command)
        self.assertIn("web_search=live", command)
        self.assertEqual(runner.choose_switches("production", "auto", "auto")["similar_search"], True)

    def test_tui_has_no_prompt_or_guessed_blue_model(self):
        off = runner.build_tui_command(self.base, self.workdir, "disabled", "codex")
        self.assertIn("daybreak=false", off)
        self.assertIn("model_provider=openai", off)
        self.assertNotIn("--cyber-access-program", off)
        self.assertEqual(off[off.index("-m") + 1], "gpt-6-luna")
        blue = runner.build_tui_command({**self.base, "daybreak": "blue"}, self.workdir, "live", "codex")
        self.assertIn("daybreak=true", blue)
        self.assertNotIn("daybreak_blue", blue)
        self.assertEqual(blue[-1], "workspace-write")

    def test_invalid_web_mode_fails(self):
        with self.assertRaises(ValueError):
            runner.build_exec_command(self.base, self.workdir, self.schema, "invalid", "fixture", "codex")
        with self.assertRaises(ValueError):
            runner.build_tui_command(self.base, self.workdir, "invalid", "codex")


class CaseAndReportTests(unittest.TestCase):
    def test_case_hashes_and_reference_selection(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(runner, "ROOT", Path(folder)):
            case = runner.init_case("crypto", "fixture", "Local self-authored fixture", 5, None)
            (case / "input" / "statement.txt").write_text("What is 2 + 3?", encoding="utf-8")
            hashes = runner.seal_case("crypto", "fixture")
            self.assertEqual(runner.load_case("crypto", "fixture")[1]["input_sha256"], hashes)
            off = runner.choose_switches("test", "auto", "auto")
            self.assertEqual(runner.resolve_reference(off, None, True), (None, None))
            with self.assertRaises(ValueError):
                runner.resolve_reference(runner.choose_switches("test", "auto", "on"), None, True)
            (case / "input" / "link").symlink_to(case / "input" / "statement.txt")
            with self.assertRaises(ValueError):
                runner.load_case("crypto", "fixture")

    def test_report_artifact_validation(self):
        with tempfile.TemporaryDirectory() as folder:
            role = Path(folder)
            (role / "analysis.py").write_text("print(2 + 3)\n", encoding="utf-8")
            hashes = {"statement.txt": "a" * 64}
            item = {"candidate": "5", "input_sha256": hashes,
                    "method": "Checked arithmetic directly from the supplied text.",
                    "evidence": ["2 + 3 = 5"], "reproduction_commands": ["uv run --offline --locked python analysis.py"],
                    "artifacts": [{"path": "analysis.py"}], "limitations": []}
            self.assertEqual(report.validate_report(item, hashes, role), [])
            item["artifacts"] = [{"path": "../answer.txt"}]
            self.assertIn("artifact path is absent or outside the role directory",
                          report.validate_report(item, hashes, role))


class RunnerExecutionTests(unittest.TestCase):
    """Exercise run_external with fake Codex processes and temporary case files."""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.root_patch = patch.object(runner, "ROOT", self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        case = runner.init_case("misc", "fixture", "Local test fixture only", 1, None)
        (case / "input" / "statement.txt").write_text("A local test fixture.", encoding="utf-8")
        runner.seal_case("misc", "fixture")
        self.config = {"model": "gpt-5.6-sol", "effort": "high", "daybreak": "blue",
                       "orchestration": "multi"}
        self.switches = runner.choose_switches("test", "auto", "auto")

    def run_mocked(self, scenarios=None, candidates=None):
        scenarios = scenarios or {}
        candidates = candidates or {}
        calls = []

        class FakeProcess:
            pid = 12345

            def __init__(self, command, cwd, stdout, stderr, env, start_new_session):
                self.role = cwd.name
                self.command = command
                self.returncode = None
                self.stopped = False
                calls.append((self.role, command, cwd))
                if scenarios.get(self.role) == "exception":
                    raise RuntimeError("private-token-must-not-appear")
                if scenarios.get(self.role) not in ("failure", "timeout", "cancel"):
                    (cwd / "analysis.txt").write_text("Checked local fixture.\n", encoding="utf-8")
                    item = {"candidate": candidates.get(self.role, "fixture-answer"),
                            "input_sha256": runner.input_hashes(cwd / "input"),
                            "method": "Checked the supplied local fixture without external access.",
                            "evidence": ["Local fixture was read."],
                            "reproduction_commands": ["cat input/statement.txt"],
                            "artifacts": [{"path": "analysis.txt"}], "limitations": []}
                    (cwd / "last-message.txt").write_text(json.dumps(item), encoding="utf-8")

            def wait(self, timeout=None):
                if not self.stopped and scenarios.get(self.role) == "timeout":
                    raise subprocess.TimeoutExpired(self.command, timeout)
                if not self.stopped and scenarios.get(self.role) == "cancel":
                    raise KeyboardInterrupt
                self.returncode = -15 if self.stopped else 1 if scenarios.get(self.role) == "failure" else 0
                return self.returncode

        def stop_process(proc):
            proc.stopped = True
            proc.returncode = -15

        with patch.object(runner.shutil, "which", return_value="mock-codex"), \
             patch.object(runner, "require_exec_capabilities"), \
             patch.object(runner, "require_chatgpt_login"), \
             patch.object(runner.subprocess, "Popen", FakeProcess), \
             patch.object(runner, "stop_process_group", side_effect=stop_process):
            path = runner.run_external("misc", "fixture", self.config, self.switches, None, None)
        self.assertTrue(path.is_relative_to(self.root))
        self.assertTrue((path / "result.json").is_file())
        summary = json.loads((path / "result.json").read_text(encoding="utf-8"))
        for role, command, cwd in calls:
            self.assertTrue(cwd.is_relative_to(path))
            self.assertEqual(command[command.index("-C") + 1], str(cwd))
            self.assertEqual(command[command.index("-m") + 1], "gpt-5.6-sol")
            self.assertEqual(command[command.index("--cyber-access-program") + 1], "daybreak_blue")
            self.assertTrue((path / role / "run.json").is_file())
        return path, summary, [role for role, _, _ in calls]

    def test_successful_multi_roles_and_candidate(self):
        path, summary, roles = self.run_mocked()
        self.assertEqual(set(roles), {"verifier", "solver_a", "solver_b", "verifier_review"})
        self.assertEqual(summary["status"], "candidate_pending")
        self.assertEqual((path / "candidate.txt").read_text(encoding="utf-8"), "fixture-answer\n")
        packet = json.loads((path / "verifier_review" / "frozen-reports.json").read_text(encoding="utf-8"))
        self.assertEqual(set(packet), {"verifier", "solver_a", "solver_b"})

    def test_verifier_failure_persists_partial_result(self):
        path, summary, roles = self.run_mocked({"verifier": "failure"})
        self.assertEqual(roles, ["verifier"])
        self.assertEqual(summary["status"], "tool_failure")
        self.assertEqual(summary["agent_statuses"], {"verifier": "tool_failure"})
        self.assertFalse((path / "candidate.txt").exists())

    def test_worker_exception_persists_sanitized_error(self):
        path, summary, roles = self.run_mocked({"solver_b": "exception"})
        self.assertEqual(set(roles), {"verifier", "solver_a", "solver_b"})
        self.assertEqual(summary["status"], "tool_failure")
        self.assertEqual(summary["agent_errors"], {"solver_b": "RuntimeError"})
        self.assertNotIn("private-token-must-not-appear", (path / "result.json").read_text(encoding="utf-8"))
        self.assertNotIn("private-token-must-not-appear", (path / "solver_b" / "run.json").read_text(encoding="utf-8"))
        self.assertFalse((path / "candidate.txt").exists())

    def test_setup_exception_after_run_directory_persists_result(self):
        with patch.object(runner.shutil, "which", return_value="mock-codex"), \
             patch.object(runner, "require_exec_capabilities"), \
             patch.object(runner, "require_chatgpt_login"), \
             patch.object(runner, "common_prompt", side_effect=RuntimeError("private-token-must-not-appear")), \
             patch.object(runner.subprocess, "Popen") as popen:
            path = runner.run_external("misc", "fixture", self.config, self.switches, None, None)
        popen.assert_not_called()
        result = (path / "result.json").read_text(encoding="utf-8")
        self.assertEqual(json.loads(result)["status"], "tool_failure")
        self.assertEqual(json.loads(result)["run_error_type"], "RuntimeError")
        self.assertNotIn("private-token-must-not-appear", result)

    def test_timeout_persists_other_worker_result(self):
        path, summary, roles = self.run_mocked({"solver_a": "timeout"})
        self.assertEqual(set(roles), {"verifier", "solver_a", "solver_b"})
        self.assertEqual(summary["status"], "timeout")
        self.assertEqual(summary["agent_statuses"]["solver_b"], "completed")
        self.assertFalse((path / "candidate.txt").exists())

    def test_disagreement_suppresses_top_level_candidate(self):
        path, summary, roles = self.run_mocked(candidates={"verifier": "first-answer"})
        self.assertEqual(len(roles), 4)
        self.assertEqual(summary["status"], "disagreement")
        self.assertIsNone(summary["candidate_file"])
        self.assertFalse((path / "candidate.txt").exists())

    def test_keyboard_interrupt_persists_cancellation(self):
        path, summary, roles = self.run_mocked({"verifier": "cancel"})
        self.assertEqual(roles, ["verifier"])
        self.assertEqual(summary["status"], "cancelled")
        self.assertEqual(summary["agent_statuses"], {"verifier": "cancelled"})
        self.assertFalse((path / "candidate.txt").exists())


class SourceAndExportTests(unittest.TestCase):
    def test_seven_source_adapters_and_license(self):
        root = config.ROOT
        self.assertTrue((root / "third_party" / "ctf-skills" / "LICENSE").is_file())
        self.assertTrue((root / "uv.lock").is_file())
        for name in runner.CATEGORIES:
            self.assertTrue((root / "categories" / name / "AGENTS.md").is_file())
            self.assertTrue((root / "categories" / name / ".agents" / "skills" / f"ctf-{name}" / "SKILL.md").is_file())
            self.assertTrue((root / "third_party" / "ctf-skills" / f"ctf-{name}" / "SKILL.md").is_file())

    def test_export_ignores_cases_runs_answers_and_local_config(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / ".gitignore").write_bytes((config.ROOT / ".gitignore").read_bytes())
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            for path in (".local/config.toml", "categories/crypto/cases/x/input.txt",
                         "categories/crypto/runs/x/candidate.txt", "answers/answer.txt"):
                result = subprocess.run(["git", "-C", str(root), "check-ignore", "-q", path], check=False)
                self.assertEqual(result.returncode, 0, path)
            source = subprocess.run(["git", "-C", str(root), "check-ignore", "-q", "harness/runner.py"], check=False)
            self.assertNotEqual(source.returncode, 0)


if __name__ == "__main__":
    unittest.main()
