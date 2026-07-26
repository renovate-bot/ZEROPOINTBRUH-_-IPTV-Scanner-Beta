"""FastWorker-compatible task queue adapter.

The project targets `fastworker`_ once we can move to Python 3.12+. Until
then this module provides a drop-in adapter that mirrors the small slice of
the FastWorker API we actually use (``@task``, ``TaskPriority``, ``Client``
with ``start``/``stop``/``delay``/``schedule_repeat``) on top of a plain
``asyncio.PriorityQueue`` worker pool.

Selection order
---------------
1. If ``IPTV_FW_EMBED`` is truthy (default ``"1"``) we always use the
   in-process implementation. This keeps behaviour deterministic in dev,
   test, and CI regardless of whatever else is on ``PYTHONPATH``.
2. Otherwise we ``import fastworker`` and re-export its ``task``,
   ``TaskPriority`` and ``Client`` symbols. Callers do not have to care
   which backend is live.

Everything else in this module (``log_worker_batch``,
``print_access_banner``, ``get_lan_ip``) works with either backend so the
Flask entry point can call them unconditionally.

.. _fastworker: https://pypi.org/project/fastworker/
"""

from __future__ import annotations

import asyncio
import enum
import functools
import inspect
import logging
import os
import socket
import time
import uuid
from typing import Any, Awaitable, Callable, Iterable, Optional


IPTV_FW_EMBED = os.environ.get("IPTV_FW_EMBED", "1").strip().lower() in (
    "1", "true", "yes", "on",
)

log = logging.getLogger("task_queue")


# ---------------------------------------------------------------------------
# Backend selection
# ---------------------------------------------------------------------------

_fastworker = None
_HAS_REAL_FW = False
if not IPTV_FW_EMBED:
    try:  # pragma: no cover - only exercised on Python 3.12+ with fastworker
        import fastworker as _fastworker  # type: ignore
        _HAS_REAL_FW = True
    except Exception as exc:
        log.info("fastworker unavailable (%s); falling back to in-process queue", exc)
        _fastworker = None
        _HAS_REAL_FW = False


def is_real_fastworker() -> bool:
    """Return ``True`` when the real ``fastworker`` package is driving jobs."""
    return _HAS_REAL_FW


# ---------------------------------------------------------------------------
# Public API — priority + registry (identical shape whether real FW or not)
# ---------------------------------------------------------------------------

if _HAS_REAL_FW:
    task = _fastworker.task  # type: ignore[attr-defined]
    TaskPriority = _fastworker.TaskPriority  # type: ignore[attr-defined]
    Client = _fastworker.Client  # type: ignore[attr-defined]

else:

    class TaskPriority(enum.IntEnum):
        """FastWorker-compatible priority ladder (lower = more urgent)."""

        CRITICAL = 0
        HIGH = 1
        NORMAL = 2
        LOW = 3

    _REGISTRY: dict[str, Callable[..., Any]] = {}

    def task(
        name: Optional[str] = None,
        *,
        priority: TaskPriority = TaskPriority.NORMAL,
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Register ``fn`` under a named entry point.

        ``fn`` may be sync or async. The decorator returns the original
        callable so it can still be invoked directly in tests.
        """

        def wrap(fn: Callable[..., Any]) -> Callable[..., Any]:
            key = name or fn.__name__
            _REGISTRY[key] = fn
            setattr(fn, "__fw_name__", key)
            setattr(fn, "__fw_priority__", priority)
            return fn

        return wrap

    def _registered_tasks() -> dict[str, Callable[..., Any]]:
        return dict(_REGISTRY)

    class _Job:
        __slots__ = ("priority", "seq", "task_id", "name", "args", "kwargs")

        def __init__(
            self,
            priority: int,
            seq: int,
            task_id: str,
            name: str,
            args: tuple,
            kwargs: dict,
        ) -> None:
            self.priority = int(priority)
            self.seq = seq
            self.task_id = task_id
            self.name = name
            self.args = args
            self.kwargs = kwargs

        def __lt__(self, other: "_Job") -> bool:
            return (self.priority, self.seq) < (other.priority, other.seq)

    class Client:
        """Small in-process replacement for :class:`fastworker.Client`."""

        def __init__(
            self,
            *,
            worker_count: int = 4,
            name: str = "iptv-scanner",
        ) -> None:
            self.worker_count = max(1, int(worker_count))
            self.name = name
            self._queue: Optional[asyncio.PriorityQueue[_Job]] = None
            self._workers: list[asyncio.Task] = []
            self._scheduled: list[asyncio.Task] = []
            self._seq = 0
            self._running = False
            self._log = logging.getLogger(f"task_queue.{name}")

        async def start(self) -> None:
            if self._running:
                return
            self._queue = asyncio.PriorityQueue()
            self._running = True
            for i in range(self.worker_count):
                t = asyncio.create_task(self._worker_loop(i), name=f"fw-{self.name}-{i}")
                self._workers.append(t)
            self._log.info(
                "started in-process task queue: %d worker%s, %d task%s registered",
                self.worker_count, "" if self.worker_count == 1 else "s",
                len(_REGISTRY), "" if len(_REGISTRY) == 1 else "s",
            )

        async def stop(self) -> None:
            if not self._running:
                return
            self._running = False
            for t in self._scheduled:
                t.cancel()
            for t in self._workers:
                t.cancel()
            await asyncio.gather(*self._scheduled, return_exceptions=True)
            await asyncio.gather(*self._workers, return_exceptions=True)
            self._scheduled.clear()
            self._workers.clear()
            self._queue = None
            self._log.info("in-process task queue stopped")

        async def delay(
            self,
            name: str,
            *args: Any,
            priority: TaskPriority = TaskPriority.NORMAL,
            **kwargs: Any,
        ) -> str:
            """Enqueue a registered task; returns a short opaque task id."""
            if name not in _REGISTRY:
                raise KeyError(f"task not registered: {name}")
            if self._queue is None:
                raise RuntimeError("task queue not started")
            self._seq += 1
            task_id = uuid.uuid4().hex[:12]
            await self._queue.put(
                _Job(int(priority), self._seq, task_id, name, tuple(args), dict(kwargs))
            )
            return task_id

        def schedule_repeat(
            self,
            name: str,
            interval_sec: float,
            *args: Any,
            priority: TaskPriority = TaskPriority.NORMAL,
            initial_delay: float = 0.0,
            **kwargs: Any,
        ) -> asyncio.Task:
            """Schedule ``name`` to run every ``interval_sec`` seconds.

            The returned :class:`asyncio.Task` can be cancelled to stop
            further enqueues (already-running jobs are unaffected).
            """
            if name not in _REGISTRY:
                raise KeyError(f"task not registered: {name}")

            async def _loop() -> None:
                if initial_delay > 0:
                    try:
                        await asyncio.sleep(initial_delay)
                    except asyncio.CancelledError:
                        return
                while self._running:
                    try:
                        await self.delay(name, *args, priority=priority, **kwargs)
                    except Exception as exc:  # noqa: BLE001
                        self._log.warning("schedule_repeat: %s enqueue failed: %s", name, exc)
                    try:
                        await asyncio.sleep(interval_sec)
                    except asyncio.CancelledError:
                        return

            t = asyncio.create_task(_loop(), name=f"fw-sched-{name}")
            self._scheduled.append(t)
            return t

        async def _worker_loop(self, idx: int) -> None:
            assert self._queue is not None
            while True:
                try:
                    job = await self._queue.get()
                except asyncio.CancelledError:
                    return
                fn = _REGISTRY.get(job.name)
                if fn is None:
                    self._log.error("no such task: %s (id=%s)", job.name, job.task_id)
                    continue
                started = time.perf_counter()
                try:
                    if inspect.iscoroutinefunction(fn):
                        await fn(*job.args, **job.kwargs)
                    else:
                        loop = asyncio.get_running_loop()
                        await loop.run_in_executor(
                            None, functools.partial(fn, *job.args, **job.kwargs)
                        )
                except asyncio.CancelledError:
                    return
                except Exception:  # noqa: BLE001
                    self._log.exception("task %s (id=%s) failed", job.name, job.task_id)
                finally:
                    dur = time.perf_counter() - started
                    self._log.debug(
                        "task %s (id=%s) done in %.2fs", job.name, job.task_id, dur,
                    )


# ---------------------------------------------------------------------------
# Console helpers — usable with either backend
# ---------------------------------------------------------------------------

_BOX_MIN_WIDTH = 44


def log_worker_batch(
    worker_name: str,
    lines: Iterable[str],
    limit: int = 5,
) -> None:
    """Emit a boxed batch summary to the shared logger.

    Format::

        ──────── [active-health] batch ────────
          ✓ Channel Name status
          ✗ Broken Channel http_404
        ──────────────────────────────────────

    Only the first ``limit`` lines are shown verbatim; the remainder is
    collapsed into a single ``… (+N more)`` line so long batches do not
    flood the console.
    """
    materialised = [str(line) for line in lines]
    shown = materialised[: max(0, limit)]
    remaining = max(0, len(materialised) - len(shown))
    if remaining:
        shown.append(f"… (+{remaining} more)")

    header_label = f" [{worker_name}] batch "
    content_width = max(
        _BOX_MIN_WIDTH,
        len(header_label) + 16,
        *(len(s) + 4 for s in shown),
    )
    dashes = "─" * max(4, (content_width - len(header_label)) // 2)
    top = f"{dashes}{header_label}{dashes}"
    bottom = "─" * len(top)

    out = [top]
    for s in shown:
        out.append(f"  {s}")
    out.append(bottom)

    logging.getLogger("task_queue.batch").info("\n%s", "\n".join(out))


def get_lan_ip() -> str:
    """Best-effort LAN IP for the current host.

    We open (but never send on) a UDP socket toward a public address so the
    OS routing table picks the interface it would actually use for outbound
    traffic. Falls back to ``127.0.0.1`` if resolution fails.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return "127.0.0.1"
    finally:
        try:
            s.close()
        except Exception:
            pass


def print_access_banner(
    bind_host: str,
    port: int,
    public_base: Optional[str] = None,
) -> None:
    """Print a Local / Network / Public URL banner to the console.

    Also notes which task-queue backend is live so operators can tell at a
    glance whether the FastWorker GUI is available or we are running the
    embedded fallback.
    """
    lan_ip = get_lan_ip()
    host_display = bind_host if bind_host not in ("", "0.0.0.0", "::", "*") else "127.0.0.1"
    local_url = f"http://{host_display}:{port}"
    network_url = f"http://{lan_ip}:{port}"
    public_url = (public_base or "").strip().rstrip("/") or "(not configured)"

    if _HAS_REAL_FW:
        queue_note = "FastWorker task queue (GUI available)"
    else:
        queue_note = "in-process task queue (FastWorker not embedded)"

    lines = [
        "  IPTV Scanner is up",
        "",
        f"  Local   → {local_url}",
        f"  Network → {network_url}",
        f"  Public  → {public_url}",
        "",
        f"  Tasks   → {queue_note}",
    ]

    width = max(len(s) for s in lines) + 4
    border = "─" * width
    top = f"┌{border}┐"
    bottom = f"└{border}┘"

    boxed = [top]
    for s in lines:
        pad = " " * (width - len(s) - 2)
        boxed.append(f"│ {s}{pad} │")
    boxed.append(bottom)

    logging.getLogger("task_queue.banner").info("\n%s", "\n".join(boxed))
