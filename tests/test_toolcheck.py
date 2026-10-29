"""Offline checks for the read-only category tool inventory."""
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from harness import toolcheck


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


if __name__ == "__main__":
    unittest.main()
