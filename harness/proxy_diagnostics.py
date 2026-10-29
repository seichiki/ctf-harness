"""Classify HTTP observations in completed tool output without storing response bodies."""

from __future__ import annotations

import json
import re
from pathlib import Path

HTTP_400 = re.compile(r"HTTP/\S+\s+400\b|\b400 Bad Request\b", re.I)
HTTP_502 = re.compile(r"HTTP/\S+\s+502\b|\b502 Bad Gateway\b", re.I)
REFUSED = re.compile(r"\b(?:Connection refused|ECONNREFUSED)\b", re.I)


def scan(run_root: Path, roles: list[str], proxy_active: bool) -> dict[str, dict]:
    if not proxy_active:
        return {}
    findings = {}
    for role in roles:
        path = run_root / role / "events.jsonl"
        if not path.is_file() or path.is_symlink():
            continue
        counts = {"http_400_seen": 0, "http_502_seen": 0, "connection_refused_seen": 0}
        with path.open(encoding="utf-8", errors="replace") as stream:
            for line in stream:
                if len(line) > 1_000_000:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(event, dict):
                    continue
                item = event.get("item")
                if event.get("type") != "item.completed" or not isinstance(item, dict) or item.get("type") != "command_execution":
                    continue
                output = item.get("aggregated_output")
                if not isinstance(output, str):
                    continue
                counts["http_400_seen"] += bool(HTTP_400.search(output))
                counts["http_502_seen"] += bool(HTTP_502.search(output))
                counts["connection_refused_seen"] += bool(REFUSED.search(output))
        if any(counts.values()):
            findings[role] = counts
    return findings
