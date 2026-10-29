"""Offline checks for the read-only category tool inventory."""
import io
import json
import os
import re
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from harness import toolcheck
from harness import cli


class ToolCheckTests(unittest.TestCase):
    def test_known_categories_and_missing_filter(self):
        with patch.object(toolcheck, "_binary_item", side_effect=lambda category, name, required, guide:
                          {"category": category, "name": name, "kind": "binary", "required": required,
                           "status": "missing" if name == "gdb" else "available",
                           "path": None, "version": None, "guidance": guide}), \
             patch.object(toolcheck, "_python_item", side_effect=lambda category, dist, module:
                          {"category": category, "name": dist, "kind": "python", "required": True,
                           "status": "available", "path": "/project/.venv/bin/python", "version": "1", "guidance": "uv"}):
            items = toolcheck.collect("pwn", missing_only=True)
        self.assertEqual([(item["category"], item["name"]) for item in items], [("pwn", "gdb")])
        with self.assertRaises(ValueError):
            toolcheck.collect("../../etc")

    def test_json_output_and_no_install(self):
        fixture = [{"category": "reverse", "name": "Ghidra", "kind": "native_provider",
                    "required": False, "status": "untested", "path": None, "version": None,
                    "guidance": "Inspect the configured provider."}]
        output = io.StringIO()
        with patch.object(toolcheck, "collect", return_value=fixture) as collect, \
             redirect_stdout(output):
            self.assertEqual(toolcheck.main(["--category", "reverse", "--missing-only", "--json"]), 0)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["tools"], fixture)
        collect.assert_called_once_with("reverse", True)

    def test_distributions_checked_with_actual_interpreter(self):
        item = toolcheck._python_item("crypto", "sympy", "sympy")
        self.assertEqual(item["status"], "available")
        self.assertEqual(item["path"], toolcheck.sys.executable)
        self.assertIsNotNone(item["version"])

    def test_reverse_provider_is_required_for_reverse_runs(self):
        with patch.object(toolcheck, "_local_native_items", wraps=toolcheck._local_native_items) as native:
            items = toolcheck.collect("reverse")
        native.assert_called_once()
        required = {item["name"] for item in items if item["required"]}
        self.assertTrue({"Ghidra", "Temurin JDK", "Node.js", "REA",
                         "REA/Ghidra provider", "rea-static role interface"}.issubset(required))

    def test_clone_local_binary_is_detected_before_system_path(self):
        with tempfile.TemporaryDirectory() as folder:
            local = Path(folder) / "bin" / "binwalk"
            local.parent.mkdir()
            local.write_text("#!/bin/sh\necho binwalk 3.1.0\n")
            local.chmod(0o755)
            with patch.object(toolcheck, "TOOLS", Path(folder)), \
                 patch.object(toolcheck.shutil, "which", return_value=None):
                item = toolcheck._binary_item("forensics", "binwalk", False, "fixture")
        self.assertEqual(item["status"], "available")
        self.assertEqual(item["version"], "binwalk 3.1.0")

    def test_historical_rea_results_never_appear_in_any_checker_output(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            tools = root / ".local/tools"
            tools.mkdir(parents=True)
            old_path = "private-old-selftest-should-not-appear"
            (tools / "rea-child-smoke.json").write_text(json.dumps({"network_off": {"result": old_path}}))
            with patch.object(toolcheck, "ROOT", root), patch.object(toolcheck, "TOOLS", tools):
                for arguments in (["--category", "reverse"],
                                  ["--category", "reverse", "--missing-only"],
                                  ["--category", "reverse", "--json"],
                                  ["--category", "reverse", "--missing-only", "--json"]):
                    output = io.StringIO()
                    with redirect_stdout(output):
                        self.assertEqual(toolcheck.main(arguments), 0)
                    self.assertNotIn(old_path, output.getvalue())
                    self.assertNotIn("recorded self-test", output.getvalue())
                    self.assertNotIn("recorded_integration", output.getvalue())
                    self.assertNotIn("network-off", output.getvalue())

    def test_missing_real_binary_still_detected_without_history(self):
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(toolcheck, "TOOLS", Path(folder)), \
             patch.object(toolcheck.shutil, "which", return_value=None):
            item = toolcheck._binary_item("pwn", "gdb", False, "Install GDB")
        self.assertEqual(item["status"], "missing")
        self.assertEqual(item["name"], "gdb")

    def test_human_table_deduplicates_shared_tools_and_keeps_json_items(self):
        fixture = [
            {"category": "web", "kind": "binary", "name": "curl", "status": "available",
             "required": False, "version": "curl 8.17.0", "path": "/private/curl"},
            {"category": "osint", "kind": "binary", "name": "curl", "status": "available",
             "required": False, "version": "curl 8.17.0", "path": "/private/curl"},
            {"category": "all", "kind": "binary", "name": "uv", "status": "available",
             "required": True, "version": "uv 0.13.1", "path": "/private/uv"},
        ]
        shown = toolcheck.render_human(fixture, width=100)
        self.assertEqual(shown.count("curl"), 1)
        self.assertIn("WEB, OSI", shown)
        self.assertIn("ALL", shown)
        self.assertIn("8.17.0", shown)
        self.assertNotIn("/private", shown)
        output = io.StringIO()
        with patch.object(toolcheck, "collect", return_value=fixture), redirect_stdout(output):
            self.assertEqual(toolcheck.main(["--json"]), 0)
        self.assertEqual(json.loads(output.getvalue())["tools"], fixture)

    def test_category_filter_keeps_actual_shared_category_association(self):
        fixture = [{"category": "pwn", "kind": "binary", "name": "readelf",
                    "status": "available", "required": False,
                    "version": "GNU readelf (GNU Binutils) 2.46", "path": "/usr/bin/readelf"}]
        shown = toolcheck.render_human(fixture, width=100)
        self.assertIn("PWN, REV", shown)
        self.assertIn("2.46", shown)

    def test_missing_unknown_and_incompatible_are_distinct(self):
        fixture = [{"category": "pwn", "kind": "binary", "name": "gdb",
                    "status": "missing", "required": False, "version": None},
                   {"category": "reverse", "kind": "integration", "name": "REA/Ghidra provider",
                    "status": "incompatible", "required": True, "version": "6.8.0 + 12.1.4"},
                   {"category": "misc", "kind": "binary", "name": "custom-tool",
                    "status": "untested", "required": False, "version": None}]
        shown = toolcheck.render_human(fixture, width=100, missing_only=True)
        self.assertEqual(shown.splitlines()[0], "Required / Optional")
        self.assertEqual(shown.splitlines()[1].split(), ["TOOL", "VERSION", "CATEGORIES", "STATUS"])
        rows = toolcheck._human_rows(fixture)
        self.assertEqual([(row[1], row[3]) for row in rows], [("-", "-"),
                                                               ("6.8.0 / 12.1.4", "✕"),
                                                               ("UNKNOWN", "-")])
        self.assertIsNone(re.search(r"[\u3040-\u30ff\u3400-\u9fff]", shown))

    def test_missing_filter_excludes_untested_but_keeps_current_failures(self):
        with patch.object(toolcheck, "_binary_item", side_effect=lambda category, name, required, guide:
                          {"category": category, "name": name, "kind": "binary", "required": required,
                           "status": "missing" if name == "gdb" else "untested" if name == "socat" else "available",
                           "path": None, "version": None, "guidance": guide}), \
             patch.object(toolcheck, "_python_item", side_effect=lambda category, dist, module:
                          {"category": category, "name": dist, "kind": "python", "required": True,
                           "status": "available", "path": None, "version": "1", "guidance": "uv"}):
            items = toolcheck.collect("pwn", missing_only=True)
        self.assertEqual([item["name"] for item in items], ["gdb"])
        self.assertEqual(toolcheck.render_human([], missing_only=True), "No missing tools.")

    def test_narrow_terminal_wraps_without_truncation_or_ambiguous_aliases(self):
        fixture = [{"category": "misc", "kind": "binary", "name": "very-long-tool-alpha",
                    "status": "available", "required": False, "version": "123.456.789"},
                   {"category": "misc", "kind": "binary", "name": "very-long-tool-beta",
                    "status": "available", "required": False, "version": "123.456.789"},
                   {"category": "web", "kind": "python", "name": "beautifulsoup4",
                    "status": "available", "required": True, "version": "4.15.0"},
                   {"category": "web", "kind": "binary", "name": "Beautiful Soup",
                    "status": "available", "required": False, "version": "1.2.3"}]
        rows = toolcheck._human_rows(fixture)
        self.assertEqual(len({row[0] for row in rows}), len(rows))
        shown = toolcheck.render_human(fixture, width=24)
        self.assertIn("TOOL:", shown)
        self.assertNotIn("…", shown)
        self.assertTrue(all(toolcheck._cell_width(line) <= 24 for line in shown.splitlines()))
        colored = toolcheck.render_human(fixture, width=24, color=True)
        uncolored = re.sub(r"\x1b\[[0-9;]*m", "", colored)
        self.assertEqual(uncolored, shown)
        self.assertTrue(all(toolcheck._cell_width(line) <= 24 for line in uncolored.splitlines()))

    def test_required_rows_and_status_glyph_colors(self):
        fixture = [{"category": "all", "kind": "binary", "name": "uv", "required": True,
                    "status": "available", "version": "uv 0.13.1"},
                   {"category": "web", "kind": "binary", "name": "curl", "required": False,
                    "status": "available", "version": "curl 8.18.0"},
                   {"category": "reverse", "kind": "python", "name": "z3-solver", "required": True,
                    "status": "incompatible", "version": "5.3.2.0"},
                   {"category": "pwn", "kind": "binary", "name": "gdb", "required": False,
                    "status": "missing", "version": None}]
        plain = toolcheck.render_human(fixture, width=100)
        self.assertEqual(plain.splitlines()[0], "Required / Optional")
        self.assertIn("✓", plain)
        self.assertIn("✕", plain)
        self.assertNotIn("\x1b[", plain)
        self.assertIsNone(re.search(r"[\u3040-\u30ff\u3400-\u9fff]", plain))
        colored = toolcheck.render_human(fixture, width=100, color=True)
        self.assertEqual(colored.splitlines()[0], "\x1b[32mRequired\x1b[0m / Optional")
        uv, curl, z3, gdb = [line for line in colored.splitlines()[3:] if line.strip()]
        self.assertIn("\x1b[32muv", uv)
        self.assertIn("\x1b[32m✓\x1b[0m", uv)
        self.assertNotIn("\x1b[32mcurl", curl)
        self.assertIn("\x1b[32m✓\x1b[0m", curl)
        self.assertIn("\x1b[32mZ3", z3)
        self.assertIn("\x1b[31m✕\x1b[0m", z3)
        self.assertNotIn("\x1b[", gdb)
        self.assertIn("-", gdb)

    def test_color_only_for_capable_interactive_stdout(self):
        class TTYBuffer(io.StringIO):
            def isatty(self):
                return True

        fixture = [{"category": "all", "kind": "binary", "name": "uv", "required": True,
                    "status": "available", "version": "uv 0.13.1"}]
        tty = TTYBuffer()
        with patch.object(toolcheck, "collect", return_value=fixture), \
             patch.object(toolcheck.sys, "stdout", tty), \
             patch.dict(os.environ, {"TERM": "xterm-256color"}, clear=True):
            toolcheck.main([])
        self.assertTrue(tty.getvalue().startswith("\x1b[32mRequired\x1b[0m / Optional\n"))
        for environment in ({"TERM": "xterm-256color", "NO_COLOR": ""}, {"TERM": "dumb"}):
            tty = TTYBuffer()
            with patch.object(toolcheck, "collect", return_value=fixture), \
                 patch.object(toolcheck.sys, "stdout", tty), \
                 patch.dict(os.environ, environment, clear=True):
                toolcheck.main([])
            self.assertNotIn("\x1b[", tty.getvalue())
            self.assertTrue(tty.getvalue().startswith("Required / Optional\n"))
        output = io.StringIO()
        with patch.object(toolcheck, "collect", return_value=fixture), \
             redirect_stdout(output), patch.dict(os.environ, {"TERM": "xterm-256color"}, clear=True):
            toolcheck.main([])
        self.assertNotIn("\x1b[", output.getvalue())
        tty = TTYBuffer()
        with patch.object(toolcheck, "collect", return_value=fixture), \
             patch.object(toolcheck.sys, "stdout", tty), \
             patch.dict(os.environ, {"TERM": "xterm-256color"}, clear=True):
            toolcheck.main(["--json"])
        self.assertNotIn("\x1b[", tty.getvalue())
        self.assertEqual(json.loads(tty.getvalue())["tools"], fixture)

    def test_outer_tools_help_explains_three_letter_category_tags(self):
        output = io.StringIO()
        with redirect_stdout(output), self.assertRaises(SystemExit) as stopped:
            cli.main(["tools", "--help"])
        self.assertEqual(stopped.exception.code, 0)
        self.assertIn("WEB=web", output.getvalue())
        self.assertIn("FOR=forensics", output.getvalue())


if __name__ == "__main__":
    unittest.main()
