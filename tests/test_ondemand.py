"""Offline checks for curated role-requested tools."""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from harness import ondemand, toolinstall, install_requested


class OnDemandTests(unittest.TestCase):
    def test_every_candidate_has_an_install_recipe_and_autopsy_is_excluded(self):
        covered = set(install_requested.APT) | set(install_requested.UV) | set(install_requested.SOURCE)
        covered |= {"ysoserial", "kaitai-struct"}
        self.assertEqual(set(ondemand.SPECS), covered)
        self.assertNotIn("autopsy", ondemand.SPECS)
        self.assertIn("ssrfmap", ondemand.SPECS)
        self.assertIn("scalpel", ondemand.SPECS)
        for name in ondemand.SPECS:
            group = {"key": ("on_demand", name), "categories": set(ondemand.SPECS[name][0]),
                     "required": False, "item": {"guidance": ""}}
            units = toolinstall.plan([group])
            self.assertEqual(units[0]["command"][-1], name)

    def test_category_catalog_explains_missing_tools_and_how_to_request(self):
        with tempfile.TemporaryDirectory() as directory:
            role = Path(directory)
            ondemand.write_catalog(role, "web")
            rows = json.loads((role / "tool-catalog.json").read_text())
            names = {row["name"] for row in rows}
            self.assertIn("ffuf", names)
            self.assertIn("ssrfmap", names)
            self.assertNotIn("tsk", names)
            content = (role / "TOOL-CATALOG.md").read_text()
            self.assertIn("request-tool.py", content)
            self.assertIn("Bounded target discovery", content)

    def test_curated_request_installs_once_and_persists_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            role = Path(directory) / "categories/web/runs/case/run/solver_a"
            requests = role / "tool-requests"
            requests.mkdir(parents=True)
            request_id = "a" * 32
            (requests / f"{request_id}.json").write_text(json.dumps(
                {"id": request_id, "tool": "ffuf", "reason": "The selected target has hidden paths"}))
            missing = {"kind": "on_demand", "name": "ffuf", "category": "web",
                       "required": False, "status": "missing", "guidance": ""}
            summary = Path(directory) / "summary.json"
            def installed(units, *, context, summary_callback):
                self.assertEqual(context["tool"], "ffuf")
                summary.write_text("{}")
                summary_callback(summary)
                return 0
            with patch.object(toolinstall, "inventory", return_value=[missing]), \
                 patch.object(toolinstall, "install", side_effect=installed):
                events = ondemand.service_requests(role, "solver_a")
                self.assertEqual(ondemand.service_requests(role, "solver_a"), [])
            self.assertEqual(events[0]["status"], "installed")
            response = role.parent / "tool-results" / f"solver_a-{request_id}.json"
            self.assertEqual(json.loads(response.read_text())["install_summary"], str(summary))
            self.assertIn("ffuf", (role.parent / "tool-installations.jsonl").read_text())

    def test_role_cannot_expand_catalog_to_install_other_category(self):
        with tempfile.TemporaryDirectory() as directory:
            role = Path(directory) / "categories/web/runs/case/run/solver_a"
            requests = role / "tool-requests"
            requests.mkdir(parents=True)
            request_id = "b" * 32
            (requests / f"{request_id}.json").write_text(json.dumps(
                {"id": request_id, "tool": "tsk", "reason": "Unrelated disk tool"}))
            (role / "tool-catalog.json").write_text('[{"name":"tsk"}]')
            with patch.object(toolinstall, "install") as install:
                events = ondemand.service_requests(role, "solver_a")
            install.assert_not_called()
            self.assertEqual(events[0]["status"], "failed")
            self.assertIn("not in this role", events[0]["error"])

    def test_request_command_receives_manager_result(self):
        with tempfile.TemporaryDirectory() as directory:
            role = Path(directory) / "categories/web/runs/case/run/solver_a"
            role.mkdir(parents=True)
            (role / "tool-catalog.json").write_text('[{"name":"ffuf"}]')
            environment = dict(os.environ, PYTHONPATH=str(Path(ondemand.__file__).resolve().parents[1]))
            process = subprocess.Popen(
                [sys.executable, "-m", "harness.ondemand", "ffuf", "--reason", "Bounded path search"],
                cwd=role, env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                for _ in range(100):
                    if list((role / "tool-requests").glob("*.json")):
                        break
                    time.sleep(0.02)
                else:
                    self.fail("request command did not write a request")
                available = {"kind": "on_demand", "name": "ffuf", "category": "web",
                             "required": False, "status": "available", "guidance": ""}
                with patch.object(toolinstall, "inventory", return_value=[available]):
                    events = ondemand.service_requests(role, "solver_a")
                output, error = process.communicate(timeout=3)
                self.assertEqual(process.returncode, 0, error)
                self.assertEqual(events[0]["status"], "already_available")
                self.assertIn("already_available", output)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()


if __name__ == "__main__":
    unittest.main()
