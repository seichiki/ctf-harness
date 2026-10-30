"""Offline tests for the opt-in, project-local tool installer."""
import io
import json
import os
import pty
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from harness import toolinstall


def group(kind, name, *, required=False, category="forensics"):
    item = {"kind": kind, "name": name, "required": required, "category": category,
            "status": "missing", "version": None}
    return {"key": (kind, name), "item": item, "required": required,
            "categories": {category}}


class InstallerTests(unittest.TestCase):
    def test_plan_resolves_bundle_and_native_dependency_once(self):
        selected = [group("python", "sympy", required=True, category="crypto"),
                    group("native_provider", "Ghidra", required=True, category="reverse"),
                    group("binary", "binwalk"), group("binary", "7z")]
        units = toolinstall.plan(selected)
        self.assertEqual([unit["id"] for unit in units],
                         ["python-bundle", "rea-ghidra-bundle", "binwalk"])
        self.assertIn("7z", units[2]["covers"])
        self.assertEqual(units[0]["command"], ["uv", "sync", "--locked"])
        self.assertIn("httpx", units[0]["covers"])  # indivisible default groups disclosed

    def test_stego_tools_have_local_ubuntu_install_plans(self):
        units = toolinstall.plan([group("binary", "steghide", required=True),
                                  group("binary", "stegseek")])
        self.assertEqual([unit["id"] for unit in units], ["steghide", "stegseek"])
        for unit in units:
            self.assertIn("libmcrypt4", unit["note"])
            self.assertIn("libmhash2", unit["note"])
            self.assertIn("libjpeg-turbo8", unit["note"])
            self.assertEqual(unit["command"][-2:], ["--only", unit["id"]])

    def test_only_selected_native_and_manual_tool(self):
        units = toolinstall.plan([group("binary", "unzip"), group("binary", "curl")])
        self.assertEqual([unit["id"] for unit in units], ["unzip", "curl"])
        self.assertEqual(units[0]["command"][-2:], ["--only", "unzip"])
        self.assertIn("Planned apt archives: unzip", units[0]["note"])
        self.assertNotIn("gdb", units[0]["note"])
        self.assertEqual(units[1]["command"][-1], "curl")
        hostile = toolinstall.plan([group("binary", "unzip; touch /tmp/unwanted")])
        self.assertIsNone(hostile[0]["command"])

    def test_missing_group_dedup_preserves_categories_and_required(self):
        items = [{"kind": "binary", "name": "curl", "category": category,
                  "required": required, "status": "missing"}
                 for category, required in (("web", False), ("osint", True))]
        groups = toolinstall.missing_groups(items)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["categories"], {"web", "osint"})
        self.assertTrue(groups[0]["required"])

    def test_secret_and_control_masking(self):
        shown = toolinstall.safe_text(
            "Authorization: Bearer ABC Cookie: abc token=xyz http://u:p@host/?key=secret\x1b[31m")
        for secret in ("ABC", "abc", "xyz", "u:p", "secret", "\x1b"):
            self.assertNotIn(secret, shown)

    def test_real_owned_subprocess_log_is_masked(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            path = Path(directory) / "unit.log"
            code = toolinstall._execute(
                [sys.executable, "-c",
                 "print('Authorization: Bearer PRIVATEVALUE'); print('step complete')"],
                path, "[----------] 0/1 units finished")
            log = path.read_text()
        self.assertEqual(code, 0)
        self.assertNotIn("PRIVATEVALUE", log)
        self.assertIn("step complete", log)

    def test_interrupt_kills_only_owned_subprocess_group(self):
        actual_popen = subprocess.Popen
        spawned = []
        def start(*args, **kwargs):
            child = actual_popen(*args, **kwargs)
            spawned.append(child)
            return child
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(toolinstall.subprocess, "Popen", side_effect=start), \
             patch.object(toolinstall.select, "select", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                toolinstall._execute(["bash", "-c", "sleep 10"],
                                     Path(directory) / "unit.log", "[----------] 0/1")
        self.assertEqual(len(spawned), 1)
        self.assertIsNotNone(spawned[0].poll())

    def test_progress_and_partial_failure_summary(self):
        units = [{"id": name, "covers": [name], "command": ["echo", name],
                  "source": "fixture", "note": ""} for name in ("one", "two")]
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(toolinstall, "ROOT", Path(directory)), \
             patch.object(toolinstall, "_execute", side_effect=[1, 0]) as execute, \
             patch.object(toolinstall, "_verify", return_value=[]), \
             redirect_stdout(io.StringIO()) as output:
            self.assertEqual(toolinstall.install(units), 1)
            path = next((Path(directory) / ".local/install-runs").glob("*/summary.json"))
            summary = json.loads(path.read_text())
        self.assertEqual([record["status"] for record in summary["units"]],
                         ["failed", "completed"])
        self.assertEqual(execute.call_count, 2)
        self.assertIn("[####################] 2/2 units finished", output.getvalue())

    def test_post_install_checker_failure_is_not_reported_complete(self):
        unit = {"id": "unzip", "covers": ["unzip"], "command": ["echo", "fixture"],
                "source": "fixture", "note": ""}
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(toolinstall, "ROOT", Path(directory)), \
             patch.object(toolinstall, "_execute", return_value=0), \
             patch.object(toolinstall, "_verify", return_value=["unzip"]), \
             redirect_stdout(io.StringIO()):
            self.assertEqual(toolinstall.install([unit]), 1)
            path = next((Path(directory) / ".local/install-runs").glob("*/summary.json"))
            record = json.loads(path.read_text())["units"][0]
        self.assertEqual(record["status"], "failed")
        self.assertIn("unzip", record["reason"])

    def test_interruption_persists_and_skips_remaining(self):
        units = [{"id": name, "covers": [name], "command": ["echo", name],
                  "source": "fixture", "note": ""} for name in ("one", "two")]
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(toolinstall, "ROOT", Path(directory)), \
             patch.object(toolinstall, "_execute", side_effect=KeyboardInterrupt), \
             redirect_stdout(io.StringIO()):
            self.assertEqual(toolinstall.install(units), 130)
            path = next((Path(directory) / ".local/install-runs").glob("*/summary.json"))
            summary = json.loads(path.read_text())
        self.assertEqual([record["status"] for record in summary["units"]],
                         ["failed", "skipped"])

    def test_mode_filter_cancel_and_non_tty(self):
        groups = [group("binary", "gdb", required=True), group("binary", "unzip")]
        with patch.object(toolinstall, "inventory", return_value=[g["item"] for g in groups]), \
             patch.object(toolinstall, "select_tools", return_value=None), \
             redirect_stdout(io.StringIO()) as output:
            self.assertEqual(toolinstall.main([]), 0)
        self.assertIn("Cancelled", output.getvalue())
        with patch.object(toolinstall, "inventory", return_value=[g["item"] for g in groups]), \
             patch.object(toolinstall, "install") as install, \
             patch.object(toolinstall.sys.stdin, "isatty", return_value=False), \
             redirect_stdout(io.StringIO()):
            self.assertEqual(toolinstall.main(["--all"]), 2)
        install.assert_not_called()
        with patch.object(toolinstall, "inventory", return_value=[g["item"] for g in groups]), \
             patch.object(toolinstall, "install", return_value=0) as install, \
             patch.object(toolinstall.sys.stdin, "isatty", return_value=False), \
             patch("builtins.input") as read, redirect_stdout(io.StringIO()):
            self.assertEqual(toolinstall.main(["--required", "--yes"]), 0)
        read.assert_not_called()
        self.assertEqual([unit["id"] for unit in install.call_args.args[0]], ["gdb"])
        with patch.object(toolinstall, "inventory", return_value=[g["item"] for g in groups]), \
             patch.object(toolinstall, "install") as install, \
             patch.object(toolinstall.sys.stdin, "isatty", return_value=False), \
             redirect_stdout(io.StringIO()):
            self.assertEqual(toolinstall.main(["--yes"]), 2)
        install.assert_not_called()
        with patch.object(toolinstall, "inventory", return_value=[g["item"] for g in groups]), \
             patch.object(toolinstall, "install", return_value=0) as install, \
             patch.object(toolinstall.sys.stdin, "isatty", return_value=True), \
             patch("builtins.input", return_value="y"), \
             redirect_stdout(io.StringIO()):
            self.assertEqual(toolinstall.main(["--all"]), 0)
        self.assertEqual([unit["id"] for unit in install.call_args.args[0]], ["gdb", "unzip"])
        with patch.object(toolinstall, "inventory", return_value=[g["item"] for g in groups]), \
             patch.object(toolinstall, "install", return_value=0) as install, \
             patch("builtins.input", return_value=""), \
             patch.object(toolinstall.sys.stdin, "isatty", return_value=True), \
             redirect_stdout(io.StringIO()):
            self.assertEqual(toolinstall.main(["--required"]), 0)
        self.assertEqual([unit["id"] for unit in install.call_args.args[0]], ["gdb"])
        with redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit):
                toolinstall.main(["--all", "--required"])

    def test_no_missing_and_confirmation_eof_do_not_install(self):
        with patch.object(toolinstall, "inventory", return_value=[]), \
             patch.object(toolinstall, "install") as install, \
             redirect_stdout(io.StringIO()) as output:
            self.assertEqual(toolinstall.main(["--all"]), 0)
        install.assert_not_called()
        self.assertIn("No missing tools.", output.getvalue())
        fixture = group("binary", "unzip")
        with patch.object(toolinstall, "inventory", return_value=[fixture["item"]]), \
             patch.object(toolinstall, "install") as install, \
             patch.object(toolinstall.sys.stdin, "isatty", return_value=True), \
             patch("builtins.input", side_effect=EOFError), \
             redirect_stdout(io.StringIO()):
            self.assertEqual(toolinstall.main(["--all"]), 130)
        install.assert_not_called()

    def test_selector_keyboard_and_terminal_restore(self):
        class TTY(io.StringIO):
            def isatty(self): return True
            def fileno(self): return 0
        keys = iter(["down", "toggle", "up", "toggle", "done"])
        output = TTY()
        with patch.object(toolinstall.sys, "stdin", TTY()), \
             patch.object(toolinstall.sys, "stdout", output), \
             patch.object(toolinstall.termios, "tcgetattr", return_value=[]), \
             patch.object(toolinstall.termios, "tcsetattr") as restore, \
             patch.object(toolinstall.tty, "setraw"), \
             patch.object(toolinstall, "_read_key", side_effect=lambda: next(keys)), \
             patch.dict(os.environ, {"TERM": "xterm"}):
            selected = toolinstall.select_tools([group("binary", "gdb"),
                                                  group("binary", "unzip")])
        self.assertEqual([g["key"][1] for g in selected], ["gdb", "unzip"])
        restore.assert_called_once()
        self.assertIn("\x1b[?25h", output.getvalue())
        with patch.object(toolinstall.sys, "stdin", TTY()), \
             patch.object(toolinstall.sys, "stdout", TTY()), \
             patch.object(toolinstall.termios, "tcgetattr", return_value=[]), \
             patch.object(toolinstall.termios, "tcsetattr") as restore, \
             patch.object(toolinstall.tty, "setraw"), \
             patch.object(toolinstall, "_read_key", return_value="cancel"), \
             patch.dict(os.environ, {"TERM": "xterm"}):
            self.assertIsNone(toolinstall.select_tools([group("binary", "gdb")]))
        restore.assert_called_once()

    def test_real_pty_arrow_space_enter(self):
        root = Path(toolinstall.__file__).resolve().parents[1]
        script = (
            "from harness.toolinstall import select_tools\n"
            "groups=[{'key':('binary',n),'item':{'kind':'binary','name':n,"
            "'category':'forensics','version':None},'required':False,"
            "'categories':{'forensics'}} for n in ('gdb','unzip')]\n"
            "result=select_tools(groups)\n"
            "print('SELECTED:' + ','.join(g['key'][1] for g in result or []), flush=True)\n"
        )
        master, slave = pty.openpty()
        process = subprocess.Popen(
            ["uv", "run", "--no-project", "--offline", "--python", "3.12",
             "python", "-c", script], cwd=root, stdin=slave, stdout=slave, stderr=slave,
            start_new_session=True, env={**os.environ, "TERM": "xterm"})
        os.close(slave)
        output = b""
        try:
            deadline = time.monotonic() + 10
            while b"Missing tools:" not in output and time.monotonic() < deadline:
                if select.select([master], [], [], 0.2)[0]:
                    output += os.read(master, 8192)
            self.assertIn(b"Missing tools:", output)
            os.write(master, b"\x1b[B \r")
            while b"SELECTED:" not in output and time.monotonic() < deadline:
                if select.select([master], [], [], 0.2)[0]:
                    try:
                        output += os.read(master, 8192)
                    except OSError:
                        break
            self.assertEqual(process.wait(timeout=2), 0)
            self.assertIn(b"SELECTED:unzip", output)
            self.assertIn(b"\x1b[?25h", output)
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=3)
            os.close(master)

    def test_fresh_bootstrap_without_project_venv(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "harness").mkdir()
            for file in ("__init__.py", "config.py", "confirm.py", "toolcheck.py", "toolinstall.py"):
                source = Path(toolinstall.__file__).parent / file
                (root / "harness" / file).write_bytes(source.read_bytes())
            shutil.copy2(Path(toolinstall.__file__).resolve().parents[1] / "ctf-start",
                         root / "ctf-start")
            completed = subprocess.run(
                ["sh", "./ctf-start", "tools", "install", "--help"],
                cwd=root, capture_output=True, text=True, timeout=20, check=False)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("--required", completed.stdout)

    def test_one_real_native_selection_from_official_cached_package(self):
        source_root = Path(toolinstall.__file__).resolve().parents[1]
        cache = list((source_root / ".local/tools/ubuntu-debs").glob("unzip_*.deb"))
        if not cache:
            self.skipTest("Official Ubuntu unzip package is not cached on this host")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "scripts").mkdir()
            target_cache = root / ".local/tools/ubuntu-debs"
            target_cache.mkdir(parents=True)
            shutil.copy2(cache[0], target_cache / cache[0].name)
            unrelated = list((source_root / ".local/tools/ubuntu-debs").glob("gdb_*.deb"))
            if unrelated:
                shutil.copy2(unrelated[0], target_cache / unrelated[0].name)
            for name in ("setup-native-tools.sh", "native-tool"):
                shutil.copy2(source_root / "scripts" / name, root / "scripts" / name)
            result = subprocess.run(
                ["bash", str(root / "scripts/setup-native-tools.sh"), "--only", "unzip"],
                capture_output=True, text=True, timeout=30, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((root / ".local/tools/bin/unzip").is_symlink())
            self.assertFalse((root / ".local/tools/bin/gdb").exists())
            self.assertFalse((root / ".local/tools/ubuntu-root/usr/bin/gdb").exists())
            verify = subprocess.run([str(root / ".local/tools/bin/unzip"), "-v"],
                                    capture_output=True, text=True, timeout=8, check=False)
            self.assertEqual(verify.returncode, 0)


if __name__ == "__main__":
    unittest.main()
