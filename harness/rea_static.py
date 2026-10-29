"""Narrow, project-local REA CLI for static analysis of the selected role's files.

This is an interface guard, not an OS sandbox. The outer Codex shell sandbox
and selected case scope remain authoritative.
"""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / ".local" / "tools"
NODE = TOOLS / "node-v24.22.1-linux-x64" / "bin" / "node"
JDK = TOOLS / "jdk-21.0.13+9"
GHIDRA = TOOLS / "ghidra_12.1.4_PUBLIC"
REA = TOOLS / "rea" / "node_modules" / "rea-agents" / "scripts" / "rea.mjs"
ROLES = {"solver", "verifier", "solver_a", "solver_b", "verifier_review"}
COMMANDS = {"inspect": "inspect", "layout": "inspect-binary-layout",
            "search": "search", "function": "function", "decompile": "decompile"}
SAFE_TERM = re.compile(r"[^\x00-\x1f\x7f]{1,256}\Z")


def selected_role(cwd: Path) -> Path:
    actual = cwd.resolve(strict=True)
    try:
        parts = actual.relative_to(ROOT.resolve()).parts
    except ValueError as exc:
        raise ValueError("run rea-static from one selected harness role directory") from exc
    if (len(parts) != 6 or parts[0] != "categories" or parts[2] != "runs"
            or parts[5] not in ROLES or not (actual / "input").is_dir()):
        raise ValueError("run rea-static from one selected harness role directory")
    return actual


def selected_file(role: Path, value: str) -> Path:
    name = Path(value)
    if name.is_absolute() or not name.parts or any(part in (".", "..") for part in name.parts):
        raise ValueError("file must be a relative path inside the current role directory")
    current = role
    for part in name.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("symlink paths are not allowed")
    target = current.resolve(strict=True)
    if not target.is_relative_to(role) or not target.is_file():
        raise ValueError("file must be a regular role file")
    if target.relative_to(role).parts[0] not in ("input", "analysis"):
        raise ValueError("only input/ and self-authored analysis/ files are analysis targets")
    return target


def command_for(role: Path, action: str, file: str, term: str | None = None) -> tuple[list[str], dict]:
    target = selected_file(role, file)
    if action not in COMMANDS:
        raise ValueError("unsupported static REA operation")
    if action in ("search", "function", "decompile"):
        if not term or not SAFE_TERM.fullmatch(term) or term.startswith(("-", "@")):
            raise ValueError("search/function/decompile needs one safe pattern or symbol")
    elif term is not None:
        raise ValueError("this operation does not take a pattern or symbol")
    for path in (NODE, JDK / "bin" / "java", JDK / "bin" / "javac",
                 GHIDRA / "support" / "analyzeHeadless", REA):
        if not path.is_file():
            raise ValueError(f"missing pinned local REA/Ghidra prerequisite: {path.name}; run ctf-start tools --category reverse")
    private = role / ".rea-static"
    if private.is_symlink():
        raise ValueError("REA state directory must not be a symlink")
    private.mkdir(exist_ok=True)
    # Explicit child environment: never forward API credentials, proxy variables,
    # user-specific REA options or Java injection variables from the agent shell.
    env = {"HOME": str(private), "XDG_CACHE_HOME": str(private / "cache"),
           "XDG_CONFIG_HOME": str(private / "config"), "XDG_DATA_HOME": str(private / "data"),
           "GHIDRA_INSTALL_DIR": str(GHIDRA), "JAVA_HOME": str(JDK),
           "REA_ANALYSIS_PROVIDER": "ghidra", "GHIDRA_HEADLESS_MAXMEM": "512M",
           "PATH": f"{NODE.parent}:{JDK / 'bin'}:/usr/local/bin:/usr/bin:/bin",
           "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}
    command = [str(NODE), str(REA), COMMANDS[action], str(target)]
    if term is not None:
        command.append(term)
    if action != "layout":
        command.extend(["--provider", "ghidra"])
    command.extend(["--format", "json"])
    return command, env


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Static REA analysis of a file inside this role; no arbitrary REA commands")
    parser.add_argument("action", choices=tuple(COMMANDS))
    parser.add_argument("file", help="relative file path such as input/program")
    parser.add_argument("term", nargs="?", help="pattern or procedure for search/function/decompile")
    args = parser.parse_args(argv)
    try:
        role = selected_role(Path.cwd())
        command, env = command_for(role, args.action, args.file, args.term)
    except (ValueError, OSError) as exc:
        parser.exit(2, f"rea-static: {exc}\n")
    return subprocess.run(command, cwd=role, env=env, stdin=subprocess.DEVNULL, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
