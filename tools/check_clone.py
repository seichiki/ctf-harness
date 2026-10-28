"""Exercise a temporary source-only copy without importing the original checkout."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = (".python-version", ".gitignore", "AGENTS.md", "README.md", "config.example.toml",
         "ctf-start", "pyproject.toml", "uv.lock")
DIRS = ("harness", "docs", "skill_templates", "third_party", "tests", "tools")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="ctf-harness-clone-") as folder:
        clone = Path(folder)
        for name in FILES:
            shutil.copy2(ROOT / name, clone / name)
        for name in DIRS:
            shutil.copytree(ROOT / name, clone / name,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        shutil.copytree(ROOT / "categories", clone / "categories",
                        ignore=shutil.ignore_patterns("cases", "runs", "__pycache__"))
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        tests = subprocess.run(["uv", "run", "--offline", "--locked", "python", "-m", "unittest",
                                "discover", "-s", "tests"], cwd=clone, env=env,
                               text=True, capture_output=True, timeout=60, check=False)
        if tests.returncode:
            raise RuntimeError(f"isolated clone tests failed: {tests.stderr[-1200:]}")
        root_check = subprocess.run(["uv", "run", "--offline", "--locked", "python", "-c",
                                     "from harness.config import ROOT; print(ROOT)"], cwd=clone, env=env,
                                    text=True, capture_output=True, timeout=20, check=True)
        if Path(root_check.stdout.strip()).resolve() != clone.resolve():
            raise RuntimeError("clone resolved the original checkout")
        doctor = subprocess.run(["./ctf-start", "doctor"], cwd=clone, env=env,
                                text=True, capture_output=True, timeout=20, check=True)
        data = json.loads(doctor.stdout)
        if data["missing_category_skills"] or not data["lockfile"]:
            raise RuntimeError("clone is missing source components")
        subprocess.run(["./ctf-start", "setup", "--model", "gpt-6-luna"],
                       cwd=clone, env=env, text=True, capture_output=True, timeout=20, check=True)
        subprocess.run(["./ctf-start", "init", "--category", "crypto", "--case-id", "fixture",
                        "--scope-note", "Self-authored local arithmetic fixture"],
                       cwd=clone, env=env, text=True, capture_output=True, timeout=20, check=True)
        statement = clone / "categories" / "crypto" / "cases" / "fixture" / "input" / "statement.txt"
        statement.write_text("What is 2 + 3?\n", encoding="utf-8")
        subprocess.run(["./ctf-start", "seal", "--category", "crypto", "--case-id", "fixture"],
                       cwd=clone, env=env, text=True, capture_output=True, timeout=20, check=True)
        dry = subprocess.run(["./ctf-start", "run", "--category", "crypto", "--case-id", "fixture",
                              "--preset", "test", "--dry-run"], cwd=clone, env=env,
                             text=True, capture_output=True, timeout=20, check=True)
        default_plan = json.loads(dry.stdout)
        if (default_plan["model"], default_plan["daybreak"], default_plan["orchestration"]) != ("gpt-6-luna", "off", "single"):
            raise RuntimeError("clone did not apply public local defaults")
        override = subprocess.run(["./ctf-start", "run", "--category", "crypto", "--case-id", "fixture",
                                   "--model", "gpt-5.6-sol", "--effort", "high", "--daybreak", "blue",
                                   "--orchestration", "multi", "--preset", "production", "--dry-run"],
                                  cwd=clone, env=env, text=True, capture_output=True, timeout=20, check=True)
        selected = json.loads(override.stdout)
        if (selected["model"], selected["daybreak"], selected["orchestration"], selected["similar_search"]) != ("gpt-5.6-sol", "blue", "multi", True):
            raise RuntimeError("clone did not apply per-run overrides")
        subprocess.run(["git", "init", "-q"], cwd=clone, env=env, check=True)
        for ignored in ("categories/crypto/cases/fixture/input/statement.txt", ".local/config.toml"):
            if subprocess.run(["git", "check-ignore", "-q", ignored], cwd=clone, env=env, check=False).returncode != 0:
                raise RuntimeError(f"clone would export private data: {ignored}")
        print(json.dumps({"clone_tests": "passed", "clone_root_resolution": "isolated",
                          "clone_doctor": "passed", "clone_setup_and_mode_dry_runs": "passed",
                          "case_inputs_and_private_config_git_ignored": True,
                          "model_requests": 0}, indent=2))


if __name__ == "__main__":
    main()
