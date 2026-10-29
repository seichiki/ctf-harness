"""Read-only, category-aware inventory for the actual project Python environment."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from harness.config import CATEGORIES, ROOT

TOOLS = ROOT / ".local" / "tools"
PYTHON = {
    "web": (("httpx", "httpx"), ("beautifulsoup4", "bs4"), ("lxml", "lxml")),
    "crypto": (("pycryptodome", "Crypto"), ("sympy", "sympy")),
    "pwn": (("pwntools", "pwn"),),
    "reverse": (("z3-solver", "z3"), ("capstone", "capstone"),
                ("pyelftools", "elftools"), ("pefile", "pefile")),
    "forensics": (("Pillow", "PIL"), ("scapy", "scapy"),
                   ("exifread", "exifread"), ("pypdf", "pypdf")),
    "osint": (("dnspython", "dns"),),
    "misc": (("regex", "regex"),),
}
BINARIES = {
    "all": (("uv", True, "https://docs.astral.sh/uv/getting-started/installation/"),
            ("codex", True, "Install the supported Codex CLI and sign in separately.")),
    "web": (("curl", False, "Install curl from your OS package manager."),
            ("jq", False, "Install jq from its official release or OS package manager.")),
    "crypto": (("openssl", False, "Install OpenSSL from your OS package manager."),),
    "pwn": (("gdb", False, "Install GDB from your OS package manager."),
            ("readelf", False, "Install GNU binutils from your OS package manager."),
            ("socat", False, "Install socat from your OS package manager.")),
    "reverse": (("objdump", False, "Install GNU binutils from your OS package manager."),
                ("readelf", False, "Install GNU binutils from your OS package manager."),
                ("strings", False, "Install GNU binutils from your OS package manager.")),
    "forensics": (("file", False, "Install file from your OS package manager."),
                  ("exiftool", False, "Install ExifTool from its official release or OS package manager."),
                  ("tshark", False, "Install Wireshark/TShark from its official release or OS package manager."),
                  ("binwalk", False, "Install official Binwalk v3; run ./scripts/setup-native-tools.sh on supported WSL."),
                  ("7z", False, "Install 7-Zip for Binwalk ZIP extraction."),
                  ("unzip", False, "Install unzip for archive handling.")),
    "osint": (("curl", False, "Install curl from your OS package manager."),),
    "misc": (("file", False, "Install file from your OS package manager."),),
}
VERSION_ARGS = {"uv": ["--version"], "codex": ["--version"], "curl": ["--version"],
                "jq": ["--version"], "openssl": ["version"], "gdb": ["--version"],
                "readelf": ["--version"], "objdump": ["--version"], "strings": ["--version"],
                "socat": ["-V"], "file": ["--version"], "exiftool": ["-ver"],
                "tshark": ["-v"], "binwalk": ["--version"],
                "7z": [], "unzip": ["-v"]}


def _safe_line(value: str) -> str:
    first = next((line for line in value.splitlines() if line.strip()), "")
    return re.sub(r"[^\x20-\x7e]", "?", first)[:160]


def _run_version(path: str, args: list[str]) -> str | None:
    try:
        result = subprocess.run([path, *args], capture_output=True, text=True, timeout=4, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode:
        return None
    output = result.stdout or result.stderr
    if Path(path).name == "socat":
        version_line = next((line for line in output.splitlines()
                             if line.lower().startswith("socat version")), "")
        if version_line:
            return _safe_line(version_line)
    return _safe_line(output)


def _python_item(category: str, distribution: str, module: str) -> dict:
    item = {"category": category, "name": distribution, "kind": "python", "required": True,
            "path": sys.executable, "version": None,
            "guidance": "Run uv sync --locked in the project after cloning; no per-challenge install."}
    try:
        item["version"] = importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        item.update(status="missing", path=None)
        return item
    try:
        result = subprocess.run([sys.executable, "-c", f"import {module}"],
                                capture_output=True, timeout=8, check=False)
        item["status"] = "available" if result.returncode == 0 else "incompatible"
    except subprocess.TimeoutExpired:
        item["status"] = "untested"
    except OSError:
        item["status"] = "misconfigured"
    return item


def _binary_item(category: str, name: str, required: bool, guidance: str) -> dict:
    local = TOOLS / "bin" / name
    path = str(local) if local.is_file() and os.access(local, os.X_OK) else shutil.which(name)
    item = {"category": category, "name": name, "kind": "binary", "required": required,
            "status": "missing" if not path else "untested", "path": path, "version": None,
            "guidance": guidance}
    if path:
        version = _run_version(path, VERSION_ARGS[name])
        if version:
            item.update(status="available", version=version)
    return item


def _local_native_items() -> list[dict]:
    ghidra = TOOLS / "ghidra_12.1.4_PUBLIC"
    jdk = TOOLS / "jdk-21.0.13+9"
    node = TOOLS / "node-v24.22.1-linux-x64"
    rea = TOOLS / "rea" / "node_modules" / ".bin" / "rea"
    specs = (("Ghidra", ghidra / "support" / "analyzeHeadless", "12.1.4", "Install the pinned official Ghidra release under .local/tools."),
             ("Temurin JDK", jdk / "bin" / "java", "21.0.13+9", "Install the matching 64-bit JDK under .local/tools."),
             ("Node.js", node / "bin" / "node", "24.22.1", "Install a REA-supported Node.js under .local/tools."),
             ("REA", rea, "6.8.0", "Install pinned rea-agents under .local/tools/rea."))
    items = []
    for name, path, version, guidance in specs:
        status = "available" if path.is_file() and os.access(path, os.X_OK) else "missing"
        detected = None
        if status == "available":
            try:
                if name == "Node.js":
                    marker = _run_version(str(path), ["--version"])
                    detected = marker
                    compatible = marker == "v24.22.1"
                elif name == "Temurin JDK":
                    marker = _run_version(str(path), ["-version"])
                    detected = marker
                    compatible = marker is not None and '"21.0.13"' in marker and (jdk / "bin/javac").is_file()
                elif name == "Ghidra":
                    props = (ghidra / "Ghidra/application.properties").read_text(encoding="utf-8")
                    detected = next((line.split("=", 1)[1] for line in props.splitlines()
                                     if line.startswith("application.version=")), None)
                    compatible = detected == "12.1.4"
                else:
                    metadata = json.loads((TOOLS / "rea/node_modules/rea-agents/package.json").read_text(encoding="utf-8"))
                    detected = metadata.get("version")
                    compatible = detected == "6.8.0"
            except (OSError, ValueError, json.JSONDecodeError):
                compatible = False
            if not compatible:
                status = "incompatible"
        items.append({"category": "reverse", "name": name, "kind": "native_provider", "required": True,
                      "status": status, "path": str(path) if path.is_file() else None,
                      "version": detected, "expected_version": version, "guidance": guidance})
    if all(item["status"] == "available" for item in items):
        env = dict(os.environ)
        env.update(GHIDRA_INSTALL_DIR=str(ghidra), JAVA_HOME=str(jdk),
                   PATH=f"{node / 'bin'}:{env.get('PATH', '')}")
        try:
            check = subprocess.run([str(rea), "doctor", "--provider", "ghidra", "--json"],
                                   capture_output=True, text=True, env=env, timeout=20, check=False)
            data = json.loads(check.stdout)
            ready = bool(data.get("healthy")) and all(x.get("ok") for x in data.get("scope_checks", []))
            status = "available" if ready else "misconfigured"
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
            status = "untested"
    else:
        status = "incompatible" if any(item["status"] == "incompatible" for item in items) else "missing"
    items.append({"category": "reverse", "name": "REA/Ghidra provider", "kind": "integration", "required": True,
                  "status": status, "path": str(rea) if status == "available" else None,
                  "version": "6.8.0 + 12.1.4" if status == "available" else None,
                  "guidance": "Run REA doctor with project-local GHIDRA_INSTALL_DIR, JAVA_HOME and Node; Codex MCP availability needs a separate check."})
    wrapper = ROOT / "rea-static"
    wrapper_ready = wrapper.is_file() and os.access(wrapper, os.X_OK)
    items.append({"category": "reverse", "name": "rea-static role interface", "kind": "integration", "required": True,
                  "status": "available" if wrapper_ready and status == "available" else
                            "missing" if not wrapper_ready else status,
                  "path": str(wrapper) if wrapper_ready else None,
                  "version": "REA 6.8.0 / Ghidra 12.1.4" if wrapper_ready and status == "available" else None,
                  "live_codex_use": "unverified",
                  "guidance": "Run only from a selected reverse role; regular input/ or analysis/ files. Checker does not launch a model or decompiler."})
    return items


def collect(category: str | None = None, missing_only: bool = False) -> list[dict]:
    if category is not None and category not in CATEGORIES:
        raise ValueError("unknown category")
    categories = (category,) if category else CATEGORIES
    items = [_binary_item("all", *spec) for spec in BINARIES["all"]]
    for current in categories:
        items.extend(_python_item(current, *spec) for spec in PYTHON[current])
        items.extend(_binary_item(current, *spec) for spec in BINARIES.get(current, ()))
    if "reverse" in categories:
        items.extend(_local_native_items())
    return [item for item in items if item["status"] != "available"] if missing_only else items


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only category tool inventory; never installs software")
    parser.add_argument("--category", choices=CATEGORIES)
    parser.add_argument("--missing-only", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    items = collect(args.category, args.missing_only)
    if args.json:
        print(json.dumps({"python": sys.executable, "tools": items}, indent=2, ensure_ascii=False))
    else:
        for item in items:
            print(f"{item['category']:10} {item['status']:13} {'required' if item['required'] else 'optional':8} "
                  f"{item['name']:24} {item['version'] or '-':18} {item['path'] or '-'}")
        if not items:
            print("No missing tools found." if args.missing_only else "No tools found for this selection.")
        print("Read-only check; no tools were installed or changed. Use --json for guidance.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
