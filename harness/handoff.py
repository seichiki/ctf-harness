"""Best-effort, atomic run handoff checkpoints from public progress events."""

from __future__ import annotations

import os
import tempfile
import threading
from pathlib import Path

from harness.progress import ROLES, render_command, safe_text


class Handoff:
    def __init__(self, run_root: Path, case: dict, settings: dict):
        self.run_root = run_root
        self.case = case
        self.settings = settings
        self.lock = threading.RLock()
        self.events: list[str] = []
        self.status = "in progress"
        self.error_type: str | None = None
        self.write()

    @property
    def path(self) -> Path:
        return self.run_root / "HANDOFF.md"

    def event(self, role: str, message: str) -> None:
        with self.lock:
            safe_role = role if role in ROLES else "run"
            # Parsed CTF candidates are intended deliverables; keep their exact quoted
            # value while masking credentials in command and tool event summaries.
            shown = safe_text(message) if message.startswith("candidate: ") else render_command(message)
            self.events.append(f"- **{safe_role}**: {shown}")
            self.events = self.events[-100:]
            self.write()

    def finish(self, status: str, error_type: str | None = None) -> None:
        with self.lock:
            self.status = safe_text(status)
            self.error_type = safe_text(error_type) if error_type else None
            self.write()

    def _render(self) -> str:
        case_id = render_command(str(self.case.get("case_id", "unknown")))
        category = render_command(str(self.case.get("category", "unknown")))
        target = self.case.get("authorized_target")
        scope = render_command(str(self.case.get("scope_note", "unknown")))
        lines = ["# Run handoff", "", f"- Case: `{category}/{case_id}`",
                 f"- Problem: {render_command(str(self.case.get('title', case_id)))}",
                 f"- Status: {self.status}", f"- Authorized scope: {scope}",
                 f"- Target recorded at case creation: {render_command(str(target)) if target else 'none (local input)' }",
                 "- Check that a live target is still valid before any later attempt.",
                 f"- Requested model: {render_command(str(self.settings.get('model', 'unknown')))}; "
                 f"effort: {render_command(str(self.settings.get('effort', 'unknown')))}; "
                 f"Daybreak: {render_command(str(self.settings.get('daybreak', 'unknown')))}",
                 f"- Orchestration: {render_command(str(self.settings.get('orchestration', 'unknown')))}; "
                 f"network requested: {render_command(str(self.settings.get('network_access', 'unknown')))}; "
                 f"proxy configured: {bool(self.settings.get('proxy_configured'))}",
                 "- Settings are requests; effective model, network and proxy behavior may differ.", ""]
        if self.error_type:
            lines.extend([f"- Runner error type: {self.error_type}", ""])
        lines.extend(["## Actions and observed progress", "",
                      "These are sanitized tool events and role reports. Commands show starts and exit codes; "
                      "an exit code alone does not prove a challenge solution.", ""])
        lines.extend(self.events or ["- No role or tool event recorded yet."])
        lines.extend(["", "## Evidence files", "", "- `settings.json`: requested run settings.",
                      f"- `categories/{category}/cases/{case_id}/input/`: original case input (project-relative).",
                      "- `result.json`: final aggregate status when available.",
                      "- `candidate.txt`: aggregate candidate when available."])
        if (self.run_root / "CANDIDATES.md").is_file():
            lines.append("- `CANDIDATES.md` and `candidates.json`: all exact role proposals and report evidence pointers; none is verified by the harness.")
        if (self.run_root / "SOLUTION.md").is_file():
            lines.append("- `SOLUTION.md`: owner-reported accepted candidate and recorded derivation.")
        if (self.run_root / "OWNER_CONFIRMATION.json").is_file():
            lines.append("- `OWNER_CONFIRMATION.json`: durable owner-reported acceptance metadata.")
        for role in sorted(ROLES):
            folder = self.run_root / role
            if folder.is_dir():
                files = [name for name in ("run.json", "structured-report.json", "events.jsonl", "last-message.txt")
                         if (folder / name).is_file()]
                for name in files:
                    lines.append(f"- `{role}/{name}`")
        lines.extend(["", "## Next step", "",
                      "Inspect the listed evidence and current target validity before continuing. "
                      "Role candidates are proposals until independently checked or accepted by the challenge.",
                      "Input binaries and full event logs are referenced, not embedded; copy them with this file for a portable handoff.",
                      "A hard kill or power loss can leave only the last completed checkpoint.", ""])
        return "\n".join(lines)

    def write(self) -> None:
        with self.lock:
            temporary = None
            try:
                with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.run_root,
                                                 prefix=".HANDOFF-", delete=False) as file:
                    temporary = Path(file.name)
                    file.write(self._render())
                    file.flush()
                    os.fsync(file.fileno())
                os.replace(temporary, self.path)
            finally:
                if temporary is not None and temporary.exists():
                    temporary.unlink()
