"""Playlist parsing, source aggregation, master-manifest expansion, and small
icon-name / country / language inference helpers used across ingest and SEO.
"""

import logging
import os
import re
import urllib.parse

import requests

from config import (
    EXPAND_ON_INGEST,
    EXTRA_M3U_URLS_ENV,
    HEADERS,
    MAX_EXPANSION_DEPTH,
    MAX_VARIANTS_PER_CHANNEL,
    SCRAPE_VARIANT_MODE,
)
from .sources import (
    ALL_DIRECT_SOURCES,
    EXCEPTION_CHANNELS,
    GLOBAL_SOURCES,
    PUBLIC_NEWS_LIST_SOURCES,
)


def check_channels(m3u_url):
    """Parse M3U playlist and return channel list with redirect detection and quality optimization."""
    try:
        response = requests.get(m3u_url, timeout=30, headers=HEADERS)
        if response.status_code == 200:
            content = response.text
            channels = []
            current_channel = {}

            for line in content.split('\n'):
                line = line.strip()
                if line.startswith('#EXTINF:'):
                    # Parse channel info
                    parts = line.split(',')
                    # The channel name is the last part after the comma
                    if len(parts) > 1:
                        current_channel['name'] = parts[-1].strip()

                    # Parse attributes from the first part
                    attr_part = parts[0]
                    for attr in attr_part.split():
                        if attr.startswith('tvg-name='):
                            current_channel['name'] = attr.split('=')[1].strip('"')
                        elif attr.startswith('tvg-logo='):
                            current_channel['tvg_logo'] = attr.split('=')[1].strip('"')
                        elif attr.startswith('tvg-id='):
                            current_channel['tvg_id'] = attr.split('=')[1].strip('"')
                        elif attr.startswith('group-title='):
                            current_channel['group_title'] = attr.split('=')[1].strip('"')
                        elif attr.startswith('channel-id='):
                            current_channel['tvg_id'] = attr.split('=')[1].strip('"')

                elif line.startswith('http') and current_channel:
                    original_url = line.strip()

                    # Temporarily disable redirect processing to get channels loading
                    processed_url = original_url  # process_stream_url(original_url)

                    current_channel['url'] = processed_url
                    current_channel['playing_now'] = 'Not available'
                    current_channel['status'] = 'unknown'
                    channels.append(current_channel.copy())
                    current_channel = {}

            # Add exception channels
            channels.extend(EXCEPTION_CHANNELS)

            return channels
        else:
            logging.error(f"Failed to fetch M3U playlist: {response.status_code}")
            return []
    except Exception as e:
        logging.error(f"Error parsing M3U playlist: {e}")
        return []


def channel_icon_safe_name(channel_name):
    return re.sub(r'[^\w\-_\.]', '', (channel_name or 'channel').lower())


def guess_image_ext(content_type, source_url):
    ct = (content_type or '').lower()
    if 'webp' in ct:
        return '.webp'
    if 'jpeg' in ct or 'jpg' in ct:
        return '.jpg'
    if 'gif' in ct:
        return '.gif'
    if 'png' in ct:
        return '.png'
    low = (source_url or '').lower()
    for ext in ('.webp', '.jpg', '.jpeg', '.png', '.gif'):
        if low.split('?')[0].endswith(ext):
            return '.jpg' if ext == '.jpeg' else ext
    return '.png'


def find_local_icon_url(safe_name):
    """Return URL path for an already-cached icon, or None."""
    for ext in ('.png', '.webp', '.jpg', '.jpeg', '.gif'):
        rel = f'webroot/icons/{safe_name}{ext}'
        if os.path.exists(rel):
            return f'/icons/{safe_name}{ext}'
    return None


def infer_country(channel, source_url=None):
    """Infer country code from channel metadata or source URL."""
    from features.storage.geo import resolve_country_code

    return resolve_country_code(channel or {}, source_url) or "GLOBAL"


def infer_language_code(url):
    """Best-effort language code inference from URL path."""
    try:
        match = re.search(r'/languages/([a-z]{2})\.m3u', url, re.IGNORECASE)
        if match:
            return match.group(1).upper()
    except Exception:
        pass
    return None


def parse_url_list_content(content):
    """Parse plain-text URL list content."""
    urls = []
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('http://') or line.startswith('https://'):
            urls.append(line)
    return urls


def get_extra_m3u_sources():
    """Return externally configured playlist sources (comma/newline separated URLs)."""
    if not EXTRA_M3U_URLS_ENV:
        return []
    raw = EXTRA_M3U_URLS_ENV.replace('\n', ',')
    urls = [u.strip() for u in raw.split(',') if u.strip()]
    return [u for u in urls if u.startswith('http://') or u.startswith('https://')]


def parse_variant_attributes(attr_line):
    """Parse #EXT-X-STREAM-INF and #EXT-X-MEDIA attributes."""
    attrs = {}
    for part in attr_line.split(','):
        if '=' not in part:
            continue
        key, value = part.split('=', 1)
        attrs[key.strip().upper()] = value.strip().strip('"')
    return attrs


def expand_master_manifest(channel, content, base_url):
    """Expand master playlist variants into channel entries."""
    variants = []
    pending_stream_inf = None
    media_lang = {}

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if line.startswith('#EXT-X-MEDIA:'):
            attrs = parse_variant_attributes(line.split(':', 1)[1])
            if attrs.get('TYPE') == 'AUDIO' and attrs.get('GROUP-ID'):
                media_lang[attrs['GROUP-ID']] = attrs.get('LANGUAGE') or attrs.get('NAME')
        elif line.startswith('#EXT-X-STREAM-INF:'):
            pending_stream_inf = parse_variant_attributes(line.split(':', 1)[1])
        elif pending_stream_inf and line and not line.startswith('#'):
            resolved = urllib.parse.urljoin(base_url, line)
            bandwidth = pending_stream_inf.get('BANDWIDTH')
            resolution = pending_stream_inf.get('RESOLUTION')
            audio_group = pending_stream_inf.get('AUDIO')
            audio_lang = media_lang.get(audio_group) if audio_group else None

            v = channel.copy()
            v['url'] = resolved
            v['variant_of'] = channel.get('url')
            v['variant_bandwidth'] = int(bandwidth) if str(bandwidth).isdigit() else None
            v['variant_quality'] = resolution or 'auto'
            v['audio_language'] = (audio_lang or infer_language_code(resolved) or '').upper() or None
            display_suffix = []
            if v['variant_quality']:
                display_suffix.append(v['variant_quality'])
            if v['audio_language']:
                display_suffix.append(v['audio_language'])
            if display_suffix:
                v['display_name'] = f"{v.get('name', 'Channel')} [{' | '.join(display_suffix)}]"
            variants.append(v)
            pending_stream_inf = None

            if len(variants) >= MAX_VARIANTS_PER_CHANNEL:
                break

    if not variants:
        return [channel]

    # best_only mode preserves old behavior but still captures metadata.
    if SCRAPE_VARIANT_MODE == 'best_only':
        variants.sort(key=lambda x: x.get('variant_bandwidth') or 0, reverse=True)
        best = variants[0]
        best['name'] = best.get('display_name', best.get('name'))
        return [best]

    return variants


def maybe_expand_channel(channel, depth=0):
    """Expand channel recursively for nested manifests and variant streams."""
    if depth >= MAX_EXPANSION_DEPTH:
        return [channel]

    url = channel.get('url', '')
    if not url:
        return [channel]

    # Only expand playlist-like URLs.
    if not any(token in url.lower() for token in ('.m3u8', '.m3u', 'playlist', 'manifest')):
        return [channel]

    try:
        response = requests.get(url, timeout=10, headers=HEADERS)
        if response.status_code != 200:
            return [channel]

        content = response.text.strip()
        if not content:
            return [channel]

        # Master playlist with variant streams.
        if '#EXT-X-STREAM-INF:' in content:
            variants = expand_master_manifest(channel, content, url)
            expanded = []
            for variant in variants:
                expanded.extend(maybe_expand_channel(variant, depth + 1))
            return expanded[:MAX_VARIANTS_PER_CHANNEL]

        # Nested playlist that points to more links in plain text.
        plain_urls = parse_url_list_content(content)
        if plain_urls and '#EXTINF:' not in content:
            children = []
            for nested_url in plain_urls[:MAX_VARIANTS_PER_CHANNEL]:
                child = channel.copy()
                child['url'] = urllib.parse.urljoin(url, nested_url)
                child['variant_of'] = channel.get('url')
                child['audio_language'] = infer_language_code(child['url'])
                children.append(child)
            expanded = []
            for child in children:
                expanded.extend(maybe_expand_channel(child, depth + 1))
            return expanded[:MAX_VARIANTS_PER_CHANNEL]

        return [channel]
    except Exception:
        return [channel]


def expand_channel_for_ingest(channel):
    """Apply maybe_expand_channel only when IPTV_EXPAND_ON_INGEST is enabled."""
    if not EXPAND_ON_INGEST:
        return [channel]
    return maybe_expand_channel(channel)


def check_all_global_sources():
    """Parse ALL global sources and return aggregated channel list with deduplication."""
    all_channels = []
    seen_urls = set()
    source_stats = {}

    logging.info("Starting COMPLETE global source aggregation...")
    logging.info(
        "Per-stream ingest expansion is %s (IPTV_EXPAND_ON_INGEST=%r to change)",
        "ON" if EXPAND_ON_INGEST else "OFF",
        os.environ.get("IPTV_EXPAND_ON_INGEST", "0"),
    )

    # Add direct sources (verified + FAST/public)
    logging.info("Adding direct source pack (verified + FAST/public)...")
    all_direct_sources = ALL_DIRECT_SOURCES

    for name, url, group in all_direct_sources:
        if url not in seen_urls:
            channel = {
                'name': name,
                'url': url,
                'tvg_id': f"direct_{name.lower().replace(' ', '_').replace('/', '_').replace('(', '_').replace(')', '_')}",
                'tvg_logo': '',
                'group_title': group,
                'playing_now': 'Not available',
                'status': 'unknown',
                'country': 'GLOBAL'
            }
            all_channels.append(channel)
            seen_urls.add(url)

    logging.info(f"Added {len(all_direct_sources)} direct channels")

    # Process all M3U sources
    all_m3u_sources = [GLOBAL_SOURCES["main"]]

    # Add all category sources
    for category, sources in GLOBAL_SOURCES.items():
        if category != "main" and isinstance(sources, list):
            all_m3u_sources.extend(sources)
        elif category != "main" and isinstance(sources, str):
            all_m3u_sources.append(sources)

    # Add extra public news/public-service playlists
    all_m3u_sources.extend(PUBLIC_NEWS_LIST_SOURCES)

    # Add externally configured M3U sources (e.g. Jellyfin/FastChannels output URLs)
    all_m3u_sources.extend(get_extra_m3u_sources())

    logging.info(f"Processing {len(all_m3u_sources)} M3U sources...")

    # Process each M3U source
    for i, source_url in enumerate(all_m3u_sources):
        try:
            logging.info(f"Processing source {i+1}/{len(all_m3u_sources)}: {source_url}")

            response = requests.get(source_url, timeout=30, headers=HEADERS)
            if response.status_code == 200:
                content = response.text
                source_channels = []
                current_channel = {}
                plain_links = parse_url_list_content(content)
                if plain_links and '#EXTINF:' not in content:
                    for plain_url in plain_links:
                        if plain_url not in seen_urls:
                            channel_name = urllib.parse.urlparse(plain_url).path.split('/')[-1] or "Stream"
                            plain_channel = {
                                'name': channel_name,
                                'url': plain_url,
                                'tvg_id': '',
                                'tvg_logo': '',
                                'group_title': 'Ungrouped',
                                'playing_now': 'Not available',
                                'status': 'unknown',
                                'country': infer_country({}, source_url),
                                'audio_language': infer_language_code(plain_url),
                            }
                            expanded_plain = expand_channel_for_ingest(plain_channel)
                            for ex in expanded_plain:
                                ex_url = ex.get('url')
                                if ex_url and ex_url not in seen_urls:
                                    source_channels.append(ex)
                                    seen_urls.add(ex_url)

                for line in content.split('\n'):
                    line = line.strip()
                    if line.startswith('#EXTINF:'):
                        # Parse channel info
                        parts = line.split(',')
                        if len(parts) > 1:
                            current_channel['name'] = parts[-1].strip()

                        # Parse attributes
                        attr_part = parts[0]
                        for attr in attr_part.split():
                            if attr.startswith('tvg-name='):
                                current_channel['name'] = attr.split('=')[1].strip('"')
                            elif attr.startswith('tvg-logo='):
                                current_channel['tvg_logo'] = attr.split('=')[1].strip('"')
                            elif attr.startswith('tvg-id='):
                                current_channel['tvg_id'] = attr.split('=')[1].strip('"')
                            elif attr.startswith('group-title='):
                                current_channel['group_title'] = attr.split('=')[1].strip('"')
                            elif attr.startswith('channel-id='):
                                current_channel['tvg_id'] = attr.split('=')[1].strip('"')

                    elif line.startswith('http') and current_channel:
                        url = line.strip()

                        # Skip if we've already seen this URL (deduplication)
                        if url not in seen_urls:
                            current_channel['url'] = url
                            current_channel['playing_now'] = 'Not available'
                            current_channel['status'] = 'unknown'
                            current_channel['country'] = infer_country(current_channel, source_url)
                            current_channel['audio_language'] = infer_language_code(source_url) or infer_language_code(url)

                            # Add source prefix to group for tracking
                            if 'group_title' not in current_channel:
                                current_channel['group_title'] = 'Unknown'

                            expanded_channels = expand_channel_for_ingest(current_channel.copy())
                            for ex in expanded_channels:
                                ex_url = ex.get('url')
                                if ex_url and ex_url not in seen_urls:
                                    source_channels.append(ex)
                                    seen_urls.add(ex_url)

                        current_channel = {}

                # Add source channels to main list
                all_channels.extend(source_channels)
                source_stats[source_url] = len(source_channels)
                logging.info(f"Added {len(source_channels)} channels from {source_url}")

            else:
                logging.warning(f"Failed to fetch source {source_url}: {response.status_code}")
                source_stats[source_url] = 0

        except Exception as e:
            logging.error(f"Error processing source {source_url}: {e}")
            source_stats[source_url] = 0

    # Add exception channels
    for channel in EXCEPTION_CHANNELS:
        if channel['url'] not in seen_urls:
            all_channels.append(channel)
            seen_urls.add(channel['url'])

    # Log comprehensive statistics
    logging.info("COMPLETE global source aggregation finished!")
    logging.info(f"Total unique channels: {len(all_channels)}")
    logging.info(f"Direct sources: {len(all_direct_sources)}")
    logging.info(f"M3U sources: {len(all_m3u_sources)}")
    logging.info("Source breakdown:")
    for source, count in source_stats.items():
        if count > 0:
            logging.info(f"  {source}: {count} channels")

    # Log category statistics
    category_counts = {}
    for channel in all_channels:
        group = channel.get('group_title', 'Unknown')
        category_counts[group] = category_counts.get(group, 0) + 1

    logging.info("Category breakdown:")
    for category, count in sorted(category_counts.items()):
        logging.info(f"  {category}: {count} channels")

    return all_channels


def process_stream_url(url):
    """Process stream URL to detect redirects and extract quality variants."""
    try:
        # Check if URL is a redirect or playlist
        if '.m3u8' in url.lower():
            return process_m3u8_playlist(url)
        else:
            # For direct streams, check for redirects
            return check_redirect_chain(url)
    except Exception as e:
        logging.warning(f"Error processing stream URL {url}: {e}")
        return url


def process_m3u8_playlist(playlist_url):
    """Process M3U8 playlist to extract all quality variants."""
    try:
        response = requests.get(playlist_url, timeout=10, headers=HEADERS)
        if response.status_code == 200:
            content = response.text
            variants = []
            bandwidth = None
            resolution = None
            codecs = None

            for line in content.split('\n'):
                line = line.strip()
                if line.startswith('#EXT-X-STREAM-INF:'):
                    # Extract quality info
                    bandwidth = None
                    resolution = None
                    codecs = None

                    parts = line.split(',')
                    for part in parts:
                        part = part.strip()
                        if part.startswith('BANDWIDTH='):
                            bandwidth = int(part.split('=')[1])
                        elif part.startswith('RESOLUTION='):
                            resolution = part.split('=')[1]
                        elif part.startswith('CODECS='):
                            codecs = part.split('=')[1]

                elif line.startswith('http') and bandwidth:
                    variants.append({
                        'url': line,
                        'bandwidth': bandwidth,
                        'resolution': resolution,
                        'codecs': codecs
                    })

            if variants:
                # Sort by bandwidth (highest quality first)
                variants.sort(key=lambda x: x['bandwidth'], reverse=True)

                # Log all variants for debugging
                for i, variant in enumerate(variants):
                    logging.info(f"Quality variant {i+1}: {variant['resolution']} ({variant['bandwidth']} bps)")

                # Return the highest quality variant
                best_variant = variants[0]
                logging.info(f"Selected best quality: {best_variant['resolution']} ({best_variant['bandwidth']} bps)")
                return best_variant['url']

        return playlist_url  # Fallback to original if processing fails
    except Exception as e:
        logging.warning(f"Error processing M3U8 playlist {playlist_url}: {e}")
        return playlist_url


def check_redirect_chain(url, max_depth=3):
    """Check redirect chain and find final working URL."""
    try:
        current_url = url
        redirect_chain = []

        for depth in range(max_depth):
            # Check if current URL is accessible
            response = requests.head(current_url, timeout=10, headers=HEADERS, allow_redirects=True)

            if response.status_code == 200:
                # Check if we were redirected
                if response.url != current_url:
                    redirect_chain.append({
                        'from': current_url,
                        'to': response.url,
                        'status': response.status_code
                    })
                    logging.info(f"Redirect {depth+1}: {current_url} -> {response.url}")
                    current_url = response.url
                else:
                    # No more redirects, we found the final URL
                    if redirect_chain:
                        logging.info(f"Final URL after {len(redirect_chain)} redirects: {current_url}")
                    return current_url
            else:
                logging.warning(f"Redirect chain broken at depth {depth}: {current_url} (status: {response.status_code})")
                return url  # Return last known good URL

        logging.warning(f"Redirect chain too deep, returning: {current_url}")
        return current_url

    except Exception as e:
        logging.warning(f"Error checking redirect chain for {url}: {e}")
        return url
