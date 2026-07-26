"""IPTV Scanner entry point.

Thin bootstrap: ensure SQLite + directories, configure logging, build the Flask
app, start the embedded FastWorker-compatible task queue, and serve HTTP.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import os
import signal
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

# Dedicated pool for asyncio.to_thread / run_in_executor so we can shut it
# down with wait=False on Ctrl+C (avoids the hanging atexit ThreadPool join).
_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=8,
    thread_name_prefix="iptv-pool",
)


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
    try:
        await client.delay("ingest_sources")
    except Exception:
        log.exception("initial ingest enqueue failed")
    return client


def _shutdown(loop: asyncio.AbstractEventLoop, client) -> None:
    log.info("Shutting own :3 XD, bye bye") # just a joke, don't take it seriously :3 XD
    if client is not None:
        try:
            loop.run_until_complete(asyncio.wait_for(client.stop(), timeout=2.5))
        except Exception:
            pass
    try:
        pending = [t for t in asyncio.all_tasks(loop) if not t.done()]
        for t in pending:
            t.cancel()
        if pending:
            loop.run_until_complete(
                asyncio.wait_for(
                    asyncio.gather(*pending, return_exceptions=True),
                    timeout=1.0,
                )
            )
    except Exception:
        pass
    try:
        _EXECUTOR.shutdown(wait=False, cancel_futures=True)
    except TypeError:
        try:
            _EXECUTOR.shutdown(wait=False)
        except Exception:
            pass
    except Exception:
        pass
    try:
        loop.close()
    except Exception:
        pass
    # Hard-exit so blocked network threads cannot hang interpreter atexit
    # (the classic Ctrl+C "Exception ignored in threading" join).
    os._exit(0)


if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.set_default_executor(_EXECUTOR)

    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()

    client = None
    stop_state = {"requested": False}

    def _request_stop(*_args):
        if stop_state["requested"]:
            os._exit(0)
        stop_state["requested"] = True
        loop.call_soon_threadsafe(loop.stop)

    try:
        signal.signal(signal.SIGINT, _request_stop)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, _request_stop)
    except Exception:
        pass

    try:
        client = loop.run_until_complete(_async_main())
        loop.run_forever()
    except KeyboardInterrupt:
        pass
    finally:
        _shutdown(loop, client)
