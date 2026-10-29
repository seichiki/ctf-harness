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
DEFAULTS = {"model": "", "effort": "medium", "daybreak": "off", "orchestration": "single",
            "network_access": "off", "progress": False, "proxy_url": ""}


def validate(config: dict) -> dict:
    if set(config) - set(DEFAULTS):
        raise ValueError("unknown keys in local config")
    data = {**DEFAULTS, **config}
    model = data["model"]
    if not isinstance(model, str) or not MODEL_ID.fullmatch(model) or model == "SET_YOUR_AVAILABLE_MODEL_ID":
        raise ValueError("set a real model ID available to your own Codex account")
    for key, choices in (("effort", EFFORTS), ("daybreak", DAYBREAK), ("orchestration", ORCHESTRATION),
                         ("network_access", NETWORK_ACCESS)):
        if not isinstance(data[key], str) or data[key] not in choices:
            raise ValueError(f"{key} must be one of: {', '.join(choices)}")
    if type(data["progress"]) is not bool:
        raise ValueError("progress must be true or false")
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
    text += "".join(f"{key} = {json.dumps(values[key])}\n" for key in DEFAULTS)
    path.write_text(text, encoding="utf-8")
    path.chmod(0o600)
    return path


def public_settings(config: dict) -> dict:
    """Configuration safe for plans, run files, and terminal summaries."""
    return {key: value for key, value in config.items() if key != "proxy_url"} | {
        "proxy_configured": bool(config.get("proxy_url")),
        "proxy_active": bool(config.get("proxy_url")) and config["network_access"] == "on",
    }
