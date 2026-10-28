"""Local, non-secret model choices. Authentication remains with Codex."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_CONFIG = ROOT / ".local" / "config.toml"
MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
EFFORTS = ("none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra")
DAYBREAK = ("off", "blue")
ORCHESTRATION = ("single", "multi", "interactive")
DEFAULTS = {"model": "", "effort": "medium", "daybreak": "off", "orchestration": "single"}


def validate(config: dict) -> dict[str, str]:
    if set(config) != set(DEFAULTS):
        raise ValueError("config must contain only model, effort, daybreak, and orchestration")
    model = config["model"]
    if not isinstance(model, str) or not MODEL_ID.fullmatch(model) or model == "SET_YOUR_AVAILABLE_MODEL_ID":
        raise ValueError("set a real model ID available to your own Codex account")
    for key, choices in (("effort", EFFORTS), ("daybreak", DAYBREAK), ("orchestration", ORCHESTRATION)):
        if not isinstance(config[key], str) or config[key] not in choices:
            raise ValueError(f"{key} must be one of: {', '.join(choices)}")
    return dict(config)


def load(overrides: dict | None = None, path: Path = LOCAL_CONFIG) -> dict[str, str]:
    data = dict(DEFAULTS)
    if path.exists():
        if path.is_symlink() or not path.is_file():
            raise ValueError("local config must be a regular file, not a symlink")
        loaded = tomllib.loads(path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict) or set(loaded) - set(DEFAULTS):
            raise ValueError("unknown keys in local config")
        data.update(loaded)
    data.update({key: value for key, value in (overrides or {}).items() if value is not None})
    return validate(data)


def save(config: dict, path: Path = LOCAL_CONFIG) -> Path:
    values = validate(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"local config already exists: {path}")
    text = "# Private local choices; authentication stays in Codex.\n"
    text += "".join(f"{key} = {json.dumps(values[key])}\n" for key in DEFAULTS)
    path.write_text(text, encoding="utf-8")
    path.chmod(0o600)
    return path
