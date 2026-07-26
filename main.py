"""IPTV Scanner entry point.

Thin bootstrap: ensure SQLite + directories, configure logging, build the Flask
app, start the embedded FastWorker-compatible task queue, and serve HTTP.
"""

from __future__ import annotations

import asyncio
import logging
import os
from threading import Thread

from app_factory import create_app
from config import DIRECTORIES, IPTV_BIND_HOST, IPTV_PORT, IPTV_PUBLIC_BASE_URL
from features.storage.db import ensure_db
from features.workers import fw_tasks


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
log = logging.getLogger("main")


def _ensure_directories():
    for directory in DIRECTORIES:
        os.makedirs(directory, exist_ok=True)
    os.makedirs("webroot/icons", exist_ok=True)
    os.makedirs("data", exist_ok=True)
    os.makedirs("jsons", exist_ok=True)


_ensure_directories()
store = ensure_db()
log.info("SQLite ready at %s (%d channels)", store.path, store.count_channels(exclude_test=False))

app = create_app()


def run_flask():
    app.run(host=IPTV_BIND_HOST, port=IPTV_PORT, use_reloader=False, threaded=True)


async def _async_main():
    client = await fw_tasks.bootstrap(
        bind_host=IPTV_BIND_HOST,
        port=IPTV_PORT,
        public_base=IPTV_PUBLIC_BASE_URL or None,
        worker_count=4,
    )
    # Kick an immediate ingest so a fresh DB fills quickly.
    try:
        await client.delay("ingest_sources")
    except Exception:
        log.exception("initial ingest enqueue failed")
    return client


if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()

    client = loop.run_until_complete(_async_main())

    try:
        loop.run_forever()
    except KeyboardInterrupt:
        log.info("shutting down")
    finally:
        try:
            loop.run_until_complete(client.stop())
        except Exception:
            pass
        loop.close()
