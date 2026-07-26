"""Channel reads — prefer SQLite ChannelStore, with JSON fallback for legacy tools."""

from __future__ import annotations

import json
import os

import state
from config import FILES, WRITE_LOCK


def load_json_file(path, default):
    """Read JSON file with safe fallback."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json_atomic(path, data):
    """Write JSON atomically (legacy path; prefer db.ChannelStore for runtime)."""
    temp_path = f"{path}.tmp"
    with WRITE_LOCK:
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
        os.replace(temp_path, path)
    if path in (FILES["streams"], FILES["master"]):
        state.CHANNEL_STATE_REVISION += 1


def _store():
    try:
        from .db import get_default_store

        return get_default_store()
    except Exception:
        return None


def get_valid_channels():
    """Online channels for UI/SEO (excludes Test by store default where applicable)."""
    store = _store()
    if store is not None:
        try:
            # Prefer online live+unknown; exclude Test for public lists.
            result = store.list_channels(
                page=1,
                limit=100000,
                include_test=False,
                media_type=None,
                status="online",
            )
            channels = result.get("channels") or []
            state.CHANNEL_STATE_REVISION = store.get_revision()
            return channels
        except Exception:
            pass
    try:
        with open(FILES["streams"], "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def get_update_count():
    """Get current count of valid channels."""
    store = _store()
    if store is not None:
        try:
            count = store.count_channels(status="online", exclude_test=True)
            if count != state.last_update_count:
                state.last_update_count = count
            return count
        except Exception:
            pass
    channels = get_valid_channels()
    count = len(channels)
    if count != state.last_update_count:
        state.last_update_count = count
    return count
