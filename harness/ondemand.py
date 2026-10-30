"""Curated tools that a case role may request from the harness manager."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from harness.config import ROOT

# name: (categories, executable, purpose, when to use)
SPECS = {
    "tsk": (("forensics",), "fls", "Disk image and filesystem metadata inspection (fls, mmls, icat).", "Partitioned or deleted-file disk image"),
    "volatility3": (("forensics",), "vol", "Memory image analysis.", "RAM dump; symbols may be needed"),
    "foremost": (("forensics",), "foremost", "Recover files by signatures from raw data.", "Deleted or embedded files"),
    "scalpel": (("forensics",), "scalpel", "Configurable file carving.", "Custom carving rules needed"),
    "xortool": (("forensics", "crypto"), "xortool", "Guess repeating XOR key length and candidate keys.", "XOR-obfuscated data"),
    "qpdf": (("forensics",), "qpdf", "Inspect and rewrite PDF object structure.", "Damaged or unusual PDF"),
    "peepdf-3": (("forensics",), "peepdf", "Inspect PDF objects and suspicious actions.", "PDF internals beyond qpdf"),
    "kaitai-struct": (("forensics", "reverse", "misc"), "ksc", "Compile .ksy binary format specifications.", "Custom binary format"),
    "sqlmap": (("web",), "sqlmap", "Test suspected SQL injection.", "Specific SQL injection point"),
    "ffuf": (("web",), "ffuf", "Fuzz web paths and parameters.", "Bounded target discovery"),
    "hashcat": (("web", "crypto", "forensics"), "hashcat", "Recover a password from a known hash.", "Local hash and case-local candidate list; GPU runtime may be needed"),
    "flask-unsign": (("web",), "flask-unsign", "Decode and test Flask signed session cookies.", "Flask session challenge"),
    "ysoserial": (("web",), "ysoserial", "Generate Java deserialization payloads.", "Confirmed Java deserialization path"),
    "dirsearch": (("web",), "dirsearch", "Discover web paths.", "Alternative to ffuf"),
    "gobuster": (("web",), "gobuster", "Discover paths, DNS names or virtual hosts.", "Alternative to ffuf; scoped DNS/vhost task"),
    "xsstrike": (("web",), "xsstrike", "Test reflected XSS contexts.", "Suspected XSS point"),
    "jwt_tool": (("web",), "jwt_tool", "Inspect and test JWTs.", "JWT-based authentication challenge"),
    "ssrfmap": (("web",), "ssrfmap", "Test SSRF behavior.", "Confirmed server-side URL fetch point"),
}
INSTALL_LOCK = threading.Lock()
PROCESSED_REQUESTS: set[tuple[str, str]] = set()


def inventory_item(category: str, name: str) -> dict:
    """A command existing on PATH is usable; installing it is a separate operation."""
    import shutil
    categories, executable, purpose, trigger = SPECS[name]
    local = ROOT / ".local/tools/bin" / executable
    path = str(local) if local.is_file() and os.access(local, os.X_OK) else shutil.which(executable)
    return {"category": category, "name": name, "kind": "on_demand", "required": False,
            "status": "available" if path else "missing", "path": path, "version": None,
            "guidance": f"Use the role's request-tool.py when needed. {purpose} {trigger}."}


def write_catalog(workdir: Path, category: str) -> None:
    from harness import toolcheck
    rows = []
    seen = set()
    import importlib.metadata
    import shutil
    for distribution, module in toolcheck.PYTHON[category]:
        try:
            importlib.metadata.version(distribution)
            status = "available"
        except importlib.metadata.PackageNotFoundError:
            status = "missing"
        rows.append({"name": distribution, "required": True, "status": status,
                     "purpose": f"Python library ({module})", "when": "The selected case needs this library"})
        seen.add(distribution)
    for name, required, guidance in (*toolcheck.BINARIES["all"], *toolcheck.BINARIES.get(category, ())):
        if name in seen:
            continue
        seen.add(name)
        executable = ROOT / ".local/tools/bin" / name
        status = "available" if executable.is_file() or shutil.which(name) else "missing"
        rows.append({"name": name, "required": required, "status": status,
                     "purpose": guidance, "when": "The selected case needs this command"})
    if category == "reverse":
        for name in ("Ghidra", "Temurin JDK", "Node.js", "REA"):
            rows.append({"name": name, "required": True, "status": "check with ctf-start tools",
                         "purpose": "Project-local reverse engineering provider", "when": "Reverse engineering case"})
    for name, spec in SPECS.items():
        if category not in spec[0]:
            continue
        executable = ROOT / ".local/tools/bin" / spec[1]
        status = "available" if executable.is_file() or shutil.which(spec[1]) else "missing"
        rows.append({"name": name, "required": False, "status": status,
                     "purpose": spec[2], "when": spec[3]})
    (workdir / "tool-catalog.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    lines = ["# Tools available on request", "", "Only request a tool that helps this selected case. The harness manager installs from a curated source and records the outcome.", "", "| Tool | Status | Use when | Purpose |", "| --- | --- | --- | --- |"]
    for row in rows:
        status = row["status"] + ("; required" if row["required"] else "; optional")
        lines.append(f"| {row['name']} | {status} | {row['when']} | {row['purpose']} |")
    lines += ["", "To request one missing tool, run `python3 request-tool.py TOOL --reason 'why this case needs it'` from this role directory. Wait for its result before using the tool. A failed request is not proof that the tool is available. Package downloads are handled by the harness manager, outside the challenge network policy. Do not run package managers yourself.", ""]
    (workdir / "TOOL-CATALOG.md").write_text("\n".join(lines), encoding="utf-8")


def request_cli() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Request a curated CTF tool from the harness manager")
    parser.add_argument("tool")
    parser.add_argument("--reason", required=True)
    args = parser.parse_args()
    workdir = Path.cwd()
    allowed = {row["name"] for row in json.loads((workdir / "tool-catalog.json").read_text(encoding="utf-8"))}
    if args.tool not in allowed:
        parser.error("tool is not listed in this role's catalog")
    if not args.reason.strip() or len(args.reason) > 500:
        parser.error("reason must be 1 to 500 characters")
    request_id = uuid.uuid4().hex
    request_dir = workdir / "tool-requests"
    request_dir.mkdir(exist_ok=True)
    result = workdir.parent / "tool-results" / f"{workdir.name}-{request_id}.json"
    payload = {"id": request_id, "tool": args.tool, "reason": args.reason.strip()}
    path = request_dir / f"{request_id}.json"
    with path.open("x", encoding="utf-8") as file:
        json.dump(payload, file)
    print(f"Requested {args.tool}; waiting for harness manager...", flush=True)
    for _ in range(1200):
        if result.is_file():
            data = json.loads(result.read_text(encoding="utf-8"))
            print(json.dumps(data, ensure_ascii=False), flush=True)
            return 0 if data.get("status") in {"installed", "already_available"} else 1
        time.sleep(0.5)
    print("Tool request timed out; check run/tool-results and install logs.", file=sys.stderr)
    return 1


def service_requests(workdir: Path, role: str) -> list[dict]:
    """Handle role-written requests on the trusted manager side only."""
    from harness import toolinstall
    events = []
    request_dir = workdir / "tool-requests"
    if not request_dir.is_dir():
        return events
    results = workdir.parent / "tool-results"
    results.mkdir(exist_ok=True)
    for path in sorted(request_dir.glob("*.json")):
        request_id = path.stem
        if not re.fullmatch(r"[0-9a-f]{32}", request_id) or path.is_symlink():
            continue
        response = results / f"{role}-{request_id}.json"
        key = (str(workdir.resolve()), request_id)
        if key in PROCESSED_REQUESTS:
            continue
        event = {"role": role, "id": request_id, "tool": None, "status": "failed", "reason": None}
        try:
            if path.stat().st_size > 4096:
                raise ValueError("request exceeds size limit")
            data = json.loads(path.read_text(encoding="utf-8"))
            name, reason = data.get("tool"), data.get("reason")
            if data.get("id") != request_id or not isinstance(name, str) or not isinstance(reason, str):
                raise ValueError("invalid request")
            if not reason.strip() or len(reason) > 500:
                raise ValueError("invalid reason")
            event.update(tool=name, reason=toolinstall.safe_text(reason.strip(), 500))
            from harness import toolcheck
            category = workdir.parents[3].name
            if category not in toolcheck.CATEGORIES:
                raise ValueError("invalid role category")
            allowed = {name for name, _ in toolcheck.PYTHON[category]}
            allowed.update(name for name, _, _ in (*toolcheck.BINARIES["all"], *toolcheck.BINARIES.get(category, ())))
            allowed.update(name for name, spec in SPECS.items() if category in spec[0])
            if category == "reverse":
                allowed.update(("Ghidra", "Temurin JDK", "Node.js", "REA"))
            if name not in allowed:
                raise ValueError("tool is not in this role's catalog")
            with INSTALL_LOCK:
                current = [item for item in toolinstall.inventory() if item["name"] == name]
                if not current:
                    raise ValueError("tool is no longer in inventory")
                if all(item["status"] == "available" for item in current):
                    event["status"] = "already_available"
                else:
                    groups = [group for group in toolinstall.missing_groups(current) if group["key"][1] == name]
                    if not groups:
                        raise ValueError("tool cannot be planned")
                    units = toolinstall.plan(groups)
                    if any(unit["command"] is None for unit in units):
                        raise ValueError("no automatic installation recipe")
                    summaries = []
                    code = toolinstall.install(units, context={"role": role, "tool": name, "reason": event["reason"]},
                                               summary_callback=summaries.append)
                    event["install_summary"] = str(summaries[0]) if summaries else None
                    event["status"] = "installed" if code == 0 else "failed"
        except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
            event["error"] = toolinstall.safe_text(str(exc))
        temporary = response.with_suffix(".tmp")
        temporary.write_text(json.dumps(event, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        temporary.replace(response)
        PROCESSED_REQUESTS.add(key)
        with (workdir.parent / "tool-installations.jsonl").open("a", encoding="utf-8") as log:
            log.write(json.dumps(event, ensure_ascii=False) + "\n")
        print(f"TOOL {event['status'].upper()} [{role}] {event['tool'] or '?'}", file=sys.stderr, flush=True)
        events.append(event)
    return events


if __name__ == "__main__":
    raise SystemExit(request_cli())
