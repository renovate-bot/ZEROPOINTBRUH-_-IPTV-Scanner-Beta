"""FastWorker task registry for the IPTV Scanner.

Every task defined here is a thin adapter that delegates to a runner in
:mod:`health_workers`. Keeping the registry separate from the worker
implementations means:

* The FastWorker GUI (or the embedded fallback in :mod:`task_queue`) sees a
  clean list of named entry points.
* The runners in :mod:`health_workers` stay directly callable from tests
  and REPL sessions without going through the queue.
* Priorities and cadences live in one place, making it easy to see what
  the scheduler is going to do.

Bootstrap
---------
Callers typically do::

    import fw_tasks   # side-effect: registers every @task
    client = fw_tasks.build_client()
    await client.start()
    await fw_tasks.schedule_defaults(client)

``schedule_defaults`` wires the standard cadences from
:mod:`health_workers`. Individual tasks can also be enqueued on demand via
``client.delay("active_health_batch")`` etc.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

import health_workers
import task_queue
from db import get_default_store
from task_queue import Client, TaskPriority, task


log = logging.getLogger("fw_tasks")


# ---------------------------------------------------------------------------
# Task definitions — each is a named entry point in the queue
# ---------------------------------------------------------------------------

@task("active_health_batch", priority=TaskPriority.HIGH)
async def active_health_batch(limit: Optional[int] = None) -> dict:
    """Run one active-health batch against ``get_default_store()``."""
    return await health_workers.run_active_health_batch(
        get_default_store(), limit=limit,
    )


@task("dead_revival_batch", priority=TaskPriority.NORMAL)
async def dead_revival_batch(limit: Optional[int] = None) -> dict:
    """Retry a batch of dead channels; survivors are promoted to online."""
    return await health_workers.run_dead_revival_batch(
        get_default_store(), limit=limit,
    )


@task("ingest_sources", priority=TaskPriority.NORMAL)
async def ingest_sources() -> dict:
    """Full scrape of every configured source, upserted into the store."""
    return await health_workers.run_ingest_sources(get_default_store())


@task("discover_playlist", priority=TaskPriority.LOW)
async def discover_playlist(seed_url: str) -> dict:
    """Depth-limited discovery walk starting from ``seed_url``."""
    return await health_workers.run_discover_playlist(
        seed_url, get_default_store(),
    )


@task("epg_refresh", priority=TaskPriority.LOW)
async def epg_refresh() -> dict:
    """Placeholder EPG refresh — reserved for the Phase 3 EPG pipeline."""
    return await health_workers.run_epg_refresh(get_default_store())


@task("icon_prefetch_batch", priority=TaskPriority.LOW)
async def icon_prefetch_batch(limit: Optional[int] = None) -> dict:
    """Fill in missing on-disk logos for up to ``limit`` channels."""
    return await health_workers.run_icon_prefetch_batch(
        get_default_store(), limit=limit,
    )


# ---------------------------------------------------------------------------
# Client bootstrap helpers
# ---------------------------------------------------------------------------

def build_client(*, worker_count: int = 4, name: str = "iptv-scanner") -> Client:
    """Return a fresh :class:`task_queue.Client`.

    Kept as a factory (rather than a module singleton) so tests can spin up
    their own client with a smaller pool without touching global state.
    """
    return Client(worker_count=worker_count, name=name)


async def schedule_defaults(client: Client) -> list[asyncio.Task]:
    """Attach the standard repeating cadences to ``client``.

    Real ``fastworker`` exposes a similar ``schedule_repeat`` shape; if a
    future backend does not, this helper is the single place to swap in the
    equivalent primitive.
    """
    scheduled: list[asyncio.Task] = []
    scheduled.append(
        client.schedule_repeat(
            "active_health_batch",
            health_workers.ACTIVE_HEALTH_INTERVAL_SEC,
            priority=TaskPriority.HIGH,
            initial_delay=5.0,
        )
    )
    scheduled.append(
        client.schedule_repeat(
            "dead_revival_batch",
            health_workers.DEAD_REVIVAL_INTERVAL_SEC,
            priority=TaskPriority.NORMAL,
            initial_delay=30.0,
        )
    )
    scheduled.append(
        client.schedule_repeat(
            "ingest_sources",
            health_workers.INGEST_INTERVAL_SEC,
            priority=TaskPriority.NORMAL,
            initial_delay=0.0,
        )
    )
    scheduled.append(
        client.schedule_repeat(
            "icon_prefetch_batch",
            health_workers.ICON_PREFETCH_INTERVAL_SEC,
            priority=TaskPriority.LOW,
            initial_delay=20.0,
        )
    )
    scheduled.append(
        client.schedule_repeat(
            "epg_refresh",
            health_workers.EPG_REFRESH_INTERVAL_SEC,
            priority=TaskPriority.LOW,
            initial_delay=120.0,
        )
    )
    log.info("fw_tasks: scheduled %d repeating cadences", len(scheduled))
    return scheduled


async def bootstrap(
    *,
    bind_host: str = "127.0.0.1",
    port: int = 40006,
    public_base: Optional[str] = None,
    worker_count: int = 4,
) -> Client:
    """One-call bootstrap for :mod:`main`.

    Starts a client, wires the default cadences, prints the access banner,
    and returns the running client so the caller can ``await client.stop()``
    on shutdown.
    """
    client = build_client(worker_count=worker_count)
    await client.start()
    await schedule_defaults(client)
    task_queue.print_access_banner(bind_host, port, public_base=public_base)
    return client


__all__ = [
    "active_health_batch",
    "dead_revival_batch",
    "ingest_sources",
    "discover_playlist",
    "epg_refresh",
    "icon_prefetch_batch",
    "build_client",
    "schedule_defaults",
    "bootstrap",
]
