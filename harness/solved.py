"""Owner-only, terminal-controlled early stop after an official CTF submission."""

from __future__ import annotations

import hashlib
import json
import os
import select
import sys
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import TextIO

from harness.progress import ROLES, render_command, safe_text


class OwnerConfirmedStop(Exception):
    """A role must not launch after the owner confirmed a candidate."""


class OwnerCancelledStop(Exception):
    """A role must not launch after the terminal run was interrupted."""


def controlling_terminal(source: TextIO) -> bool:
    """Require the foreground controlling terminal, not a pipe or pseudo TTY elsewhere."""
    try:
        descriptor = source.fileno()
        return bool(source.isatty() and os.isatty(descriptor) and
                    os.tcgetpgrp(descriptor) == os.getpgrp())
    except (OSError, ValueError):
        return False


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_text(path: Path, content: str) -> None:
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                         prefix=f".{path.name}-", delete=False) as file:
            temporary = Path(file.name)
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


class OwnerControl:
    """Tracks parsed candidates; only this run's terminal can confirm acceptance."""

    def __init__(self, run_root: Path, case: dict, stream: TextIO | None = None,
                 input_stream: TextIO | None = None):
        self.run_root = run_root
        self.case = case
        self.stream = stream if stream is not None else sys.stderr
        self.input_stream = input_stream if input_stream is not None else sys.stdin
        self.lock = threading.RLock()
        self.closed = threading.Event()
        self.confirmed = threading.Event()
        self.cancelled = threading.Event()
        self.final_review = threading.Event()
        self.review_done = threading.Event()
        self.review_outcome: str | None = None
        self.accepted: dict | None = None
        self.solution_error = False
        self.candidates: dict[str, dict] = {}
        self.thread: threading.Thread | None = None
        self._input_buffer = bytearray()

    def _say(self, message: str) -> None:
        with self.lock:
            try:
                self.stream.write(message + "\n")
                self.stream.flush()
            except (OSError, ValueError):
                pass

    def record_candidate(self, role: str, record: dict) -> None:
        if role not in ROLES or record.get("status") != "completed" or not record.get("report_sha256"):
            return
        candidate = record.get("candidate")
        if not isinstance(candidate, str) or not candidate:
            return
        with self.lock:
            for entry in self.candidates.values():
                if entry["candidate"] == candidate:
                    if role not in entry["roles"]:
                        entry["roles"].append(role)
                        self._say(f"同じ候補を {role} も報告しました。")
                    return
            identifier = f"C{len(self.candidates) + 1}"
            self.candidates[identifier] = {"candidate": candidate, "roles": [role]}
            self._say(f"候補 {identifier} ({role}): {json.dumps(candidate, ensure_ascii=True)}")

    def list_candidates(self) -> list[tuple[str, str, tuple[str, ...]]]:
        with self.lock:
            return [(identifier, entry["candidate"], tuple(entry["roles"]))
                    for identifier, entry in self.candidates.items()]

    def _solution(self, accepted: dict) -> str:
        candidate = accepted["candidate"]
        lines = ["# Owner-confirmed CTF solution handoff", "",
                 f"- Problem: {render_command(str(self.case.get('title', self.case.get('case_id', 'unknown'))))}",
                 f"- Case: `{render_command(str(self.case.get('category', 'unknown')))}/{render_command(str(self.case.get('case_id', 'unknown')) )}`",
                 f"- Authorized scope at run time: {render_command(str(self.case.get('scope_note', 'unknown')))}",
                 f"- Recorded target: {render_command(str(self.case.get('authorized_target') or 'none'))}",
                 "- Recheck target validity before any later request.",
                 f"- Owner-selected candidate ID: {accepted['id']}",
                 f"- Exact candidate: `{json.dumps(candidate, ensure_ascii=True)}`",
                 f"- Candidate UTF-8 SHA-256: `{accepted['candidate_utf8_sha256']}`",
                 f"- Owner-reported official acceptance at: {accepted['reported_at']}",
                 "- Acceptance is reported by the owner; this harness did not submit to or verify with the challenge server.",
                 f"- Origin role(s): {', '.join(accepted['roles'])}", "",
                 "## Recorded actions and results", "",
                 "The following command lines are saved Codex events, not private reasoning. "
                 "Exit codes alone do not establish a successful challenge result.", ""]
        for role in accepted["roles"]:
            path = self.run_root / role / "events.jsonl"
            lines.append(f"### {role}")
            if not path.is_file():
                lines.append("- No event file was saved for this role.")
                continue
            commands: dict[str, dict] = {}
            try:
                for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
                    try:
                        event = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(event, dict) or not isinstance(event.get("item"), dict):
                        continue
                    item = event["item"]
                    if item.get("type") != "command_execution":
                        continue
                    identity = str(item.get("id", "unknown"))
                    entry = commands.setdefault(identity, {})
                    if event.get("type") == "item.started":
                        entry["command"] = item.get("command")
                    if event.get("type") in ("item.completed", "item.failed"):
                        entry["exit_code"] = item.get("exit_code")
                        entry["state"] = event["type"]
            except OSError:
                commands = {}
            if not commands:
                lines.append("- No command events were saved.")
            for identity, entry in list(commands.items())[:40]:
                command = render_command(entry.get("command"))
                code = entry.get("exit_code")
                state = entry.get("state", "no completion event")
                outcome = f"exit {code}" if type(code) is int else safe_text(state)
                lines.append(f"- `{safe_text(identity)}` {command} — {outcome}")
            if len(commands) > 40:
                lines.append(f"- {len(commands) - 40} further commands omitted; see `{role}/events.jsonl`.")
        lines.extend(["", "## Role-reported derivation (claims, not independent verification)", ""])
        for role in accepted["roles"]:
            report_path = self.run_root / role / "structured-report.json"
            lines.append(f"### {role} — `{role}/structured-report.json`")
            if not report_path.is_file():
                lines.append("- Structured report unavailable at confirmation time.")
                continue
            try:
                report = json.loads(report_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                lines.append("- Structured report could not be read at confirmation time.")
                continue
            if report.get("candidate") != candidate:
                lines.append("- Report candidate no longer matches the owner-selected candidate; inspect the raw report.")
                continue
            for field, title in (("method", "Method"), ("evidence", "Evidence"),
                                 ("reproduction_commands", "Role-proposed reproduction commands"),
                                 ("limitations", "Limitations")):
                value = report.get(field)
                entries = value if isinstance(value, list) else [value] if isinstance(value, str) else []
                for item in entries[:12]:
                    if isinstance(item, str):
                        lines.append(f"- {title}: {render_command(item)}")
                if len(entries) > 12:
                    lines.append(f"- More {title.lower()} entries in `{role}/structured-report.json`.")
        lines.extend(["", "## Files to retain", "", "- `HANDOFF.md`: incremental run context and role statuses.",
                      "- `OWNER_CONFIRMATION.json`: exact owner-reported acceptance metadata.",
                      "- `result.json`: final aggregate status when available.",
                      "- `candidate.txt`: the owner-confirmed candidate when finalization succeeded.",
                      "- Each origin role's `structured-report.json`, `events.jsonl`, and evidence artifacts.",
                      "- Original case input files; they are not embedded in this document.",
                      "This document is assembled from recorded events and role reports. Missing outputs or steps are not inferred.", ""])
        return "\n".join(lines)

    def confirm(self, identifier: str, acknowledgement: str) -> bool:
        with self.lock:
            if (self.closed.is_set() or self.cancelled.is_set() or
                    self.confirmed.is_set() or identifier not in self.candidates):
                return False
            if acknowledgement != f"ACCEPT {identifier}":
                return False
            entry = self.candidates[identifier]
            candidate = entry["candidate"]
            accepted = {"id": identifier, "candidate": candidate,
                        "candidate_utf8_sha256": hashlib.sha256(candidate.encode("utf-8")).hexdigest(),
                        "roles": list(entry["roles"]), "reported_at": _utc_now(),
                        "acceptance_source": "owner_reported_official_submission",
                        "harness_verified": False}
            # Persist the minimal acceptance record first. A writeup rendering error
            # must not erase the owner's report or cause the wrong run status.
            _atomic_text(self.run_root / "OWNER_CONFIRMATION.json",
                         json.dumps(accepted, ensure_ascii=False, indent=2) + "\n")
            self.accepted = accepted
            self.ensure_solution()
            self.confirmed.set()
            self.review_outcome = "confirmed"
            self.review_done.set()
            return True

    def wait_for_final_review(self) -> str:
        """Keep the owner terminal open after roles finish if candidates were shown."""
        if self.confirmed.is_set():
            return "confirmed"
        if self.cancelled.is_set() or not self.list_candidates():
            return "not_requested"
        if not self.review_done.is_set():
            self.final_review.set()
            self._say("候補の公式提出結果を確認します。正解なら solved、すべて不正解なら wrong、未確認なら skip と入力してください。")
            while not self.review_done.wait(0.25):
                if self.cancelled.is_set() or self.closed.is_set():
                    break
                if self.thread is not None and not self.thread.is_alive():
                    break
        return self.review_outcome or ("cancelled" if self.cancelled.is_set() else "input_ended")

    def ensure_solution(self) -> None:
        with self.lock:
            if self.accepted is None or (self.run_root / "SOLUTION.md").is_file():
                return
            try:
                _atomic_text(self.run_root / "SOLUTION.md", self._solution(self.accepted))
                self.solution_error = False
            except Exception:
                self.solution_error = True

    def _readline(self) -> str | None:
        while not self.closed.is_set() and not self.confirmed.is_set() and not self.cancelled.is_set():
            if b"\n" in self._input_buffer:
                line, _, rest = self._input_buffer.partition(b"\n")
                self._input_buffer = bytearray(rest)
                return line.decode("utf-8", errors="replace").rstrip("\r")
            try:
                descriptor = self.input_stream.fileno()
                readable, _, _ = select.select([descriptor], [], [], 0.25)
            except (OSError, ValueError):
                return None
            if readable:
                try:
                    chunk = os.read(descriptor, 4096)
                except OSError:
                    return None
                if not chunk:
                    return None
                self._input_buffer.extend(chunk)
                if len(self._input_buffer) > 8192 and b"\n" not in self._input_buffer:
                    self._input_buffer.clear()
                    self._say("入力が長すぎます。短いコマンドを入力してください。")
        return None

    def _loop(self) -> None:
        self._say("候補を公式画面で提出して正解だった場合、この端末で solved と入力してください。")
        while not self.closed.is_set() and not self.confirmed.is_set() and not self.cancelled.is_set():
            command = self._readline()
            if command is None:
                if not (self.closed.is_set() or self.cancelled.is_set() or self.confirmed.is_set()):
                    self._say("端末入力が終了しました。候補の確認は記録しません。")
                break
            if self.final_review.is_set() and command.strip() in ("wrong", "skip"):
                self.review_outcome = "all_rejected" if command.strip() == "wrong" else "skipped"
                self._say("全候補を不正解として記録します。" if command.strip() == "wrong" else
                          "候補は未確認のまま終了します。")
                self.review_done.set()
                break
            if command.strip() != "solved":
                continue
            choices = self.list_candidates()
            if not choices:
                self._say("まだ選べる候補はありません。")
                continue
            for identifier, candidate, roles in choices:
                self._say(f"{identifier} ({', '.join(roles)}): {json.dumps(candidate, ensure_ascii=True)}")
            self._say("公式画面で正解だった候補の ID を入力してください（Enter で戻る）。")
            identifier = self._readline()
            if identifier is None:
                break
            with self.lock:
                entry = self.candidates.get(identifier)
                exact = entry["candidate"] if entry else None
            if exact is None:
                self._say("候補 ID が見つかりません。")
                continue
            self._say(f"選択した候補全文: {json.dumps(exact, ensure_ascii=True)}")
            self._say(f"この候補の公式提出が正解だった場合だけ ACCEPT {identifier} と入力してください。")
            acknowledgement = self._readline()
            if acknowledgement is None:
                break
            try:
                accepted = self.confirm(identifier, acknowledgement)
            except Exception:
                self._say("正解報告を保存できませんでした。実行は続けます。")
                continue
            if accepted:
                self._say("ユーザーによる正解報告を保存しました。残りの実行を停止します。")
                if self.solution_error:
                    self._say("解法ファイルは作成できませんでした。OWNER_CONFIRMATION.json と役割ログを保存してください。")
            else:
                self._say("正解確認は記録していません。実行を続けます。")
        self.review_done.set()

    def start(self) -> None:
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def close(self) -> None:
        self.closed.set()
        self.review_done.set()
        if self.thread is not None:
            self.thread.join(timeout=1)
        # Fence an acceptance that entered confirm() just before close().
        # Final aggregation must not read accepted while its atomic write is pending.
        with self.lock:
            pass
