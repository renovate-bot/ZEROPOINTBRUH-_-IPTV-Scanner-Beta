"""Static configuration for IPTV Scanner (constants, env-derived settings, shared lock)."""

import os
import threading


BATCH_SIZE = 10  # number of channels to process in each batch.

FILES = {
    "streams": 'jsons/IPTV_STREAMS_FILE.json',
    "dead": 'jsons/DEAD_STREAMS_FILE.json',
    "invalid": 'jsons/INVALID_LINKS_FILE.json',
    "master": 'jsons/MASTER_CACHE_FILE.json',
}

DIRECTORIES = ['webroot', 'webroot/js']

WRITE_LOCK = threading.Lock()

SWEEP_INTERVAL_SEC = int(os.environ.get("IPTV_SWEEP_INTERVAL_SEC", str(45 * 60)))
MAX_EXPANSION_DEPTH = int(os.environ.get("IPTV_MAX_EXPANSION_DEPTH", "2"))
MAX_VARIANTS_PER_CHANNEL = int(os.environ.get("IPTV_MAX_VARIANTS_PER_CHANNEL", "8"))
SCRAPE_VARIANT_MODE = os.environ.get("IPTV_VARIANT_MODE", "all_variants").lower()
EXTRA_M3U_URLS_ENV = os.environ.get("IPTV_EXTRA_M3U_URLS", "")
IPTV_PUBLIC_BASE_URL = os.environ.get("IPTV_PUBLIC_BASE_URL", "").strip().rstrip("/")
IPTV_SITE_NAME = os.environ.get("IPTV_SITE_NAME", "IPTV Scanner").strip() or "IPTV Scanner"
# Optional: require ?token=SECRET on /jellyfin/live.m3u and friends when set.
IPTV_PLAYLIST_SECRET = os.environ.get("IPTV_PLAYLIST_SECRET", "").strip()
# Fetch every playlist URL during M3U ingest to expand master manifests (very slow; default off).
EXPAND_ON_INGEST = os.environ.get("IPTV_EXPAND_ON_INGEST", "0").strip().lower() in (
    "1", "true", "yes", "on",
)

# Phase 2: SQLite storage + network binding + XMLTV + checker cadence.
IPTV_DB_PATH = os.environ.get("IPTV_DB_PATH", os.path.join("data", "iptv.db"))
IPTV_BIND_HOST = os.environ.get("IPTV_BIND_HOST", "0.0.0.0").strip() or "0.0.0.0"
try:
    IPTV_PORT = int(os.environ.get("IPTV_PORT", "40006"))
except (TypeError, ValueError):
    IPTV_PORT = 40006
IPTV_XMLTV_URL = os.environ.get("IPTV_XMLTV_URL", "").strip()
try:
    IPTV_ACTIVE_CHECK_INTERVAL_SEC = int(
        os.environ.get("IPTV_ACTIVE_CHECK_INTERVAL_SEC", str(15 * 60))
    )
except (TypeError, ValueError):
    IPTV_ACTIVE_CHECK_INTERVAL_SEC = 15 * 60
try:
    IPTV_DEAD_CHECK_INTERVAL_SEC = int(
        os.environ.get("IPTV_DEAD_CHECK_INTERVAL_SEC", str(6 * 60 * 60))
    )
except (TypeError, ValueError):
    IPTV_DEAD_CHECK_INTERVAL_SEC = 6 * 60 * 60

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Cache-Control": "max-age=0",
}
