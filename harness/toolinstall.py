"""Opt-in, project-local tool installer. No challenge/model invocation."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import select
import shutil
import signal
import subprocess
import sys
import termios
import time
import tomllib
import tty
from pathlib import Path

from harness import toolcheck
from harness.confirm import ConfirmationCancelled, ConfirmationUnavailable, ask
from harness.config import ROOT

PROBLEMS = {"missing", "misconfigured", "incompatible"}
NATIVE = {"gdb", "socat", "exiftool", "tshark", "binwalk", "7z", "unzip"}
REA_NAMES = {"Ghidra", "Temurin JDK", "Node.js", "REA", "REA/Ghidra provider",
             "rea-static role interface"}
SCRUB = re.compile(
    r"(authorization\s*[:=]\s*|cookie\s*[:=]\s*|(?:api[_-]?key|password|token|secret)\s*[:=]\s*)"
    r"([^\s,;]+)|(https?://)[^/@\s:]+:[^/@\s]+@|"
    r"([?&](?:token|key|password|secret)=)[^&#\s]+", re.IGNORECASE
)


def safe_text(value: str, limit: int = 240) -> str:
    value = re.sub(r"(?i)(cookie\s*[:=]\s*)[^\r\n]+", r"\1[REDACTED]", value)
    value = re.sub(r"(?i)(authorization\s*[:=]\s*)(?:Bearer|Basic)\s+[^\s,;]+",
                   r"\1[REDACTED]", value)
    value = SCRUB.sub(lambda m: (m.group(1) or m.group(3) or m.group(4) or "") +
                      ("[REDACTED]" if m.group(1) or m.group(4) else "[REDACTED]@"),
                      value)
    value = "".join(c if c.isprintable() or c == "\n" else "?" for c in value)
    return value[:limit] + ("… [truncated]" if len(value) > limit else "")


def inventory() -> list[dict]:
    """Use the project venv for imports; bootstrap Python never proves them absent."""
    python = ROOT / ".venv/bin/python"
    if python.is_file():
        result = subprocess.run([str(python), "-m", "harness.toolcheck", "--json"],
                                cwd=ROOT, capture_output=True, text=True, timeout=120, check=False)
        if result.returncode == 0:
            return json.loads(result.stdout)["tools"]
    items = toolcheck.collect()
    for item in items:
        if item["kind"] == "python":
            item.update(status="missing", version=None, path=None)
    return items


def missing_groups(items: list[dict]) -> list[dict]:
    groups: dict[tuple[str, str], dict] = {}
    for item in items:
        if item["status"] not in PROBLEMS:
            continue
        key = (item["kind"], item["name"])
        if key not in groups:
            groups[key] = {"key": key, "item": item, "required": False, "categories": set()}
        groups[key]["required"] |= bool(item["required"])
        groups[key]["categories"].update(toolcheck._usage_categories(item))
    return list(groups.values())


def _label(group: dict) -> str:
    kind, name = group["key"]
    return toolcheck.DISPLAY_NAMES.get((kind, name), name)


def _categories(group: dict) -> str:
    uses = group["categories"]
    if len(uses) == len(toolcheck.CATEGORIES):
        return "ALL"
    return ", ".join(toolcheck.CATEGORY_TAGS[c] for c in toolcheck.CATEGORIES if c in uses)


def _read_key() -> str:
    char = os.read(sys.stdin.fileno(), 1)
    if not char:
        return "cancel"
    if char == b"\x03":
        return "cancel"
    if char == b"\x1b":
        if select.select([sys.stdin], [], [], 0.08)[0]:
            following = os.read(sys.stdin.fileno(), 1)
            if following == b"[" and select.select([sys.stdin], [], [], 0.08)[0]:
                return {"A": "up", "B": "down"}.get(os.read(sys.stdin.fileno(), 1).decode("ascii", "ignore"), "ignore")
        return "cancel"
    return {b" ": "toggle", b"\r": "done", b"\n": "done"}.get(char, "ignore")


def select_tools(groups: list[dict]) -> list[dict] | None:
    if not sys.stdin.isatty() or not sys.stdout.isatty() or os.environ.get("TERM") == "dumb":
        raise ValueError("Interactive selection needs a TTY. Use --all or --required for a prepared selection.")
    fd = sys.stdin.fileno()
    original = termios.tcgetattr(fd)
    selected: set[int] = set()
    cursor = 0
    narrow = shutil.get_terminal_size((80, 24)).columns < 65
    size = min(6 if narrow else 12, len(groups))
    try:
        tty.setraw(fd)
        sys.stdout.write("\x1b[?25l")
        while True:
            start = max(0, min(cursor - size // 2, len(groups) - size))
            lines = ["Missing tools: Up/Down move, Space toggles, Enter plans, Esc cancels."]
            if not narrow:
                lines.append("    TOOL                     VERSION       CATEGORIES")
            for index in range(start, start + size):
                group = groups[index]
                marker = ">" if cursor == index else " "
                check = "x" if index in selected else " "
                name = safe_text(_label(group), 24)
                version = safe_text(str(group["item"].get("version") or "-"), 13)
                if narrow:
                    lines.append(f"{marker} [{check}] {name}")
                    lines.append(f"      {version} | {_categories(group)}")
                else:
                    lines.append(f"{marker} [{check}] {name:<24} {version:<13} {_categories(group)}")
            lines.append(f"Selected: {len(selected)} / {len(groups)}")
            sys.stdout.write("\x1b[H\x1b[2J" + "\r\n".join(lines) + "\r\n")
            sys.stdout.flush()
            key = _read_key()
            if key == "cancel":
                return None
            if key == "done":
                return [group for index, group in enumerate(groups) if index in selected]
            if key == "up":
                cursor = max(0, cursor - 1)
            if key == "down":
                cursor = min(len(groups) - 1, cursor + 1)
            if key == "toggle":
                if cursor in selected:
                    selected.remove(cursor)
                else:
                    selected.add(cursor)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, original)
        sys.stdout.write("\x1b[?25h\x1b[H\x1b[2J")
        sys.stdout.flush()


def _locked_versions() -> str:
    data = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    names = {name for category in toolcheck.PYTHON.values() for name, _ in category}
    found = [f"{p['name']}={p['version']}" for p in data["package"] if p["name"].lower() in {n.lower() for n in names}]
    return ", ".join(sorted(found))


def plan(selected: list[dict]) -> list[dict]:
    keys = {g["key"] for g in selected}
    units: list[dict] = []
    def add(identifier: str, covers: list[str], command: list[str] | None, source: str, note: str = "") -> None:
        units.append({"id": identifier, "covers": covers, "command": command, "source": source, "note": note})
    python = sorted(name for kind, name in keys if kind == "python")
    if python:
        all_python = sorted({name for category in toolcheck.PYTHON.values() for name, _ in category})
        add("python-bundle", all_python, ["uv", "sync", "--locked"], "uv.lock / declared registry packages",
            "All seven default groups are one locked environment: " + _locked_versions())
    rea = sorted(name for kind, name in keys if name in REA_NAMES)
    if rea:
        add("rea-ghidra-bundle", sorted(REA_NAMES), ["bash", str(ROOT / "scripts/setup-rea-ghidra.sh")],
            "Official Node/Temurin/Ghidra releases and locked official rea-agents npm",
            "Indivisible local bundle: Node 24.22.1, JDK 21.0.13+9, Ghidra 12.1.4, REA 6.8.0.")
    native = {name for kind, name in keys if kind == "binary" and name in NATIVE}
    if "binwalk" in native:
        native.discard("7z")
    for name in sorted(native):
        covers = [name, "7z"] if name == "binwalk" else [name]
        script = ROOT / "scripts/setup-native-tools.sh"
        dry = subprocess.run(["bash", str(script), "--plan", "--only", name],
                             capture_output=True, text=True, timeout=10, check=True)
        apt_archives = ", ".join(dry.stdout.splitlines())
        note = ("Binwalk 3.1.0 uses Rust 1.99.1 and includes local 7-Zip extraction support."
                if name == "binwalk" else "Ubuntu 26.04 x86-64 packages; revisions are not pinned.")
        note += " Planned apt archives: " + apt_archives
        add(name, covers, ["bash", str(script), "--only", name],
            "Configured Ubuntu 26.04 package repository" +
            (", official Rustup/Cargo registry" if name == "binwalk" else ""), note)
    covered = {name for unit in units for name in unit["covers"]}
    selected_by_key = {group["key"]: group for group in selected}
    for kind, name in sorted(keys):
        if name not in covered:
            add(f"manual:{name}", [name], None, "Manual prerequisite",
                selected_by_key[(kind, name)]["item"].get("guidance") or
                "No safe project-local installer is declared for this tool; no automatic changes.")
    return units


def _bar(done: int, total: int) -> str:
    width = 20
    count = width * done // max(1, total)
    return f"[{'#' * count}{'-' * (width - count)}] {done}/{total} units finished"


def _save(path: Path, data: dict) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def _execute(command: list[str], log: Path, progress: str) -> int:
    process = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               start_new_session=True, bufsize=0)
    last_heartbeat = time.monotonic()
    pending = b""
    try:
        with log.open("w", encoding="utf-8") as output:
            while True:
                ready, _, _ = select.select([process.stdout], [], [], 1)
                if ready:
                    chunk = os.read(process.stdout.fileno(), 4096)
                    if not chunk:
                        break
                    pending += chunk
                    while b"\n" in pending:
                        line, pending = pending.split(b"\n", 1)
                        cleaned = safe_text(line.decode("utf-8", "replace"), 500)
                        output.write(cleaned + "\n")
                        print("  " + cleaned, flush=True)
                    if len(pending) > 8192:
                        cleaned = safe_text(pending.decode("utf-8", "replace"), 500)
                        output.write(cleaned + "\n")
                        print("  " + cleaned, flush=True)
                        pending = b""
                elif time.monotonic() - last_heartbeat >= 10:
                    print("  still running; " + progress, flush=True)
                    last_heartbeat = time.monotonic()
            if pending:
                cleaned = safe_text(pending.decode("utf-8", "replace"), 500)
                output.write(cleaned + "\n")
                print("  " + cleaned, flush=True)
            return process.wait()
    except BaseException:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
        raise
    finally:
        process.stdout.close()


def _verify(unit: dict) -> list[str]:
    current = inventory()
    statuses: dict[str, set[str]] = {}
    for item in current:
        statuses.setdefault(item["name"], set()).add(item["status"])
    return sorted(name for name in unit["covers"]
                  if name not in statuses or statuses[name] != {"available"})


def install(units: list[dict]) -> int:
    run_dir = ROOT / ".local/install-runs" / (dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ") +
                                               f"-{os.getpid()}")
    run_dir.mkdir(parents=True, exist_ok=False)
    summary = {"created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
               "units": [{"id": u["id"], "covers": u["covers"], "status": "pending"} for u in units]}
    summary_path = run_dir / "summary.json"
    _save(summary_path, summary)
    done = 0
    try:
        for index, unit in enumerate(units):
            record = summary["units"][index]
            if unit["command"] is None:
                record.update(status="skipped", reason=unit["note"])
                print(f"SKIPPED {unit['id']}: {unit['note']}")
            else:
                print(f"STARTED {unit['id']} ({', '.join(unit['covers'])})", flush=True)
                print(_bar(done, len(units)), flush=True)
                record["status"] = "started"
                _save(summary_path, summary)
                try:
                    code = _execute(unit["command"], run_dir / f"{index:02d}-{unit['id']}.log",
                                    _bar(done, len(units)))
                    record.update(status="completed" if code == 0 else "failed", exit_code=code)
                    if code == 0:
                        remaining = _verify(unit)
                        if remaining:
                            record.update(status="failed", reason="Checker still reports unavailable: " +
                                          ", ".join(remaining))
                except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError, ValueError) as exc:
                    record.update(status="failed", error=safe_text(str(exc)))
                print(f"{record['status'].upper()} {unit['id']}", flush=True)
            done += 1
            _save(summary_path, summary)
            print(_bar(done, len(units)), flush=True)
    except KeyboardInterrupt:
        summary["interrupted"] = True
        for record in summary["units"]:
            if record["status"] == "started":
                record["status"] = "failed"
                record["reason"] = "Interrupted by user"
            elif record["status"] == "pending":
                record["status"] = "skipped"
                record["reason"] = "Interrupted by user"
        _save(summary_path, summary)
        print("\nCancelled; installed tools remain in place.", file=sys.stderr)
        print(f"Install summary: {summary_path}", file=sys.stderr)
        return 130
    print(f"Install summary: {summary_path}")
    print("Run ./ctf-start tools --missing-only to recheck current availability.")
    return 0 if all(record["status"] == "completed" for record in summary["units"]) else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ctf-start tools install",
        description="Install selected missing tools into this clone; no system configuration changes.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--all", action="store_true", help="plan every currently missing tool")
    mode.add_argument("--required", action="store_true", help="plan required missing tools only")
    parser.add_argument("-y", "--yes", action="store_true",
                        help="accept the displayed install plan; still requires a tool selection")
    args = parser.parse_args(argv)
    try:
        groups = missing_groups(inventory())
        if not groups:
            print("No missing tools.")
            return 0
        if args.all:
            selected = groups
        elif args.required:
            selected = [group for group in groups if group["required"]]
        else:
            selected = select_tools(groups)
        if selected is None:
            print("Cancelled; no installation started.")
            return 0
        if not selected:
            print("No tools selected; no installation started.")
            return 0
        units = plan(selected)
        print("Install plan (one progress unit per line):")
        for unit in units:
            print(f"- {unit['id']}: {', '.join(unit['covers'])}")
            destination = ("manual / no automatic path" if unit["command"] is None else
                           ROOT / ".venv" if unit["id"] == "python-bundle" else
                           ROOT / ".local/tools")
            print(f"  Source: {unit['source']}; destination: {destination}")
            print(f"  {unit['note']}")
            if unit["command"] is None:
                print("  MANUAL ONLY: this unit will be skipped.")
        print("No sudo, system package install, global CA, or Codex login changes are planned.")
        if not ask("Install these units", yes=args.yes):
            print("Cancelled; no installation started.")
            return 0
        return install(units)
    except ConfirmationUnavailable as exc:
        print(f"{exc}; nothing installed.", file=sys.stderr)
        return 2
    except ConfirmationCancelled:
        print("\nCancelled; no installation started.", file=sys.stderr)
        return 130
    except (ValueError, OSError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        print(f"Installer could not prepare plan: {safe_text(str(exc))}", file=sys.stderr)
        return 2
    except (EOFError, KeyboardInterrupt):
        print("\nCancelled; no installation started.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
