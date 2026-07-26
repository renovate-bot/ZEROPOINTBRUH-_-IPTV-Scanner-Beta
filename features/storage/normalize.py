"""Normalization helpers for IPTV Scanner Phase 2.

These utilities canonicalize channel data before it enters the SQLite store so
the same underlying stream cannot appear twice under slightly different URLs
or contradictory metadata. Helpers are intentionally conservative — when in
doubt, keep the original value rather than mangling it.
"""

from __future__ import annotations

import re
import urllib.parse
from typing import Any, Optional


# Query params commonly used for analytics / session tracking that should be
# stripped when building a normalized URL. Anything not on this list is kept
# (and sorted alphabetically) so real stream tokens survive round-trips.
_TRACKING_QUERY_PARAMS = frozenset(
    {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "gclid",
        "fbclid",
        "mc_cid",
        "mc_eid",
        "_ga",
        "yclid",
    }
)

# Hosts that are well-known demo / sample streams. Anything served from these
# hosts should be treated as a Test channel regardless of the group-title we
# received.
_DEMO_HOSTS = frozenset(
    {
        "d3rlna7iyyu8wu.cloudfront.net",
        "amssamples.streaming.mediaservices.windows.net",
        "test-streams.mux.dev",
        "demo.unified-streaming.com",
        "cph-p2p-msl.akamaized.net",
        "bitdash-a.akamaihd.net",
        "sample.vodobox.com",
    }
)

# Substring markers that make a channel a Test channel. Kept conservative so
# we don't accidentally re-tag legitimate networks (e.g. "Contest TV").
_TEST_NAME_MARKERS = (
    "dolby vod test",
    "azure test",
    "big buck bunny",
    "sintel",
    "tears of steel",
    " sample",
    " demo stream",
    "test pattern",
    "hls test",
    "dash test",
)

_TEST_GROUPS = frozenset({"test", "tests", "sample", "samples", "demo", "demos"})

_VOD_URL_TOKENS = (
    ".mp4",
    ".mkv",
    ".mov",
    ".webm",
    ".avi",
    "/vod/",
    "/movies/",
    "/movie/",
    "/series/",
    "/episodes/",
    "/episode/",
)

_LIVE_URL_TOKENS = (
    "/live/",
    "/hls/live",
    "/dash/live",
    "manifest.mpd",
    "playlist.m3u8",
    "live.m3u8",
    "master.m3u8",
    "index.m3u8",
    "chunklist",
)


def normalize_url(url: Optional[str]) -> Optional[str]:
    """Return a canonical form of ``url`` suitable for de-duplication.

    Returns ``None`` for empty / non-string input so callers can decide whether
    to skip the row entirely.
    """
    if not url:
        return None
    raw = str(url).strip()
    if not raw:
        return None

    try:
        parsed = urllib.parse.urlsplit(raw)
    except Exception:
        return raw.lower()

    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https", "rtmp", "rtsp", "rtmps"):
        # Non-web schemes are returned lowercased but otherwise untouched.
        return raw.lower()

    hostname = (parsed.hostname or "").lower()
    port = parsed.port
    if port is not None:
        if (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
            port = None

    userinfo = ""
    if parsed.username:
        userinfo = parsed.username
        if parsed.password:
            userinfo += f":{parsed.password}"
        userinfo += "@"

    netloc = f"{userinfo}{hostname}"
    if port is not None:
        netloc += f":{port}"

    path = parsed.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")

    if parsed.query:
        params = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        params = [(k, v) for k, v in params if k.lower() not in _TRACKING_QUERY_PARAMS]
        params.sort()
        query = urllib.parse.urlencode(params, doseq=True)
    else:
        query = ""

    return urllib.parse.urlunsplit((scheme, netloc, path, query, ""))


def _primary_group(raw: Optional[str]) -> str:
    """Split ``group_title`` on ``;`` / ``,`` and return the first token."""
    if not raw:
        return ""
    text = str(raw)
    for sep in (";", ","):
        if sep in text:
            text = text.split(sep, 1)[0]
    return text.strip()


def is_test_channel(channel: dict) -> bool:
    """Return True when the channel looks like a demo / test stream."""
    if not isinstance(channel, dict):
        return False

    group = (channel.get("group_title") or "").strip().lower()
    if group in _TEST_GROUPS:
        return True

    name = (channel.get("name") or "").strip().lower()
    if name:
        for marker in _TEST_NAME_MARKERS:
            if marker in name:
                return True
        if name.startswith("test ") or name.endswith(" test") or name == "test":
            return True

    url = (channel.get("url") or "").strip().lower()
    if url:
        try:
            host = urllib.parse.urlsplit(url).hostname or ""
        except Exception:
            host = ""
        host = host.lower()
        if host in _DEMO_HOSTS:
            return True
        if "sample" in url or "/test/" in url or "test-streams" in url:
            return True

    return False


def normalize_group_title(channel: dict) -> str:
    """Reduce a channel's ``group_title`` to a single primary group.

    Mutates ``channel`` in place and also returns the resulting group. Test
    streams are always forced into the ``"Test"`` group so they can be excluded
    from public listings by default.
    """
    if not isinstance(channel, dict):
        return ""

    primary = _primary_group(channel.get("group_title"))
    if not primary:
        primary = "Ungrouped"

    if is_test_channel({**channel, "group_title": primary}):
        primary = "Test"

    channel["group_title"] = primary
    return primary


def classify_media_type(
    content_or_url: Optional[str],
    playlist_text: Optional[str] = None,
) -> str:
    """Best-effort classification of a stream as ``live``, ``vod``, or ``unknown``.

    ``content_or_url`` is normally the channel URL. ``playlist_text`` is the
    optional body of the fetched playlist. When both are provided the playlist
    body wins because HLS manifests are authoritative.
    """
    if playlist_text:
        text = playlist_text
        if "#EXT-X-ENDLIST" in text:
            return "vod"
        if re.search(r"#EXT-X-PLAYLIST-TYPE\s*:\s*VOD", text, re.IGNORECASE):
            return "vod"
        if re.search(r"#EXT-X-PLAYLIST-TYPE\s*:\s*EVENT", text, re.IGNORECASE):
            return "live"
        if "#EXTM3U" in text or "#EXT-X-STREAM-INF" in text or "#EXTINF" in text:
            return "live"

    if not content_or_url:
        return "unknown"

    url = str(content_or_url).strip().lower()
    if not url:
        return "unknown"

    for token in _VOD_URL_TOKENS:
        if token in url:
            return "vod"
    for token in _LIVE_URL_TOKENS:
        if token in url:
            return "live"
    if url.endswith(".m3u8") or url.endswith(".mpd"):
        return "live"

    return "unknown"


def normalize_channel(channel: dict) -> dict:
    """Apply every normalizer to ``channel`` and return the mutated dict."""
    if not isinstance(channel, dict):
        return channel

    from .geo import resolve_country_code

    url = channel.get("url")
    channel["url_norm"] = normalize_url(url)
    normalize_group_title(channel)

    media_type = channel.get("media_type")
    if not media_type or media_type == "unknown":
        channel["media_type"] = classify_media_type(url)

    for key in ("name", "tvg_id", "tvg_logo", "country", "playing_now"):
        val = channel.get(key)
        if isinstance(val, str):
            channel[key] = val.strip()

    # Prefer ISO codes; recover from group-title when playlists stuffed the
    # country name into group-title and left country empty/GLOBAL.
    resolved = resolve_country_code(channel)
    if resolved:
        channel["country"] = resolved
    elif (channel.get("country") or "").strip().upper() in (
        "",
        "GLOBAL",
        "XX",
        "ZZ",
        "UNKNOWN",
        "UNDEFINED",
    ):
        channel["country"] = "GLOBAL"

    return channel


def coerce_dict(row: Any) -> dict:
    """Convert an ``sqlite3.Row`` (or already-dict) into a plain dict."""
    if row is None:
        return {}
    if isinstance(row, dict):
        return dict(row)
    try:
        return {k: row[k] for k in row.keys()}
    except Exception:
        return dict(row) if hasattr(row, "keys") else {}
