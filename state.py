"""Mutable runtime state shared across IPTV Scanner modules.

Import as `import state` so that assignments (state.CHANNEL_STATE_REVISION += 1)
mutate the shared module attribute rather than a local rebound name.
"""

CHANNEL_STATE_REVISION = 0
SCAN_ACTIVE = False

LAST_SWEEP_STARTED_AT = None
LAST_SWEEP_COMPLETED_AT = None
LAST_SWEEP_COUNTS = {"valid": 0, "dead": 0}

last_update_count = 0

image_cache = {}
last_cache_clear = 0

# Learned from the Host / X-Forwarded-* of real browser/API requests so absolute
# URLs (API, SEO, M3U) match whatever domain.tld or ip:port users call from.
LEARNED_PUBLIC_BASE = ""
