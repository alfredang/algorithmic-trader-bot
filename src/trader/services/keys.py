"""API keys pasted into the app (Integrations page) - saved to <DATA_DIR>/keys.env.

Learner-friendly: no terminal, no text editor. Rules:
  * only the key names in EDITABLE can be written (an allow-list - nothing else in the
    environment can be changed from the browser);
  * values are validated (no newlines, quotes or spaces; length-capped) and stored in a
    file readable only by the current user (chmod 600), never in the database or git;
  * the API never returns a stored value - only masked previews and where it came from;
  * a blank field means "keep the current value"; clearing is explicit.
"""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

from trader.config import get_settings, keys_file, mask, read_keys_file, reset_settings

# integration -> [(ENV NAME, label, kind, options)]
EDITABLE: dict[str, list[tuple[str, str, str, tuple[str, ...]]]] = {
    "alpaca": [("APCA_API_KEY_ID", "API Key ID (starts with PK)", "secret", ()),
               ("APCA_API_SECRET_KEY", "Secret Key", "secret", ()),
               ("APCA_DATA_FEED", "Data feed", "select", ("iex", "sip"))],
    "twelvedata": [("TWELVEDATA_API_KEY", "API key", "secret", ())],
    "newsapi": [("NEWSAPI_KEY", "API key", "secret", ())],
    "equibles": [("EQUIBLES_API_KEY", "API key (starts with eq_)", "secret", ())],
    "claude": [("ANTHROPIC_API_KEY", "Anthropic API key (starts with sk-ant-)", "secret", ())],
    "openai": [("OPENAI_API_KEY", "OpenAI API key (starts with sk-)", "secret", ())],
}
ALL_KEYS = {name for fields in EDITABLE.values() for name, *_ in fields}
_VALUE = re.compile(r"^[A-Za-z0-9_\-.:/+=]{1,512}$")

_ATTR = {"APCA_API_KEY_ID": "alpaca_key_id", "APCA_API_SECRET_KEY": "alpaca_secret_key",
         "APCA_DATA_FEED": "alpaca_data_feed", "TWELVEDATA_API_KEY": "twelvedata_api_key",
         "NEWSAPI_KEY": "newsapi_key", "EQUIBLES_API_KEY": "equibles_api_key",
         "ANTHROPIC_API_KEY": "anthropic_api_key", "OPENAI_API_KEY": "openai_api_key"}


class KeyError_(ValueError):
    pass


def fields_for(integration: str) -> list[dict]:
    """Form description for one integration card: label, kind, masked current value, source."""
    saved = read_keys_file()
    dotenv = read_keys_file(Path(".env"))
    s = get_settings()
    out = []
    for name, label, kind, options in EDITABLE.get(integration, []):
        current = getattr(s, _ATTR[name], "") or ""
        if saved.get(name):
            source = "saved in the app"
        elif os.environ.get(name) or dotenv.get(name):
            source = "from .env / environment"
        else:
            source = "default" if current else ""
        if kind == "select":
            preview = current
        else:
            preview = mask(current)
        out.append({"name": name, "label": label, "kind": kind, "options": list(options),
                    "current": preview, "source": source, "saved_in_app": bool(saved.get(name))})
    return out


def _validate(name: str, value: str) -> str:
    if name not in ALL_KEYS:
        raise KeyError_(f"{name} cannot be set from the app")
    v = (value or "").strip()
    for kind_name, _, kind, options in [f for fs in EDITABLE.values() for f in fs]:
        if kind_name == name and kind == "select":
            if v.lower() not in options:
                raise KeyError_(f"{name} must be one of {', '.join(options)}")
            return v.lower()
    if not _VALUE.match(v):
        raise KeyError_(f"{name}: paste the key exactly as shown by the provider "
                        "(no spaces, quotes or line breaks)")
    return v


def _write(values: dict[str, str], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# API keys saved from the app's Integrations page. Keep this file private.",
             "# It is git-ignored and never uploaded. Delete a line (or use 'Remove') to clear a key."]
    lines += [f"{k}={v}" for k, v in sorted(values.items()) if v]
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".keys.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)           # atomic: a reader never sees a half-written file
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def save(integration: str, values: dict[str, str] | None = None, clear: list[str] | None = None) -> list[dict]:
    """Save pasted keys for one integration. Blank values are ignored ("keep current")."""
    allowed = {name for name, *_ in EDITABLE.get(integration, [])}
    if not allowed:
        raise KeyError_(f"{integration} has no keys that can be set from the app")
    values = values or {}
    clear = clear or []
    bad = [k for k in list(values) + list(clear) if k not in allowed]
    if bad:
        raise KeyError_(f"not a {integration} setting: {', '.join(bad)}")
    path = keys_file()
    stored = read_keys_file(path)
    for name in clear:
        stored.pop(name, None)
    for name, value in values.items():
        if value is None or str(value).strip() == "":
            continue
        stored[name] = _validate(name, str(value))
    _write(stored, path)
    reset_settings()
    return fields_for(integration)
