"""Feature packages — domain logic lives in subfolders under ``features/``.

Site-wide pieces (``config``, ``state``, Flask app/routes) stay at the repo root.
"""

__all__ = [
    "storage",
    "ingest",
    "validate",
    "icons",
    "seo",
    "workers",
]
