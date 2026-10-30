"""Preserve exact role proposals without treating model reports as verification."""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

from harness.progress import safe_text

URL = re.compile(r"https?://[^\s<>\"']+")
MEMORY = re.compile(r"(?i)\b(?:memory|memorized|remember(?:ed)?|recall(?:ed)?|prior knowledge|guess)\b|記憶|推測|未検証")
REFERENCE_PATH = re.compile(r"/(?:write-?ups?|solutions?|walkthroughs?|blogs?|guides?|answers?)(?:/|$)", re.I)
HTTP_SUCCESS = re.compile(r"HTTP/\S+\s+([23][0-9][0-9])\b", re.I)


def report_urls(report: dict) -> list[str]:
    found: set[str] = set()
    for field in ("method", "evidence", "limitations"):
        value = report.get(field)
        chunks = value if isinstance(value, list) else [value] if isinstance(value, str) else []
        for chunk in chunks:
            if isinstance(chunk, str):
                found.update(part.rstrip(".,;:)]}") for part in URL.findall(chunk))
    return sorted(found)


def external_urls(urls: list[str], authorized_target: str | None) -> list[str]:
    if not authorized_target:
        return urls
    target = urlsplit(authorized_target if "://" in authorized_target else "http://" + authorized_target)
    try:
        origin = (target.hostname, target.port or (443 if target.scheme == "https" else 80))
    except ValueError:
        return urls
    external = []
    for url in urls:
        parsed = urlsplit(url)
        try:
            actual = (parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
        except ValueError:
            external.append(url)
            continue
        if actual != origin or REFERENCE_PATH.search(unquote(parsed.path)):
            external.append(url)
    return external


def observed_references(run_root: Path, roles: list[str], authorized_target: str | None) -> tuple[list[str], bool]:
    """Recognize completed, successful shell requests and completed hosted searches only.

    This is an observation of tool metadata, not proof the report used its result.
    """
    urls: set[str] = set()
    search_completed = False
    for role in roles:
        events = run_root / role / "events.jsonl"
        if not events.is_file() or events.is_symlink():
            continue
        with events.open(encoding="utf-8", errors="replace") as stream:
            for line in stream:
                if len(line) > 100_000:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(event, dict):
                    continue
                if event.get("type") != "item.completed":
                    continue
                item = event.get("item")
                if not isinstance(item, dict):
                    continue
                if item.get("type") in ("web_search_call", "web_search"):
                    search_completed = True
                if item.get("type") == "command_execution" and item.get("exit_code") == 0:
                    command = item.get("command")
                    if isinstance(command, str):
                        urls.update(part.rstrip(".,;:)]}") for part in URL.findall(command))
    return external_urls(sorted(urls), authorized_target), search_completed


def basis(report: dict, authorized_target: str | None, role: str | None = None) -> str:
    if role == "verifier_review":
        return "dependent_review_reported"
    claims = [report.get("method", ""), *report.get("evidence", []), *report.get("limitations", [])]
    if MEMORY.search(" ".join(str(item) for item in claims)):
        return "memory_hypothesis"
    urls = report_urls(report)
    if external_urls(urls, authorized_target):
        return "external_reference_reported"
    if urls:
        return "target_reported"
    return "local_or_unspecified_reported"


def target_http_observations(run_root: Path, role: str, authorized_target: str | None) -> list[dict]:
    """Record successful-looking HTTP tool output; this never proves candidate derivation."""
    if not authorized_target:
        return []
    path = run_root / role / "events.jsonl"
    if not path.is_file() or path.is_symlink():
        return []
    observations = []
    with path.open(encoding="utf-8", errors="replace") as stream:
        for line in stream:
            if len(line) > 100_000:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict) or event.get("type") != "item.completed":
                continue
            item = event.get("item")
            if not isinstance(item, dict) or item.get("type") != "command_execution" or item.get("exit_code") != 0:
                continue
            command, output = item.get("command"), item.get("aggregated_output")
            if not isinstance(command, str) or not isinstance(output, str):
                continue
            urls = [part.rstrip(".,;:)]}") for part in URL.findall(command)]
            if not urls or len(external_urls(urls, authorized_target)) == len(urls):
                continue
            for status in HTTP_SUCCESS.findall(output):
                observations.append({"event_id": item.get("id") if isinstance(item.get("id"), str) else None,
                                     "http_status": int(status), "events_file": f"{role}/events.jsonl"})
    return observations[:20]


def catalog(results: dict, authorized_target: str | None, run_root: Path | None = None,
            accepted: dict | None = None) -> list[dict]:
    """One entry per exact proposal; roles and evidence stay distinct."""
    groups: dict[str, dict] = {}
    for role, record in results.items():
        value = record.get("candidate")
        if record.get("status") != "completed" or not record.get("report_sha256") or not value:
            continue
        report = record.get("report_data", {})
        if not isinstance(report, dict):
            report = {}
        entry = groups.setdefault(value, {"candidate": value, "challenge_verified_by_harness": False,
                                          "owner_confirmed": bool(accepted and accepted.get("candidate") == value),
                                          "sources": []})
        reported = basis(report, authorized_target, role)
        artifacts = {f"{role}/{name}": digest for name, digest in record.get("artifact_sha256", {}).items()}
        target_seen = target_http_observations(run_root, role, authorized_target) if run_root else []
        external_seen = bool(observed_references(run_root, [role], authorized_target)[0]) if run_root else False
        grade = ("prior_model_informed" if record.get("reads_deepseek_handoff") else
                 "dependent_review" if role == "verifier_review" else
                 "memory_hypothesis" if reported == "memory_hypothesis" else
                 "target_http_observed" if target_seen else
                 "external_reference_access_observed" if external_seen else
                 "local_artifact_backed_report" if artifacts else "unknown")
        entry["sources"].append({"role": role, "basis": reported, "evidence_grade": grade,
                                 "report": f"{role}/structured-report.json",
                                 "report_sha256": record["report_sha256"],
                                 "artifacts": list(artifacts), "artifact_sha256": artifacts,
                                 "target_http_observations": target_seen,
                                 "external_reference_access_observed": external_seen,
                                 "reads_frozen_reports": role == "verifier_review",
                                 "reads_deepseek_handoff": bool(record.get("reads_deepseek_handoff")),
                                 "reads_prior_handoff": bool(record.get("reads_prior_handoff"))})
    # Do not promote a proposal merely because a dependent review repeated it.
    return sorted(groups.values(), key=lambda item: item["candidate"])


def write_catalog(root: Path, proposals: list[dict]) -> None:
    (root / "candidates.json").write_text(json.dumps(proposals, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    lines = ["# Role candidates", "", "Every exact proposal is preserved. All are unverified by the harness; matching roles do not prove correctness.",
             "An owner-confirmed official submission is recorded separately in OWNER_CONFIRMATION.json.", ""]
    if not proposals:
        lines.append("No valid role candidate was reported.")
    for index, item in enumerate(proposals, 1):
        lines.extend([f"## Candidate {index}", "", "    " + safe_text(item["candidate"]), ""])
        for source in item["sources"]:
            lines.append(f"- {source['role']}: {source['evidence_grade']} ({source['basis']}); "
                         f"target HTTP observations {len(source['target_http_observations'])}; report `{source['report']}`; "
                         f"artifacts {', '.join('`' + path + '`' for path in source['artifacts']) or 'none'}")
        lines.append("")
    (root / "CANDIDATES.md").write_text("\n".join(lines), encoding="utf-8")
