"""Optional live command and candidate display from untrusted Codex JSONL."""

from __future__ import annotations

import json
import re
import threading
import time
import unicodedata
from pathlib import Path
from typing import Callable, TextIO


ROLES = frozenset({"solver", "verifier", "solver_a", "solver_b", "verifier_review"})
STATUSES = frozenset({"completed", "tool_failure", "timeout", "cancelled",
                      "invalid_report", "auth_blocked", "rate_limited",
                      "safety_blocked", "model_unavailable", "permission_blocked",
                      "candidate_pending", "no_candidate", "disagreement",
                      "owner_confirmed_stop", "user_confirmed"})
ITEM_ID = re.compile(r"item_[A-Za-z0-9_-]{1,40}\Z")
ANSI = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)|.)", re.DOTALL)
URL_USERINFO = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^/@\s'\"]+@")
SECRET_QUERY = re.compile(
    r"(?i)([?&](?:api[_-]?key|access[_-]?token|client[_-]?secret|token|auth|password|passwd|secret|session|cookie|jwt|signature|sig|code|flag)=)[^&#'\"\s]+")
SECRET_HEADER = re.compile(r"(?i)(\b(?:authorization|proxy-authorization|cookie|set-cookie|x-api-key)\s*:\s*)[^'\"\n]+")
SECRET_OPTION = re.compile(
    r"(?i)(--(?:cookie|cookie-jar|password|passwd|token|api-key|access-token|client-secret|proxy-user|user)(?:\s+|=)|-(?:u|b)\s+)(?:\"[^\"]*\"|'[^']*'|\S+)")
SECRET_ASSIGNMENT = re.compile(
    r"(?i)(?<![?&])\b((?:[A-Za-z_][A-Za-z0-9_]*_)?(?:API_KEY|SECRET_KEY|ACCESS_KEY|PRIVATE_KEY|TOKEN|SECRET|PASSWORD|PASSWD|COOKIE|AUTHORIZATION|SESSION)\s*=\s*)(?:\"[^\"]*\"|'[^']*'|[^\s;&]+)")
SECRET_JSON = re.compile(
    r"(?i)([\"'](?:password|passwd|token|api_key|secret|cookie|authorization|session)[\"']\s*:\s*)([\"'])(.*?)\2")
MAX_COMMAND_CHARS = 420
MAX_CANDIDATE_CHARS = 1000


def safe_text(value: str) -> str:
    """Make untrusted text one printable terminal line before applying masking."""
    value = ANSI.sub("", value)
    output = []
    for char in value:
        if char in "\r\n":
            output.append(r"\n")
        elif char == "\t":
            output.append(" ")
        elif unicodedata.category(char).startswith("C"):
            continue
        else:
            output.append(char)
    return "".join(output)


def render_command(command: object) -> str:
    """Show the shell command with best-effort secret masking and clear truncation."""
    if not isinstance(command, str):
        return "[command unavailable]"
    shown = safe_text(command)
    shown = URL_USERINFO.sub(r"\1[REDACTED]@", shown)
    shown = SECRET_QUERY.sub(r"\1[REDACTED]", shown)
    shown = SECRET_HEADER.sub(r"\1[REDACTED]", shown)
    shown = SECRET_OPTION.sub(r"\1[REDACTED]", shown)
    shown = SECRET_ASSIGNMENT.sub(r"\1[REDACTED]", shown)
    shown = SECRET_JSON.sub(r"\1\2[REDACTED]\2", shown)
    if len(shown) > MAX_COMMAND_CHARS:
        return shown[:MAX_COMMAND_CHARS] + "… [truncated; full command in events.jsonl]"
    return shown or "[empty command]"


class ProgressReporter:
    def __init__(self, stream: TextIO, *, enabled: bool = True,
                 on_event: Callable[[str, str], None] | None = None):
        self.stream = stream
        self.enabled = enabled
        self.on_event = on_event
        self.started = time.monotonic()
        self.lock = threading.RLock()
        self.started_items: set[tuple[str, str]] = set()
        self.finished_items: set[tuple[str, str]] = set()

    def emit(self, role: str, message: str) -> None:
        safe_role = role if role in ROLES else "run"
        # Event text reaches here only through render_command or quoted candidate.
        with self.lock:
            if self.on_event is not None:
                try:
                    self.on_event(safe_role, message)
                except Exception:
                    # The handoff is optional; preserve the original run and logs.
                    pass
            if not self.enabled:
                return
            try:
                self.stream.write(f"[{time.monotonic() - self.started:6.1f}s] {safe_role}: {message}\n")
                self.stream.flush()
            except (OSError, ValueError):
                # Progress is informational; a closed stderr must not lose results.
                pass

    def role_started(self, role: str) -> None:
        self.emit(role, "started")

    def role_finished(self, role: str, status: str) -> None:
        safe_status = status if status in STATUSES else "unknown"
        self.emit(role, f"finished ({safe_status})")

    def role_candidate(self, role: str, record: dict) -> None:
        """Emit only a parsed report candidate; distinguish empty from unavailable."""
        status = record.get("status")
        if status == "completed" and record.get("report_sha256"):
            candidate = record.get("candidate")
            if candidate == "":
                self.emit(role, "candidate: no candidate (valid report)")
            elif isinstance(candidate, str):
                quoted = json.dumps(candidate, ensure_ascii=True)
                if len(quoted) > MAX_CANDIDATE_CHARS:
                    self.emit(role, "candidate: [too long; see structured-report.json]")
                else:
                    label = record.get("reported_basis", "basis_unknown")
                    self.emit(role, f"candidate: {quoted} [unverified; {label}]")
            else:
                self.emit(role, "candidate: unavailable (report has no candidate field)")
        else:
            safe_status = status if status in STATUSES else "unknown"
            self.emit(role, f"candidate: unavailable ({safe_status}; no valid report)")

    def run_finished(self, status: str) -> None:
        self.role_finished("run", status)

    def handle_line(self, role: str, line: str) -> None:
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, TypeError, ValueError):
            return
        if not isinstance(event, dict):
            return
        kind = event.get("type")
        if kind in ("turn.completed", "turn.failed"):
            self.emit(role, "model turn completed" if kind == "turn.completed" else "model turn failed")
            return
        if kind not in ("item.started", "item.completed", "item.failed"):
            return
        item = event.get("item")
        if not isinstance(item, dict):
            return
        item_type = item.get("type")
        if item_type == "command_execution":
            label = "command"
        elif item_type == "mcp_tool_call":
            label = "tool call"
        elif item_type in ("web_search", "web_search_call"):
            label = "web search"
        elif item_type == "file_change":
            label = "file change"
        else:
            # This deliberately excludes agent messages and hidden reasoning.
            return
        raw_id = item.get("id")
        item_id = raw_id if isinstance(raw_id, str) and ITEM_ID.fullmatch(raw_id) else "unknown"
        key = (role, item_id)
        with self.lock:
            if kind == "item.started":
                if item_id != "unknown" and key in self.started_items:
                    return
                self.started_items.add(key)
                suffix = f": {render_command(item.get('command'))}" if item_type == "command_execution" else ""
                self.emit(role, f"{label} #{item_id} started{suffix}")
                return
            if item_id != "unknown" and key in self.finished_items:
                return
            self.finished_items.add(key)
            state = "failed" if kind == "item.failed" else "completed"
            if item_type == "command_execution":
                code = item.get("exit_code")
                if type(code) is int and -255 <= code <= 255:
                    if code != 0:
                        state = "failed"
                    state += f" (exit {code})"
            elif item.get("status") in ("failed", "in_progress", "completed"):
                state = item["status"]
            self.emit(role, f"{label} #{item_id} {state}")


def tail_events(path: Path, role: str, reporter: ProgressReporter,
                stopped: threading.Event) -> None:
    """Read completed JSONL lines as Codex writes them, then drain at exit."""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as source:
            drained_after_stop = 0
            while True:
                position = source.tell()
                line = source.readline()
                if line and line.endswith("\n"):
                    reporter.handle_line(role, line)
                    if stopped.is_set():
                        drained_after_stop += 1
                        if drained_after_stop >= 1000:
                            break
                    continue
                if line:
                    source.seek(position)
                if stopped.wait(0.1):
                    final = source.readline()
                    if final:
                        reporter.handle_line(role, final)
                    break
    except OSError:
        # The run keeps its original event file and result-saving behavior.
        pass
