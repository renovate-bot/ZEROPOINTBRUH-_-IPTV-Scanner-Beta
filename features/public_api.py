"""Public paginated streams API for VRChat, Resonite, Neos VR, ChilloutVR,
Unity, websites, and other HTTP clients.

No API key. Responses are small (50 rows/page) and rate-limited lightly so
worlds/mods cannot hammer the server by skipping pages too quickly.
Every JSON body includes a kind ``support`` reminder.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Optional
from urllib.parse import quote

from flask import Response, jsonify, render_template, request

from config import (
    API_PUBLIC_BURST,
    API_PUBLIC_MIN_INTERVAL_SEC,
    API_PUBLIC_PAGE_SIZE,
    IPTV_SITE_NAME,
    SELF_HOST_REPO,
    SUPPORT_CASHAPP,
    SUPPORT_KOFI,
    SUPPORT_MESSAGE,
    SUPPORT_PAYPAL,
)
from features.public_base import resolve_public_base_url
from features.ingest.ingest import channel_icon_safe_name, find_local_icon_url, infer_country
from features.storage.geo import resolve_country_code


log = logging.getLogger("public_api")

_rate_lock = threading.Lock()
# ip -> {"tokens": float, "updated": float}
_rate_buckets: dict[str, dict[str, float]] = {}


def support_block() -> dict:
    """Kind support reminder included in every public JSON response."""
    return {
        "please_consider_supporting": SUPPORT_MESSAGE,
        "kofi": SUPPORT_KOFI,
        "paypal": SUPPORT_PAYPAL,
        "cashapp": SUPPORT_CASHAPP,
        "self_host": SELF_HOST_REPO,
        "self_host_tree": f"{SELF_HOST_REPO}/tree/main",
    }


def platform_guides() -> list[dict[str, Any]]:
    """Clickable integration guides for /api docs (compliance-minded)."""
    wait = max(1, int(round(API_PUBLIC_MIN_INTERVAL_SEC)) or 2)
    vrc_wait = max(wait, 5)
    page = API_PUBLIC_PAGE_SIZE
    return [
        {
            "id": "vrchat",
            "name": "VRChat",
            "tagline": "Udon String Loading + VRCJson",
            "official": [
                {"label": "String Loading", "url": "https://creators.vrchat.com/worlds/udon/string-loading/"},
                {"label": "VRCJson", "url": "https://creators.vrchat.com/worlds/udon/data-containers/vrcjson/"},
                {"label": "External URLs", "url": "https://creators.vrchat.com/worlds/udon/external-urls/"},
            ],
            "compliance": [
                "Use only official Udon APIs (VRCStringDownloader / DownloadString) — do not bypass VRChat networking.",
                "VRChat allows about one string download every 5 seconds; queue extras. Prefer waiting "
                f"at least {vrc_wait}s between our page calls.",
                "Hosts not on VRChat’s URL allowlist need the user to enable Allow Untrusted URLs.",
                "Follow VRChat Terms of Service and Community Guidelines; video players have separate URL rules.",
                f"Fetch one page at a time (≤{page} streams). Do not hammer next_url in a tight loop.",
            ],
            "steps": [
                f"Create a VRCUrl pointing at {{BASE}}/streams.json (or your public host).",
                "Call VRCStringDownloader.LoadUrl(url, this) from Udon / U#.",
                "On OnStringLoadSuccess, pass Result into VRCJson.TryDeserializeFromJson.",
                "Read streams as a DataList; each item has name, url, logo, group, country, proxy_url.",
                "To load more, read next_url and wait wait_seconds (use ≥5s for VRChat’s own limit).",
                "Play media only through VRChat-approved video player components and allowed stream URLs.",
            ],
            "snippet": "VRCStringDownloader.LoadUrl(streamsUrl, (IUdonEventReceiver)this);\n// OnStringLoadSuccess → VRCJson.TryDeserializeFromJson(result.Result, out token)",
        },
        {
            "id": "resonite",
            "name": "Resonite",
            "tagline": "ProtoFlux GET String + host consent",
            "official": [
                {"label": "GET String", "url": "https://wiki.resonite.com/ProtoFlux:GETString"},
                {"label": "Connecting apps", "url": "https://wiki.resonite.com/Connecting_Resonite_to_other_applications"},
                {"label": "Network nodes", "url": "https://wiki.resonite.com/Category:ProtoFlux:Network"},
            ],
            "compliance": [
                "Always check IsHostAccessAllowedUrl and RequestHostAccessUrl so users consent to your host.",
                "Do not embed credentials in URLs — Resonite HTTP cannot authenticate that way.",
                "Prefer HTTP GET for catalog pulls; use WebSockets only if you truly need realtime.",
                "Respect user privacy and Resonite guidelines; only fetch what your experience needs.",
                f"One page per request (≤{page} items); wait ~{wait}s before the next page.",
            ],
            "steps": [
                "Convert your API URL with String to Absolute URI.",
                "Impulse GET String (or HTTP GET) when a user actually needs the catalog.",
                "On OnResponse, read Content (JSON string) and StatusCode (expect 200; handle 429).",
                "Parse JSON with string tools or a community JSON ProtoFlux library (no built-in arrays).",
                "Use each stream’s url (or proxy_url) with your world’s media playback setup.",
                "Follow next_url / next_page for pagination; never merge pages into one giant spam request.",
            ],
            "snippet": "RequestHostAccessUrl(apiUri) → GETString(apiUri)\nOnResponse → parse Content JSON → read streams[] → wait wait_seconds → next_url",
        },
        {
            "id": "neos-vr",
            "name": "Neos VR",
            "tagline": "LogiX / HTTP GET (legacy worlds)",
            "official": [
                {"label": "Resonite migration notes", "url": "https://wiki.resonite.com/Connecting_Resonite_to_other_applications"},
            ],
            "compliance": [
                "Neos is legacy; prefer Resonite for new work. Same idea: user-consented HTTP GET only.",
                "Do not scrape private APIs or store other users’ credentials.",
                f"Paginate with ≤{page} streams per call and respect wait_seconds.",
            ],
            "steps": [
                "Issue an HTTP GET to /streams.json from LogiX / your bridging tool.",
                "Parse the JSON string for the streams array.",
                "Present channels in-world; load page 2+ only on demand via next_url.",
                "Handle HTTP 429 by waiting retry_after seconds.",
            ],
            "snippet": "HTTP GET {BASE}/streams.json → parse streams → on demand GET next_url",
        },
        {
            "id": "chilloutvr",
            "name": "ChilloutVR",
            "tagline": "Unity / MelonLoader clients",
            "official": [
                {"label": "ChilloutVR", "url": "https://docs.abinteractive.net/"},
            ],
            "compliance": [
                "Follow ABI / ChilloutVR Terms and modding rules for your distribution method.",
                "Do not inject malicious network traffic; only GET our public catalog.",
                "Cache pages locally; refresh on a timer instead of every frame.",
                f"Respect our rate limit (~{wait}s) and platform ToS for media playback.",
            ],
            "steps": [
                "From a CVR mod or Unity component, UnityWebRequest.Get(/streams.json).",
                "JsonUtility / Newtonsoft → read streams[].",
                "Spawn UI entries; play url if your video stack allows it.",
                "When the user pages forward, GET next_url after wait_seconds.",
            ],
            "snippet": "UnityWebRequest.Get(base + \"/streams.json\");\n// parse JSON → streams; delay → /streams2.json",
        },
        {
            "id": "jellyfin",
            "name": "Jellyfin",
            "tagline": "Live TV via M3U playlist",
            "official": [
                {"label": "Jellyfin Live TV", "url": "https://jellyfin.org/docs/general/server/live-tv/"},
                {"label": "M3U tuner", "url": "https://jellyfin.org/docs/general/server/live-tv/setup-guide/"},
            ],
            "compliance": [
                "Use only publicly listed streams you are allowed to redistribute on your server.",
                "Point Jellyfin at our M3U — do not scrape private admin APIs.",
                "Refresh the tuner on a schedule; do not hammer playlist URLs every second.",
            ],
            "steps": [
                "In Jellyfin Dashboard → Live TV → Add tuner → M3U Tuner.",
                "Playlist URL: {BASE}/jellyfin/live.m3u (proxied) or {BASE}/streams.m3u (paged public).",
                "Optional: set IPTV_PUBLIC_BASE_URL so guide links match your domain.",
                "Guide data: set IPTV_XMLTV_URL if you have an XMLTV source, or leave empty.",
                "For very large catalogs prefer /jellyfin/live.m3u (server-built) over walking every /streamsN.m3u page.",
            ],
            "snippet": "Jellyfin → Live TV → M3U Tuner\nFile or URL: {BASE}/jellyfin/live.m3u",
        },
        {
            "id": "plex",
            "name": "Plex",
            "tagline": "Live TV / DVR with M3U (via tuner bridge)",
            "official": [
                {"label": "Plex Live TV & DVR", "url": "https://support.plex.tv/articles/live-tv-dvr-overview/"},
            ],
            "compliance": [
                "Follow Plex Terms and your local broadcast rules.",
                "Plex expects an HDHomeRun-compatible tuner — use Threadfin/xTeVe/Telly in front of our M3U when needed.",
                "Do not flood this API; cache the M3U on the bridge.",
            ],
            "steps": [
                "Run Threadfin, xTeVe, or similar; set the source playlist to {BASE}/jellyfin/live.m3u or {BASE}/streams.m3u.",
                "Expose the bridge as an HDHomeRun device to Plex.",
                "In Plex: Settings → Live TV & DVR → Set Up → pick the bridge tuner.",
                "Map channels once; refresh on a slow timer.",
            ],
            "snippet": "Threadfin/xTeVe source = {BASE}/jellyfin/live.m3u\nPlex Live TV → detect HDHomeRun bridge",
        },
        {
            "id": "emby",
            "name": "Emby",
            "tagline": "Live TV M3U tuner",
            "official": [
                {"label": "Emby Live TV", "url": "https://emby.media/support/articles/Live-TV.html"},
            ],
            "compliance": [
                "Respect Emby licensing for your edition and local content law.",
                "Prefer one M3U URL refresh — not per-channel API spam.",
            ],
            "steps": [
                "Emby Dashboard → Live TV → Tuner → M3U Tuner.",
                "Playlist: {BASE}/jellyfin/live.m3u (works the same as Jellyfin-style M3U).",
                "Save and scan guide data if configured.",
            ],
            "snippet": "Emby → Live TV → M3U → {BASE}/jellyfin/live.m3u",
        },
        {
            "id": "kodi",
            "name": "Kodi",
            "tagline": "PVR IPTV Simple Client",
            "official": [
                {"label": "PVR IPTV Simple Client", "url": "https://kodi.wiki/view/Add-on:PVR_IPTV_Simple_Client"},
            ],
            "compliance": [
                "Use Kodi’s official PVR add-on; keep playlists you are allowed to use.",
                "Set a sensible M3U reload interval (minutes/hours), not continuous polling.",
            ],
            "steps": [
                "Install PVR IPTV Simple Client.",
                "Settings → General → M3U play list path: {BASE}/jellyfin/live.m3u or {BASE}/streams.m3u.",
                "Enable TV section; reload the PVR database after saving.",
            ],
            "snippet": "Kodi → PVR IPTV Simple → M3U URL = {BASE}/jellyfin/live.m3u",
        },
        {
            "id": "roku",
            "name": "Roku TV",
            "tagline": "M3U via channel / media player apps",
            "official": [
                {"label": "Roku developer docs", "url": "https://developer.roku.com/docs/developer-program/getting-started/roku-dev-prog.md"},
            ],
            "compliance": [
                "Follow the Roku Channel Developer Agreement and certification rules for published channels.",
                "Private/sideloaded channels: only load URLs users consent to.",
                "Roku video nodes expect direct media URLs — use stream url fields from M3U/JSON, not browser proxy pages.",
                "Do not bypass Roku DRM or platform security APIs.",
            ],
            "steps": [
                "Easiest path: use an IPTV/M3U Roku channel and paste {BASE}/streams.m3u or {BASE}/jellyfin/live.m3u.",
                "Custom channel (BrightScript): download the M3U or page JSON with roUrlTransfer.",
                "Parse EXTINF / streams[]; feed Video node ContentNode with the stream url.",
                "Paginate JSON with next_url if you build a custom grid; wait wait_seconds between pages.",
                "Prefer direct stream urls on-device; proxy_url is mainly for browsers.",
            ],
            "snippet": "roUrlTransfer → GET {BASE}/streams.m3u\nParse #EXTINF → Video.ContentNode.URL = streamUrl",
        },
        {
            "id": "vlc",
            "name": "VLC",
            "tagline": "Open Network Stream / playlist",
            "official": [
                {"label": "VLC", "url": "https://www.videolan.org/vlc/"},
            ],
            "compliance": [
                "Local playback of public streams only.",
            ],
            "steps": [
                "Media → Open Network Stream → {BASE}/streams.m3u or a single channel url.",
                "Or Media → Open File after saving the M3U locally.",
            ],
            "snippet": "VLC → Open Network Stream → {BASE}/jellyfin/live.m3u",
        },
        {
            "id": "threadfin",
            "name": "Threadfin / xTeVe",
            "tagline": "M3U → HDHomeRun bridge for Plex & friends",
            "official": [
                {"label": "Threadfin", "url": "https://github.com/Threadfin/Threadfin"},
            ],
            "compliance": [
                "Cache playlists; do not refresh from us every few seconds.",
                "One bridge instance can feed Plex/Emby/Jellyfin — share it.",
            ],
            "steps": [
                "Add playlist source: {BASE}/jellyfin/live.m3u.",
                "Map channels; expose HDHomeRun emulator.",
                "Point Plex / Emby / Jellyfin tuner at the bridge.",
            ],
            "snippet": "Threadfin source URL = {BASE}/jellyfin/live.m3u",
        },
        {
            "id": "unity",
            "name": "Unity",
            "tagline": "UnityWebRequest (player, Editor, WebGL)",
            "official": [
                {"label": "UnityWebRequest", "url": "https://docs.unity3d.com/ScriptReference/Networking.UnityWebRequest.html"},
            ],
            "compliance": [
                "Only call public GET endpoints; no scraping of private admin APIs.",
                "On WebGL, rely on our CORS (*); do not disable browser security.",
                f"Page size is {page}; use next_url rather than inventing large limits.",
            ],
            "steps": [
                "UnityWebRequest.Get for /api/v1/streams?page=1 (or /streams.json).",
                "Parse with JsonUtility (wrapper class) or Newtonsoft.Json.",
                "Bind UI / spawn prefabs from streams.",
                "Optional: play via proxy_url if you need same-origin HLS through our proxy.",
            ],
            "snippet": "using var req = UnityWebRequest.Get(baseUrl + \"/streams.json\");\nyield return req.SendWebRequest();",
        },
        {
            "id": "unity-mods",
            "name": "Unity mods",
            "tagline": "BepInEx / MelonLoader / game mods",
            "official": [],
            "compliance": [
                "Obey the host game’s ToS and modding policy.",
                "Do not DDoS this API from many clients — share a local cache when possible.",
                "Keep fetches off the hot path (not every Update tick).",
            ],
            "steps": [
                "Same as Unity: GET JSON pages with HttpClient or UnityWebRequest.",
                "Store last revision; only refresh when revision changes or on a slow timer.",
                "Map streams into your mod’s channel list UI.",
            ],
            "snippet": "HttpClient.GetStringAsync(base + \"/api/v1/streams?page=\" + page)",
        },
        {
            "id": "unreal",
            "name": "Unreal",
            "tagline": "HTTP module + JSON utilities",
            "official": [
                {"label": "HTTP in UE", "url": "https://dev.epicgames.com/documentation/en-us/unreal-engine/API/Runtime/HTTP"},
            ],
            "compliance": [
                "Use Epic’s HTTP module; do not ship secrets in client builds for this public API (none needed).",
                f"Paginate ({page}/page) and honor Retry-After on 429.",
            ],
            "steps": [
                "FHttpModule GET /streams.json.",
                "Deserialize with FJsonSerializer / FJsonObjectConverter.",
                "Drive UMG list from streams; fetch next_url when the user advances.",
            ],
            "snippet": "FHttpModule::Get().CreateRequest() → SetURL(/streams.json) → ProcessRequest()",
        },
        {
            "id": "godot",
            "name": "Godot",
            "tagline": "HTTPRequest node",
            "official": [
                {"label": "HTTPRequest", "url": "https://docs.godotengine.org/en/stable/classes/class_httprequest.html"},
            ],
            "compliance": [
                "Only GET public catalog URLs; cache responses.",
                "Handle 429 and wait retry_after before retrying.",
            ],
            "steps": [
                "HTTPRequest.request(base + \"/streams.json\").",
                "JSON.parse_string(body) → Dictionary → streams Array.",
                "Populate ItemList / buttons; request next_url for page 2+.",
            ],
            "snippet": "$HTTPRequest.request(base + \"/streams.json\")\n# request_completed → JSON.parse_string → data[\"streams\"]",
        },
        {
            "id": "websites",
            "name": "websites",
            "tagline": "Browser fetch / your own site",
            "official": [
                {"label": "Fetch API", "url": "https://developer.mozilla.org/en-US/docs/Web/API/Fetch_API"},
            ],
            "compliance": [
                "CORS is open (*). Still don’t abuse rate limits from many tabs.",
                "If embedding video, respect stream owners and local law; prefer linking out when unsure.",
                "Show attribution / support links if you redistribute the catalog UI.",
            ],
            "steps": [
                "fetch('/streams.json') or your absolute public URL.",
                "const data = await res.json(); render data.streams.",
                "Optional: use proxy_url for HLS in-browser via hls.js.",
                "Paginate with next_url; wait wait_seconds between calls.",
            ],
            "snippet": "const r = await fetch(`${base}/streams.json`);\nconst data = await r.json();\nfor (const s of data.streams) { /* render */ }",
        },
        {
            "id": "http",
            "name": "any HTTP client",
            "tagline": "curl, bots, scripts, IoT",
            "official": [],
            "compliance": [
                "GET only. No API key. Identify your client with a clear User-Agent.",
                f"One page (~{page} rows) per call; sleep wait_seconds between pages.",
                "Back off on HTTP 429 using Retry-After.",
            ],
            "steps": [
                "GET /api/v1 for discovery.",
                "GET /streams.json then follow next_url.",
                "Or GET /api/v1/streams?page=N&country=&group=&q=.",
                "Optional playlist: GET /streams.m3u (same paging as JSON).",
            ],
            "snippet": "curl -sS \"$BASE/streams.json\" | jq '.streams[].name'\ncurl -sS \"$BASE/streams2.m3u\"",
        },
    ]


def supported_platforms() -> list[str]:
    return [g["name"] for g in platform_guides()]


def integrations_map() -> dict[str, str]:
    return {g["id"]: _abs_url(f"/api#integrate-{g['id']}") for g in platform_guides()}


def response_styles() -> dict[str, Any]:
    wait = max(1, int(round(API_PUBLIC_MIN_INTERVAL_SEC)) or 2)
    return {
        "rest_get": {
            "method": "GET",
            "content_type": "application/json",
            "endpoints": [
                "/api/v1",
                "/api/v1/streams?page=1",
                "/streams.json",
                "/streams2.json",
            ],
        },
        "file_style_pages": {
            "description": "One JSON file URL per page (easy for VR string downloaders).",
            "page1": "/streams.json",
            "page_n": "/streams{N}.json",
        },
        "query_style_pages": {
            "description": "Classic REST query pagination with optional filters.",
            "endpoint": "/api/v1/streams?page={N}&country=&group=&q=",
        },
        "m3u_playlist_pages": {
            "description": "Same paging as JSON, but M3U for IPTV players.",
            "page1": "/streams.m3u",
            "page_n": "/streams{N}.m3u",
            "query": "/api/v1/streams.m3u?page={N}",
        },
        "unchecked_directory": {
            "description": (
                "Separate directory for unchecked (pending/unknown) and dead "
                "(offline/error) channels. May not load — report successes."
            ),
            "index": "/unchecked/",
            "all": "/unchecked/all.json",
            "unchecked_only": "/unchecked/streams.json",
            "dead_only": "/unchecked/dead.json",
            "query": "/api/v1/unchecked?page=1&kind=all|unchecked|dead",
            "report_alive": "POST /api/report-alive",
        },
        "cors": {
            "Access-Control-Allow-Origin": "*",
            "methods": ["GET", "OPTIONS", "HEAD"],
        },
        "rate_limit": {
            "wait_seconds": wait,
            "burst": max(1, int(API_PUBLIC_BURST or 3)),
            "on_limit": "HTTP 429 + Retry-After + JSON body",
        },
        "page_size": API_PUBLIC_PAGE_SIZE,
        "auth": "none",
    }


def _attach_support(payload: dict) -> dict:
    out = dict(payload)
    out["support"] = support_block()
    out["works_with"] = supported_platforms()
    out["integrations"] = integrations_map()
    out["response_styles"] = list(response_styles().keys())
    return out


def _client_ip() -> str:
    forwarded = (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
    return forwarded or (request.remote_addr or "unknown")


def _prune_buckets(now: float) -> None:
    stale = [ip for ip, b in _rate_buckets.items() if now - b.get("updated", 0) > 600]
    for ip in stale:
        _rate_buckets.pop(ip, None)


def check_public_rate_limit() -> Optional[Response]:
    """Token-bucket limit. Returns a 429 Response when the client should wait."""
    interval = max(0.5, float(API_PUBLIC_MIN_INTERVAL_SEC or 2.0))
    burst = max(1, int(API_PUBLIC_BURST or 3))
    ip = _client_ip()
    now = time.monotonic()

    with _rate_lock:
        _prune_buckets(now)
        bucket = _rate_buckets.get(ip)
        if not bucket:
            _rate_buckets[ip] = {"tokens": float(burst - 1), "updated": now}
            return None

        elapsed = now - float(bucket.get("updated") or now)
        tokens = float(bucket.get("tokens") or 0) + elapsed / interval
        if tokens > burst:
            tokens = float(burst)

        if tokens < 1.0:
            wait = max(1, int(round((1.0 - tokens) * interval)) or 1)
            bucket["updated"] = now
            bucket["tokens"] = tokens
            body = _attach_support({
                "ok": False,
                "error": "rate_limited",
                "message": (
                    f"Please wait a few seconds - you are making too many requests. "
                    f"Try again in about {wait} second{'s' if wait != 1 else ''}."
                ),
                "retry_after": wait,
                "wait_seconds": wait,
            })
            resp = Response(
                json.dumps(body, ensure_ascii=False),
                status=429,
                mimetype="application/json; charset=utf-8",
            )
            resp.headers["Retry-After"] = str(wait)
            resp.headers["Access-Control-Allow-Origin"] = "*"
            resp.headers["Cache-Control"] = "no-store"
            resp.headers["X-Support-Ko-fi"] = SUPPORT_KOFI
            return resp

        bucket["tokens"] = tokens - 1.0
        bucket["updated"] = now
        return None


def _public_base() -> str:
    return resolve_public_base_url()


def _abs_url(path: str) -> str:
    base = _public_base()
    if not path.startswith("/"):
        path = "/" + path
    if not base:
        return path
    return base + path


UNCHECKED_STATUSES = ("pending", "unknown")
DEAD_PUBLIC_STATUSES = ("offline", "error")
UNVERIFIED_WARNING = (
    "WARNING: Channels in this directory are unchecked or previously dead and may not load. "
    "If a stream plays successfully, POST /api/report-alive with {\"url\": \"...\"} "
    "so we promote it and run a priority health check."
)


def streams_page_path(page: int) -> str:
    page = max(1, int(page))
    if page <= 1:
        return "/streams.json"
    return f"/streams{page}.json"


def unchecked_page_path(page: int, *, kind: str = "all") -> str:
    """Paths under the /unchecked/ directory (separate from live streams)."""
    page = max(1, int(page))
    kind = (kind or "all").lower()
    if kind not in ("all", "unchecked", "dead"):
        kind = "all"
    if kind == "all":
        base = "/unchecked/all"
    elif kind == "dead":
        base = "/unchecked/dead"
    else:
        base = "/unchecked/streams"
    if page <= 1:
        return f"{base}.json"
    return f"{base}{page}.json"


def serialize_public_stream(channel: dict, *, include_proxy: bool = True) -> dict:
    """Flat, engine-friendly channel object (VRChat / Unity / Unreal / etc.)."""
    name = (channel.get("name") or "Untitled").strip() or "Untitled"
    url = (channel.get("url") or "").strip()
    country = resolve_country_code(channel) or channel.get("country") or infer_country(channel) or "GLOBAL"
    if isinstance(country, str):
        country = country.strip().upper() or "GLOBAL"
    if country == "UK":
        country = "GB"

    logo = (channel.get("icon_url") or channel.get("tvg_logo") or "").strip()
    if not logo:
        local = find_local_icon_url(channel_icon_safe_name(name))
        if local:
            logo = _abs_url(local) if local.startswith("/") else local
    elif logo.startswith("/"):
        logo = _abs_url(logo)

    row = {
        "name": name,
        "url": url,
        "logo": logo or "",
        "group": (channel.get("group_title") or "").strip(),
        "country": country,
        "status": (channel.get("status") or "online").lower(),
        "media_type": (channel.get("media_type") or "live").lower(),
    }
    if include_proxy and url:
        row["proxy_url"] = _abs_url("/proxy/stream?url=" + quote(url, safe=""))
    return row


def build_streams_page(
    page: int = 1,
    *,
    per_page: int = API_PUBLIC_PAGE_SIZE,
    country: Optional[str] = None,
    group: Optional[str] = None,
    q: Optional[str] = None,
    catalog: str = "online",
) -> dict[str, Any]:
    """Paginated public catalog.

    ``catalog``:
      * ``online`` — verified live list (default ``/streams.json``)
      * ``unchecked`` — pending / unknown (never confirmed)
      * ``dead`` — offline / error
      * ``all_unverified`` — unchecked + dead (full ``/unchecked/`` directory)
    """
    from features.storage.db import get_default_store

    page = max(1, int(page or 1))
    per_page = max(1, min(int(per_page or API_PUBLIC_PAGE_SIZE), API_PUBLIC_PAGE_SIZE))
    catalog = (catalog or "online").lower().strip()

    status = None
    status_in = None
    path_kind = "online"
    if catalog in ("online", "live"):
        status = "online"
        path_kind = "online"
    elif catalog in ("unchecked", "pending"):
        status_in = UNCHECKED_STATUSES
        path_kind = "unchecked"
    elif catalog in ("dead", "offline"):
        status_in = DEAD_PUBLIC_STATUSES
        path_kind = "dead"
    elif catalog in ("all_unverified", "unverified", "all"):
        status_in = UNCHECKED_STATUSES + DEAD_PUBLIC_STATUSES
        path_kind = "all"
    else:
        status = "online"
        path_kind = "online"

    store = get_default_store()
    result = store.list_channels(
        page=page,
        limit=per_page,
        q=(q or None),
        group=(group or None),
        country=(country or None),
        include_test=False,
        media_type="live",
        status=status,
        status_in=status_in,
        sort="name",
        sort_dir="asc",
    )
    channels = result.get("channels") or []
    streams = [serialize_public_stream(ch) for ch in channels]

    total = int(result.get("total") or 0)
    total_pages = int(result.get("total_pages") or 1) or 1
    has_more = bool(result.get("has_more"))
    wait = max(1, int(round(API_PUBLIC_MIN_INTERVAL_SEC)) or 2)

    next_page = page + 1 if has_more and page < total_pages else None
    prev_page = page - 1 if page > 1 else None

    if path_kind == "online":
        self_path = streams_page_path(page)
        next_path = streams_page_path(next_page) if next_page else None
        prev_path = streams_page_path(prev_page) if prev_page else None
    else:
        self_path = unchecked_page_path(page, kind=path_kind)
        next_path = unchecked_page_path(next_page, kind=path_kind) if next_page else None
        prev_path = unchecked_page_path(prev_page, kind=path_kind) if prev_page else None

    payload: dict[str, Any] = {
        "ok": True,
        "api": "iptv-scanner-public/v1",
        "site": IPTV_SITE_NAME,
        "catalog": path_kind if path_kind != "all" else "all_unverified",
        "directory": "live" if path_kind == "online" else "unchecked",
        "page": page,
        "per_page": per_page,
        "total": total,
        "total_pages": total_pages,
        "has_more": has_more,
        "next_page": next_page,
        "prev_page": prev_page,
        "next_url": _abs_url(next_path) if next_path else None,
        "prev_url": _abs_url(prev_path) if prev_path else None,
        "self_url": _abs_url(self_path),
        "revision": int(result.get("revision") or store.get_revision() or 0),
        "wait_seconds": wait,
        "offset": (page - 1) * per_page,
        "count": len(streams),
        "streams": streams,
        "report_alive_url": _abs_url("/api/report-alive"),
    }
    if path_kind != "online":
        payload["warning"] = UNVERIFIED_WARNING
        payload["may_not_load"] = True
        payload["on_success"] = (
            "If playback works, POST JSON {\"url\": \"<stream url>\"} to report_alive_url. "
            "We mark it online and queue a priority health check."
        )
    return _attach_support(payload)


def streams_m3u_path(page: int) -> str:
    page = max(1, int(page))
    if page <= 1:
        return "/streams.m3u"
    return f"/streams{page}.m3u"


def build_streams_m3u(page: int = 1, **filters) -> tuple[str, dict]:
    """Return (m3u_body, meta_payload) for one page."""
    payload = build_streams_page(page, **filters)
    lines = [
        "#EXTM3U",
        f"#IPTV-SCANNER:page={payload.get('page')} per_page={payload.get('per_page')} "
        f"total={payload.get('total')} wait_seconds={payload.get('wait_seconds')} "
        f"catalog={payload.get('catalog')}",
        f"#IPTV-SCANNER-SUPPORT:{SUPPORT_MESSAGE}",
        f"#IPTV-SCANNER-KOFI:{SUPPORT_KOFI}",
    ]
    if payload.get("warning"):
        lines.append(f"#IPTV-SCANNER-WARNING:{payload['warning']}")
        lines.append("#IPTV-SCANNER-REPORT-ALIVE:/api/report-alive")
    for s in payload.get("streams") or []:
        name = (s.get("name") or "Channel").replace("\n", " ").strip()
        logo = (s.get("logo") or "").replace('"', "")
        group = (s.get("group") or "").replace('"', "")
        country = (s.get("country") or "").replace('"', "")
        url = (s.get("url") or "").strip()
        if not url:
            continue
        attrs = [f'tvg-name="{name}"']
        if logo:
            attrs.append(f'tvg-logo="{logo}"')
        if country:
            attrs.append(f'tvg-country="{country}"')
        if group:
            attrs.append(f'group-title="{group}"')
        lines.append(f"#EXTINF:-1 {' '.join(attrs)},{name}")
        lines.append(url)
    if payload.get("next_url"):
        # Hint for clients that understand comments (JSON next stays authoritative).
        next_m3u = streams_m3u_path(int(payload["next_page"]))
        lines.append(f"#IPTV-SCANNER-NEXT:{_abs_url(next_m3u)}")
    body = "\n".join(lines) + "\n"
    return body, payload


def json_response(payload: dict, *, status: int = 200) -> Response:
    data = payload if "support" in payload else _attach_support(payload)
    body = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    resp = Response(body, status=status, mimetype="application/json; charset=utf-8")
    _apply_cors_headers(resp)
    resp.headers["Cache-Control"] = "public, max-age=15"
    resp.headers["X-Support-Message"] = SUPPORT_MESSAGE
    resp.headers["X-Support-Ko-fi"] = SUPPORT_KOFI
    if status == 429 and isinstance(data.get("retry_after"), int):
        resp.headers["Retry-After"] = str(data["retry_after"])
        resp.headers["Cache-Control"] = "no-store"
    return resp


def m3u_response(body: str, *, filename: str = "streams.m3u") -> Response:
    resp = Response(body, status=200, mimetype="application/vnd.apple.mpegurl; charset=utf-8")
    _apply_cors_headers(resp)
    resp.headers["Cache-Control"] = "public, max-age=15"
    resp.headers["Content-Disposition"] = f'inline; filename="{filename}"'
    resp.headers["X-Support-Message"] = SUPPORT_MESSAGE
    resp.headers["X-Support-Ko-fi"] = SUPPORT_KOFI
    return resp


def _apply_cors_headers(resp: Response) -> None:
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, HEAD, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Accept"


def _cors_preflight() -> Response:
    resp = Response(status=204)
    _apply_cors_headers(resp)
    return resp


def _prepare_guides_for_template(base: str) -> list[dict]:
    host = base.rstrip("/") if base else "https://YOUR-HOST"
    guides = []
    for raw in platform_guides():
        g = dict(raw)
        g["steps"] = [str(s).replace("{BASE}", host) for s in (g.get("steps") or [])]
        g["snippet"] = str(g.get("snippet") or "").replace("{BASE}", host)
        guides.append(g)
    return guides


def register_public_api(app) -> None:
    """Attach public API routes to the Flask app."""

    @app.route("/api")
    @app.route("/api/")
    def public_api_docs():
        base = _public_base() or ""
        return render_template(
            "api_docs.html",
            site_name=IPTV_SITE_NAME,
            base_url=base,
            page_size=API_PUBLIC_PAGE_SIZE,
            wait_seconds=max(1, int(round(API_PUBLIC_MIN_INTERVAL_SEC)) or 2),
            burst=max(1, int(API_PUBLIC_BURST or 3)),
            support_message=SUPPORT_MESSAGE,
            support_kofi=SUPPORT_KOFI,
            support_paypal=SUPPORT_PAYPAL,
            support_cashapp=SUPPORT_CASHAPP,
            works_with=supported_platforms(),
            platforms=_prepare_guides_for_template(base),
            styles=response_styles(),
            self_host_repo=SELF_HOST_REPO,
            self_host_tree=f"{SELF_HOST_REPO}/tree/main",
        )

    def _serve_streams_json(page: int = 1):
        if request.method == "OPTIONS":
            return _cors_preflight()
        if request.method == "HEAD":
            limited = check_public_rate_limit()
            if limited is not None:
                return limited
            resp = Response(status=200, mimetype="application/json; charset=utf-8")
            _apply_cors_headers(resp)
            return resp
        limited = check_public_rate_limit()
        if limited is not None:
            return limited
        if page < 1:
            page = 1
        return json_response(build_streams_page(page))

    @app.route("/streams.json", methods=["GET", "HEAD", "OPTIONS"])
    @app.route("/streams<int:page>.json", methods=["GET", "HEAD", "OPTIONS"])
    def public_streams_file(page: int = 1):
        return _serve_streams_json(page)

    def _serve_streams_m3u(page: int = 1, **filters):
        if request.method == "OPTIONS":
            return _cors_preflight()
        limited = check_public_rate_limit()
        if limited is not None:
            return limited
        if page < 1:
            page = 1
        body, payload = build_streams_m3u(page, **filters)
        fname = "streams.m3u" if page <= 1 else f"streams{page}.m3u"
        resp = m3u_response(body, filename=fname)
        if payload.get("next_page"):
            resp.headers["X-Next-Page"] = str(payload["next_page"])
            resp.headers["Link"] = f'<{_abs_url(streams_m3u_path(payload["next_page"]))}>; rel="next"'
        return resp

    @app.route("/streams.m3u", methods=["GET", "HEAD", "OPTIONS"])
    @app.route("/streams<int:page>.m3u", methods=["GET", "HEAD", "OPTIONS"])
    def public_streams_m3u_file(page: int = 1):
        if request.method == "HEAD":
            limited = check_public_rate_limit()
            if limited is not None:
                return limited
            resp = Response(status=200, mimetype="application/vnd.apple.mpegurl")
            _apply_cors_headers(resp)
            return resp
        return _serve_streams_m3u(page)

    @app.route("/unchecked/", methods=["GET", "HEAD", "OPTIONS"])
    @app.route("/unchecked", methods=["GET", "HEAD", "OPTIONS"])
    def public_unchecked_index():
        if request.method == "OPTIONS":
            return _cors_preflight()
        wait = max(1, int(round(API_PUBLIC_MIN_INTERVAL_SEC)) or 2)
        return json_response(
            {
                "ok": True,
                "directory": "unchecked",
                "warning": UNVERIFIED_WARNING,
                "may_not_load": True,
                "docs": _abs_url("/api#unchecked"),
                "report_alive_url": _abs_url("/api/report-alive"),
                "on_success": (
                    "If a stream from this directory plays, POST {\"url\": \"...\"} to "
                    "report_alive_url so we promote it and run a priority health check."
                ),
                "endpoints": {
                    "all_unverified": _abs_url("/unchecked/all.json"),
                    "unchecked_only": _abs_url("/unchecked/streams.json"),
                    "dead_only": _abs_url("/unchecked/dead.json"),
                    "query": _abs_url("/api/v1/unchecked?page=1&kind=all"),
                },
                "kinds": {
                    "all": "pending + unknown + offline + error",
                    "unchecked": "pending + unknown (not yet confirmed)",
                    "dead": "offline + error (previously failed)",
                },
                "wait_seconds": wait,
                "page_size": API_PUBLIC_PAGE_SIZE,
                "rate_limit": {
                    "same_as_live": True,
                    "wait_seconds": wait,
                    "burst": max(1, int(API_PUBLIC_BURST or 3)),
                    "page_size": API_PUBLIC_PAGE_SIZE,
                },
            }
        )

    def _serve_unchecked_json(page: int = 1, *, catalog: str = "all_unverified"):
        if request.method == "OPTIONS":
            return _cors_preflight()
        if request.method == "HEAD":
            limited = check_public_rate_limit()
            if limited is not None:
                return limited
            resp = Response(status=200, mimetype="application/json; charset=utf-8")
            _apply_cors_headers(resp)
            return resp
        limited = check_public_rate_limit()
        if limited is not None:
            return limited
        if page < 1:
            page = 1
        return json_response(build_streams_page(page, catalog=catalog))

    @app.route("/unchecked/all.json", methods=["GET", "HEAD", "OPTIONS"])
    @app.route("/unchecked/all<int:page>.json", methods=["GET", "HEAD", "OPTIONS"])
    def public_unchecked_all(page: int = 1):
        return _serve_unchecked_json(page, catalog="all_unverified")

    @app.route("/unchecked/streams.json", methods=["GET", "HEAD", "OPTIONS"])
    @app.route("/unchecked/streams<int:page>.json", methods=["GET", "HEAD", "OPTIONS"])
    def public_unchecked_streams(page: int = 1):
        return _serve_unchecked_json(page, catalog="unchecked")

    @app.route("/unchecked/dead.json", methods=["GET", "HEAD", "OPTIONS"])
    @app.route("/unchecked/dead<int:page>.json", methods=["GET", "HEAD", "OPTIONS"])
    def public_unchecked_dead(page: int = 1):
        return _serve_unchecked_json(page, catalog="dead")

    @app.route("/api/v1/unchecked", methods=["GET", "HEAD", "OPTIONS"])
    def public_unchecked_query():
        if request.method == "OPTIONS":
            return _cors_preflight()
        if request.method == "HEAD":
            limited = check_public_rate_limit()
            if limited is not None:
                return limited
            resp = Response(status=200, mimetype="application/json; charset=utf-8")
            _apply_cors_headers(resp)
            return resp
        limited = check_public_rate_limit()
        if limited is not None:
            return limited
        try:
            page = max(1, int(request.args.get("page", 1) or 1))
        except (TypeError, ValueError):
            page = 1
        kind = (request.args.get("kind") or "all").strip().lower()
        catalog = {
            "all": "all_unverified",
            "unverified": "all_unverified",
            "unchecked": "unchecked",
            "pending": "unchecked",
            "dead": "dead",
            "offline": "dead",
        }.get(kind, "all_unverified")
        country = (request.args.get("country") or "").strip() or None
        group = (request.args.get("group") or "").strip() or None
        q = (request.args.get("q") or request.args.get("search") or "").strip() or None
        payload = build_streams_page(
            page, country=country, group=group, q=q, catalog=catalog
        )
        if payload.get("next_page"):
            qs = [f"page={payload['next_page']}", f"kind={kind}"]
            if country:
                qs.append("country=" + quote(country))
            if group:
                qs.append("group=" + quote(group))
            if q:
                qs.append("q=" + quote(q))
            payload["next_query_url"] = _abs_url("/api/v1/unchecked?" + "&".join(qs))
        return json_response(payload)

    @app.route("/api/v1/streams", methods=["GET", "HEAD", "OPTIONS"])
    def public_streams_query():
        if request.method == "OPTIONS":
            return _cors_preflight()
        if request.method == "HEAD":
            limited = check_public_rate_limit()
            if limited is not None:
                return limited
            resp = Response(status=200, mimetype="application/json; charset=utf-8")
            _apply_cors_headers(resp)
            return resp

        limited = check_public_rate_limit()
        if limited is not None:
            return limited

        try:
            page = max(1, int(request.args.get("page", 1) or 1))
        except (TypeError, ValueError):
            page = 1
        country = (request.args.get("country") or "").strip() or None
        group = (request.args.get("group") or "").strip() or None
        q = (request.args.get("q") or request.args.get("search") or "").strip() or None
        payload = build_streams_page(page, country=country, group=group, q=q)
        if payload.get("next_page"):
            qs = [f"page={payload['next_page']}"]
            if country:
                qs.append("country=" + quote(country))
            if group:
                qs.append("group=" + quote(group))
            if q:
                qs.append("q=" + quote(q))
            payload["next_query_url"] = _abs_url("/api/v1/streams?" + "&".join(qs))
        return json_response(payload)

    @app.route("/api/v1/streams.m3u", methods=["GET", "HEAD", "OPTIONS"])
    def public_streams_m3u_query():
        if request.method == "OPTIONS":
            return _cors_preflight()
        try:
            page = max(1, int(request.args.get("page", 1) or 1))
        except (TypeError, ValueError):
            page = 1
        country = (request.args.get("country") or "").strip() or None
        group = (request.args.get("group") or "").strip() or None
        q = (request.args.get("q") or request.args.get("search") or "").strip() or None
        if request.method == "HEAD":
            limited = check_public_rate_limit()
            if limited is not None:
                return limited
            resp = Response(status=200, mimetype="application/vnd.apple.mpegurl")
            _apply_cors_headers(resp)
            return resp
        return _serve_streams_m3u(page, country=country, group=group, q=q)

    @app.route("/api/v1", methods=["GET", "HEAD", "OPTIONS"])
    @app.route("/api/v1/", methods=["GET", "HEAD", "OPTIONS"])
    def public_api_v1_index():
        if request.method == "OPTIONS":
            return _cors_preflight()
        wait = max(1, int(round(API_PUBLIC_MIN_INTERVAL_SEC)) or 2)
        styles = response_styles()
        return json_response(
            {
                "ok": True,
                "api": "iptv-scanner-public/v1",
                "docs": _abs_url("/api"),
                "endpoints": {
                    "streams_page1_json": _abs_url("/streams.json"),
                    "streams_page_n_json": _abs_url("/streams2.json"),
                    "streams_query_json": _abs_url("/api/v1/streams?page=1"),
                    "streams_page1_m3u": _abs_url("/streams.m3u"),
                    "streams_page_n_m3u": _abs_url("/streams2.m3u"),
                    "streams_query_m3u": _abs_url("/api/v1/streams.m3u?page=1"),
                    "unchecked_directory": _abs_url("/unchecked/"),
                    "unchecked_all": _abs_url("/unchecked/all.json"),
                    "unchecked_only": _abs_url("/unchecked/streams.json"),
                    "dead_only": _abs_url("/unchecked/dead.json"),
                    "unchecked_query": _abs_url("/api/v1/unchecked?page=1&kind=all"),
                    "report_alive": _abs_url("/api/report-alive"),
                },
                "response_styles": styles,
                "integrations": integrations_map(),
                "page_size": API_PUBLIC_PAGE_SIZE,
                "wait_seconds": wait,
                "auth": "none",
                "methods": ["GET", "HEAD", "OPTIONS", "POST (report-alive only)"],
                "notes": [
                    "No API key required.",
                    f"Each page returns at most {API_PUBLIC_PAGE_SIZE} streams (page N is a separate slice, not cumulative).",
                    f"Fetch at most one page every ~{wait}s to avoid rate limits.",
                    "Use next_url from each JSON response (or Link / X-Next-Page on M3U) to walk pages.",
                    "Live catalog: /streams.json. Unchecked/dead catalog: /unchecked/ (may not load).",
                    "If an unchecked/dead stream plays, POST /api/report-alive to prioritize a health check.",
                    "Open /api and click a platform chip for compliance-friendly integration steps.",
                    SUPPORT_MESSAGE,
                ],
            }
        )
