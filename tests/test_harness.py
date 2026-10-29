"""Offline checks for a standalone clone; no Codex model request is made."""

import json
import io
import os
import subprocess
import tempfile
import threading
import unittest
from contextlib import nullcontext, redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from harness import archive, candidates as candidate_module, cli, config, report, runner
from harness.locks import category_lock
from harness.progress import ProgressReporter, render_command, tail_events
from harness.proxy_diagnostics import scan as scan_proxy_diagnostics
from harness.solved import OwnerControl
from harness import solved as solved_module


class ConfigTests(unittest.TestCase):
    def test_reverse_requires_local_rea_before_external_launch(self):
        runner.require_rea_available("web")
        with patch.object(runner, "REA_STATIC", Path("/nonexistent/rea-static")):
            with self.assertRaisesRegex(ValueError, "REA/Ghidra is missing"):
                runner.require_rea_available("reverse")

    def test_tools_subcommand_passes_read_only_filters(self):
        with patch("harness.toolcheck.main", return_value=0) as checker:
            self.assertEqual(cli.main(["tools", "--category", "reverse", "--missing-only", "--json"]), 0)
        checker.assert_called_once_with(["--category", "reverse", "--missing-only", "--json"])

    def test_public_defaults_and_local_override(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "config.toml"
            values = config.load({"model": "gpt-6-luna"}, path)
            self.assertEqual((values["effort"], values["daybreak"], values["orchestration"],
                              values["network_access"]), ("medium", "off", "single", "off"))
            config.save({"model": "gpt-5.6-sol", "effort": "high", "daybreak": "blue",
                         "orchestration": "multi", "network_access": "on"}, path)
            self.assertEqual(config.load(path=path)["daybreak"], "blue")
            self.assertEqual(config.load(path=path)["network_access"], "on")
            self.assertEqual(config.load({"daybreak": "off"}, path)["daybreak"], "off")
            self.assertEqual(config.load({"network_access": "off"}, path)["network_access"], "off")
            with self.assertRaises(FileExistsError):
                config.save(values, path)

            path.write_text('model = "gpt-5.6-sol"\neffort = "high"\ndaybreak = "blue"\norchestration = "multi"\n',
                            encoding="utf-8")
            self.assertEqual(config.load(path=path)["network_access"], "off")

    def test_invalid_configuration_stops(self):
        for key, value in (("model", ""), ("model", "other/provider"), ("effort", "invalid"),
                           ("daybreak", "red"), ("orchestration", "auto"),
                           ("network_access", "sometimes"), ("network_access", True)):
            data = {"model": "gpt-6-luna", "effort": "medium", "daybreak": "off",
                    "orchestration": "single", "network_access": "off"}
            data[key] = value
            with self.assertRaises(ValueError):
                config.validate(data)

    def test_personal_defaults_and_one_run_overrides(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "config.toml"
            path.write_text('model = "gpt-5.6-sol"\nnetwork_access = "on"\n'
                            'progress = true\nproxy_url = "http://127.0.0.1:8080"\n', encoding="utf-8")
            saved = config.load(path=path)
            self.assertTrue(saved["progress"])
            self.assertEqual(saved["proxy_url"], "http://127.0.0.1:8080")
            once = config.load({"network_access": "off", "progress": False, "proxy_url": ""}, path)
            self.assertEqual((once["network_access"], once["progress"], once["proxy_url"]),
                             ("off", False, ""))
            self.assertEqual(config.load(path=path), saved)
            self.assertNotIn("proxy_url", config.public_settings(saved))
            self.assertTrue(config.public_settings(saved)["proxy_active"])

            path.write_text('model = "gpt-5.6-sol"\n', encoding="utf-8")
            older = config.load(path=path)
            self.assertEqual((older["network_access"], older["progress"], older["proxy_url"]),
                             ("off", False, ""))

    def test_proxy_validation_rejects_credentials_and_non_http_urls(self):
        for proxy in ("https://localhost:8080", "http://user:pass@localhost:8080",
                      "http://localhost:8080/path", "http://localhost:8080/?token=abc",
                      "http://localhost", "http://localhost:99999", "http://localhost:8080\n",
                      "http://localhost:8080#fragment", 123):
            with self.subTest(proxy=proxy), self.assertRaises(ValueError):
                config.validate({"model": "gpt-5.6-sol", "proxy_url": proxy})
        with self.assertRaises(ValueError):
            config.validate({"model": "gpt-5.6-sol", "progress": "true"})

    def test_proxy_environment_only_for_agent_shell(self):
        endpoint = "http://127.0.0.1:8080"
        selected = {"model": "gpt-5.6-sol", "effort": "high", "daybreak": "blue",
                    "orchestration": "multi", "network_access": "on", "proxy_url": endpoint}
        command = runner.build_exec_command(selected, Path("/tmp/role"), Path("/tmp/schema"),
                                            "disabled", "fixture", "codex")
        self.assertIn(f"shell_environment_policy.set.http_proxy={json.dumps(endpoint)}", command)
        self.assertIn(f"shell_environment_policy.set.HTTPS_PROXY={json.dumps(endpoint)}", command)
        self.assertIn('shell_environment_policy.set.NO_PROXY=""', command)
        tui = runner.build_tui_command(selected, Path("/tmp/role"), "disabled", "codex")
        self.assertIn(f"shell_environment_policy.set.http_proxy={json.dumps(endpoint)}", tui)
        self.assertNotIn(endpoint, json.dumps(runner.redact_proxy_command(command)))
        self.assertNotIn(endpoint, json.dumps(runner.redact_proxy_command(tui)))
        self.assertNotIn(endpoint, json.dumps(config.public_settings(selected)))
        prompt = runner.common_prompt("web", "fixture", {"scope_note": "Local fixture",
            "authorized_target": None}, runner.choose_switches("test", "auto", "auto"), selected)
        self.assertIn("Do not bypass the proxy", prompt)
        self.assertNotIn(endpoint, prompt)
        off = runner.build_exec_command({**selected, "network_access": "off"}, Path("/tmp/role"),
                                        Path("/tmp/schema"), "disabled", "fixture", "codex")
        self.assertFalse(any("shell_environment_policy.set.http_proxy" in part for part in off))

    def test_configured_proxy_does_not_enter_codex_api_environment(self):
        endpoint = "http://127.0.0.1:8080"
        with patch.dict(os.environ, {"HTTP_PROXY": endpoint, "https_proxy": endpoint,
                                     "ALL_PROXY": endpoint, "NO_PROXY": "example.invalid"}):
            env = runner.scrub_api_environment(configured_proxy=True)
        for key in ("HTTP_PROXY", "https_proxy", "ALL_PROXY", "NO_PROXY"):
            self.assertNotIn(key, env)
        self.assertNotIn(endpoint, json.dumps(env))
        with patch.object(runner.subprocess, "run") as codex:
            codex.return_value.returncode = 0
            codex.return_value.stdout = "Logged in using ChatGPT"
            codex.return_value.stderr = ""
            runner.require_chatgpt_login("codex", configured_proxy=True)
        self.assertNotIn(endpoint, json.dumps(codex.call_args.kwargs["env"]))

    def test_explicit_no_proxy_clears_inherited_proxy_for_one_run(self):
        selected = {"model": "gpt-5.6-sol", "effort": "high", "daybreak": "blue",
                    "network_access": "on", "proxy_url": "", "proxy_override_off": True}
        with patch.dict(os.environ, {"HTTP_PROXY": "http://127.0.0.1:8080",
                                      "https_proxy": "http://127.0.0.1:8080"}):
            child_env = runner.scrub_api_environment(True)
        self.assertNotIn("HTTP_PROXY", child_env)
        self.assertNotIn("https_proxy", child_env)
        command = runner.build_exec_command(selected, Path("/tmp/role"), Path("/tmp/schema"),
                                            "disabled", "fixture", "codex")
        self.assertIn('shell_environment_policy.set.HTTP_PROXY=""', command)
        self.assertIn('shell_environment_policy.set.https_proxy=""', command)
        self.assertNotIn("127.0.0.1:8080", json.dumps(command))

    def test_clone_local_native_tools_reach_exec_and_tui_shells(self):
        with tempfile.TemporaryDirectory() as folder:
            local_bin = Path(folder) / ".local/tools/bin"
            local_bin.mkdir(parents=True)
            selected = {"model": "gpt-5.6-sol", "effort": "high", "daybreak": "blue",
                        "network_access": "off", "proxy_url": ""}
            with patch.object(runner, "ROOT", Path(folder)):
                commands = (runner.build_exec_command(selected, Path(folder) / "role", Path(folder) / "schema",
                                                       "disabled", "fixture", "codex"),
                            runner.build_tui_command(selected, Path(folder) / "role", "disabled", "codex"))
            for command in commands:
                self.assertTrue(any(part.startswith("shell_environment_policy.set.PATH=") and
                                    str(local_bin) in part for part in command))

    def test_unavailable_proxy_fails_closed_before_role(self):
        selected = {"network_access": "on", "proxy_url": "http://127.0.0.1:8080"}
        with patch.object(runner.socket, "create_connection", side_effect=OSError("secret-address")):
            with self.assertRaisesRegex(ValueError, "configured HTTP proxy is unavailable") as raised:
                runner.require_proxy_available(selected)
        self.assertNotIn("secret-address", str(raised.exception))

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
                     "orchestration": "single", "network_access": "off"}

    def test_off_is_explicit_and_single_is_default(self):
        command = runner.build_exec_command(self.base, self.workdir, self.schema, "disabled", "fixture prompt", "codex")
        self.assertIn("--ignore-user-config", command)
        self.assertEqual(command[command.index("--cyber-access-program") + 1], "standard")
        self.assertIn("daybreak=false", command)
        self.assertIn("model_reasoning_effort=medium", command)
        self.assertIn("features.multi_agent=false", command)
        self.assertIn("web_search=disabled", command)
        self.assertIn("sandbox_workspace_write.network_access=false", command)
        self.assertIn("approval_policy=on-request", command)
        self.assertEqual(command[command.index("-m") + 1], "gpt-6-luna")
        self.assertNotIn("daybreak_blue", command)
        self.assertEqual(runner.choose_switches("test", "auto", "auto"), {
            "preset": "test", "similar_search": False, "answer_reference": False,
        })

    def test_blue_multi_is_explicit_for_each_exec(self):
        selected = {"model": "gpt-5.6-sol", "effort": "high", "daybreak": "blue",
                    "orchestration": "multi", "network_access": "on"}
        command = runner.build_exec_command(selected, self.workdir, self.schema, "live", "fixture", "codex")
        self.assertEqual(command[command.index("--cyber-access-program") + 1], "daybreak_blue")
        self.assertIn("daybreak=true", command)
        self.assertIn("model_reasoning_effort=high", command)
        self.assertIn("web_search=live", command)
        self.assertIn("sandbox_workspace_write.network_access=true", command)
        self.assertEqual(runner.choose_switches("production", "auto", "auto")["similar_search"], True)

    def test_network_and_search_are_independent(self):
        for network_access, web_mode in (("off", "disabled"), ("off", "live"),
                                         ("on", "disabled"), ("on", "live")):
            command = runner.build_exec_command({**self.base, "network_access": network_access},
                                                self.workdir, self.schema, web_mode, "fixture", "codex")
            self.assertIn(f"sandbox_workspace_write.network_access={'true' if network_access == 'on' else 'false'}", command)
            self.assertIn(f"web_search={web_mode}", command)

    def test_tui_has_no_prompt_or_guessed_blue_model(self):
        off = runner.build_tui_command(self.base, self.workdir, "disabled", "codex")
        self.assertIn("daybreak=false", off)
        self.assertIn("model_provider=openai", off)
        self.assertIn("sandbox_workspace_write.network_access=false", off)
        self.assertNotIn("--cyber-access-program", off)
        self.assertEqual(off[off.index("-m") + 1], "gpt-6-luna")
        blue = runner.build_tui_command({**self.base, "daybreak": "blue", "network_access": "on"},
                                        self.workdir, "live", "codex")
        self.assertIn("daybreak=true", blue)
        self.assertIn("sandbox_workspace_write.network_access=true", blue)
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


class ProgressTests(unittest.TestCase):
    def test_event_is_visible_before_process_exit(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "events.jsonl"
            path.touch()
            observed = threading.Event()

            class SignalingStream(io.StringIO):
                def write(self, value):
                    result = super().write(value)
                    observed.set()
                    return result

            output = SignalingStream()
            stopped = threading.Event()
            watcher = threading.Thread(target=tail_events,
                args=(path, "solver", ProgressReporter(output), stopped))
            watcher.start()
            try:
                with path.open("a", encoding="utf-8") as target:
                    target.write(json.dumps({"type": "item.started", "item": {
                        "type": "command_execution", "command": "curl http://example.invalid"}}) + "\n")
                    target.flush()
                    self.assertTrue(observed.wait(2), "progress should arrive while the child is active")
                self.assertIn("solver: command #unknown started: curl http://example.invalid", output.getvalue())
            finally:
                stopped.set()
                watcher.join(2)
            self.assertFalse(watcher.is_alive())

    def test_command_and_tool_events_omit_untrusted_content(self):
        output = io.StringIO()
        live = ProgressReporter(output)
        live.role_started("solver_a")
        secret = "private-bearer-token-123"
        events = [
            {"type": "item.started", "item": {"type": "command_execution",
                "id": "item_1",
                "command": f"curl -H 'Authorization: Bearer {secret}' http://example.invalid/\u001b[31m"}},
            {"type": "item.completed", "item": {"type": "command_execution",
                "id": "item_1",
                "command": f"curl --cookie session={secret}", "aggregated_output": secret, "exit_code": 6}},
            {"type": "item.completed", "item": {"type": "mcp_tool_call",
                "id": "item_2",
                "server": secret, "tool": f"Cookie: {secret}", "result": secret, "status": "failed"}},
            {"type": "item.completed", "item": {"type": "agent_message", "text": secret}},
            {"type": "item.completed", "item": {"type": "reasoning", "text": secret}},
            {"type": "turn.completed", "usage": {"secret": secret}},
        ]
        for event in events:
            live.handle_line("solver_a", json.dumps(event))
        text = output.getvalue()
        self.assertIn("solver_a: command #item_1 started: curl -H 'Authorization: [REDACTED]' http://example.invalid/", text)
        self.assertIn("solver_a: command #item_1 failed (exit 6)", text)
        self.assertIn("solver_a: tool call #item_2 failed", text)
        self.assertIn("model turn completed", text)
        self.assertNotIn(secret, text)
        self.assertNotIn("\u001b", text)
        self.assertNotIn("Bearer " + secret, text)
        self.assertNotIn("Cookie: " + secret, text)

    def test_raw_command_masks_common_secrets_but_preserves_ordinary_arguments(self):
        command = ("curl -I -u alice:hunter2 -H 'Authorization: Bearer auth123' "
                   "-H 'Cookie: session=cook123; next=other123' "
                   "'https://bob:pw456@ctf.example/path?token=query789&mode=fast' "
                   "--data 'password=body123&name=ordinary' --cookie jar999 "
                   "--proxy-user proxyuser:proxypass export OPENAI_API_KEY=env123 "
                   "GH_TOKEN=tok123 SECRET_KEY='line1\nline2' "
                   "'{\"api_key\":\"jsonsecret\"}'")
        shown = render_command(command)
        self.assertIn("curl -I", shown)
        self.assertIn("ctf.example/path", shown)
        self.assertIn("mode=fast", shown)
        self.assertIn("name=ordinary", shown)
        for secret in ("hunter2", "auth123", "cook123", "other123", "pw456", "query789",
                       "body123", "jar999", "proxypass", "env123", "tok123", "line1", "line2",
                       "jsonsecret"):
            self.assertNotIn(secret, shown)
        self.assertIn("[REDACTED]", shown)

    def test_control_sequences_and_truncation_are_visible_as_safe_text(self):
        shown = render_command("echo good\x1b[2J\x1b]0;injected title\x07\nnext\rline")
        self.assertIn("echo good", shown)
        self.assertIn(r"\nnext\nline", shown)
        self.assertNotIn("\x1b", shown)
        self.assertNotIn("injected title", shown)
        long = render_command("echo " + "x" * 900)
        self.assertIn("[truncated; full command in events.jsonl]", long)
        self.assertLess(len(long), 510)

    def test_event_ids_associate_parallel_commands_and_deduplicate_starts(self):
        output = io.StringIO()
        live = ProgressReporter(output)
        started = {"type": "item.started", "item": {"id": "item_7",
            "type": "command_execution", "command": "bash -lc 'curl http://example.invalid:1234/'"}}
        completed = {"type": "item.completed", "item": {"id": "item_7",
            "type": "command_execution", "command": started["item"]["command"], "exit_code": 0}}
        live.handle_line("solver_a", json.dumps(started))
        live.handle_line("solver_b", json.dumps(started))
        live.handle_line("solver_a", json.dumps(started))
        live.handle_line("solver_b", json.dumps(completed))
        live.handle_line("solver_a", json.dumps(completed))
        live.handle_line("solver_a", json.dumps(completed))
        text = output.getvalue()
        self.assertEqual(text.count("solver_a: command #item_7 started"), 1)
        self.assertEqual(text.count("solver_a: command #item_7 completed"), 1)
        self.assertEqual(text.count("solver_b: command #item_7 started"), 1)
        self.assertIn("bash -lc 'curl http://example.invalid:1234/'", text)

    def test_candidate_is_exact_and_control_characters_are_escaped(self):
        output = io.StringIO()
        live = ProgressReporter(output)
        candidate = "academy{TOKEN=ctf-flag_123}"
        live.role_candidate("verifier", {"status": "completed", "report_sha256": "a" * 64,
                                         "candidate": candidate})
        self.assertIn(json.dumps(candidate), output.getvalue())
        self.assertNotIn("[REDACTED]", output.getvalue())
        live.role_candidate("solver_a", {"status": "completed", "report_sha256": "b" * 64,
                                         "candidate": "flag\x1b[31m"})
        self.assertNotIn("\x1b", output.getvalue())
        self.assertIn(r"\u001b", output.getvalue())

    def test_malformed_events_and_untrusted_labels_are_safe(self):
        output = io.StringIO()
        live = ProgressReporter(output)
        for line in ("not json", "[]", "null", '{"type":"item.started","item":[]}',
                     '{"type":"item.started","item":{"type":"unknown"}}'):
            live.handle_line("\u001b[31msecret", line)
        live.handle_line("\u001b[31msecret", json.dumps({"type": "item.started", "item": {
            "type": "command_execution", "command": "TOKEN=abc curl --cookie secret"}}))
        live.role_finished("\u001b[31msecret", "Authorization: Bearer secret")
        self.assertIn("run: command #unknown started: TOKEN=[REDACTED] curl --cookie [REDACTED]", output.getvalue())
        self.assertIn("run: finished (unknown)", output.getvalue())
        self.assertNotIn("secret", output.getvalue())
        self.assertNotIn("\u001b", output.getvalue())

    def test_interleaved_roles_keep_atomic_lines(self):
        output = io.StringIO()
        live = ProgressReporter(output)
        for role in ("solver_a", "solver_b", "solver_a"):
            live.handle_line(role, json.dumps({"type": "item.started", "item": {
                "type": "command_execution", "command": "rg pattern input"}}))
        self.assertEqual([line.split(": ")[0].split()[-1] for line in output.getvalue().splitlines()],
                         ["solver_a", "solver_b", "solver_a"])


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
                       "orchestration": "multi", "network_access": "off",
                       "progress": False, "proxy_url": ""}
        self.switches = runner.choose_switches("test", "auto", "auto")

    def test_positive_unbounded_case_minutes_with_finite_validation(self):
        for value in (1, 15, 16, 120, 10080):
            self.assertTrue(runner.valid_minutes(value))
        for value in (0, -1, True, 1.5, "120", 10 ** 400):
            self.assertFalse(runner.valid_minutes(value))
        case = runner.init_case("misc", "long-case", "Local fixture", 480, None)
        (case / "input" / "statement.txt").write_text("Long test case", encoding="utf-8")
        runner.seal_case("misc", "long-case")
        self.assertEqual(runner.load_case("misc", "long-case")[1]["time_limit_minutes"], 480)

    def run_mocked(self, scenarios=None, candidates=None, events=None, progress=False,
                   owner_confirmation=False, owner_class=None, handoff_failure=False,
                   solution_failure=False, reports=None):
        scenarios = scenarios or {}
        candidates = candidates or {}
        events = events or {}
        reports = reports or {}
        calls = []
        environments = {}
        child_stdin = []
        original_atomic = solved_module._atomic_text

        def write_with_optional_solution_failure(path, content):
            if solution_failure and path.name == "SOLUTION.md":
                raise OSError("writeup unavailable")
            return original_atomic(path, content)

        class FakeProcess:
            pid = 12345

            def __init__(self, command, cwd, stdout, stderr, env, start_new_session, stdin=None):
                self.role = cwd.name
                self.command = command
                self.returncode = None
                self.stopped = False
                calls.append((self.role, command, cwd))
                child_stdin.append(stdin)
                environments[self.role] = env
                if scenarios.get(self.role) == "exception":
                    raise RuntimeError("private-token-must-not-appear")
                if scenarios.get(self.role) == "safety":
                    stderr.write("safety block")
                    stderr.flush()
                for event in events.get(self.role, []):
                    stdout.write(json.dumps(event) + "\n")
                stdout.flush()
                if scenarios.get(self.role) not in ("failure", "timeout", "cancel", "safety"):
                    (cwd / "analysis.txt").write_text("Checked local fixture.\n", encoding="utf-8")
                    item = {"candidate": candidates.get(self.role, "fixture-answer"),
                            "input_sha256": runner.input_hashes(cwd / "input"),
                            "method": "Checked the supplied local fixture without external access.",
                            "evidence": ["Local fixture was read."],
                            "reproduction_commands": ["cat input/statement.txt"],
                            "artifacts": [{"path": "analysis.txt"}], "limitations": []}
                    item.update(reports.get(self.role, {}))
                    (cwd / "last-message.txt").write_text(json.dumps(item), encoding="utf-8")
                if scenarios.get(self.role) == "invalid_report":
                    (cwd / "last-message.txt").write_text("{invalid json", encoding="utf-8")

            def wait(self, timeout=None):
                if not self.stopped and scenarios.get(self.role) == "timeout":
                    raise subprocess.TimeoutExpired(self.command, timeout)
                if not self.stopped and scenarios.get(self.role) == "cancel":
                    raise KeyboardInterrupt
                self.returncode = -15 if self.stopped else 1 if scenarios.get(self.role) in ("failure", "safety") else 0
                return self.returncode

        def stop_process(proc):
            proc.stopped = True
            proc.returncode = -15

        output = io.StringIO()
        final = io.StringIO()
        with redirect_stderr(output), redirect_stdout(final), \
             patch.object(runner.shutil, "which", return_value="mock-codex"), \
             patch.object(runner, "require_exec_capabilities"), \
             patch.object(runner, "require_chatgpt_login"), \
             patch.object(runner, "require_proxy_available") as proxy_check, \
             patch.object(runner.subprocess, "Popen", FakeProcess), \
             patch.object(runner, "stop_process_group", side_effect=stop_process), \
             (patch.object(runner, "OwnerControl", owner_class) if owner_class else nullcontext()), \
             (patch.object(runner, "controlling_terminal", return_value=True)
              if owner_confirmation else nullcontext()), \
             (patch.object(runner, "Handoff", side_effect=OSError("handoff unavailable"))
              if handoff_failure else nullcontext()), \
             (patch.object(solved_module, "_atomic_text", side_effect=write_with_optional_solution_failure)
              if solution_failure else nullcontext()):
            path = runner.run_external("misc", "fixture", self.config, self.switches, None, None,
                                       progress=progress, owner_confirmation=owner_confirmation)
        self.progress_output = output.getvalue()
        self.final_output = json.loads(final.getvalue())
        self.process_environments = environments
        self.owner_child_stdin = child_stdin
        self.proxy_check_count = proxy_check.call_count
        self.assertTrue(path.is_relative_to(self.root))
        self.assertTrue((path / "result.json").is_file())
        handoff = path / "HANDOFF.md"
        if not handoff_failure:
            self.assertTrue(handoff.is_file())
            self.assertIn("Status: ", handoff.read_text(encoding="utf-8"))
        summary = json.loads((path / "result.json").read_text(encoding="utf-8"))
        if not handoff_failure:
            self.assertIn(f"Status: {summary['status']}", handoff.read_text(encoding="utf-8"))
            self.assertIn("**verifier**: started", handoff.read_text(encoding="utf-8"))
        for role, command, cwd in calls:
            self.assertTrue(cwd.is_relative_to(path))
            self.assertEqual(command[command.index("-C") + 1], str(cwd))
            self.assertEqual(command[command.index("-m") + 1], "gpt-5.6-sol")
            self.assertEqual(command[command.index("--cyber-access-program") + 1], "daybreak_blue")
            self.assertIn(f"sandbox_workspace_write.network_access={'true' if self.config['network_access'] == 'on' else 'false'}", command)
            self.assertTrue((path / role / "run.json").is_file())
        return path, summary, [role for role, _, _ in calls]

    def test_successful_multi_roles_and_candidate(self):
        path, summary, roles = self.run_mocked()
        self.assertEqual(set(roles), {"verifier", "solver_a", "solver_b", "verifier_review"})
        self.assertEqual(summary["status"], "candidate_pending")
        self.assertEqual((path / "candidate.txt").read_text(encoding="utf-8"), "fixture-answer\n")
        packet = json.loads((path / "verifier_review" / "frozen-reports.json").read_text(encoding="utf-8"))
        self.assertEqual(set(packet), {"verifier", "solver_a", "solver_b"})
        self.assertFalse(summary["network_access_requested"])
        self.assertEqual(summary["network_access_effective"], "unverified")
        self.assertEqual(self.progress_output, "")

    def test_owner_confirmed_verifier_candidate_stops_before_solvers(self):
        class ConfirmFromTerminal(OwnerControl):
            def start(self):
                pass  # The test substitutes a human terminal confirmation.

            def record_candidate(self, role, record):
                super().record_candidate(role, record)
                if role == "verifier":
                    self.confirm("C1", "ACCEPT C1")

        path, summary, roles = self.run_mocked(owner_confirmation=True,
                                               owner_class=ConfirmFromTerminal)
        self.assertEqual(roles, ["verifier"])
        self.assertEqual(self.owner_child_stdin, [subprocess.DEVNULL])
        self.assertEqual(summary["status"], "user_confirmed")
        self.assertFalse(summary["challenge_verified_by_harness"])
        self.assertTrue(summary["owner_confirmation_requested"])
        self.assertEqual(summary["owner_confirmation"]["roles"], ["verifier"])
        self.assertTrue(summary["candidates"][0]["owner_confirmed"])
        self.assertFalse(summary["candidates"][0]["challenge_verified_by_harness"])
        self.assertEqual(summary["owner_confirmation_file"], "OWNER_CONFIRMATION.json")
        self.assertEqual((path / "candidate.txt").read_text(encoding="utf-8"), "fixture-answer\n")
        self.assertIn("Owner-reported official acceptance", (path / "SOLUTION.md").read_text(encoding="utf-8"))
        self.assertIn("SOLUTION.md", (path / "HANDOFF.md").read_text(encoding="utf-8"))

    def test_owner_confirmation_survives_optional_handoff_write_failure(self):
        class ConfirmFromTerminal(OwnerControl):
            def start(self):
                pass

            def record_candidate(self, role, record):
                super().record_candidate(role, record)
                if role == "verifier":
                    self.confirm("C1", "ACCEPT C1")

        path, summary, roles = self.run_mocked(owner_confirmation=True,
            owner_class=ConfirmFromTerminal, handoff_failure=True)
        self.assertEqual(roles, ["verifier"])
        self.assertEqual(summary["status"], "user_confirmed")
        self.assertTrue((path / "SOLUTION.md").is_file())
        self.assertTrue((path / "OWNER_CONFIRMATION.json").is_file())
        self.assertFalse((path / "HANDOFF.md").exists())

    def test_owner_confirmation_remains_durable_if_writeup_cannot_be_saved(self):
        class ConfirmFromTerminal(OwnerControl):
            def start(self):
                pass

            def record_candidate(self, role, record):
                super().record_candidate(role, record)
                if role == "verifier":
                    self.confirm("C1", "ACCEPT C1")

        path, summary, roles = self.run_mocked(owner_confirmation=True,
            owner_class=ConfirmFromTerminal, solution_failure=True)
        self.assertEqual(roles, ["verifier"])
        self.assertEqual(summary["status"], "user_confirmed")
        self.assertIsNone(summary["solution_file"])
        self.assertTrue((path / "OWNER_CONFIRMATION.json").is_file())
        self.assertFalse((path / "SOLUTION.md").exists())
        self.assertIn("OWNER_CONFIRMATION.json", (path / "HANDOFF.md").read_text(encoding="utf-8"))

    def test_owner_confirmation_without_tty_refuses_before_model_preflight(self):
        with patch.object(runner, "controlling_terminal", return_value=False), \
             patch.object(runner.shutil, "which") as which:
            with self.assertRaisesRegex(ValueError, "foreground controlling terminal"):
                runner.run_external("misc", "fixture", self.config, self.switches, None, None,
                                    owner_confirmation=True)
        which.assert_not_called()

    def test_owner_confirmation_cli_is_opt_in_and_quiet_is_rejected(self):
        with patch.object(cli, "load", return_value=dict(self.config)), \
             patch.object(cli, "run_external") as external, \
             redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(["run", "--category", "misc", "--case-id", "fixture"]), 0)
            self.assertNotIn("owner_confirmation", external.call_args.kwargs)
            self.assertEqual(cli.main(["run", "--category", "misc", "--case-id", "fixture",
                                       "--owner-confirmation"]), 0)
            self.assertTrue(external.call_args.kwargs["owner_confirmation"])
            with self.assertRaises(SystemExit):
                cli.main(["run", "--category", "misc", "--case-id", "fixture",
                          "--owner-confirmation", "--quiet"])

    def test_live_progress_streams_roles_and_results_without_secrets(self):
        secret = "session-cookie-secret-value"
        events = {role: [
            {"type": "item.started", "item": {"type": "command_execution",
                "id": "item_1",
                "command": f"curl --cookie {secret} http://example.invalid/"}},
            {"type": "item.completed", "item": {"type": "command_execution",
                "id": "item_1",
                "command": "curl", "aggregated_output": secret, "exit_code": 0}},
        ] for role in ("verifier", "solver_a", "solver_b", "verifier_review")}
        path, summary, roles = self.run_mocked(events=events, progress=True)
        self.assertEqual(summary["status"], "candidate_pending")
        for role in roles:
            self.assertIn(f"{role}: started", self.progress_output)
            self.assertIn(f"{role}: command #item_1 started: curl --cookie [REDACTED] http://example.invalid/", self.progress_output)
            self.assertIn(f"{role}: command #item_1 completed (exit 0)", self.progress_output)
            self.assertIn(f'{role}: candidate: "fixture-answer"', self.progress_output)
            self.assertIn(f"{role}: finished (completed)", self.progress_output)
            self.assertLess(self.progress_output.index(f'{role}: candidate: "fixture-answer"'),
                            self.progress_output.index(f"{role}: finished (completed)"))
        self.assertLess(self.progress_output.index('verifier: candidate: "fixture-answer"'),
                        self.progress_output.index("solver_a: started"))
        self.assertIn("run: finished (candidate_pending)", self.progress_output)
        self.assertNotIn(secret, self.progress_output)
        self.assertTrue((path / "result.json").is_file())
        self.assertEqual(self.final_output["status"], "candidate_pending")
        self.assertEqual(self.final_output["run_dir"], str(path))

    def test_saved_proxy_reaches_all_roles_without_leaking_into_run_metadata(self):
        endpoint = "http://127.0.0.1:8080"
        self.config.update(network_access="on", proxy_url=endpoint)
        with patch.dict(os.environ, {"HTTP_PROXY": endpoint, "https_proxy": endpoint}):
            path, summary, roles = self.run_mocked()
        self.assertEqual(self.proxy_check_count, 5)
        self.assertEqual(set(roles), {"verifier", "solver_a", "solver_b", "verifier_review"})
        self.assertTrue(summary["proxy_active"])
        for role, env in self.process_environments.items():
            self.assertNotIn("HTTP_PROXY", env)
            self.assertNotIn("https_proxy", env)
            invocation = (path / role / "invocation.json").read_text(encoding="utf-8")
            self.assertIn("shell_environment_policy.set.http_proxy", invocation)
            self.assertNotIn(endpoint, invocation)
        for name in ("settings.json", "result.json"):
            self.assertNotIn(endpoint, (path / name).read_text(encoding="utf-8"))

    def test_proxy_failure_prevents_model_launch(self):
        self.config.update(network_access="on", proxy_url="http://127.0.0.1:8080")
        with patch.object(runner, "require_proxy_available",
                          side_effect=ValueError("configured HTTP proxy is unavailable")), \
             patch.object(runner.subprocess, "Popen") as popen:
            with self.assertRaisesRegex(ValueError, "proxy is unavailable"):
                runner.run_external("misc", "fixture", self.config, self.switches, None, None)
        popen.assert_not_called()

    def test_cli_saved_settings_can_be_overridden_off_without_editing_file(self):
        endpoint = "http://127.0.0.1:8080"
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "config.toml"
            path.write_text('model = "gpt-5.6-sol"\nnetwork_access = "on"\n'
                            f'progress = true\nproxy_url = "{endpoint}"\n', encoding="utf-8")
            original = path.read_text(encoding="utf-8")

            def local_load(overrides):
                return config.load(overrides, path)

            output = io.StringIO()
            with patch.object(cli, "load", side_effect=local_load), redirect_stdout(output):
                self.assertEqual(cli.main(["run", "--category", "misc", "--case-id", "fixture",
                                           "--network-access", "off", "--no-progress", "--no-proxy",
                                           "--dry-run"]), 0)
            plan = json.loads(output.getvalue())
            self.assertEqual((plan["network_access"], plan["progress"], plan["proxy_active"]),
                             ("off", False, False))
            self.assertNotIn(endpoint, output.getvalue())
            self.assertEqual(path.read_text(encoding="utf-8"), original)

            output = io.StringIO()
            with patch.object(cli, "load", side_effect=local_load), redirect_stdout(output):
                self.assertEqual(cli.main(["run", "--category", "misc", "--case-id", "fixture",
                                           "--dry-run"]), 0)
            inherited = json.loads(output.getvalue())
            self.assertTrue(inherited["progress"])
            self.assertTrue(inherited["proxy_active"])
            self.assertNotIn(endpoint, output.getvalue())

    def test_quiet_suppresses_startup_and_saved_progress_but_keeps_stdout_json(self):
        self.config["progress"] = True
        stderr = io.StringIO()
        stdout = io.StringIO()
        with patch.object(cli, "load", return_value=dict(self.config)), \
             patch.object(cli, "run_external") as external, \
             redirect_stderr(stderr), redirect_stdout(stdout):
            external.side_effect = lambda *args, **kwargs: print(json.dumps({"status": "fixture"}))
            self.assertEqual(cli.main(["run", "--category", "misc", "--case-id", "fixture",
                                       "--quiet"]), 0)
        self.assertEqual(stderr.getvalue(), "")
        self.assertFalse(external.call_args.kwargs["progress"])
        self.assertEqual(json.loads(stdout.getvalue()), {"status": "fixture"})

    def test_startup_settings_are_on_stderr_without_proxy_endpoint(self):
        self.config.update(network_access="on", proxy_url="http://127.0.0.1:8080", progress=True)
        stderr = io.StringIO()
        stdout = io.StringIO()
        with patch.object(cli, "load", return_value=dict(self.config)), \
             patch.object(cli, "run_external") as external, \
             redirect_stderr(stderr), redirect_stdout(stdout):
            external.side_effect = lambda *args, **kwargs: print(json.dumps({"status": "fixture"}))
            self.assertEqual(cli.main(["run", "--category", "misc", "--case-id", "fixture"]), 0)
        self.assertIn("model=gpt-5.6-sol", stderr.getvalue())
        self.assertIn("network=on proxy=on progress=on", stderr.getvalue())
        self.assertNotIn("127.0.0.1", stderr.getvalue())
        self.assertEqual(json.loads(stdout.getvalue()), {"status": "fixture"})

    def test_progress_reports_failure_and_cancellation(self):
        _, summary, _ = self.run_mocked({"verifier": "failure"}, progress=True)
        self.assertEqual(summary["status"], "tool_failure")
        self.assertIn("verifier: candidate: unavailable (tool_failure; no valid report)", self.progress_output)
        self.assertIn("verifier: finished (tool_failure)", self.progress_output)
        _, summary, _ = self.run_mocked({"verifier": "cancel"}, progress=True)
        self.assertEqual(summary["status"], "cancelled")
        self.assertIn("verifier: candidate: unavailable (cancelled; no valid report)", self.progress_output)
        self.assertIn("verifier: finished (cancelled)", self.progress_output)
        self.assertIn("run: finished (cancelled)", self.progress_output)

    def test_valid_empty_candidate_and_invalid_report_are_distinct(self):
        _, summary, _ = self.run_mocked(candidates={"solver_a": "", "solver_b": ""}, progress=True)
        self.assertEqual(summary["status"], "disagreement")
        self.assertIn("solver_a: candidate: no candidate (valid report)", self.progress_output)
        _, summary, _ = self.run_mocked({"verifier": "invalid_report"}, progress=True)
        self.assertEqual(summary["status"], "invalid_report")
        self.assertIn("verifier: candidate: unavailable (invalid_report; no valid report)", self.progress_output)

    def test_timeout_and_safety_block_show_unavailable_candidate(self):
        _, summary, _ = self.run_mocked({"verifier": "timeout"}, progress=True)
        self.assertEqual(summary["status"], "timeout")
        self.assertIn("verifier: candidate: unavailable (timeout; no valid report)", self.progress_output)
        _, summary, _ = self.run_mocked({"verifier": "safety"}, progress=True)
        self.assertEqual(summary["status"], "safety_blocked")
        self.assertIn("verifier: candidate: unavailable (safety_blocked; no valid report)", self.progress_output)

    def test_cli_progress_switch_passes_to_external_runner(self):
        def selected(overrides):
            return config.validate({**self.config,
                **{key: value for key, value in overrides.items() if value is not None}})

        with patch.object(cli, "load", side_effect=selected), \
             patch.object(cli, "run_external") as external, redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(["run", "--category", "misc", "--case-id", "fixture",
                                       "--progress"]), 0)
        self.assertTrue(external.call_args.kwargs["progress"])

    def test_network_on_reaches_all_multi_roles_without_search(self):
        self.config["network_access"] = "on"
        path, summary, roles = self.run_mocked()
        self.assertEqual(set(roles), {"verifier", "solver_a", "solver_b", "verifier_review"})
        settings = json.loads((path / "settings.json").read_text(encoding="utf-8"))
        self.assertTrue(settings["network_access_requested"])
        self.assertFalse(settings["similar_search"])
        self.assertEqual(settings["network_access_effective"], "unverified")
        self.assertTrue(summary["network_access_requested"])
        self.assertFalse(summary["network_host_restriction"])
        for role in roles:
            invocation = json.loads((path / role / "invocation.json").read_text(encoding="utf-8"))
            self.assertIn("sandbox_workspace_write.network_access=true", invocation["argv_without_prompt"])
            self.assertIn("web_search=disabled", invocation["argv_without_prompt"])

    def test_dry_run_reports_network_override_without_model_call(self):
        self.config["network_access"] = "on"
        output = io.StringIO()
        with patch.object(cli, "load", return_value=self.config) as loaded, redirect_stdout(output):
            self.assertEqual(cli.main(["run", "--category", "misc", "--case-id", "fixture",
                                       "--preset", "test", "--network-access", "on", "--dry-run"]), 0)
        self.assertEqual(loaded.call_args.args[0]["network_access"], "on")
        plan = json.loads(output.getvalue())
        self.assertTrue(plan["network_access_requested"])
        self.assertFalse(plan["similar_search"])
        self.assertFalse(plan["answer_reference"])
        self.assertEqual(plan["network_access_effective"], "unverified")

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
        self.assertTrue((path / "candidates.json").is_file())
        self.assertGreaterEqual(summary["candidate_count"], 1)

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
        self.assertTrue((path / "candidates.json").is_file())
        self.assertGreaterEqual(summary["candidate_count"], 1)

    def test_disagreement_suppresses_top_level_candidate(self):
        path, summary, roles = self.run_mocked(candidates={"verifier": "first-answer"})
        self.assertEqual(len(roles), 4)
        self.assertEqual(summary["status"], "disagreement")
        self.assertIsNone(summary["candidate_file"])
        self.assertFalse((path / "candidate.txt").exists())
        proposals = json.loads((path / "candidates.json").read_text(encoding="utf-8"))
        self.assertEqual({item["candidate"] for item in proposals}, {"first-answer", "fixture-answer"})
        self.assertEqual(summary["candidate_count"], 2)
        self.assertTrue((path / "CANDIDATES.md").is_file())
        self.assertFalse(any(item["challenge_verified_by_harness"] for item in proposals))

    def test_target_url_is_not_external_reference_and_memory_is_unverified(self):
        target = "http://challenge.example:4080/"
        case_file = self.root / "categories" / "misc" / "cases" / "fixture" / "case.json"
        manifest = json.loads(case_file.read_text(encoding="utf-8"))
        manifest["authorized_target"] = target
        case_file.write_text(json.dumps(manifest), encoding="utf-8")
        reports = {"solver_a": {"method": "This is a memory guess from prior knowledge, not live evidence.",
                                "evidence": ["Unverified recalled candidate for http://challenge.example:4080/."]},
                   "verifier": {"evidence": ["Observed http://challenge.example:4080/login"]}}
        path, summary, roles = self.run_mocked(reports=reports, progress=True)
        self.assertEqual(summary["provenance_class"], "no-reference-requested")
        self.assertEqual(summary["external_reference_urls_declared"], [])
        self.assertIn("[unverified; memory_hypothesis]", self.progress_output)
        proposals = json.loads((path / "candidates.json").read_text(encoding="utf-8"))
        sources = {source["role"]: source for item in proposals for source in item["sources"]}
        self.assertEqual(sources["solver_a"]["basis"], "memory_hypothesis")
        self.assertTrue(sources["verifier_review"]["reads_frozen_reports"])

    def test_external_reference_requires_observed_tool_use(self):
        self.assertEqual(candidate_module.external_urls(
            ["http://challenge.example:4080/login", "https://writeup.example/guide"],
            "http://challenge.example:4080/"), ["https://writeup.example/guide"])
        self.assertEqual(candidate_module.external_urls(
            ["https://ctf.example/login", "https://ctf.example/writeups/cookie"],
            "https://ctf.example/"), ["https://ctf.example/writeups/cookie"])
        with tempfile.TemporaryDirectory() as folder:
            role = Path(folder) / "solver"
            role.mkdir()
            events = [{"type": "item.completed", "item": {"type": "command_execution", "exit_code": 0,
                "command": "curl -I https://writeup.example/guide"}}]
            (role / "events.jsonl").write_text("[]\n{bad json}\n" +
                                               "\n".join(json.dumps(event) for event in events), encoding="utf-8")
            urls, search = candidate_module.observed_references(Path(folder), ["solver"],
                                                                 "http://challenge.example:4080/")
            self.assertEqual(urls, ["https://writeup.example/guide"])
            self.assertFalse(search)

    def test_external_reference_provenance_distinguishes_declaration_from_access(self):
        reports = {"verifier": {"evidence": ["Public note: https://reference.example/guide"]}}
        _, declared, _ = self.run_mocked(reports=reports)
        self.assertEqual(declared["provenance_class"], "external-reference-declared-unverified")
        event = {"type": "item.completed", "item": {"type": "command_execution",
                 "id": "item_1", "command": "curl -f https://reference.example/guide",
                 "exit_code": 0, "aggregated_output": "fixture"}}
        _, observed, _ = self.run_mocked(reports=reports, events={"verifier": [event]})
        self.assertEqual(observed["provenance_class"], "reference-assisted")
        self.assertTrue(observed["external_reference_tool_observed"])

    def test_proxy_http_errors_are_observations_not_role_success(self):
        with tempfile.TemporaryDirectory() as folder:
            role = Path(folder) / "solver"
            role.mkdir()
            event = {"type": "item.completed", "item": {"type": "command_execution", "exit_code": 0,
                     "aggregated_output": "HTTP/1.1 400 Bad Request\nHTTP/1.1 502 Bad Gateway\nConnection refused\n"}}
            (role / "events.jsonl").write_text("[]\n{bad json}\n" + json.dumps(event) + "\n", encoding="utf-8")
            self.assertEqual(scan_proxy_diagnostics(Path(folder), ["solver"], True),
                             {"solver": {"http_400_seen": 1, "http_502_seen": 1, "connection_refused_seen": 1}})
            self.assertEqual(scan_proxy_diagnostics(Path(folder), ["solver"], False), {})

    def test_proxy_http_diagnostics_persist_without_response_body(self):
        self.config.update(network_access="on", proxy_url="http://127.0.0.1:8080")
        event = {"type": "item.completed", "item": {"type": "command_execution", "id": "item_2",
                 "exit_code": 0, "command": "curl http://example.invalid/",
                 "aggregated_output": "HTTP/1.1 502 Bad Gateway\nConnection refused\nprivate-cookie-value"}}
        path, summary, _ = self.run_mocked(events={"solver_a": [event]})
        self.assertEqual(summary["proxy_http_observations"]["solver_a"],
                         {"http_400_seen": 0, "http_502_seen": 1, "connection_refused_seen": 1})
        self.assertNotIn("private-cookie-value", (path / "result.json").read_text(encoding="utf-8"))

    def test_cookie_style_roles_keep_distinct_evidence_grades(self):
        target = "http://fixture.example:43123/"
        with tempfile.TemporaryDirectory() as folder:
            run = Path(folder)
            for role, code in (("verifier", "HTTP/1.1 302 Found"),
                               ("solver_a", "HTTP/1.1 502 Bad Gateway")):
                path = run / role
                path.mkdir()
                event = {"type": "item.completed", "item": {"type": "command_execution",
                         "id": "item_1", "exit_code": 0, "command": f"curl {target}login",
                         "aggregated_output": code}}
                (path / "events.jsonl").write_text(json.dumps(event) + "\n", encoding="utf-8")
            results = {
                "verifier": {"status": "completed", "candidate": "academy{fixture}",
                             "report_sha256": "a" * 64, "artifact_sha256": {"trace.txt": "b" * 64},
                             "report_data": {"method": "Read a cookie from the live target response.",
                                             "evidence": [target + "login"], "limitations": []}},
                "solver_a": {"status": "completed", "candidate": "picoCTF{memory_fixture}",
                             "report_sha256": "c" * 64, "artifact_sha256": {"notes.txt": "d" * 64},
                             "report_data": {"method": "Memory guess from a prior challenge, no live response.",
                                             "evidence": ["HTTP 502"], "limitations": ["Unverified memory"]}},
                "verifier_review": {"status": "completed", "candidate": "academy{fixture}",
                                    "report_sha256": "e" * 64, "artifact_sha256": {"review.txt": "f" * 64},
                                    "report_data": {"method": "Reviewed the frozen verifier result and solver guesses.",
                                                    "evidence": [], "limitations": []}},
            }
            proposals = candidate_module.catalog(results, target, run)
            self.assertEqual({item["candidate"] for item in proposals},
                             {"academy{fixture}", "picoCTF{memory_fixture}"})
            grades = {source["role"]: source for item in proposals for source in item["sources"]}
            self.assertEqual(grades["verifier"]["evidence_grade"], "target_http_observed")
            self.assertEqual(grades["verifier"]["target_http_observations"][0]["http_status"], 302)
            self.assertEqual(grades["solver_a"]["evidence_grade"], "memory_hypothesis")
            self.assertEqual(grades["verifier_review"]["evidence_grade"], "dependent_review")
            self.assertFalse(any(item["owner_confirmed"] for item in proposals))

    def test_candidate_catalog_failure_preserves_proposals_in_result(self):
        with patch.object(runner, "write_catalog", side_effect=OSError("private text")):
            path, summary, _ = self.run_mocked(candidates={"verifier": "one", "solver_a": "two"})
        self.assertEqual(summary["candidate_catalog_error_type"], "OSError")
        self.assertEqual({item["candidate"] for item in summary["candidates"]}, {"one", "two", "fixture-answer"})
        self.assertNotIn("private text", (path / "result.json").read_text(encoding="utf-8"))

    def test_keyboard_interrupt_persists_cancellation(self):
        path, summary, roles = self.run_mocked({"verifier": "cancel"})
        self.assertEqual(roles, ["verifier"])
        self.assertEqual(summary["status"], "cancelled")
        self.assertEqual(summary["agent_statuses"], {"verifier": "cancelled"})
        self.assertFalse((path / "candidate.txt").exists())


class ArchiveTests(unittest.TestCase):
    """All archive moves use temporary fixtures, never the owner's case data."""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.cases = self.root / "categories" / "web" / "cases"
        self.runs = self.root / "categories" / "web" / "runs"
        self.cases.mkdir(parents=True)
        self.runs.mkdir()
        self.local = self.root / ".local" / "config.toml"
        self.local.parent.mkdir()
        self.local.write_bytes(b'model = "owner-model"\nprogress = true\n')

    def populate(self):
        task = self.cases / "fixture" / "input"
        task.mkdir(parents=True)
        (task / "statement.txt").write_text("fixture challenge", encoding="utf-8")
        run = self.runs / "orphan-case" / "run-1"
        run.mkdir(parents=True)
        (run / "result.json").write_text('{"status":"fixture"}\n', encoding="utf-8")

    def test_empty_archive_is_noop_and_preserves_settings(self):
        preview = archive.archive_categories(self.root, ("web",))
        result = archive.archive_categories(self.root, ("web",), confirm=True)
        self.assertEqual(preview["status"], "nothing_to_archive")
        self.assertEqual(result["status"], "nothing_to_archive")
        self.assertFalse((self.root / "archives").exists())
        self.assertEqual(self.local.read_bytes(), b'model = "owner-model"\nprogress = true\n')

    def test_all_categories_requires_explicit_scope_and_keeps_empty_categories_usable(self):
        self.populate()
        crypto_cases = self.root / "categories" / "crypto" / "cases"
        crypto_cases.mkdir(parents=True)
        (crypto_cases / "fixture.txt").write_text("crypto fixture", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "select a valid category"):
            archive.archive_categories(self.root, confirm=True)
        preview = archive.archive_categories(self.root, archive.CATEGORIES)
        self.assertEqual({item["category"] for item in preview["items"]}, {"web", "crypto"})
        result = archive.archive_categories(self.root, archive.CATEGORIES, confirm=True)
        self.assertEqual(list(crypto_cases.iterdir()), [])
        self.assertEqual(list(self.cases.iterdir()), [])
        self.assertEqual(list(self.runs.iterdir()), [])
        self.assertTrue((Path(result["archive_dir"]) / "crypto" / "cases" / "fixture.txt").is_file())

    def test_archive_and_restore_cases_runs_orphans_and_preserved_files(self):
        self.populate()
        tool = self.root / ".venv" / "marker.txt"
        tool.parent.mkdir()
        tool.write_text("unchanged", encoding="utf-8")
        skills = self.root / "categories" / "web" / ".agents" / "SKILL.md"
        skills.parent.mkdir()
        skills.write_text("unchanged", encoding="utf-8")
        preview = archive.archive_categories(self.root, ("web",))
        self.assertEqual({item["kind"] for item in preview["items"]}, {"cases", "runs"})
        self.assertFalse((self.root / "archives").exists())
        self.assertTrue((self.cases / "fixture").exists())

        result = archive.archive_categories(self.root, ("web",), confirm=True)
        saved = Path(result["archive_dir"])
        manifest = json.loads((saved / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "complete")
        self.assertEqual({item["original"] for item in manifest["items"]},
                         {"categories/web/cases", "categories/web/runs"})
        self.assertTrue((saved / "web" / "cases" / "fixture" / "input" / "statement.txt").is_file())
        self.assertTrue((saved / "web" / "runs" / "orphan-case" / "run-1" / "result.json").is_file())
        self.assertEqual(list(self.cases.iterdir()), [])
        self.assertEqual(list(self.runs.iterdir()), [])
        self.assertEqual(self.local.read_bytes(), b'model = "owner-model"\nprogress = true\n')
        self.assertEqual(tool.read_text(encoding="utf-8"), "unchanged")
        self.assertEqual(skills.read_text(encoding="utf-8"), "unchanged")
        self.assertEqual(archive.list_archives(self.root)[0]["archive_id"], result["archive_id"])

        restore_preview = archive.restore_archive(self.root, result["archive_id"])
        self.assertEqual(restore_preview["status"], "ready")
        restored = archive.restore_archive(self.root, result["archive_id"], confirm=True)
        self.assertEqual(restored["status"], "restored")
        self.assertTrue((self.cases / "fixture" / "input" / "statement.txt").is_file())
        self.assertTrue((self.runs / "orphan-case" / "run-1" / "result.json").is_file())
        self.assertEqual(archive.restore_archive(self.root, result["archive_id"])["status"], "already_restored")

    def test_restore_refuses_nonempty_active_path_without_overwrite(self):
        self.populate()
        result = archive.archive_categories(self.root, ("web",), confirm=True)
        marker = self.cases / "new-case.txt"
        marker.write_text("new data", encoding="utf-8")
        preview = archive.restore_archive(self.root, result["archive_id"])
        self.assertEqual(preview["status"], "conflict")
        self.assertIn("categories/web/cases", preview["conflicts"])
        with self.assertRaisesRegex(ValueError, "restore refused"):
            archive.restore_archive(self.root, result["archive_id"], confirm=True)
        self.assertEqual(marker.read_text(encoding="utf-8"), "new data")
        self.assertTrue((Path(result["archive_dir"]) / "web" / "cases").is_dir())

    def test_active_run_lock_refuses_archive_and_restore(self):
        self.populate()
        with category_lock("web", self.root):
            with self.assertRaisesRegex(ValueError, "active"):
                archive.archive_categories(self.root, ("web",), confirm=True)
        result = archive.archive_categories(self.root, ("web",), confirm=True)
        with category_lock("web", self.root):
            with self.assertRaisesRegex(ValueError, "active"):
                archive.restore_archive(self.root, result["archive_id"], confirm=True)

    def test_symlinks_and_path_traversal_are_refused(self):
        self.populate()
        (self.cases / "fixture" / "input" / "escape").symlink_to(self.local)
        with self.assertRaisesRegex(ValueError, "symlinks"):
            archive.archive_categories(self.root, ("web",), confirm=True)
        (self.cases / "fixture" / "input" / "escape").unlink()
        result = archive.archive_categories(self.root, ("web",), confirm=True)
        with self.assertRaisesRegex(ValueError, "invalid archive ID"):
            archive.restore_archive(self.root, "../../escape", confirm=True)
        manifest_path = Path(result["manifest"])
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        data["items"][0]["original"] = "../outside"
        manifest_path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "path is invalid"):
            archive.restore_archive(self.root, result["archive_id"], confirm=True)

    def test_archive_root_symlink_is_refused(self):
        self.populate()
        (self.root / "archives").symlink_to(self.local.parent, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "archives path"):
            archive.archive_categories(self.root, ("web",), confirm=True)
        self.assertTrue((self.cases / "fixture" / "input" / "statement.txt").is_file())

    def test_partial_archive_move_rolls_back_without_losing_data(self):
        self.populate()
        original_rename = Path.rename

        def fail_run_move(path, target):
            if path == self.runs:
                raise OSError("injected second move failure")
            return original_rename(path, target)

        with patch.object(Path, "rename", fail_run_move):
            with self.assertRaisesRegex(ValueError, "original case and run directories were restored"):
                archive.archive_categories(self.root, ("web",), confirm=True)
        self.assertTrue((self.cases / "fixture" / "input" / "statement.txt").is_file())
        self.assertTrue((self.runs / "orphan-case" / "run-1" / "result.json").is_file())
        self.assertEqual(archive.list_archives(self.root), [])

    def test_failed_rollback_leaves_named_recovery_folder_and_all_data(self):
        self.populate()
        original_rename = Path.rename

        def fail_second_and_rollback(path, target):
            if path == self.runs:
                raise OSError("injected second move failure")
            if path.name == "cases" and path.parent.name == "web" and path.parent.parent.name.startswith(".pending-"):
                raise OSError("injected rollback failure")
            return original_rename(path, target)

        with patch.object(Path, "rename", fail_second_and_rollback):
            with self.assertRaisesRegex(ValueError, "recovery needed"):
                archive.archive_categories(self.root, ("web",), confirm=True)
        pending = archive.list_archives(self.root)
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["status"], "recovery_needed")
        saved = Path(pending[0]["path"])
        self.assertTrue((saved / "web" / "cases" / "fixture" / "input" / "statement.txt").is_file())
        self.assertTrue((self.runs / "orphan-case" / "run-1" / "result.json").is_file())
        self.assertEqual(self.local.read_bytes(), b'model = "owner-model"\nprogress = true\n')

    def test_partial_restore_move_rolls_back_to_archive(self):
        self.populate()
        result = archive.archive_categories(self.root, ("web",), confirm=True)
        saved = Path(result["archive_dir"])
        original_rename = Path.rename

        def fail_run_restore(path, target):
            if path == saved / "web" / "runs":
                raise OSError("injected second restore failure")
            return original_rename(path, target)

        with patch.object(Path, "rename", fail_run_restore):
            with self.assertRaisesRegex(ValueError, "archive contents were returned"):
                archive.restore_archive(self.root, result["archive_id"], confirm=True)
        self.assertTrue((saved / "web" / "cases" / "fixture" / "input" / "statement.txt").is_file())
        self.assertTrue((saved / "web" / "runs" / "orphan-case" / "run-1" / "result.json").is_file())
        self.assertEqual(list(self.cases.iterdir()), [])
        self.assertEqual(list(self.runs.iterdir()), [])
        self.assertEqual(json.loads((saved / "manifest.json").read_text(encoding="utf-8"))["status"], "complete")

    def test_cli_preview_then_confirm_then_list_and_restore(self):
        self.populate()
        output = io.StringIO()
        with patch.object(cli, "ROOT", self.root), redirect_stdout(output):
            self.assertEqual(cli.main(["archive", "--category", "web", "--dry-run"]), 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "ready")
        self.assertTrue((self.cases / "fixture").exists())
        with patch.object(cli, "ROOT", self.root), redirect_stdout(io.StringIO()) as output:
            self.assertEqual(cli.main(["archive", "--category", "web", "--confirm"]), 0)
        archive_id = json.loads(output.getvalue())["archive_id"]
        with patch.object(cli, "ROOT", self.root), redirect_stdout(io.StringIO()) as output:
            self.assertEqual(cli.main(["archives"]), 0)
        self.assertEqual(json.loads(output.getvalue())[0]["archive_id"], archive_id)
        with patch.object(cli, "ROOT", self.root), redirect_stdout(io.StringIO()) as output:
            self.assertEqual(cli.main(["restore", "--archive-id", archive_id, "--confirm"]), 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "restored")


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
            for path in ("archives/20261028T120000Z-12345678/web/cases/x/input.txt",
                         "categories/web/.harness.lock"):
                result = subprocess.run(["git", "-C", str(root), "check-ignore", "-q", path], check=False)
                self.assertEqual(result.returncode, 0, path)
            source = subprocess.run(["git", "-C", str(root), "check-ignore", "-q", "harness/runner.py"], check=False)
            self.assertNotEqual(source.returncode, 0)


if __name__ == "__main__":
    unittest.main()
