"""Validate model reports without accepting arbitrary paths or command strings."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from harness.config import ROOT

REQUIRED = {"candidate", "input_sha256", "method", "evidence", "reproduction_commands", "artifacts", "limitations"}
HEX256 = re.compile(r"[a-f0-9]{64}\Z")
TOKEN = re.compile(r"\S{1,512}\Z")
ARTIFACT_PATH = re.compile(r"[A-Za-z0-9_./-]{1,240}\Z")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_schema(hashes: dict[str, str], path: Path) -> None:
    schema = json.loads((ROOT / "docs" / "report.schema.json").read_text(encoding="utf-8"))
    field = schema["properties"]["input_sha256"]
    field["properties"] = {name: {"type": "string"} for name in hashes}
    field["required"] = list(hashes)
    field["additionalProperties"] = False
    path.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")


def validate_report(report: object, hashes: dict[str, str], workdir: Path) -> list[str]:
    if not isinstance(report, dict) or set(report) != REQUIRED:
        return ["report must contain exactly the required fields"]
    errors: list[str] = []
    candidate = report["candidate"]
    if not isinstance(candidate, str) or (candidate and not TOKEN.fullmatch(candidate)):
        errors.append("candidate must be empty or one complete whitespace-free token")
    supplied = report["input_sha256"]
    if not isinstance(supplied, dict) or supplied != hashes or not all(
        isinstance(value, str) and HEX256.fullmatch(value) for value in supplied.values()
    ):
        errors.append("input hashes do not match")
    if not isinstance(report["method"], str) or len(report["method"].strip()) < 20:
        errors.append("method is too short")
    for field in ("evidence", "reproduction_commands"):
        items = report[field]
        if not isinstance(items, list) or not items or not all(isinstance(x, str) and x.strip() for x in items):
            errors.append(f"{field} must be a nonempty list of strings")
    if not isinstance(report["limitations"], list) or not all(isinstance(x, str) for x in report["limitations"]):
        errors.append("limitations must be a list of strings")
    artifacts = report["artifacts"]
    if not isinstance(artifacts, list) or not artifacts:
        errors.append("artifacts must be a nonempty list")
    else:
        for item in artifacts:
            if not isinstance(item, dict) or set(item) != {"path"} or not isinstance(item["path"], str):
                errors.append("artifact must contain only a path string")
                break
            value = item["path"]
            relative = Path(value)
            target = workdir / relative
            if (not ARTIFACT_PATH.fullmatch(value) or relative.is_absolute() or
                any(part in (".", "..") for part in relative.parts) or not target.is_file() or
                target.is_symlink() or not target.resolve().is_relative_to(workdir.resolve())):
                errors.append("artifact path is absent or outside the role directory")
                break
    return errors


def parse_report(text: str, hashes: dict[str, str], workdir: Path) -> tuple[dict | None, list[str]]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None, ["final answer is not JSON"]
    errors = validate_report(data, hashes, workdir)
    return (data if not errors else None), errors
