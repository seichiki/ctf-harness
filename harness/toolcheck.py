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
import unicodedata
from pathlib import Path

from harness.config import CATEGORIES, ROOT
try:
    from harness import ondemand
except ImportError:  # minimal installer bootstrap copies only core modules
    ondemand = None

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
                  ("debugfs", False, "Install e2fsprogs for ext2/ext3/ext4 image inspection; Ubuntu commonly includes it."),
                  ("exiftool", False, "Install ExifTool from its official release or OS package manager."),
                  ("tshark", False, "Install Wireshark/TShark from its official release or OS package manager."),
                  ("binwalk", False, "Install official Binwalk v3; run ./scripts/setup-native-tools.sh on supported WSL."),
                  ("steghide", True, "Install project-local steghide with ./ctf-start tools install --required."),
                  ("stegseek", False, "Install project-local stegseek with ./ctf-start tools install."),
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
                "steghide": ["--version"], "stegseek": ["--help"],
                "7z": [], "unzip": ["-v"], "debugfs": ["-V"]}


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
        if ondemand is not None:
            items.extend(ondemand.inventory_item(current, name) for name, spec in ondemand.SPECS.items()
                         if current in spec[0])
    if "reverse" in categories:
        items.extend(_local_native_items())
    problems = {"missing", "misconfigured", "incompatible"}
    return [item for item in items if item["status"] in problems] if missing_only else items


DISPLAY_NAMES = {
    ("python", "beautifulsoup4"): "Beautiful Soup",
    ("python", "z3-solver"): "Z3",
    ("integration", "REA/Ghidra provider"): "REA/Ghidra",
    ("integration", "rea-static role interface"): "rea-static",
}
CATEGORY_TAGS = {"web": "WEB", "crypto": "CRY", "pwn": "PWN", "reverse": "REV",
                 "forensics": "FOR", "osint": "OSI", "misc": "MSC"}
GREEN = "\x1b[32m"
RED = "\x1b[31m"
RESET = "\x1b[0m"


def _usage_categories(item: dict) -> tuple[str, ...]:
    """Actual declared use, including categories outside a current filter."""
    category = item["category"]
    if category == "all":
        return tuple(CATEGORIES)
    kind, name = item["kind"], item["name"]
    if kind == "binary":
        uses = [current for current in CATEGORIES
                if any(spec[0] == name for spec in BINARIES.get(current, ()))]
    elif kind == "on_demand" and ondemand is not None:
        return ondemand.SPECS[name][0]
    elif kind == "python":
        uses = [current for current in CATEGORIES
                if any(spec[0] == name for spec in PYTHON[current])]
    else:
        uses = []
    return tuple(uses) if uses else (category,)


def _cell_width(value: str) -> int:
    return sum(0 if unicodedata.combining(char) else
               2 if unicodedata.east_asian_width(char) in ("F", "W") else 1
               for char in value)


def _clean_cell(value: str) -> str:
    return "".join(char if unicodedata.category(char)[0] != "C" else "?" for char in value)


def _wrap_cell(value: str, width: int) -> list[str]:
    lines, current, used = [], "", 0
    for char in value:
        size = _cell_width(char)
        if current and used + size > width:
            lines.append(current)
            current, used = "", 0
        current += char
        used += size
    return lines + [current]


def _version_label(item: dict) -> str:
    if item["status"] == "missing":
        return "-"
    raw = item.get("version")
    if not raw:
        return "UNKNOWN"
    raw = _clean_cell(str(raw))
    matches = re.findall(r"\d+(?:\.\d+)+(?:[-+][A-Za-z0-9.]+)?", raw)
    if item["name"] == "gdb" and matches:
        return matches[-1]
    if item["name"] in ("REA/Ghidra provider", "rea-static role interface") and len(matches) >= 2:
        return " / ".join(matches[:2])
    return matches[0] if matches else raw


def _human_rows(items: list[dict]) -> list[tuple[str, str, str, str, bool]]:
    groups: dict[tuple[str, str], dict] = {}
    for item in items:
        key = (item["kind"], item["name"])
        if key not in groups:
            groups[key] = {"item": item, "statuses": set(), "required": False, "categories": set()}
        group = groups[key]
        group["statuses"].add(item["status"])
        group["required"] |= item["required"]
        group["categories"].update(_usage_categories(item))
    labels = {key: DISPLAY_NAMES.get(key, key[1]) for key in groups}
    for key, label in tuple(labels.items()):
        if sum(other == label for other in labels.values()) > 1:
            labels[key] = f"{label} ({key[1]})"
    rows = []
    for key, group in groups.items():
        item = group["item"]
        status = (next(iter(group["statuses"])) if len(group["statuses"]) == 1
                  else "mixed")
        version = _version_label(item) if status != "mixed" else "UNKNOWN"
        categories = ("ALL" if group["categories"] == set(CATEGORIES) else
                      ", ".join(CATEGORY_TAGS[current] for current in CATEGORIES
                                if current in group["categories"]))
        state = "✓" if status == "available" else "✕" if group["required"] else "-"
        rows.append((_clean_cell(labels[key]), version, categories, state, group["required"]))
    return rows


def _supports_color() -> bool:
    if not sys.stdout.isatty() or "NO_COLOR" in os.environ or os.environ.get("CLICOLOR") == "0":
        return False
    term = os.environ.get("TERM", "").lower()
    if term in ("", "dumb"):
        return False
    return (term.startswith(("xterm", "screen", "tmux", "linux", "rxvt", "alacritty", "wezterm", "foot", "konsole"))
            or term == "ansi" or bool(os.environ.get("COLORTERM")))


def _paint(value: str, *, required: bool = False, status: bool = False, color: bool = False) -> str:
    if not color:
        return value
    if status:
        glyph = value.rstrip(" ")
        shade = GREEN if glyph == "✓" else RED if glyph == "✕" else ""
        return f"{shade}{glyph}{RESET}{value[len(glyph):]}" if shade else value
    return f"{GREEN}{value}{RESET}" if required else value


def render_human(items: list[dict], *, width: int | None = None, missing_only: bool = False,
                 color: bool = False) -> str:
    """Compact Unicode-safe display; JSON remains the canonical per-category inventory."""
    if not items:
        return "No missing tools." if missing_only else "No tools for this selection."
    rows = _human_rows(items)
    legend = _paint("Required", required=True, color=color) + " / Optional"
    headers = ("TOOL", "VERSION", "CATEGORIES", "STATUS")
    limits = (24, 20, 24, 16)
    widths = [min(limit, max(_cell_width(header), *(_cell_width(row[index]) for row in rows)))
              for index, (header, limit) in enumerate(zip(headers, limits))]
    terminal_width = width if width is not None else shutil.get_terminal_size((100, 24)).columns
    if sum(widths) + 6 > terminal_width:
        lines = ([legend] if _cell_width("Required / Optional") <= terminal_width else
                 [_paint("Required", required=True, color=color), "/ Optional"])
        for row in rows:
            if len(lines) > 1:
                lines.append("")
            for index, (label, value) in enumerate(zip(headers, row[:4])):
                prefix = f"{label}: "
                indent = " " * _cell_width(prefix)
                chunks = _wrap_cell(value, max(1, terminal_width - _cell_width(prefix)))
                if index == 3:
                    lines.append(_paint(prefix, required=row[4], color=color) +
                                 _paint(chunks[0], status=True, color=color))
                    lines.extend(indent + _paint(chunk, status=True, color=color) for chunk in chunks[1:])
                else:
                    lines.append(_paint(prefix + chunks[0], required=row[4], color=color))
                    lines.extend(_paint(indent + chunk, required=row[4], color=color) for chunk in chunks[1:])
        return "\n".join(lines)

    def pad(value: str, size: int) -> str:
        return value + " " * (size - _cell_width(value))

    lines = [legend, "  ".join(pad(header, size) for header, size in zip(headers, widths)),
             "  ".join("-" * size for size in widths)]
    for row in rows:
        cells = [_wrap_cell(value, size) for value, size in zip(row[:4], widths)]
        for line_number in range(max(map(len, cells))):
            values = [pad(cell[line_number] if line_number < len(cell) else "", size)
                      for cell, size in zip(cells, widths)]
            lines.append("  ".join(_paint(value, required=row[4], status=index == 3, color=color)
                                   for index, value in enumerate(values)))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only category tool inventory; never installs software",
        epilog="Category labels: WEB=web, CRY=crypto, PWN=pwn, REV=reverse, FOR=forensics, OSI=osint, MSC=misc, ALL=all.")
    parser.add_argument("--category", choices=CATEGORIES)
    parser.add_argument("--missing-only", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    items = collect(args.category, args.missing_only)
    if args.json:
        print(json.dumps({"python": sys.executable, "tools": items}, indent=2, ensure_ascii=False))
    else:
        print(render_human(items, missing_only=args.missing_only, color=_supports_color()))
        print("Read-only check; no tools or settings were changed. Use --json for details.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
