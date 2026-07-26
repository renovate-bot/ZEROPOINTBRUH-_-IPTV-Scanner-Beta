"""All Flask route handlers.

Imported for side-effects: importing this module attaches every `@app.route`
handler to the singleton :data:`app_factory.app`.
"""

import asyncio
import datetime
import json
import logging
import mimetypes
import os
import re
import threading
import time
import urllib.parse
from email.utils import format_datetime
from urllib.parse import quote
from xml.sax.saxutils import escape as xml_escape

import requests
import yt_dlp
from flask import (
    Response,
    abort,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    stream_with_context,
)

import state
from app_factory import app
from features.storage.channels_io import get_valid_channels, load_json_file
from config import (
    FILES,
    HEADERS,
    IPTV_PLAYLIST_SECRET,
    IPTV_SITE_NAME,
    SWEEP_INTERVAL_SEC,
)
from features.icons.icons import download_channel_icon
from features.ingest.ingest import channel_icon_safe_name, find_local_icon_url, infer_country
from features.seo.seo import (
    SEO_RESERVED_SLUGS,
    SEO_SLUG_RE,
    build_proxied_live_m3u,
    seo_abs_url,
    seo_json_ld_broadcast,
    seo_meta_for_channel,
    seo_og_image_for_channel,
    seo_public_base_url,
    seo_refresh_slug_index,
    seo_slug_snapshot,
)
from features.workers.workers import initial_scan, sweep_channels_async


# --- SEO endpoints ------------------------------------------------------------

@app.route("/robots.txt")
def seo_robots_txt():
    base = seo_public_base_url()
    body = (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /proxy/\n"
        "Disallow: /api/\n"
        "Disallow: /export/\n"
        "Disallow: /admin/\n"
        f"\nSitemap: {base}/sitemap.xml\n"
    )
    return Response(body, mimetype="text/plain; charset=utf-8")


@app.route("/sitemap.xml")
def seo_sitemap_xml():
    """Sitemap index pointing at live + videos sitemaps."""
    base = seo_public_base_url()
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    body = "\n".join([
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
        "<sitemap>",
        f"  <loc>{xml_escape(base + '/sitemap-live.xml')}</loc>",
        f"  <lastmod>{now}</lastmod>",
        "</sitemap>",
        "<sitemap>",
        f"  <loc>{xml_escape(base + '/sitemap-videos.xml')}</loc>",
        f"  <lastmod>{now}</lastmod>",
        "</sitemap>",
        "</sitemapindex>",
    ])
    return Response(body, mimetype="application/xml; charset=utf-8")


def _sitemap_urlset(media_type=None):
    seo_refresh_slug_index()
    slug_map, slugs_sorted = seo_slug_snapshot()
    base = seo_public_base_url()
    urls = [base + "/"] if media_type in (None, "live") else []
    for slug in slugs_sorted:
        ch = slug_map.get(slug) or {}
        if (ch.get("group_title") or "") == "Test":
            continue
        mt = (ch.get("media_type") or "unknown").lower()
        if media_type == "live" and mt == "vod":
            continue
        if media_type == "vod" and mt != "vod":
            continue
        if (ch.get("status") or "").lower() != "online":
            continue
        urls.append(f"{base}/{slug}")
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    for loc in urls:
        lines.append("<url>")
        lines.append(f"  <loc>{xml_escape(loc)}</loc>")
        lines.append(f"  <lastmod>{now}</lastmod>")
        lines.append("  <changefreq>hourly</changefreq>")
        lines.append(f"  <priority>{'0.9' if loc.rstrip('/').endswith(base.rstrip('/')) or loc == base + '/' else '0.7'}</priority>")
        lines.append("</url>")
    lines.append("</urlset>")
    return Response("\n".join(lines), mimetype="application/xml; charset=utf-8")


@app.route("/sitemap-live.xml")
def seo_sitemap_live():
    return _sitemap_urlset("live")


@app.route("/sitemap-videos.xml")
def seo_sitemap_videos():
    return _sitemap_urlset("vod")


@app.route("/feed.xml")
def seo_rss_feed():
    seo_refresh_slug_index()
    slug_map, slugs_sorted = seo_slug_snapshot()
    base = seo_public_base_url()
    site = xml_escape(IPTV_SITE_NAME)
    link = xml_escape(base + "/")
    now = format_datetime(datetime.datetime.now(datetime.timezone.utc))
    items = []
    for slug in slugs_sorted:
        ch = slug_map[slug]
        meta = seo_meta_for_channel(ch)
        item_link = xml_escape(f"{base}/{slug}")
        title = xml_escape(meta["name"])
        desc = xml_escape(meta["description"])
        items.append(
            f"<item><title>{title}</title><link>{item_link}</link>"
            f"<guid isPermaLink=\"true\">{item_link}</guid>"
            f"<description>{desc}</description><pubDate>{now}</pubDate></item>"
        )
    rss = "\n".join(
        [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">',
            f'<channel><title>{site} — Live channels</title><link>{link}</link>',
            f"<description>Directory of live streams from {site}</description>",
            f'<atom:link href="{xml_escape(base + "/feed.xml")}" rel="self" type="application/rss+xml"/>',
            f"<lastBuildDate>{now}</lastBuildDate>",
            *items,
            "</channel></rss>",
        ]
    )
    return Response(rss, mimetype="application/rss+xml; charset=utf-8")


@app.route("/atom.xml")
def seo_atom_feed():
    seo_refresh_slug_index()
    slug_map, slugs_sorted = seo_slug_snapshot()
    base = seo_public_base_url()
    site = xml_escape(IPTV_SITE_NAME)
    self_link = xml_escape(base + "/atom.xml")
    index_link = xml_escape(base + "/")
    now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
    updated = format_datetime(now)
    entries = []
    for slug in slugs_sorted:
        ch = slug_map[slug]
        meta = seo_meta_for_channel(ch)
        u = xml_escape(f"{base}/{slug}")
        title = xml_escape(meta["name"])
        summary = xml_escape(meta["description"])
        entries.append(
            f"<entry><title>{title}</title><link href=\"{u}\"/><id>{u}</id>"
            f"<updated>{updated}</updated><summary>{summary}</summary></entry>"
        )
    atom = "\n".join(
        [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<feed xmlns="http://www.w3.org/2005/Atom">',
            f"<title>{site} — Channels</title>",
            f'<link href="{index_link}" rel="alternate"/>',
            f'<link href="{self_link}" rel="self"/>',
            f"<id>{index_link}</id><updated>{updated}</updated>",
            *entries,
            "</feed>",
        ]
    )
    return Response(atom, mimetype="application/atom+xml; charset=utf-8")


# --- Core UI + status ---------------------------------------------------------

@app.route('/')
def index():
    """Render the main TV guide page."""
    return render_template('index.html')


@app.route('/manifest.webmanifest')
def pwa_manifest():
    """Serve the PWA manifest at a root path (many browsers expect this)."""
    try:
        path = os.path.join(app.static_folder, 'manifest.webmanifest')
        if not os.path.exists(path):
            return jsonify({'error': 'manifest missing'}), 404
        return send_file(path, mimetype='application/manifest+json')
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/sw.js')
def pwa_service_worker():
    """Serve the service worker from origin root so its scope is '/'."""
    try:
        path = os.path.join(app.static_folder, 'sw.js')
        if not os.path.exists(path):
            return Response("// no sw", mimetype='application/javascript')
        resp = send_file(path, mimetype='application/javascript')
        resp.headers['Cache-Control'] = 'no-cache'
        resp.headers['Service-Worker-Allowed'] = '/'
        return resp
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/variants')
def api_variants():
    """Return HLS variant streams recorded for a given channel URL."""
    try:
        from features.storage.db import get_default_store
        url = (request.args.get('url') or '').strip()
        if not url:
            return jsonify({'variants': []})
        variants = get_default_store().get_variants(url) or []
        cleaned = []
        for v in variants:
            cleaned.append({
                'url': v.get('variant_url') or v.get('url') or '',
                'resolution': v.get('resolution') or v.get('variant_quality') or '',
                'bandwidth': v.get('bandwidth') or v.get('variant_bandwidth') or 0,
                'codecs': v.get('codecs') or '',
                'audio_language': v.get('audio_language') or '',
            })
        return jsonify({'variants': cleaned})
    except Exception as e:
        logging.error(f"variants api failed: {e}")
        return jsonify({'variants': [], 'error': str(e)})


@app.route('/status')
def get_status():
    """Return current scanning status and channel count."""
    try:
        from features.storage.db import get_default_store
        store = get_default_store()
        total = store.count_channels(status="online", exclude_test=True)
        online_ct = total
        rev = store.get_revision()
        state.CHANNEL_STATE_REVISION = rev
        return jsonify({
            'total_channels': total,
            'online_channels': online_ct,
            'scanning': state.SCAN_ACTIVE,
            'revision': rev,
            'sweep_interval_sec': SWEEP_INTERVAL_SEC,
            'last_sweep_started_at': state.LAST_SWEEP_STARTED_AT,
            'last_sweep_completed_at': state.LAST_SWEEP_COMPLETED_AT,
            'last_sweep_counts': state.LAST_SWEEP_COUNTS,
            'last_update': time.time(),
        })
    except Exception as e:
        return jsonify({'error': str(e)})


@app.route('/api/events')
def sse_channel_events():
    """Server-Sent Events: channel list revision and counts (for smooth live UI updates)."""
    def event_stream():
        last_rev = -1
        while True:
            try:
                from features.storage.db import get_default_store
                store = get_default_store()
                rev = store.get_revision()
                if rev != last_rev:
                    last_rev = rev
                    state.CHANNEL_STATE_REVISION = rev
                    total = store.count_channels(status="online", exclude_test=True)
                    payload = json.dumps({
                        'revision': rev,
                        'total_channels': total,
                        'online_channels': total,
                        'scanning': state.SCAN_ACTIVE,
                    })
                    yield f"data: {payload}\n\n"
                else:
                    yield ": ping\n\n"
            except Exception as err:
                yield f"data: {json.dumps({'error': str(err)})}\n\n"
            time.sleep(2)

    return Response(
        stream_with_context(event_stream()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no',
        },
    )


# --- Icons --------------------------------------------------------------------

@app.route('/icons/<filename>')
def serve_icon(filename):
    """Serve cached channel icons."""
    try:
        icon_path = f'webroot/icons/{filename}'
        if os.path.exists(icon_path):
            mt = mimetypes.guess_type(icon_path)[0] or 'image/png'
            return send_file(icon_path, mimetype=mt)
        else:
            return "Icon not found", 404
    except Exception as e:
        logging.error(f"Error serving icon {filename}: {e}")
        return "Error serving icon", 500


def get_channel_info(channel_name, channel_url):
    """Get current program information for a channel."""
    try:
        # For YouTube channels, try to get video title
        if 'youtube.com' in channel_url or 'youtu.be' in channel_url:
            try:
                if '/live' in channel_url:
                    return f" LIVE - {channel_name}"
                else:
                    return " Live Stream"
            except Exception:
                return " Live Stream"

        # For Twitch channels
        elif 'twitch.tv' in channel_url:
            return " Live Stream"

        # For other M3U8 streams
        elif '.m3u8' in channel_url:
            try:
                response = requests.get(channel_url, timeout=5, headers=HEADERS)
                if response.status_code == 200:
                    content = response.text
                    title_match = re.search(r'#EXT-X-STREAM-TITLE:(.+)', content, re.IGNORECASE)
                    if title_match:
                        return title_match.group(1).strip()
            except Exception:
                pass

        return f" {channel_name}"

    except Exception as e:
        logging.debug(f"Error getting channel info for {channel_name}: {e}")
        return f" {channel_name}"


@app.route('/channel-info/<channel_name>')
def get_channel_info_endpoint(channel_name):
    """API endpoint to get channel information."""
    try:
        with open(FILES['streams'], 'r') as f:
            channels = json.load(f)

        channel = None
        for ch in channels:
            if ch['name'] == channel_name:
                channel = ch
                break

        if channel:
            info = get_channel_info(channel['name'], channel['url'])
            return jsonify({
                'name': channel['name'],
                'playing_now': info,
                'status': channel.get('status', 'unknown')
            })
        else:
            return jsonify({'error': 'Channel not found'}), 404

    except Exception as e:
        logging.error(f"Error getting channel info: {e}")
        return jsonify({'error': str(e)}), 500


# --- Scan controls ------------------------------------------------------------

@app.route('/scan')
def trigger_scan():
    """Enqueue ingest + health via the task queue."""
    try:
        def _kick():
            async def _run():
                from features.workers import fw_tasks
                from features.workers.task_queue import Client
                c = Client(worker_count=2, name="scan-kick")
                await c.start()
                await c.delay("ingest_sources")
                await c.delay("active_health_batch")
                await asyncio.sleep(2)
                await c.stop()
            asyncio.run(_run())
        threading.Thread(target=_kick, daemon=True).start()
        return jsonify({'message': 'Ingest queued', 'status': 'scanning'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/sweep-now')
def trigger_sweep_now():
    """Enqueue active + dead health batches."""
    try:
        def _kick():
            async def _run():
                from features.workers.task_queue import Client
                c = Client(worker_count=2, name="sweep-kick")
                await c.start()
                await c.delay("active_health_batch")
                await c.delay("dead_revival_batch")
                await asyncio.sleep(2)
                await c.stop()
            asyncio.run(_run())
        threading.Thread(target=_kick, daemon=True).start()
        return jsonify({'message': 'Health check queued', 'status': 'sweeping'}), 202
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# --- Channel listing / export -------------------------------------------------

@app.route('/channels')
def get_channels():
    """Paginated channel list from SQLite (default page size 50)."""
    try:
        from features.storage.db import get_default_store
        store = get_default_store()
        page = max(1, int(request.args.get('page', 1) or 1))
        limit = min(100, max(1, int(request.args.get('limit', 50) or 50)))
        q = (request.args.get('q') or request.args.get('query') or '').strip() or None
        group = (request.args.get('group') or '').strip() or None
        country = (request.args.get('country') or '').strip() or None
        online_only = request.args.get('online_only', '0').lower() in ('1', 'true', 'yes')
        include_test = request.args.get('include_test', '0').lower() in ('1', 'true', 'yes')
        media_type = (request.args.get('media_type') or '').strip() or None
        # Default guide: live + unknown; exclude vod unless asked
        if media_type is None and request.args.get('videos', '0') not in ('1', 'true', 'yes'):
            media_type = 'live'
        if request.args.get('videos', '0').lower() in ('1', 'true', 'yes'):
            media_type = 'vod'
        status = 'online' if online_only or not request.args.get('status') else request.args.get('status')
        if request.args.get('pending', '0').lower() in ('1', 'true', 'yes'):
            status = 'pending'
            media_type = None
        sort = (request.args.get('sort') or 'name').strip()
        sort_dir = (request.args.get('sort_dir') or 'asc').strip()

        result = store.list_channels(
            page=page,
            limit=limit,
            q=q,
            group=group,
            country=country,
            online_only=online_only,
            include_test=include_test,
            media_type=media_type if media_type not in ('', 'all') else None,
            status=status,
            sort=sort,
            sort_dir=sort_dir,
        )
        channels = result.get('channels') or []
        for channel in channels:
            safe_name = channel_icon_safe_name(channel.get('name', ''))
            local_icon = find_local_icon_url(safe_name)
            if local_icon:
                channel['icon_url'] = local_icon
            channel['country'] = channel.get('country') or infer_country(channel)
            # quality_count hint for UI
            try:
                channel['quality_count'] = len(store.get_variants(channel.get('url') or ''))
            except Exception:
                channel['quality_count'] = 0

        state.CHANNEL_STATE_REVISION = result.get('revision') or store.get_revision()
        return jsonify({
            'channels': channels,
            'countries': result.get('countries') or [],
            'groups': result.get('groups') or [],
            'total_channels': result.get('total') or 0,
            'revision': state.CHANNEL_STATE_REVISION,
            'current_page': result.get('page') or page,
            'has_more': bool(result.get('has_more')),
            'total_pages': result.get('total_pages') or 1,
        })
    except Exception as e:
        logging.error(f"Error loading channels: {e}")
        return jsonify({'channels': [], 'total_channels': 0, 'error': str(e)})


@app.route('/export/IPTV_STREAMS_FILE.json')
def export_streams_file():
    """Full JSON array of online channels for external apps."""
    try:
        from features.storage.db import get_default_store
        channels = get_default_store().get_export_channels()
        return Response(
            json.dumps(channels, indent=2, ensure_ascii=False),
            mimetype='application/json',
            headers={'Content-Disposition': 'inline; filename=IPTV_STREAMS_FILE.json'},
        )
    except Exception as e:
        logging.error("export failed: %s", e)
        return jsonify([])


# --- Image proxy + icon bulk downloader ---------------------------------------

@app.route('/proxy/image')
def proxy_image():
    """Proxy image requests with caching and rate limiting."""
    try:
        image_url = request.args.get('url')
        if not image_url:
            return "No URL provided", 400

        # Check cache first
        if image_url in state.image_cache:
            cached_data = state.image_cache[image_url]
            if time.time() - cached_data['timestamp'] < 3600:  # Cache for 1 hour
                return Response(
                    cached_data['content'],
                    mimetype=cached_data['mimetype'],
                    headers={
                        'Cache-Control': 'public, max-age=3600',
                        'Access-Control-Allow-Origin': '*'
                    }
                )

        # Rate limiting - clear old cache entries periodically
        if time.time() - state.last_cache_clear > 300:  # Clear cache every 5 minutes
            current_time = time.time()
            state.image_cache = {k: v for k, v in state.image_cache.items()
                                 if current_time - v['timestamp'] < 1800}  # Keep entries < 30 minutes
            state.last_cache_clear = current_time

        response = requests.get(image_url, timeout=5, headers=HEADERS)

        if response.status_code == 200:
            state.image_cache[image_url] = {
                'content': response.content,
                'mimetype': response.headers.get('content-type', 'image/png'),
                'timestamp': time.time()
            }

            return Response(
                response.content,
                mimetype=response.headers.get('content-type', 'image/png'),
                headers={
                    'Cache-Control': 'public, max-age=3600',
                    'Access-Control-Allow-Origin': '*'
                }
            )
        else:
            return f"Failed to fetch image: {response.status_code}", response.status_code

    except Exception as e:
        logging.error(f"Error proxying image: {e}")
        return f"Error: {str(e)}", 500


@app.route('/download-icons')
def download_all_icons():
    """Download icons for all channels."""
    try:
        with open(FILES['streams'], 'r') as f:
            channels = json.load(f)

        downloaded = 0
        failed = 0

        for channel in channels:
            try:
                icon_url = download_channel_icon(channel['name'], channel['url'], channel.get('tvg_logo', ''))
                if icon_url:
                    downloaded += 1
                    logging.info(f"✅ Downloaded icon for {channel['name']}")
                else:
                    failed += 1
                    logging.info(f"❌ No icon found for {channel['name']}")
            except Exception as e:
                failed += 1
                logging.error(f"Error downloading icon for {channel['name']}: {e}")

        return jsonify({
            'message': 'Icon download complete',
            'downloaded': downloaded,
            'failed': failed,
            'total': len(channels)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/search')
def search_channels():
    """Search for channels by name."""
    try:
        query = request.args.get('query', '').lower()
        with open(FILES['streams'], 'r') as f:
            channels = json.load(f)
        return jsonify([ch for ch in channels if query in ch['name'].lower()])
    except Exception as e:
        logging.error(f"Error searching channels: {e}")
        return jsonify([])


# --- YouTube / Twitch stream URL extraction ----------------------------------

def get_youtube_stream_url(url):
    """Extract actual stream URL from YouTube using yt-dlp for reliable extraction."""
    try:
        logging.info(f"Attempting to extract YouTube stream from URL: {url}")

        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'format': 'best[height<=720]',  # Limit to 720p for performance
            'noplaylist': True,
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)

                if info:
                    if info.get('is_live'):
                        logging.info(f"Detected live stream: {info.get('title', 'Unknown')}")
                        formats = info.get('formats', [])
                        if formats:
                            best_format = None
                            for fmt in formats:
                                if fmt.get('vcodec') != 'none' and fmt.get('acodec') != 'none':
                                    if not best_format or fmt.get('height', 0) > best_format.get('height', 0):
                                        best_format = fmt

                            if best_format and best_format.get('url'):
                                stream_url = best_format['url']
                                logging.info(f"Extracted live stream URL: {stream_url}")
                                return stream_url
                    else:
                        formats = info.get('formats', [])
                        if formats:
                            best_format = None
                            for fmt in formats:
                                if fmt.get('vcodec') != 'none' and fmt.get('acodec') != 'none':
                                    if not best_format or fmt.get('height', 0) > best_format.get('height', 0):
                                        best_format = fmt

                            if best_format and best_format.get('url'):
                                stream_url = best_format['url']
                                logging.info(f"Extracted video stream URL: {stream_url}")
                                return stream_url

                    # Fallback to embed URL if no direct stream found
                    video_id = info.get('id')
                    if video_id:
                        embed_url = f"https://www.youtube.com/embed/{video_id}?autoplay=1&rel=0"
                        logging.info(f"Falling back to embed URL: {embed_url}")
                        return embed_url

        except Exception as e:
            logging.warning(f"yt-dlp extraction failed: {e}")
            return extract_youtube_url_basic(url)

    except ImportError:
        logging.error("yt-dlp not installed, falling back to basic extraction")
        return extract_youtube_url_basic(url)
    except Exception as e:
        logging.error(f"Error extracting YouTube URL: {e}")
        logging.error(f"Exception details: {type(e).__name__}: {str(e)}")
        return None


def extract_youtube_url_basic(url):
    """Basic YouTube URL extraction as fallback."""
    try:
        logging.info(f"Using basic YouTube extraction for: {url}")

        video_id = None

        if 'youtube.com/watch?v=' in url:
            video_id = url.split('v=')[1].split('&')[0]
            logging.info(f"Extracted video ID using pattern 1: {video_id}")
        elif 'youtu.be/' in url:
            video_id = url.split('youtu.be/')[1].split('?')[0]
            logging.info(f"Extracted video ID using pattern 2: {video_id}")
        elif 'youtube.com/embed/' in url:
            video_id = url.split('embed/')[1].split('?')[0]
            logging.info(f"Extracted video ID using pattern 3: {video_id}")
        elif '/live' in url:
            logging.info(f"Detected YouTube live stream URL: {url}")
            if '/@' in url:
                channel_handle = url.split('/@')[1].split('/')[0]
                logging.info(f"Extracted channel handle: {channel_handle}")
                return f"https://www.youtube.com/embed/live_stream?channel={channel_handle}"
            elif '/channel/' in url:
                channel_id = url.split('/channel/')[1].split('/')[0]
                logging.info(f"Extracted channel ID: {channel_id}")
                return f"https://www.youtube.com/embed/live_stream?channel={channel_id}"
            elif '/c/' in url:
                channel_name = url.split('/c/')[1].split('/')[0]
                logging.info(f"Extracted channel name: {channel_name}")
                return f"https://www.youtube.com/embed/live_stream?channel={channel_name}"
            elif '/user/' in url:
                username = url.split('/user/')[1].split('/')[0]
                logging.info(f"Extracted username: {username}")
                return f"https://www.youtube.com/embed/live_stream?channel={username}"
            else:
                logging.warning(f"Unknown live stream format: {url}")
                return None
        else:
            # Try to extract video ID using regex
            patterns = [
                r'(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/)([a-zA-Z0-9_-]{11})',
                r'youtube\.com.*[?&]v=([a-zA-Z0-9_-]{11})'
            ]
            for i, pattern in enumerate(patterns):
                match = re.search(pattern, url)
                if match:
                    video_id = match.group(1)
                    logging.info(f"Extracted video ID using regex pattern {i+1}: {video_id}")
                    break

        if video_id:
            if len(video_id) != 11:
                logging.warning(f"Invalid video ID format: {video_id} (length: {len(video_id)})")
                return None

            logging.info(f"Valid video ID extracted: {video_id}")

            embed_url = f"https://www.youtube.com/embed/{video_id}?autoplay=1&rel=0"
            logging.info(f"Generated embed URL: {embed_url}")
            return embed_url
        else:
            logging.warning(f"Could not extract video ID from URL: {url}")
            logging.warning("URL patterns checked: youtube.com/watch?v=, youtu.be/, youtube.com/embed/, /live, regex patterns")
            return None

    except Exception as e:
        logging.error(f"Error in basic YouTube extraction: {e}")
        return None


def get_twitch_stream_url(url):
    """Extract actual stream URL from Twitch using direct API approach."""
    try:
        if 'twitch.tv/' in url:
            channel = url.split('twitch.tv/')[1].split('/')[0]
        else:
            return None

        if not channel:
            return None

        # Return Twitch embed URL for iframe
        return f"https://player.twitch.tv/?channel={channel}&parent=localhost&parent=127.0.0.1&autoplay=true"

    except Exception as e:
        logging.error(f"Error extracting Twitch URL: {e}")
        return None


# --- HLS proxy helpers --------------------------------------------------------

# HLS manifests are small text; rewrite so every segment/variant URL loads via same-origin proxy (CORS + Firefox).
MAX_HLS_PLAYLIST_BYTES = 4 * 1024 * 1024


def _url_looks_like_hls_manifest(url: str) -> bool:
    path = urllib.parse.urlparse(url).path.lower()
    return path.endswith('.m3u8') or path.endswith('.m3u')


def rewrite_hls_playlist_for_proxy(body: str, resolved_base_url: str) -> str:
    """Rewrite manifest lines so absolute/relative URLs are fetched through /proxy/stream."""
    uri_in_tag = re.compile(r'URI="([^"]+)"')
    lines_out = []

    for raw in body.splitlines():
        stripped = raw.strip()
        if stripped.startswith('#'):
            if 'URI="' in raw:

                def repl_tag(m):
                    inner = m.group(1)
                    if inner.startswith('/proxy/stream?'):
                        return m.group(0)
                    if inner.startswith(('http://', 'https://')):
                        resolved = inner
                    else:
                        resolved = urllib.parse.urljoin(resolved_base_url, inner)
                    enc = quote(resolved, safe='')
                    return f'URI="/proxy/stream?url={enc}"'

                raw = uri_in_tag.sub(repl_tag, raw)
            lines_out.append(raw)
            continue
        if not stripped:
            lines_out.append(raw)
            continue
        if stripped.startswith('/proxy/stream?'):
            lines_out.append(stripped)
            continue
        if stripped.startswith(('http://', 'https://')):
            resolved = stripped
        else:
            resolved = urllib.parse.urljoin(resolved_base_url, stripped)
        enc = quote(resolved, safe='')
        lines_out.append(f'/proxy/stream?url={enc}')

    return '\n'.join(lines_out)


@app.route('/proxy/stream')
def proxy_stream():
    """Proxy YouTube and Twitch streams to work with HTML5 video player."""
    try:
        stream_url = request.args.get('url')
        if not stream_url:
            logging.error("No URL provided to proxy/stream endpoint")
            return jsonify({'error': 'No URL provided'}), 400

        logging.info(f"Proxy stream request for URL: {stream_url}")
        logging.info(f"URL type check - YouTube: {'youtube.com' in stream_url or 'youtu.be' in stream_url}, Twitch: {'twitch.tv' in stream_url}")

        # YouTube handling
        if 'youtube.com' in stream_url or 'youtu.be' in stream_url:
            logging.info(f"Processing YouTube URL: {stream_url}")
            direct_url = get_youtube_stream_url(stream_url)
            if direct_url:
                logging.info(f"YouTube extraction successful, redirecting to: {direct_url}")
                return redirect(direct_url, code=302)
            else:
                logging.error(f"YouTube extraction failed for URL: {stream_url}")
                return jsonify({'error': 'Failed to extract YouTube stream'}), 500

        # Twitch handling
        elif 'twitch.tv' in stream_url:
            logging.info(f"Processing Twitch URL: {stream_url}")
            direct_url = get_twitch_stream_url(stream_url)
            if direct_url:
                logging.info(f"Twitch extraction successful, redirecting to: {direct_url}")
                return redirect(direct_url, code=302)
            else:
                logging.error(f"Twitch extraction failed for URL: {stream_url}")
                return jsonify({'error': 'Failed to extract Twitch stream'}), 500

        # Direct stream for other sources
        else:
            logging.info(f"Processing direct stream URL: {stream_url}")
            return proxy_direct_stream(stream_url)

    except Exception as e:
        logging.error(f"Error proxying stream: {e}")
        logging.error(f"Exception details: {type(e).__name__}: {str(e)}")
        return jsonify({'error': str(e)}), 500


def proxy_direct_stream(url):
    """Proxy direct streams (progressive passthrough or HLS manifest rewrite + segment relay)."""
    cors = {'Access-Control-Allow-Origin': '*'}
    try:
        ct_hint = ''
        if _url_looks_like_hls_manifest(url):
            upstream = requests.get(url, headers=HEADERS, timeout=45)
            if upstream.status_code != 200:
                return jsonify({'error': f'Upstream HTTP {upstream.status_code}'}), upstream.status_code
            body = upstream.content
            ct_hint = upstream.headers.get('Content-Type') or ''

            if len(body) <= MAX_HLS_PLAYLIST_BYTES:
                text = body.decode('utf-8', errors='replace')
                if text.lstrip().startswith('#EXTM3U'):
                    text = rewrite_hls_playlist_for_proxy(text, upstream.url)
                    return Response(
                        text,
                        mimetype='application/vnd.apple.mpegurl',
                        headers={**cors, 'Cache-Control': 'no-store'},
                    )

            # Large or non-manifest body from .m3u URL — passthrough binary
            return Response(
                body,
                content_type=ct_hint or 'application/octet-stream',
                headers=cors,
            )

        response = requests.get(url, headers=HEADERS, stream=True, timeout=120)
        if response.status_code != 200:
            response.close()
            return jsonify({'error': f'Upstream HTTP {response.status_code}'}), 502

        def generate():
            try:
                for chunk in response.iter_content(chunk_size=65536):
                    if chunk:
                        yield chunk
            finally:
                response.close()

        return Response(
            stream_with_context(generate()),
            content_type=response.headers.get('Content-Type', 'application/octet-stream'),
            headers=cors,
        )

    except Exception as e:
        logging.error(f"Error proxying direct stream: {e}")
        return jsonify({'error': 'Failed to proxy stream'}), 500


@app.route("/admin/backup")
def admin_backup():
    """Download a SQLite backup (optional token via IPTV_PLAYLIST_SECRET)."""
    if IPTV_PLAYLIST_SECRET and request.args.get("token") != IPTV_PLAYLIST_SECRET:
        abort(403)
    try:
        from features.storage.db import get_default_store
        path = get_default_store().backup()
        return send_file(path, as_attachment=True, download_name=os.path.basename(path))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# --- Jellyfin / VLC M3U tuner endpoint ----------------------------------------

@app.route("/jellyfin/live.m3u")
@app.route("/iptv/live.m3u")
@app.route("/live-proxy.m3u")
def jellyfin_style_proxied_m3u():
    """Expose current lineup as an M3U whose stream URLs hit /proxy/stream (Jellyfin Live TV tuner, VLC, etc.)."""
    if IPTV_PLAYLIST_SECRET and request.args.get("token") != IPTV_PLAYLIST_SECRET:
        abort(403)
    online_only = request.args.get("online", "").lower() in ("1", "true", "yes")
    include_test = request.args.get("include_test", "").lower() in ("1", "true", "yes")
    country = (request.args.get("country") or "").strip() or None
    group = (request.args.get("group") or "").strip() or None
    media_type = (request.args.get("media_type") or "live").strip() or "live"
    if request.args.get("videos", "").lower() in ("1", "true", "yes"):
        media_type = "vod"
    base = seo_public_base_url().rstrip("/")
    body = build_proxied_live_m3u(
        base,
        online_only=online_only or True,
        country=country,
        group=group,
        include_test=include_test,
        media_type=media_type,
    )
    return Response(
        body,
        mimetype="audio/x-mpegurl",
        headers={
            "Content-Disposition": 'inline; filename="iptv-scanner-proxy.m3u"',
            "Cache-Control": "no-store, max-age=0",
        },
    )


# --- SEO catch-all landing page (MUST stay last) -----------------------------

@app.route("/<slug>")
def seo_channel_page(slug):
    """SEO landing + player for /<slug>-style URLs (e.g. /fox-news)."""
    if not SEO_SLUG_RE.match(slug):
        abort(404)
    if slug.lower() in SEO_RESERVED_SLUGS:
        abort(404)
    seo_refresh_slug_index()
    slug_map, _ = seo_slug_snapshot()
    ch = slug_map.get(slug)
    canonical = seo_abs_url(slug)

    if not ch or not (ch.get("url") or "").strip():
        return (
            render_template(
                "seo_missing.html",
                site_name=IPTV_SITE_NAME,
                slug=slug,
                canonical=seo_abs_url(""),
                home_url=seo_public_base_url().rstrip("/"),
                error_title="Stream not found",
                error_body="That channel slug is not in the current lineup, or the listing has no stream URL yet. Try scanning again from the guide or browse the home page.",
            ),
            404,
        )

    raw_url = ch.get("url", "").strip()
    meta = seo_meta_for_channel(ch)
    og_img = seo_og_image_for_channel(ch)
    json_ld = seo_json_ld_broadcast(ch, canonical)

    youtube = ("youtube.com" in raw_url) or ("youtu.be" in raw_url)
    twitch = "twitch.tv" in raw_url
    embed_player = youtube or twitch
    path_lc = raw_url.split("?")[0].lower()
    progressive = path_lc.endswith((".mp4", ".webm", ".ogv"))

    proxied_play = "/proxy/stream?url=" + quote(raw_url, safe="")

    public_root = seo_public_base_url().rstrip("/")

    return render_template(
        "seo_channel.html",
        site_name=IPTV_SITE_NAME,
        channel_name=meta["name"],
        description=meta["description"],
        group_title=meta.get("group") or "",
        country=meta.get("country") or "",
        canonical=canonical,
        og_image=og_img or "",
        json_ld=json_ld,
        slug=slug,
        stream_url_encoded=proxied_play,
        embed_player=embed_player,
        progressive=progressive,
        raw_stream_url=raw_url,
        home_url=public_root,
    )
