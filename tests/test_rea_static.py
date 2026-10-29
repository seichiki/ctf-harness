"""No model or external binary launch: static REA command guard tests."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from harness import rea_static


class StaticReaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.role = self.root / "categories/reverse/runs/case/run/solver"
        (self.role / "input").mkdir(parents=True)
        (self.role / "input/demo").write_bytes(b"fixture")
        tool = self.root / "tools"
        self.node = tool / "node/bin/node"
        self.jdk = tool / "jdk"
        self.ghidra = tool / "ghidra"
        self.rea = tool / "rea/rea.mjs"
        for path in (self.node, self.jdk / "bin/java", self.jdk / "bin/javac",
                     self.ghidra / "support/analyzeHeadless", self.rea):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixture")
        patches = [patch.object(rea_static, key, value) for key, value in (
            ("ROOT", self.root), ("NODE", self.node), ("JDK", self.jdk),
            ("GHIDRA", self.ghidra), ("REA", self.rea))]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def test_selected_role_and_static_decompile_command(self):
        self.assertEqual(rea_static.selected_role(self.role), self.role)
        command, env = rea_static.command_for(self.role, "decompile", "input/demo", "helper")
        self.assertEqual(command[:4], [str(self.node), str(self.rea), "decompile", str(self.role / "input/demo")])
        self.assertIn("--provider", command)
        self.assertEqual(env["REA_ANALYSIS_PROVIDER"], "ghidra")
        self.assertEqual(env["HOME"], str(self.role / ".rea-static"))
        self.assertNotIn("HTTP_PROXY", env)
        self.assertNotIn("OPENAI_API_KEY", env)
        self.assertTrue((self.role / ".rea-static").is_dir())

    def test_rejects_traversal_symlink_and_broad_commands(self):
        for value in ("../run.json", "/etc/passwd", "input/../run.json"):
            with self.assertRaises(ValueError):
                rea_static.selected_file(self.role, value)
        (self.role / "input/link").symlink_to(self.role / "input/demo")
        with self.assertRaises(ValueError):
            rea_static.selected_file(self.role, "input/link")
        for action, term in (("debug", None), ("decompile", "--other-provider"),
                             ("inspect", "unexpected")):
            with self.assertRaises(ValueError):
                rea_static.command_for(self.role, action, "input/demo", term)
        with self.assertRaises(ValueError):
            rea_static.selected_role(self.root)
        (self.role / "prompt.txt").write_text("secret")
        with self.assertRaises(ValueError):
            rea_static.selected_file(self.role, "prompt.txt")


if __name__ == "__main__":
    unittest.main()
