"""Local, non-secret model choices. Authentication remains with Codex."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
LOCAL_CONFIG = ROOT / ".local" / "config.toml"
CATEGORIES = ("web", "crypto", "pwn", "reverse", "forensics", "osint", "misc")
MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
EFFORTS = ("none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra")
DAYBREAK = ("off", "blue")
ORCHESTRATION = ("single", "multi", "interactive")
NETWORK_ACCESS = ("off", "on")
ROLES = ("solver", "verifier", "solver_a", "solver_b", "verifier_review", "writeup", "interactive")
ROLE_FIELDS = ("model", "effort", "daybreak")
DEFAULTS = {"model": "", "effort": "medium", "daybreak": "off", "orchestration": "single",
            "network_access": "off", "progress": False, "proxy_url": "", "writeup_draft": False,
            "role_settings": {}}


def _valid_model(value: object) -> bool:
    return isinstance(value, str) and bool(MODEL_ID.fullmatch(value)) and value != "SET_YOUR_AVAILABLE_MODEL_ID"


def role_choice(config: dict, role: str) -> dict[str, str]:
    """Resolve a role's explicit settings, then the shared fallback."""
    if role not in ROLES:
        raise ValueError("unknown model role")
    selected = config.get("role_settings", {}).get(role, {})
    choice = {field: selected[field] if field in selected else config[field] for field in ROLE_FIELDS}
    # Preserve the existing writeup-only standard access default. An explicit
    # writeup Daybreak choice still takes precedence over this exception.
    if role == "writeup" and "daybreak" not in selected:
        choice["daybreak"] = "off"
    return choice


def active_roles(orchestration: str, writeup_draft: bool = False) -> tuple[str, ...]:
    if orchestration == "single":
        roles = ("solver",)
    elif orchestration == "multi":
        roles = ("verifier", "solver_a", "solver_b", "verifier_review")
    elif orchestration == "interactive":
        roles = ("interactive",)
    else:
        raise ValueError("unknown orchestration")
    return roles + (("writeup",) if writeup_draft and orchestration != "interactive" else ())


def validate(config: dict) -> dict:
    if set(config) - set(DEFAULTS):
        raise ValueError("unknown keys in local config")
    data = {**DEFAULTS, **config}
    model = data["model"]
    if not _valid_model(model):
        raise ValueError("set a real model ID available to your own Codex account")
    for key, choices in (("effort", EFFORTS), ("daybreak", DAYBREAK), ("orchestration", ORCHESTRATION),
                         ("network_access", NETWORK_ACCESS)):
        if not isinstance(data[key], str) or data[key] not in choices:
            raise ValueError(f"{key} must be one of: {', '.join(choices)}")
    if type(data["progress"]) is not bool:
        raise ValueError("progress must be true or false")
    if type(data["writeup_draft"]) is not bool:
        raise ValueError("writeup_draft must be true or false")
    roles = data["role_settings"]
    if not isinstance(roles, dict) or set(roles) - set(ROLES):
        raise ValueError("role_settings must contain only known roles")
    normalized_roles = {}
    for role, selected in roles.items():
        if not isinstance(selected, dict) or not selected or set(selected) - set(ROLE_FIELDS):
            raise ValueError(f"role_settings.{role} must contain model, effort, or daybreak")
        if "model" in selected and not _valid_model(selected["model"]):
            raise ValueError(f"role_settings.{role}.model must be a valid model ID")
        if "effort" in selected and (not isinstance(selected["effort"], str) or selected["effort"] not in EFFORTS):
            raise ValueError(f"role_settings.{role}.effort is invalid")
        if "daybreak" in selected and (not isinstance(selected["daybreak"], str) or selected["daybreak"] not in DAYBREAK):
            raise ValueError(f"role_settings.{role}.daybreak is invalid")
        normalized_roles[role] = dict(selected)
    data["role_settings"] = normalized_roles
    proxy = data["proxy_url"]
    if not isinstance(proxy, str):
        raise ValueError("proxy_url must be an HTTP proxy endpoint or empty")
    if proxy:
        if any(ord(char) < 33 or ord(char) == 127 for char in proxy):
            raise ValueError("proxy_url must not contain whitespace or control characters")
        try:
            parsed = urlsplit(proxy)
            port = parsed.port
        except ValueError as exc:
            raise ValueError("invalid proxy_url") from exc
        if (parsed.scheme != "http" or not parsed.hostname or not port or
                parsed.username is not None or parsed.password is not None or
                parsed.path not in ("", "/") or parsed.query or parsed.fragment or
                not re.fullmatch(r"[A-Za-z0-9_.:-]+", parsed.hostname)):
            raise ValueError("proxy_url must be an HTTP host:port without credentials, path, query, or fragment")
    return data


def load(overrides: dict | None = None, path: Path = LOCAL_CONFIG) -> dict:
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
    text += "".join(f"{key} = {json.dumps(values[key])}\n" for key in DEFAULTS if key != "role_settings")
    for role in ROLES:
        if role in values["role_settings"]:
            text += f"\n[role_settings.{role}]\n"
            text += "".join(f"{key} = {json.dumps(value)}\n"
                            for key, value in values["role_settings"][role].items())
    path.write_text(text, encoding="utf-8")
    path.chmod(0o600)
    return path


def public_settings(config: dict) -> dict:
    """Configuration safe for plans, run files, and terminal summaries."""
    return {key: value for key, value in config.items() if key != "proxy_url"} | {
        "proxy_configured": bool(config.get("proxy_url")),
        "proxy_active": bool(config.get("proxy_url")) and config["network_access"] == "on",
    }
