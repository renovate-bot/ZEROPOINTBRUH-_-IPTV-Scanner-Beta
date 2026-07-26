"""SEO helpers: slug index, canonical URLs, feed metadata, proxied M3U builder.

Route handlers themselves live in :mod:`routes`; this module only provides the
data-shaping helpers so it stays framework-light.
"""

import json
import logging
import os
import re
import unicodedata
from urllib.parse import quote

from flask import request

import state
from channels_io import get_valid_channels
from config import IPTV_PUBLIC_BASE_URL, IPTV_SITE_NAME
from ingest import channel_icon_safe_name, find_local_icon_url, infer_country

# --- SEO / syndication: slug pages, sitemap, RSS, Atom ----------------------------

SEO_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

SEO_RESERVED_SLUGS = frozenset(
    {
        "status",
        "channels",
        "scan",
        "sweep-now",
        "search",
        "download-icons",
        "export",
        "proxy",
        "icons",
        "channel-info",
        "static",
        "api",
        "health",
        "manifest",
        "feed",
        "atom",
        "rss",
        "css",
        "js",
        "fonts",
        "admin",
        "jellyfin",
        "iptv",
        "playlist",
    }
)

_seo_slug_revision = None
_seo_slug_to_channel = {}
_seo_slugs_sorted = []


def seo_slugify_name(name):
    if not name:
        return "channel"
    s = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode("ascii").lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    s = re.sub(r"-{2,}", "-", s)
    return s or "channel"


def seo_refresh_slug_index():
    global _seo_slug_revision, _seo_slug_to_channel, _seo_slugs_sorted
    rev = state.CHANNEL_STATE_REVISION
    if _seo_slug_revision == rev and _seo_slug_to_channel:
        return
    channels = get_valid_channels()
    mapping = {}
    for ch in channels:
        base = seo_slugify_name(ch.get("name", "channel"))
        slug = base
        n = 2
        while slug in mapping or slug in SEO_RESERVED_SLUGS:
            slug = f"{base}-{n}"
            n += 1
        mapping[slug] = ch
    _seo_slug_to_channel = mapping
    _seo_slugs_sorted = sorted(mapping.keys())
    _seo_slug_revision = rev
    logging.info("SEO: rebuilt slug map (%d channels → %d URLs)", len(channels), len(mapping))
    try:
        mp = "jsons/SEO_SLUG_MANIFEST.json"
        out = {"slug_order": _seo_slugs_sorted, "slugs": {s: mapping[s].get("name") for s in _seo_slugs_sorted}}
        tp = f"{mp}.tmp"
        with open(tp, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2, ensure_ascii=False)
        os.replace(tp, mp)
    except Exception as exc:
        logging.debug("SEO manifest write skipped: %s", exc)


def seo_slug_snapshot():
    """Return the current slug mapping and ordered list for route handlers."""
    return _seo_slug_to_channel, _seo_slugs_sorted


def seo_public_base_url():
    if IPTV_PUBLIC_BASE_URL:
        return IPTV_PUBLIC_BASE_URL.rstrip("/")
    return (request.url_root.rstrip("/") if request else "") or "http://127.0.0.1:40006"


def seo_abs_url(path):
    if not path.startswith("/"):
        path = "/" + path
    return seo_public_base_url().rstrip("/") + path


def seo_meta_for_channel(ch):
    name = ch.get("name") or "Channel"
    group = ch.get("group_title") or ""
    country = ch.get("country") or infer_country(ch)
    playing = (ch.get("playing_now") or "").strip() or "Live stream"
    parts = [f"Watch {name} live in your browser.", f"Current listing: {playing}."]
    if group:
        parts.append(f"Category: {group}.")
    if country and str(country).upper() != "GLOBAL":
        parts.append(f"Region: {country}.")
    desc = " ".join(parts)
    if len(desc) > 300:
        desc = desc[:297] + "..."
    return {"name": name, "description": desc, "group": group, "country": country, "playing": playing}


def seo_og_image_for_channel(ch):
    safe = channel_icon_safe_name(ch.get("name", ""))
    local = find_local_icon_url(safe)
    rel = local or ch.get("icon_url") or ch.get("tvg_logo") or ""
    if not rel:
        return ""
    if rel.startswith("http://") or rel.startswith("https://"):
        return rel
    if rel.startswith("/"):
        return seo_abs_url(rel)
    return rel


def _m3u_safe_attr(val):
    if val is None:
        return ""
    return str(val).replace('"', "'").replace("\r", " ").replace("\n", " ").strip()


def build_proxied_live_m3u(
    public_base,
    online_only=False,
    country=None,
    group=None,
    include_test=False,
    media_type="live",
):
    """M3U where every stream URL is this server's /proxy/stream?url=… (Jellyfin / VLC M3U tuner)."""
    base = (public_base or "").rstrip("/")
    lines = ["#EXTM3U"]
    try:
        from db import get_default_store
        result = get_default_store().list_channels(
            page=1,
            limit=100000,
            country=country or None,
            group=group or None,
            include_test=include_test,
            media_type=media_type,
            status="online" if online_only else "online",
        )
        channels = result.get("channels") or []
    except Exception:
        channels = get_valid_channels()
    for ch in channels:
        raw = (ch.get("url") or "").strip()
        if not raw:
            continue
        if not include_test and (ch.get("group_title") or "") == "Test":
            continue
        if country and (ch.get("country") or "").upper() != str(country).upper():
            continue
        if group and (ch.get("group_title") or "") != group:
            continue
        name = (ch.get("name") or "Channel").replace(",", " ").strip() or "Channel"
        name = _m3u_safe_attr(re.sub(r"[\r\n]", " ", name))
        tid = _m3u_safe_attr(ch.get("tvg_id") or seo_slugify_name(ch.get("name", "channel")))
        grp = _m3u_safe_attr(ch.get("group_title") or IPTV_SITE_NAME)
        logo_raw = seo_og_image_for_channel(ch) or ""
        if logo_raw.startswith("/"):
            logo_raw = base + logo_raw
        attrs = [f'tvg-id="{tid}"']
        if logo_raw:
            attrs.append(f'tvg-logo="{_m3u_safe_attr(logo_raw)}"')
        attrs.append(f'group-title="{grp}"')
        lines.append("#EXTINF:-1 " + " ".join(attrs) + f",{name}")
        lines.append(base + "/proxy/stream?url=" + quote(raw, safe=""))
    return "\n".join(lines) + "\n"


def seo_json_ld_broadcast(ch, canonical_url):
    meta = seo_meta_for_channel(ch)
    img = seo_og_image_for_channel(ch)
    stream = (ch.get("url") or "").strip()
    data = {
        "@context": "https://schema.org",
        "@type": "BroadcastService",
        "name": meta["name"],
        "description": meta["description"],
        "url": canonical_url,
        "broadcastDisplayName": meta["name"],
        "inLanguage": (ch.get("audio_language") or "en")[:8],
        "publisher": {"@type": "Organization", "name": IPTV_SITE_NAME},
    }
    if img:
        data["logo"] = img
        data["image"] = img
    data["potentialAction"] = {
        "@type": "WatchAction",
        "target": {"@type": "EntryPoint", "urlTemplate": canonical_url, "actionPlatform": "http://schema.org/DesktopWebPlatform"},
    }
    if stream:
        data["broadcastChannelId"] = ch.get("tvg_id") or meta["name"].lower().replace(" ", "")[:120]
    return json.dumps(data, ensure_ascii=False)
