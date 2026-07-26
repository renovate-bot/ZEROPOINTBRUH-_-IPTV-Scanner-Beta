"""SQLite-backed storage for IPTV Scanner Phase 2.

The legacy pipeline persisted every scan into a handful of large JSON files
under ``jsons/``. That worked but forced the whole channel list to be rewritten
on every mutation, and cross-worker coordination required a global write lock.

Phase 2 replaces those files with a WAL-mode SQLite database managed by the
:class:`ChannelStore` here. All read and write paths go through this store so
the checker workers, ingest task and Flask routes see a consistent view.

The module exposes:

* :func:`ensure_db` — idempotent factory that creates the schema, applies
  indexes, runs a one-shot JSON import if the ``channels`` table is empty, and
  returns a ready-to-use :class:`ChannelStore` bound to the target file.
* :class:`ChannelStore` — thread-safe wrapper around ``sqlite3.Connection``
  with high-level helpers (``list_channels``, ``upsert_from_ingest``, etc.).
* Small CLI (``python -m features.storage.db`` / ``python -m features.storage.db backup``).
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import shutil
import sqlite3
import sys
import threading
import time
from typing import Any, Iterable, Optional, Sequence

from .normalize import (
    classify_media_type,
    coerce_dict,
    is_test_channel,
    normalize_channel,
    normalize_group_title,
    normalize_url,
)


logger = logging.getLogger(__name__)


DEFAULT_DB_PATH = os.environ.get("IPTV_DB_PATH", os.path.join("data", "iptv.db"))
LEGACY_JSON_DIR = "jsons"
LEGACY_JSON_FILES = {
    "streams": os.path.join(LEGACY_JSON_DIR, "IPTV_STREAMS_FILE.json"),
    "dead": os.path.join(LEGACY_JSON_DIR, "DEAD_STREAMS_FILE.json"),
    "invalid": os.path.join(LEGACY_JSON_DIR, "INVALID_LINKS_FILE.json"),
    "master": os.path.join(LEGACY_JSON_DIR, "MASTER_CACHE_FILE.json"),
    "slugs": os.path.join(LEGACY_JSON_DIR, "SEO_SLUG_MANIFEST.json"),
}

VALID_STATUSES = frozenset({"online", "offline", "pending", "unknown", "error"})
VALID_MEDIA_TYPES = frozenset({"live", "vod", "unknown"})

_SORT_COLUMNS = {
    "name": "name COLLATE NOCASE",
    "group": "group_title COLLATE NOCASE",
    "group_title": "group_title COLLATE NOCASE",
    "country": "country COLLATE NOCASE",
    "status": "status",
    "media_type": "media_type",
    "last_checked_at": "last_checked_at",
    "updated_at": "updated_at",
    "url": "url",
    "fail_count": "fail_count",
    "trending": "trend_score",
    "popular": "trend_score",
    "trend_score": "trend_score",
    "watch_count": "watch_count",
    "last_watched_at": "last_watched_at",
    "variant_quality": "variant_quality COLLATE NOCASE",
    "variant_bandwidth": "variant_bandwidth",
}

# Exponential half-life for trending popularity (hours).
TREND_HALF_LIFE_HOURS = 6.0
# Ignore repeat plays of the same URL within this window.
WATCH_MIN_INTERVAL_SEC = 120.0
# Drop raw watch events older than this.
WATCH_PRUNE_DAYS = 30


SCHEMA_STATEMENTS: Sequence[str] = (
    """
    CREATE TABLE IF NOT EXISTS channels (
        url               TEXT PRIMARY KEY,
        url_norm          TEXT UNIQUE,
        name              TEXT,
        tvg_id            TEXT,
        tvg_logo          TEXT,
        group_title       TEXT,
        playing_now       TEXT,
        status            TEXT DEFAULT 'unknown',
        country           TEXT,
        icon_url          TEXT,
        audio_language    TEXT,
        variant_of        TEXT,
        media_type        TEXT DEFAULT 'unknown',
        fail_reason       TEXT,
        fail_count        INTEGER DEFAULT 0,
        last_checked_at   REAL,
        updated_at        REAL,
        variant_quality   TEXT,
        variant_bandwidth INTEGER,
        trend_score       REAL DEFAULT 0,
        watch_count       INTEGER DEFAULT 0,
        last_watched_at   REAL,
        trend_updated_at  REAL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS channel_variants (
        variant_url    TEXT PRIMARY KEY,
        channel_url    TEXT NOT NULL,
        resolution     TEXT,
        bandwidth      INTEGER,
        codecs         TEXT,
        audio_language TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS invalid_links (
        url        TEXT PRIMARY KEY,
        created_at REAL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS seo_slugs (
        slug         TEXT PRIMARY KEY,
        channel_url  TEXT,
        channel_name TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS meta (
        key   TEXT PRIMARY KEY,
        value TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS playlist_queue (
        url        TEXT PRIMARY KEY,
        depth      INTEGER DEFAULT 0,
        created_at REAL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS channel_watches (
        url         TEXT NOT NULL,
        watched_at  REAL NOT NULL
    )
    """,
)

INDEX_STATEMENTS: Sequence[str] = (
    "CREATE INDEX IF NOT EXISTS idx_channels_status ON channels(status)",
    "CREATE INDEX IF NOT EXISTS idx_channels_group_title ON channels(group_title)",
    "CREATE INDEX IF NOT EXISTS idx_channels_country ON channels(country)",
    "CREATE INDEX IF NOT EXISTS idx_channels_media_type ON channels(media_type)",
    "CREATE INDEX IF NOT EXISTS idx_channels_last_checked_at ON channels(last_checked_at)",
    "CREATE INDEX IF NOT EXISTS idx_channels_url_norm ON channels(url_norm)",
    "CREATE INDEX IF NOT EXISTS idx_channels_variant_of ON channels(variant_of)",
    "CREATE INDEX IF NOT EXISTS idx_channels_trend_score ON channels(trend_score)",
    "CREATE INDEX IF NOT EXISTS idx_variants_channel_url ON channel_variants(channel_url)",
    "CREATE INDEX IF NOT EXISTS idx_seo_slugs_channel_url ON seo_slugs(channel_url)",
    "CREATE INDEX IF NOT EXISTS idx_playlist_queue_depth ON playlist_queue(depth)",
    "CREATE INDEX IF NOT EXISTS idx_channel_watches_watched_at ON channel_watches(watched_at)",
    "CREATE INDEX IF NOT EXISTS idx_channel_watches_url ON channel_watches(url)",
)

# Columns added to existing DBs via ALTER (CREATE TABLE IF NOT EXISTS won't add them).
_CHANNEL_COLUMN_MIGRATIONS: Sequence[tuple[str, str]] = (
    ("trend_score", "REAL DEFAULT 0"),
    ("watch_count", "INTEGER DEFAULT 0"),
    ("last_watched_at", "REAL"),
    ("trend_updated_at", "REAL"),
)


CHANNEL_COLUMNS: tuple = (
    "url",
    "url_norm",
    "name",
    "tvg_id",
    "tvg_logo",
    "group_title",
    "playing_now",
    "status",
    "country",
    "icon_url",
    "audio_language",
    "variant_of",
    "media_type",
    "fail_reason",
    "fail_count",
    "last_checked_at",
    "updated_at",
    "variant_quality",
    "variant_bandwidth",
    "trend_score",
    "watch_count",
    "last_watched_at",
    "trend_updated_at",
)


ACTIVE_STATUSES = ("online", "pending", "unknown")
DEAD_STATUSES = ("offline", "error")

_default_store: Optional["ChannelStore"] = None
_default_store_lock = threading.Lock()


def ensure_db(path: Optional[str] = None) -> "ChannelStore":
    """Return a ready :class:`ChannelStore` at ``path`` (env / default).

    The parent directory is created, the schema is applied idempotently, WAL
    mode is enabled, and a legacy JSON import is attempted whenever the
    ``channels`` table is empty.
    """
    global _default_store
    db_path = path or DEFAULT_DB_PATH
    parent = os.path.dirname(os.path.abspath(db_path))
    if parent:
        os.makedirs(parent, exist_ok=True)

    store = ChannelStore(db_path)
    store._init_schema()

    if store.count_channels(exclude_test=False) == 0:
        try:
            imported = store.import_from_json_files()
            if imported:
                logger.info("Imported %d channels from legacy JSON files", imported)
        except Exception as exc:
            logger.warning("Legacy JSON import skipped: %s", exc)

    try:
        moved = store.separate_country_groups()
        if moved:
            logger.info("Separated %d country group-titles into country codes", moved)
    except Exception as exc:
        logger.warning("Country/category separation skipped: %s", exc)

    with _default_store_lock:
        if path is None or os.path.abspath(db_path) == os.path.abspath(DEFAULT_DB_PATH):
            _default_store = store
    return store


def get_default_store() -> "ChannelStore":
    """Return the process-wide store, creating it on first use."""
    global _default_store
    with _default_store_lock:
        if _default_store is None:
            return ensure_db()
        return _default_store


class ChannelStore:
    """Thread-safe wrapper around a WAL-mode SQLite connection."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False, timeout=30.0)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.execute("PRAGMA busy_timeout=30000")

    # ------------------------------------------------------------------ core

    def close(self) -> None:
        with self._lock:
            with contextlib.suppress(Exception):
                self._conn.close()

    def _execute(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._conn.execute(sql, params)

    def _executemany(self, sql: str, seq: Iterable[Sequence[Any]]) -> sqlite3.Cursor:
        with self._lock:
            return self._conn.executemany(sql, seq)

    @contextlib.contextmanager
    def transaction(self):
        """Yield a raw connection guarded by the write lock, committing on exit."""
        with self._lock:
            try:
                yield self._conn
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def _init_schema(self) -> None:
        with self.transaction() as conn:
            for statement in SCHEMA_STATEMENTS:
                conn.execute(statement)
            # Existing DBs created before trending columns need ALTER TABLE.
            existing_cols = {
                row[1]
                for row in conn.execute("PRAGMA table_info(channels)").fetchall()
            }
            for col_name, col_type in _CHANNEL_COLUMN_MIGRATIONS:
                if col_name not in existing_cols:
                    conn.execute(
                        f"ALTER TABLE channels ADD COLUMN {col_name} {col_type}"
                    )
            for statement in INDEX_STATEMENTS:
                conn.execute(statement)
            conn.execute(
                "INSERT OR IGNORE INTO meta(key, value) VALUES ('revision', '0')"
            )
            conn.execute(
                "INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', '1')"
            )

    # ---------------------------------------------------------------- meta

    def bump_revision(self) -> int:
        """Increment the shared revision counter and return the new value."""
        with self.transaction() as conn:
            row = conn.execute(
                "SELECT value FROM meta WHERE key = 'revision'"
            ).fetchone()
            current = int(row[0]) if row and row[0] is not None else 0
            new_value = current + 1
            conn.execute(
                "INSERT INTO meta(key, value) VALUES ('revision', ?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (str(new_value),),
            )
        return new_value

    def get_revision(self) -> int:
        row = self._execute(
            "SELECT value FROM meta WHERE key = 'revision'"
        ).fetchone()
        try:
            return int(row[0]) if row and row[0] is not None else 0
        except (TypeError, ValueError):
            return 0

    def get_meta(self, key: str, default: Optional[str] = None) -> Optional[str]:
        row = self._execute(
            "SELECT value FROM meta WHERE key = ?", (key,)
        ).fetchone()
        return row[0] if row and row[0] is not None else default

    def set_meta(self, key: str, value: Optional[str]) -> None:
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO meta(key, value) VALUES (?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value if value is None else str(value)),
            )

    # ------------------------------------------------------------- reading

    def count_channels(
        self,
        status: Optional[str] = None,
        media_type: Optional[str] = None,
        exclude_test: bool = True,
    ) -> int:
        clauses = []
        params: list = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if media_type:
            clauses.append("media_type = ?")
            params.append(media_type)
        if exclude_test:
            clauses.append("(group_title IS NULL OR group_title != 'Test')")
        sql = "SELECT COUNT(*) FROM channels"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        row = self._execute(sql, params).fetchone()
        return int(row[0]) if row else 0

    def count_check_queue(
        self,
        statuses: Sequence[str],
        *,
        exclude_test: bool = True,
    ) -> int:
        """How many channels in ``statuses`` still sit in the check rotation."""
        if not statuses:
            return 0
        placeholders = ",".join("?" for _ in statuses)
        clauses = [f"status IN ({placeholders})"]
        params: list = list(statuses)
        if exclude_test:
            clauses.append("(group_title IS NULL OR group_title != 'Test')")
        sql = "SELECT COUNT(*) FROM channels WHERE " + " AND ".join(clauses)
        row = self._execute(sql, params).fetchone()
        return int(row[0]) if row else 0

    def count_priority_checks(
        self,
        statuses: Optional[Sequence[str]] = None,
        *,
        exclude_test: bool = True,
    ) -> int:
        """Never-checked channels (``last_checked_at IS NULL``) — scan first."""
        statuses = tuple(statuses or ACTIVE_STATUSES)
        placeholders = ",".join("?" for _ in statuses)
        clauses = [
            f"status IN ({placeholders})",
            "last_checked_at IS NULL",
        ]
        params: list = list(statuses)
        if exclude_test:
            clauses.append("(group_title IS NULL OR group_title != 'Test')")
        sql = "SELECT COUNT(*) FROM channels WHERE " + " AND ".join(clauses)
        row = self._execute(sql, params).fetchone()
        return int(row[0]) if row else 0

    def list_channels(
        self,
        page: int = 1,
        limit: int = 50,
        q: Optional[str] = None,
        group: Optional[str] = None,
        country: Optional[str] = None,
        online_only: bool = False,
        include_test: bool = False,
        media_type: Optional[str] = None,
        status: Optional[str] = None,
        status_in: Optional[Sequence[str]] = None,
        sort: Optional[str] = None,
        sort_dir: str = "asc",
    ) -> dict:
        """Paginated channel listing plus facet counts and the current revision."""
        try:
            page = max(1, int(page))
        except (TypeError, ValueError):
            page = 1
        try:
            limit = max(1, min(int(limit), 1000))
        except (TypeError, ValueError):
            limit = 50

        clauses: list = []
        params: list = []
        if q:
            like = f"%{q.strip().lower()}%"
            clauses.append(
                "(LOWER(name) LIKE ? OR LOWER(group_title) LIKE ?"
                " OR LOWER(country) LIKE ? OR LOWER(url) LIKE ?)"
            )
            params.extend([like, like, like, like])
        if group:
            clauses.append("group_title = ?")
            params.append(group)
        if country:
            from .geo import country_code_to_name, country_name_to_code

            # Accept ISO code or English name from the UI.
            code = country_name_to_code(country) or (
                country.strip().upper() if len(country.strip()) == 2 else country.strip().upper()
            )
            name = country_code_to_name(code) or country.strip()
            # Many playlists put the country in group-title and leave country blank/GLOBAL.
            clauses.append(
                "("
                " UPPER(COALESCE(country, '')) = ?"
                " OR LOWER(COALESCE(group_title, '')) = LOWER(?)"
                ")"
            )
            params.extend([code, name])
        if online_only:
            clauses.append("status = 'online'")
        elif status_in:
            cleaned = [s for s in status_in if s]
            if cleaned:
                placeholders = ",".join("?" for _ in cleaned)
                clauses.append(f"status IN ({placeholders})")
                params.extend(cleaned)
        elif status:
            clauses.append("status = ?")
            params.append(status)
        if media_type:
            if media_type == "live":
                clauses.append("(media_type = 'live' OR media_type = 'unknown' OR media_type IS NULL OR media_type = '')")
            else:
                clauses.append("media_type = ?")
                params.append(media_type)
        if not include_test:
            clauses.append("(group_title IS NULL OR group_title != 'Test')")

        where = ""
        if clauses:
            where = " WHERE " + " AND ".join(clauses)

        total_row = self._execute(
            f"SELECT COUNT(*) FROM channels{where}", params
        ).fetchone()
        total = int(total_row[0]) if total_row else 0

        sort_key = (sort or "name").lower()
        order_col = _SORT_COLUMNS.get(sort_key, _SORT_COLUMNS["name"])
        direction = "DESC" if str(sort_dir).lower() == "desc" else "ASC"
        if sort_key in ("trending", "popular", "trend_score"):
            # Hot channels first; recent watches break ties.
            order_clause = (
                f" ORDER BY COALESCE(trend_score, 0) {direction},"
                f" COALESCE(last_watched_at, 0) DESC,"
                f" name COLLATE NOCASE ASC, url ASC"
            )
        else:
            order_clause = f" ORDER BY {order_col} {direction}, url ASC"

        offset = (page - 1) * limit
        query_sql = (
            f"SELECT * FROM channels{where}{order_clause} LIMIT ? OFFSET ?"
        )
        rows = self._execute(query_sql, (*params, limit, offset)).fetchall()
        channels = [coerce_dict(r) for r in rows]

        groups_rows = self._execute(
            "SELECT group_title, COUNT(*) FROM channels"
            " WHERE group_title IS NOT NULL AND group_title != ''"
            " GROUP BY group_title ORDER BY group_title COLLATE NOCASE"
        ).fetchall()
        from .geo import country_code_to_name, is_country_like_group

        # Category menu: drop country names (those belong in Countries).
        groups = [
            {"name": r[0], "count": int(r[1])}
            for r in groups_rows
            if not is_country_like_group(r[0])
        ]

        countries_rows = self._execute(
            "SELECT country, COUNT(*) FROM channels"
            " WHERE country IS NOT NULL AND country != ''"
            " AND UPPER(country) NOT IN ('GLOBAL', 'XX', 'ZZ', 'UNKNOWN', 'UNDEFINED')"
            " GROUP BY country ORDER BY country COLLATE NOCASE"
        ).fetchall()
        countries = []
        seen_codes: set[str] = set()
        for r in countries_rows:
            code = (r[0] or "").strip().upper()
            if not code or code in seen_codes:
                continue
            seen_codes.add(code)
            countries.append(
                {
                    "code": code,
                    "name": country_code_to_name(code) or code,
                    "count": int(r[1]),
                }
            )

        # Also surface countries that only appear as group-title labels.
        for r in groups_rows:
            label = r[0]
            if not is_country_like_group(label):
                continue
            from .geo import country_name_to_code

            code = country_name_to_code(label)
            if not code or code in seen_codes:
                continue
            seen_codes.add(code)
            countries.append(
                {
                    "code": code,
                    "name": country_code_to_name(code) or label,
                    "count": int(r[1]),
                }
            )
        countries.sort(key=lambda c: (c.get("name") or c.get("code") or "").lower())

        total_pages = (total + limit - 1) // limit if limit > 0 else 1
        return {
            "channels": channels,
            "total": total,
            "page": page,
            "limit": limit,
            "total_pages": total_pages,
            "has_more": page < total_pages,
            "countries": countries,
            "groups": groups,
            "revision": self.get_revision(),
        }

    def get_valid_channels(self, include_test: bool = False) -> list:
        """Return online channels — the primary feed for the public UI."""
        clauses = ["status = 'online'"]
        if not include_test:
            clauses.append("(group_title IS NULL OR group_title != 'Test')")
        sql = (
            "SELECT * FROM channels WHERE "
            + " AND ".join(clauses)
            + " ORDER BY name COLLATE NOCASE"
        )
        rows = self._execute(sql).fetchall()
        return [coerce_dict(r) for r in rows]

    def get_export_channels(self) -> list:
        """Return every online channel, including Test entries — for M3U export."""
        rows = self._execute(
            "SELECT * FROM channels WHERE status = 'online'"
            " ORDER BY name COLLATE NOCASE"
        ).fetchall()
        return [coerce_dict(r) for r in rows]

    def get_channel(self, url: str) -> Optional[dict]:
        if not url:
            return None
        row = self._execute(
            "SELECT * FROM channels WHERE url = ?", (url,)
        ).fetchone()
        return coerce_dict(row) if row else None

    def get_master_map(self) -> dict:
        """Return ``{url: channel_dict}`` used to merge with the legacy master cache."""
        rows = self._execute("SELECT * FROM channels").fetchall()
        return {r["url"]: coerce_dict(r) for r in rows}

    # -------------------------------------------------------------- checker

    def claim_check_batch(
        self,
        statuses: Sequence[str],
        limit: int,
    ) -> list:
        """Return channels ready to be re-checked, oldest ``last_checked_at`` first.

        Rows that were never checked (``last_checked_at IS NULL``) come first so
        newly ingested channels get a status quickly.
        """
        if not statuses:
            return []
        try:
            limit = max(1, int(limit))
        except (TypeError, ValueError):
            limit = 50
        placeholders = ",".join("?" for _ in statuses)
        sql = (
            f"SELECT * FROM channels WHERE status IN ({placeholders})"
            " ORDER BY (last_checked_at IS NULL) DESC, last_checked_at ASC, url ASC"
            " LIMIT ?"
        )
        rows = self._execute(sql, (*statuses, limit)).fetchall()
        return [coerce_dict(r) for r in rows]

    def claim_active_batch(
        self,
        limit: int,
        statuses: Optional[Sequence[str]] = None,
    ) -> list:
        """Claim online/pending/unknown channels for the active-health worker."""
        return self.claim_check_batch(statuses or ACTIVE_STATUSES, limit)

    def claim_dead_batch(
        self,
        limit: int,
        statuses: Optional[Sequence[str]] = None,
    ) -> list:
        """Claim offline/error channels for the dead-revival worker."""
        return self.claim_check_batch(statuses or DEAD_STATUSES, limit)

    def mark_priority_check(self, url: str) -> bool:
        """Force ``url`` to the front of the health queue (unchecked-first).

        Clears ``last_checked_at`` so :meth:`claim_check_batch` picks it up
        before already-scanned rows. Used when a client reports a stream from
        the unchecked/dead directory actually played.
        """
        url = (url or "").strip()
        if not url:
            return False
        now = time.time()
        cur = self._execute(
            "UPDATE channels SET last_checked_at = NULL, updated_at = ? WHERE url = ?",
            (now, url),
        )
        if cur.rowcount:
            self.bump_revision()
            return True
        return False

    def update_channel_results(self, results: Sequence[dict]) -> int:
        """Batch-apply check results.

        Only the status-related columns are touched here so metadata written by
        ingest (name, group_title, tvg_logo, ...) is never overwritten.
        """
        if not results:
            return 0

        rows_written = 0
        now = time.time()
        with self.transaction() as conn:
            for result in results:
                if not isinstance(result, dict):
                    continue
                url = result.get("url")
                if not url:
                    continue

                status = (result.get("status") or "unknown").lower()
                if status not in VALID_STATUSES:
                    status = "unknown"

                media_type = result.get("media_type")
                if media_type and media_type not in VALID_MEDIA_TYPES:
                    media_type = None

                playing_now = result.get("playing_now")
                fail_reason = result.get("fail_reason")
                fail_delta = result.get("fail_delta")
                explicit_fail_count = result.get("fail_count")

                assignments = ["status = ?", "updated_at = ?", "last_checked_at = ?"]
                params: list = [status, now, now]

                if playing_now is not None:
                    assignments.append("playing_now = ?")
                    params.append(playing_now)
                if fail_reason is not None:
                    assignments.append("fail_reason = ?")
                    params.append(fail_reason)
                if media_type is not None:
                    assignments.append("media_type = ?")
                    params.append(media_type)

                if explicit_fail_count is not None:
                    assignments.append("fail_count = ?")
                    params.append(int(explicit_fail_count))
                elif status == "online":
                    assignments.append("fail_count = 0")
                elif fail_delta:
                    assignments.append(
                        "fail_count = COALESCE(fail_count, 0) + ?"
                    )
                    params.append(int(fail_delta))

                params.append(url)
                sql = f"UPDATE channels SET {', '.join(assignments)} WHERE url = ?"
                cur = conn.execute(sql, params)
                rows_written += cur.rowcount or 0

        if rows_written:
            self.bump_revision()
        return rows_written

    def separate_country_groups(self) -> int:
        """Peel country/region names out of ``group_title`` into ``country``.

        Playlists often use Italy / UK / US as the M3U group. Those belong in
        the Countries filter, not Categories. Idempotent — safe to run on every
        startup.
        """
        from .geo import DEFAULT_CATEGORY_AFTER_COUNTRY_SPLIT, country_name_to_code

        rows = self._execute(
            "SELECT DISTINCT group_title FROM channels"
            " WHERE group_title IS NOT NULL AND TRIM(group_title) != ''"
        ).fetchall()
        if not rows:
            return 0

        moved = 0
        now = time.time()
        with self.transaction() as conn:
            for (label,) in rows:
                code = country_name_to_code(label)
                if not code:
                    continue
                cur = conn.execute(
                    "UPDATE channels SET"
                    " country = CASE"
                    "   WHEN country IS NULL OR TRIM(country) = ''"
                    "     OR UPPER(country) IN ('GLOBAL','XX','ZZ','UNKNOWN','UNDEFINED')"
                    "   THEN ? ELSE country END,"
                    " group_title = ?,"
                    " updated_at = ?"
                    " WHERE group_title = ?",
                    (code, DEFAULT_CATEGORY_AFTER_COUNTRY_SPLIT, now, label),
                )
                moved += int(cur.rowcount or 0)

        if moved:
            self.bump_revision()
        return moved

    # ------------------------------------------------------------- trending

    @staticmethod
    def _decay_factor(hours: float, half_life: float = TREND_HALF_LIFE_HOURS) -> float:
        if hours <= 0 or half_life <= 0:
            return 1.0
        return 0.5 ** (hours / half_life)

    def record_watch(
        self,
        url: str,
        *,
        min_interval_sec: float = WATCH_MIN_INTERVAL_SEC,
    ) -> Optional[dict]:
        """Record a channel play and bump its decaying trend score.

        Same URL is rate-limited to once per ``min_interval_sec``. Does not
        bump the catalog revision (avoids thrashing soft-refresh for everyone).
        """
        url = (url or "").strip()
        if not url:
            return None

        now = time.time()
        with self.transaction() as conn:
            row = conn.execute(
                "SELECT url, trend_score, watch_count, last_watched_at, trend_updated_at"
                " FROM channels WHERE url = ? OR url_norm = ? LIMIT 1",
                (url, normalize_url(url)),
            ).fetchone()
            if not row:
                return None

            target = row[0]
            score = float(row[1] or 0)
            watch_count = int(row[2] or 0)
            last_watched = row[3]
            trend_updated = row[4]

            if last_watched is not None and (now - float(last_watched)) < float(
                min_interval_sec
            ):
                return {
                    "ok": True,
                    "recorded": False,
                    "rate_limited": True,
                    "url": target,
                    "trend_score": score,
                    "watch_count": watch_count,
                }

            baseline = trend_updated if trend_updated is not None else last_watched
            if baseline is not None and score > 0:
                hours = max(0.0, (now - float(baseline)) / 3600.0)
                score *= self._decay_factor(hours)
            score += 1.0
            watch_count += 1

            conn.execute(
                "UPDATE channels SET trend_score = ?, watch_count = ?,"
                " last_watched_at = ?, trend_updated_at = ? WHERE url = ?",
                (score, watch_count, now, now, target),
            )
            conn.execute(
                "INSERT INTO channel_watches(url, watched_at) VALUES (?, ?)",
                (target, now),
            )

            # Prune occasionally (~1/40 of watches) to keep the event table small.
            if watch_count % 40 == 0:
                cutoff = now - (WATCH_PRUNE_DAYS * 86400.0)
                conn.execute(
                    "DELETE FROM channel_watches WHERE watched_at < ?",
                    (cutoff,),
                )

        return {
            "ok": True,
            "recorded": True,
            "rate_limited": False,
            "url": target,
            "trend_score": score,
            "watch_count": watch_count,
        }

    def decay_trend_scores(self) -> int:
        """Apply global exponential decay so inactive channels sink over time.

        Uses ``meta.trend_decay_at`` so repeated calls within a short window are
        no-ops. Updates ``trend_updated_at`` so the next watch does not
        double-decay the same period.
        """
        now = time.time()
        with self.transaction() as conn:
            row = conn.execute(
                "SELECT value FROM meta WHERE key = 'trend_decay_at'"
            ).fetchone()
            try:
                last = float(row[0]) if row and row[0] is not None else None
            except (TypeError, ValueError):
                last = None

            if last is None:
                conn.execute(
                    "INSERT INTO meta(key, value) VALUES ('trend_decay_at', ?)"
                    " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (str(now),),
                )
                return 0

            hours = max(0.0, (now - last) / 3600.0)
            if hours < (1.0 / 60.0):  # < ~1 minute
                return 0

            factor = self._decay_factor(hours)
            if factor >= 0.9999:
                conn.execute(
                    "INSERT INTO meta(key, value) VALUES ('trend_decay_at', ?)"
                    " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (str(now),),
                )
                return 0

            cur = conn.execute(
                "UPDATE channels SET trend_score = trend_score * ?,"
                " trend_updated_at = ?"
                " WHERE trend_score IS NOT NULL AND trend_score > 0.0001",
                (factor, now),
            )
            conn.execute(
                "UPDATE channels SET trend_score = 0 WHERE trend_score IS NOT NULL"
                " AND trend_score <= 0.0001"
            )
            conn.execute(
                "INSERT INTO meta(key, value) VALUES ('trend_decay_at', ?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (str(now),),
            )
            return int(cur.rowcount or 0)

    # --------------------------------------------------------------- ingest

    def upsert_from_ingest(self, channels: Sequence[dict]) -> dict:
        """Insert or update channel metadata from an ingest pass.

        * New URLs (or URLs whose ``url_norm`` isn't already in the store) are
          inserted with ``status='pending'`` so the checker picks them up on the
          next batch — we never bulk-flag existing channels offline here.
        * Existing rows keep their status; only descriptive metadata is updated
          (name, tvg_id, tvg_logo, group_title, country, ...).
        * Normalization helpers are always applied before writing.

        Returns a summary dict: ``{new, updated, skipped}``.
        """
        summary = {"new": 0, "updated": 0, "skipped": 0}
        if not channels:
            return summary

        now = time.time()
        with self.transaction() as conn:
            for raw in channels:
                if not isinstance(raw, dict):
                    summary["skipped"] += 1
                    continue
                ch = dict(raw)
                url = (ch.get("url") or "").strip()
                if not url:
                    summary["skipped"] += 1
                    continue
                ch["url"] = url
                normalize_channel(ch)
                url_norm = ch.get("url_norm") or normalize_url(url)

                existing = conn.execute(
                    "SELECT url FROM channels WHERE url = ?"
                    " UNION ALL SELECT url FROM channels WHERE url_norm = ?"
                    " LIMIT 1",
                    (url, url_norm),
                ).fetchone()

                if existing:
                    target_url = existing[0]
                    updates: list = []
                    params: list = []
                    for column in (
                        "name",
                        "tvg_id",
                        "tvg_logo",
                        "group_title",
                        "country",
                        "icon_url",
                        "audio_language",
                        "variant_of",
                        "variant_quality",
                        "variant_bandwidth",
                    ):
                        val = ch.get(column)
                        if val not in (None, ""):
                            updates.append(f"{column} = ?")
                            params.append(val)

                    media_type = ch.get("media_type")
                    if media_type and media_type in VALID_MEDIA_TYPES and media_type != "unknown":
                        updates.append("media_type = COALESCE(NULLIF(media_type, 'unknown'), ?)")
                        params.append(media_type)

                    if url_norm:
                        updates.append("url_norm = COALESCE(url_norm, ?)")
                        params.append(url_norm)

                    updates.append("updated_at = ?")
                    params.append(now)

                    params.append(target_url)
                    conn.execute(
                        f"UPDATE channels SET {', '.join(updates)} WHERE url = ?",
                        params,
                    )
                    summary["updated"] += 1
                    continue

                media_type = ch.get("media_type") or classify_media_type(url)
                if media_type not in VALID_MEDIA_TYPES:
                    media_type = "unknown"

                conn.execute(
                    "INSERT INTO channels ("
                    " url, url_norm, name, tvg_id, tvg_logo, group_title,"
                    " playing_now, status, country, icon_url, audio_language,"
                    " variant_of, media_type, fail_reason, fail_count,"
                    " last_checked_at, updated_at, variant_quality, variant_bandwidth"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        url,
                        url_norm,
                        ch.get("name"),
                        ch.get("tvg_id"),
                        ch.get("tvg_logo"),
                        ch.get("group_title"),
                        ch.get("playing_now"),
                        "pending",
                        ch.get("country"),
                        ch.get("icon_url"),
                        ch.get("audio_language"),
                        ch.get("variant_of"),
                        media_type,
                        None,
                        0,
                        None,
                        now,
                        ch.get("variant_quality"),
                        ch.get("variant_bandwidth"),
                    ),
                )
                summary["new"] += 1

        if summary["new"] or summary["updated"]:
            self.bump_revision()
        return summary

    # ------------------------------------------------------------- variants

    def replace_variants(
        self,
        channel_url: str,
        variants: Sequence[dict],
    ) -> int:
        """Replace the variant set for ``channel_url`` atomically."""
        if not channel_url:
            return 0
        with self.transaction() as conn:
            conn.execute(
                "DELETE FROM channel_variants WHERE channel_url = ?",
                (channel_url,),
            )
            written = 0
            for variant in variants or ():
                if not isinstance(variant, dict):
                    continue
                v_url = (variant.get("url") or variant.get("variant_url") or "").strip()
                if not v_url:
                    continue
                conn.execute(
                    "INSERT OR REPLACE INTO channel_variants ("
                    " variant_url, channel_url, resolution, bandwidth, codecs, audio_language"
                    ") VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        v_url,
                        channel_url,
                        variant.get("resolution") or variant.get("variant_quality"),
                        int(variant["bandwidth"])
                        if str(variant.get("bandwidth") or "").isdigit()
                        else variant.get("variant_bandwidth"),
                        variant.get("codecs"),
                        variant.get("audio_language"),
                    ),
                )
                written += 1
            return written

    def get_variants(self, channel_url: str) -> list:
        if not channel_url:
            return []
        rows = self._execute(
            "SELECT * FROM channel_variants WHERE channel_url = ?"
            " ORDER BY bandwidth DESC",
            (channel_url,),
        ).fetchall()
        return [coerce_dict(r) for r in rows]

    # -------------------------------------------------------- invalid links

    def get_invalid_links(self) -> list:
        rows = self._execute(
            "SELECT url FROM invalid_links ORDER BY created_at DESC, url"
        ).fetchall()
        return [r[0] for r in rows]

    def set_invalid_links(self, urls: Iterable[str]) -> int:
        now = time.time()
        with self.transaction() as conn:
            conn.execute("DELETE FROM invalid_links")
            payload = [
                (str(u).strip(), now)
                for u in (urls or ())
                if isinstance(u, str) and u.strip()
            ]
            if payload:
                conn.executemany(
                    "INSERT OR IGNORE INTO invalid_links(url, created_at) VALUES (?, ?)",
                    payload,
                )
            return len(payload)

    def add_invalid_links(self, urls: Iterable[str]) -> int:
        now = time.time()
        payload = [
            (str(u).strip(), now)
            for u in (urls or ())
            if isinstance(u, str) and u.strip()
        ]
        if not payload:
            return 0
        with self.transaction() as conn:
            conn.executemany(
                "INSERT OR IGNORE INTO invalid_links(url, created_at) VALUES (?, ?)",
                payload,
            )
        return len(payload)

    # ------------------------------------------------------------- SEO slugs

    def save_seo_slugs(self, slug_order: Sequence[str], slugs: dict) -> int:
        """Persist the slug manifest. ``slugs`` may map slug→name or slug→dict."""
        if not slug_order:
            with self.transaction() as conn:
                conn.execute("DELETE FROM seo_slugs")
            return 0

        rows: list = []
        for slug in slug_order:
            if not slug:
                continue
            entry = slugs.get(slug) if isinstance(slugs, dict) else None
            channel_name = None
            channel_url = None
            if isinstance(entry, dict):
                channel_name = entry.get("name") or entry.get("channel_name")
                channel_url = entry.get("url") or entry.get("channel_url")
            elif isinstance(entry, str):
                channel_name = entry
            rows.append((slug, channel_url, channel_name))

        with self.transaction() as conn:
            conn.execute("DELETE FROM seo_slugs")
            if rows:
                conn.executemany(
                    "INSERT OR REPLACE INTO seo_slugs("
                    " slug, channel_url, channel_name"
                    ") VALUES (?, ?, ?)",
                    rows,
                )
        return len(rows)

    def get_seo_slug(self, slug: str) -> Optional[dict]:
        if not slug:
            return None
        row = self._execute(
            "SELECT slug, channel_url, channel_name FROM seo_slugs WHERE slug = ?",
            (slug,),
        ).fetchone()
        return coerce_dict(row) if row else None

    def all_seo_slugs(self) -> list:
        rows = self._execute(
            "SELECT slug, channel_url, channel_name FROM seo_slugs"
            " ORDER BY slug"
        ).fetchall()
        return [coerce_dict(r) for r in rows]

    # ----------------------------------------------------------- playlist queue

    def enqueue_playlist(self, url: str, depth: int = 0) -> bool:
        if not url:
            return False
        with self.transaction() as conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO playlist_queue(url, depth, created_at)"
                " VALUES (?, ?, ?)",
                (url, int(depth), time.time()),
            )
            return (cur.rowcount or 0) > 0

    def pop_playlist_batch(self, limit: int = 10) -> list:
        try:
            limit = max(1, int(limit))
        except (TypeError, ValueError):
            limit = 10
        with self.transaction() as conn:
            rows = conn.execute(
                "SELECT url, depth, created_at FROM playlist_queue"
                " ORDER BY created_at ASC LIMIT ?",
                (limit,),
            ).fetchall()
            if rows:
                conn.executemany(
                    "DELETE FROM playlist_queue WHERE url = ?",
                    [(r[0],) for r in rows],
                )
        return [coerce_dict(r) for r in rows]

    # ---------------------------------------------------------------- backup

    def backup(self, dest: Optional[str] = None) -> str:
        """Copy the live database to ``data/backups/<timestamp>.db`` via SQLite."""
        if dest is None:
            backups_dir = os.path.join(
                os.path.dirname(os.path.abspath(self.path)) or ".",
                "backups",
            )
            os.makedirs(backups_dir, exist_ok=True)
            stamp = time.strftime("%Y%m%d-%H%M%S")
            dest = os.path.join(backups_dir, f"iptv-{stamp}.db")
        else:
            parent = os.path.dirname(os.path.abspath(dest))
            if parent:
                os.makedirs(parent, exist_ok=True)

        with self._lock:
            try:
                target = sqlite3.connect(dest)
                try:
                    self._conn.backup(target)
                finally:
                    target.close()
            except sqlite3.Error:
                # Fallback for very old sqlite builds that lack .backup().
                self._conn.commit()
                shutil.copyfile(self.path, dest)
        return dest

    # ---------------------------------------------------------- json import

    def import_from_json_files(self, jsons_dir: str = LEGACY_JSON_DIR) -> int:
        """One-shot bulk import from the legacy ``jsons/*.json`` files.

        Safe to call more than once — existing rows are merged in place and
        their status is left alone. The function returns the number of rows
        that were inserted or updated.
        """
        touched = 0
        streams_path = os.path.join(jsons_dir, "IPTV_STREAMS_FILE.json")
        dead_path = os.path.join(jsons_dir, "DEAD_STREAMS_FILE.json")
        master_path = os.path.join(jsons_dir, "MASTER_CACHE_FILE.json")
        invalid_path = os.path.join(jsons_dir, "INVALID_LINKS_FILE.json")
        slugs_path = os.path.join(jsons_dir, "SEO_SLUG_MANIFEST.json")

        online = _load_json_list(streams_path)
        dead = _load_json_list(dead_path)
        master = _load_json_list(master_path)

        touched += self._import_channel_list(online, default_status="online")
        touched += self._import_channel_list(dead, default_status="offline")
        touched += self._import_channel_list(master, default_status=None)

        invalid = _load_json_list(invalid_path)
        if isinstance(invalid, list):
            urls = [u for u in invalid if isinstance(u, str) and u.strip()]
            if urls:
                self.add_invalid_links(urls)

        slug_data = _load_json_file(slugs_path)
        if isinstance(slug_data, dict):
            order = slug_data.get("slug_order") or []
            slugs = slug_data.get("slugs") or {}
            if order:
                try:
                    self.save_seo_slugs(order, slugs)
                except Exception as exc:
                    logger.debug("Legacy slug import failed: %s", exc)

        if touched:
            self.set_meta("legacy_import_at", str(time.time()))
        return touched

    def _import_channel_list(
        self,
        entries: Iterable[dict],
        default_status: Optional[str],
    ) -> int:
        if not entries:
            return 0

        touched = 0
        now = time.time()
        with self.transaction() as conn:
            for raw in entries:
                if not isinstance(raw, dict):
                    continue
                ch = dict(raw)
                url = (ch.get("url") or "").strip()
                if not url:
                    continue
                ch["url"] = url
                normalize_channel(ch)
                url_norm = ch.get("url_norm") or normalize_url(url)

                status = (ch.get("status") or default_status or "unknown").lower()
                if status not in VALID_STATUSES:
                    status = "unknown"
                if is_test_channel(ch) and ch.get("group_title") != "Test":
                    ch["group_title"] = "Test"

                media_type = ch.get("media_type") or classify_media_type(url)
                if media_type not in VALID_MEDIA_TYPES:
                    media_type = "unknown"

                existing = conn.execute(
                    "SELECT url FROM channels WHERE url = ?"
                    " UNION ALL SELECT url FROM channels WHERE url_norm = ?"
                    " LIMIT 1",
                    (url, url_norm),
                ).fetchone()

                if existing:
                    target_url = existing[0]
                    conn.execute(
                        "UPDATE channels SET"
                        "  name           = COALESCE(NULLIF(?, ''), name),"
                        "  tvg_id         = COALESCE(NULLIF(?, ''), tvg_id),"
                        "  tvg_logo       = COALESCE(NULLIF(?, ''), tvg_logo),"
                        "  group_title    = COALESCE(NULLIF(?, ''), group_title),"
                        "  playing_now    = COALESCE(NULLIF(?, ''), playing_now),"
                        "  country        = COALESCE(NULLIF(?, ''), country),"
                        "  icon_url       = COALESCE(NULLIF(?, ''), icon_url),"
                        "  audio_language = COALESCE(NULLIF(?, ''), audio_language),"
                        "  variant_of     = COALESCE(NULLIF(?, ''), variant_of),"
                        "  variant_quality= COALESCE(NULLIF(?, ''), variant_quality),"
                        "  variant_bandwidth = COALESCE(?, variant_bandwidth),"
                        "  media_type     = CASE WHEN media_type IN ('unknown', '') OR media_type IS NULL"
                        "                        THEN ? ELSE media_type END,"
                        "  url_norm       = COALESCE(url_norm, ?),"
                        "  updated_at     = ?"
                        " WHERE url = ?",
                        (
                            ch.get("name"),
                            ch.get("tvg_id"),
                            ch.get("tvg_logo"),
                            ch.get("group_title"),
                            ch.get("playing_now"),
                            ch.get("country"),
                            ch.get("icon_url"),
                            ch.get("audio_language"),
                            ch.get("variant_of"),
                            ch.get("variant_quality"),
                            ch.get("variant_bandwidth"),
                            media_type,
                            url_norm,
                            now,
                            target_url,
                        ),
                    )
                else:
                    conn.execute(
                        "INSERT INTO channels ("
                        " url, url_norm, name, tvg_id, tvg_logo, group_title,"
                        " playing_now, status, country, icon_url, audio_language,"
                        " variant_of, media_type, fail_reason, fail_count,"
                        " last_checked_at, updated_at, variant_quality, variant_bandwidth"
                        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            url,
                            url_norm,
                            ch.get("name"),
                            ch.get("tvg_id"),
                            ch.get("tvg_logo"),
                            ch.get("group_title"),
                            ch.get("playing_now"),
                            status,
                            ch.get("country"),
                            ch.get("icon_url"),
                            ch.get("audio_language"),
                            ch.get("variant_of"),
                            media_type,
                            ch.get("fail_reason"),
                            int(ch.get("fail_count") or 0),
                            ch.get("last_checked_at"),
                            now,
                            ch.get("variant_quality"),
                            ch.get("variant_bandwidth"),
                        ),
                    )
                touched += 1
        return touched


# --------------------------------------------------------------- helpers

def _load_json_file(path: str) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return None
    except Exception as exc:
        logger.debug("Failed to read %s: %s", path, exc)
        return None


def _load_json_list(path: str) -> list:
    data = _load_json_file(path)
    if isinstance(data, list):
        return data
    return []


# ------------------------------------------------------------------- CLI

def _cli(argv: Sequence[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = list(argv[1:])
    command = args[0].lower() if args else "ensure"

    if command in ("ensure", "init", "migrate"):
        store = ensure_db()
        try:
            total = store.count_channels(exclude_test=False)
            print(f"Database ready at {store.path} ({total} channels, revision {store.get_revision()})")
        finally:
            store.close()
        return 0

    if command == "backup":
        store = ensure_db()
        try:
            dest = store.backup()
            print(f"Backup written to {dest}")
        finally:
            store.close()
        return 0

    if command in ("stats", "info"):
        store = ensure_db()
        try:
            total = store.count_channels(exclude_test=False)
            online = store.count_channels(status="online", exclude_test=False)
            offline = store.count_channels(status="offline", exclude_test=False)
            pending = store.count_channels(status="pending", exclude_test=False)
            print(f"Path        : {store.path}")
            print(f"Revision    : {store.get_revision()}")
            print(f"Channels    : {total}")
            print(f"  online    : {online}")
            print(f"  offline   : {offline}")
            print(f"  pending   : {pending}")
        finally:
            store.close()
        return 0

    print(f"Unknown command: {command}. Use 'ensure' or 'backup'.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(_cli(sys.argv))
