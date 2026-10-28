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
