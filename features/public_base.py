"""Resolve the public site base URL from env, the live request, or last-seen host.

Priority
--------
1. ``IPTV_PUBLIC_BASE_URL`` (explicit override)
2. Current request host (``domain.tld`` or ``ip:port``, respecting
   ``X-Forwarded-Host`` / ``X-Forwarded-Proto`` behind a reverse proxy)
3. Last learned non-empty host from earlier requests
4. Local fallback ``http://127.0.0.1:<port>``
"""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlparse

import state
from config import IPTV_PORT, IPTV_PUBLIC_BASE_URL


_LOOPBACK = {"127.0.0.1", "localhost", "::1", "0.0.0.0"}
_IPV4 = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")


def _host_rank(base: str) -> int:
    """Higher is better for remembering a default: domain > ip > loopback."""
    try:
        host = (urlparse(base).hostname or "").lower()
    except Exception:
        return -1
    if not host or host in _LOOPBACK:
        return 0
    if _IPV4.match(host) or ":" in host:
        return 1
    return 2


def detect_request_base() -> str:
    """Build ``scheme://host[:port]`` from the active Flask request."""
    try:
        from flask import has_request_context, request
    except Exception:
        return ""
    if not has_request_context():
        return ""

    host = (request.headers.get("X-Forwarded-Host") or request.host or "").split(",")[0].strip()
    if not host:
        return ""
    proto = (
        request.headers.get("X-Forwarded-Proto")
        or request.headers.get("X-Forwarded-Scheme")
        or request.scheme
        or "http"
    ).split(",")[0].strip() or "http"
    return f"{proto}://{host}".rstrip("/")


def remember_public_base(base: str) -> None:
    """Keep the best-seen caller host for absolute URLs outside a request."""
    base = (base or "").strip().rstrip("/")
    if not base:
        return
    current = (state.LEARNED_PUBLIC_BASE or "").strip().rstrip("/")
    if not current or _host_rank(base) >= _host_rank(current):
        state.LEARNED_PUBLIC_BASE = base


def resolve_public_base_url(*, fallback: Optional[str] = None) -> str:
    """Return the site base URL callers should see in links / API payloads."""
    if IPTV_PUBLIC_BASE_URL:
        return IPTV_PUBLIC_BASE_URL.rstrip("/")

    detected = detect_request_base()
    if detected:
        remember_public_base(detected)
        return detected

    learned = (state.LEARNED_PUBLIC_BASE or "").strip().rstrip("/")
    if learned:
        return learned

    if fallback:
        return fallback.rstrip("/")
    return f"http://127.0.0.1:{IPTV_PORT}"


def register_public_base_hooks(app) -> None:
    """Learn the caller host on every HTTP request."""

    @app.before_request
    def _learn_public_base_from_request():  # noqa: ANN202
        detected = detect_request_base()
        if detected:
            remember_public_base(detected)
