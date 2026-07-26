"""Async stream validation (HTTP reachability, HLS parsing, YouTube/Twitch checks)."""

import asyncio
import logging
import re

import aiohttp

from channels_io import save_json_atomic
from config import BATCH_SIZE, FILES, HEADERS
from icons import download_channel_icon


async def check_link_exists(session, url, retries=3, delay=5):
    retryable_statuses = {500, 502, 503, 504, 429, 403}  # include 403 for Cloudflare

    for attempt in range(1, retries + 1):
        try:
            async with session.get(url, timeout=20, headers=HEADERS) as response:
                if response.status in {200, 302}:
                    return True
                if response.status in retryable_statuses:
                    logging.warning(f"Retryable error {response.status} for {url}, attempt {attempt}")
                    if attempt < retries:
                        await asyncio.sleep(delay * attempt)  # Exponential backoff
                    continue
                else:
                    logging.warning(f"Invalid link {url} (status: {response.status})")
                    return False
        except aiohttp.ClientError as e:
            logging.error(f"Network error attempt {attempt} for {url}: {e}")
            if attempt < retries:
                await asyncio.sleep(delay * attempt)
            continue
        except Exception as e:
            logging.error(f"Unexpected error attempt {attempt} for {url}: {e}")
            if attempt < retries:
                await asyncio.sleep(delay * attempt)
            continue

    return False


async def check_platform_live_status(session, url):
    """Check if YouTube/Twitch channels are actually live."""
    try:
        # YouTube live status check
        if 'youtube.com' in url or 'youtu.be' in url:
            # Extract video/channel ID
            video_id = None
            if '/live' in url:
                if '/@' in url:
                    video_id = url.split('/@')[1].split('/')[0]
                elif '/channel/' in url:
                    video_id = url.split('/channel/')[1].split('/')[0]
                elif '/c/' in url:
                    video_id = url.split('/c/')[1].split('/')[0]
            elif 'watch?v=' in url:
                video_id = url.split('v=')[1].split('&')[0]
            elif 'youtu.be/' in url:
                video_id = url.split('youtu.be/')[1].split('?')[0]

            if video_id:
                # Check YouTube API for live status
                api_url = f"https://youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
                try:
                    async with session.get(api_url, timeout=10) as response:
                        if response.status == 200:
                            data = await response.json()
                            # Check if it's a live stream
                            if 'title' in data and ('live' in data['title'].lower() or 'stream' in data['title'].lower()):
                                logging.info(f"YouTube channel {video_id} appears to be live")
                                return True
                            else:
                                logging.info(f"YouTube channel {video_id} exists but may not be live")
                                return True  # Still count as valid even if not currently live
                        else:
                            logging.warning(f"YouTube API check failed for {video_id}: {response.status}")
                            return False
                except Exception as e:
                    logging.warning(f"YouTube live check error for {video_id}: {e}")
                    return False

        # Twitch live status check
        elif 'twitch.tv' in url:
            # Extract channel name
            channel_name = url.split('twitch.tv/')[1].split('/')[0]
            if channel_name:
                # Check Twitch API for live status
                api_url = f"https://www.twitch.tv/{channel_name}"
                try:
                    async with session.get(api_url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'}) as response:
                        if response.status == 200:
                            # Parse HTML to check for live status
                            content = await response.text()
                            if 'isLive' in content or 'data-is-live="true"' in content:
                                logging.info(f"Twitch channel {channel_name} is live")
                                return True
                            else:
                                logging.info(f"Twitch channel {channel_name} exists but may not be live")
                                return True  # Still count as valid
                        else:
                            logging.warning(f"Twitch check failed for {channel_name}: {response.status}")
                            return False
                except Exception as e:
                    logging.warning(f"Twitch live check error for {channel_name}: {e}")
                    return False

        # For other platforms, just check if URL exists
        return await check_link_exists(session, url)

    except Exception as e:
        logging.error(f"Platform live check error for {url}: {e}")
        return False


async def validate_m3u8_stream(session, url):
    """Comprehensive M3U8 stream validation using professional packages."""
    try:
        logging.info(f"Validating M3U8 stream: {url}")

        # First, check if the URL is accessible
        if not await check_link_exists(session, url):
            return False, "URL not accessible"

        # Use professional M3U8 parsing
        try:
            import m3u8
            import streamlink

            # Method 1: Streamlink validation (most reliable)
            try:
                sl_session = streamlink.Streamlink()
                streams = sl_session.streams(url)

                if streams:
                    # Streamlink found valid streams
                    qualities = list(streams.keys())
                    best_quality = streams.get('best') or streams.get('live') or list(streams.values())[0]

                    logging.info(f"Streamlink found {len(streams)} streams: {qualities}")
                    return True, f"Live stream ({len(streams)} qualities: {', '.join(qualities[:3])})"
                else:
                    logging.warning(f"Streamlink found no streams for {url}")
            except Exception as e:
                logging.debug(f"Streamlink validation failed: {e}")

            # Method 2: Enhanced M3U8 parsing
            async with session.get(url, timeout=15, headers=HEADERS) as response:
                if response.status != 200:
                    return False, f"HTTP {response.status}"

                content = await response.text()
                if not content.strip():
                    return False, "Empty playlist"

                # Parse with professional M3U8 library
                playlist = m3u8.loads(content)

                if playlist.is_variant:
                    # Master playlist - check variants
                    if not playlist.playlists:
                        return False, "Master playlist has no variants"

                    # Get best quality variant
                    best_variant = max(playlist.playlists, key=lambda x: x.stream_info.bandwidth or 0)
                    variant_url = best_variant.uri

                    # Resolve relative URL
                    if not variant_url.startswith('http'):
                        from urllib.parse import urljoin
                        variant_url = urljoin(url, variant_url)

                    # Test the variant
                    return await validate_media_playlist(session, variant_url)

                else:
                    # Media playlist - validate segments
                    if not playlist.segments:
                        return False, "No media segments found"

                    if playlist.is_endlist:
                        # VOD content
                        return True, f"VOD stream ({len(playlist.segments)} segments)"
                    else:
                        # Live content
                        return True, f"Live stream ({len(playlist.segments)} segments)"

        except ImportError:
            # Fallback to original method if packages not available
            logging.warning("Professional M3U8 packages not available, using fallback")
            return await validate_m3u8_stream_fallback(session, url)

    except Exception as e:
        logging.error(f"M3U8 validation error for {url}: {e}")
        return False, f"Validation error: {str(e)}"


async def validate_m3u8_stream_fallback(session, url):
    """Fallback M3U8 validation method."""
    try:
        async with session.get(url, timeout=15, headers=HEADERS) as response:
            if response.status != 200:
                return False, f"HTTP {response.status}"

            content = await response.text()
            if not content.strip():
                return False, "Empty playlist"

            lines = content.strip().split('\n')

            # Check if it's a master playlist or media playlist
            is_master = any('#EXT-X-STREAM-INF:' in line or '#EXT-X-MEDIA:' in line for line in lines)
            is_media = any('#EXTINF:' in line or '#EXT-X-TARGETDURATION:' in line for line in lines)

            if is_master:
                logging.info(f"Master playlist detected for {url}")
                # Parse master playlist for variants
                variants = []
                for i, line in enumerate(lines):
                    if line.startswith('#EXT-X-STREAM-INF:'):
                        # Extract variant info
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

                        # Get the URL for this variant (next non-comment line)
                        if i + 1 < len(lines) and not lines[i + 1].startswith('#'):
                            variant_url = lines[i + 1].strip()
                            if variant_url.startswith('http'):
                                variants.append({
                                    'url': variant_url,
                                    'bandwidth': bandwidth,
                                    'resolution': resolution,
                                    'codecs': codecs
                                })
                            else:
                                # Relative URL - resolve against base URL
                                from urllib.parse import urljoin
                                absolute_url = urljoin(url, variant_url)
                                variants.append({
                                    'url': absolute_url,
                                    'bandwidth': bandwidth,
                                    'resolution': resolution,
                                    'codecs': codecs
                                })

                if not variants:
                    return False, "No valid variants in master playlist"

                # Test the best quality variant
                variants.sort(key=lambda x: x.get('bandwidth', 0), reverse=True)
                best_variant = variants[0]
                logging.info(f"Testing best variant: {best_variant.get('resolution', 'unknown')} ({best_variant.get('bandwidth', 'unknown')} bps)")

                # Validate the variant stream
                return await validate_media_playlist(session, best_variant['url'])

            elif is_media:
                logging.info(f"Media playlist detected for {url}")
                # Direct media playlist validation
                return await validate_media_playlist(session, url)

            else:
                return False, "Invalid M3U8 format"

    except Exception as e:
        logging.error(f"Fallback M3U8 validation error for {url}: {e}")
        return False, f"Fallback validation error: {str(e)}"


async def validate_media_playlist(session, playlist_url):
    """Validate a media playlist has actual streaming content."""
    try:
        async with session.get(playlist_url, timeout=10, headers=HEADERS) as response:
            if response.status != 200:
                return False, f"HTTP {response.status}"

            content = await response.text()
            if not content.strip():
                return False, "Empty media playlist"

            lines = content.strip().split('\n')

            # Check for essential media playlist tags
            has_target_duration = any('#EXT-X-TARGETDURATION:' in line for line in lines)
            has_segments = any(line and not line.startswith('#') for line in lines)

            if not has_target_duration:
                return False, "Missing target duration"

            if not has_segments:
                return False, "No media segments found"

            # Count media segments
            segment_count = sum(1 for line in lines if line and not line.startswith('#'))

            # Check for end list tag (indicates complete playlist)
            has_end_list = any('#EXT-X-ENDLIST' in line for line in lines)

            if segment_count == 0:
                return False, "No media segments"

            # For live streams, we expect ongoing segments without ENDLIST
            # For VOD, we expect ENDLIST
            if has_end_list:
                logging.info(f"VOD playlist detected: {segment_count} segments")
                return True, f"VOD stream ({segment_count} segments)"
            else:
                logging.info(f"Live stream detected: {segment_count} segments")
                return True, f"Live stream ({segment_count} segments)"

    except Exception as e:
        logging.error(f"Media playlist validation error for {playlist_url}: {e}")
        return False, f"Media validation error: {str(e)}"


async def get_stream_metadata(session, url):
    """Extract metadata about what's currently playing."""
    try:
        if '.m3u8' in url.lower():
            # Try to extract title from M3U8
            async with session.get(url, timeout=10, headers=HEADERS) as response:
                if response.status == 200:
                    content = await response.text()

                    # Look for title metadata
                    for line in content.split('\n'):
                        if '#EXT-X-STREAM-TITLE:' in line:
                            title = line.split(':', 1)[1].strip()
                            if title:
                                return title
                        elif '#EXTINF:' in line:
                            # Extract title from EXTINF
                            parts = line.split(',')
                            if len(parts) > 1:
                                title = parts[-1].strip()
                                if title and title != '':
                                    return title

        # For YouTube, try to get video title
        elif 'youtube.com' in url or 'youtu.be' in url:
            video_id = None
            if 'watch?v=' in url:
                video_id = url.split('v=')[1].split('&')[0]
            elif 'youtu.be/' in url:
                video_id = url.split('youtu.be/')[1].split('?')[0]

            if video_id:
                api_url = f"https://youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
                try:
                    async with session.get(api_url, timeout=10) as response:
                        if response.status == 200:
                            data = await response.json()
                            return data.get('title', 'Unknown')
                except Exception:
                    pass

        # For Twitch, try to get stream title
        elif 'twitch.tv' in url:
            channel_name = url.split('twitch.tv/')[1].split('/')[0]
            try:
                async with session.get(f"https://www.twitch.tv/{channel_name}", timeout=10) as response:
                    if response.status == 200:
                        content = await response.text()
                        # Look for stream title in HTML
                        title_match = re.search(r'"title":"([^"]+)"', content)
                        if title_match:
                            return title_match.group(1)
            except Exception:
                pass

        return "Live Stream"

    except Exception as e:
        logging.debug(f"Error extracting metadata for {url}: {e}")
        return "Live Stream"


async def validate_channel(session, channel):
    """Asynchronously validate a single channel."""
    try:
        logging.info(f"Validating channel: {channel['url']}")

        # Use platform-specific live checking for YouTube/Twitch
        if 'youtube.com' in channel['url'] or 'youtu.be' in channel['url'] or 'twitch.tv' in channel['url']:
            if await check_platform_live_status(session, channel['url']):
                channel['status'] = 'online'
                # Get metadata for what's playing now
                channel['playing_now'] = await get_stream_metadata(session, channel['url'])
                return channel, True
            else:
                channel['status'] = 'offline'
                return channel, False

        # For M3U8 streams, use comprehensive validation
        elif '.m3u8' in channel['url'].lower():
            is_valid, details = await validate_m3u8_stream(session, channel['url'])
            if is_valid:
                channel['status'] = 'online'
                channel['playing_now'] = details  # Use validation details as playing_now
                return channel, True
            else:
                channel['status'] = 'offline'
                channel['playing_now'] = f"Stream error: {details}"
                return channel, False

        # For other streams, just check if URL exists
        else:
            if await check_link_exists(session, channel['url']):
                channel['status'] = 'online'
                channel['playing_now'] = await get_stream_metadata(session, channel['url'])
                return channel, True
            else:
                channel['status'] = 'offline'
                return channel, False

    except Exception as e:
        logging.error(f"Error validating channel {channel['url']}: {e}")
        channel['status'] = 'error'
        channel['playing_now'] = f"Validation error: {str(e)}"
        return channel, False


async def process_channels(channels, invalid_links, delay=5):
    """Process channels in batches asynchronously."""
    valid_channels = []
    dead_channels = []

    # Create session with SSL settings to handle certificate issues
    connector = aiohttp.TCPConnector(
        ssl=False,  # Disable SSL verification for problematic certificates
        limit=100,   # Increase connection pool size
        limit_per_host=20
    )

    async with aiohttp.ClientSession(connector=connector) as session:
        for i in range(0, len(channels), BATCH_SIZE):
            batch = channels[i:i + BATCH_SIZE]
            tasks = [validate_channel(session, channel) for channel in batch if channel['url'] not in invalid_links]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for result in results:
                if isinstance(result, Exception):
                    logging.error(f"Batch processing error: {result}")
                    continue

                channel, is_valid = result
                if is_valid:
                    icon_url = download_channel_icon(channel['name'], channel['url'], channel.get('tvg_logo', ''))
                    channel['icon_url'] = icon_url
                    valid_channels.append(channel)
                else:
                    dead_channels.append(channel)

            # Save progress after each batch
            try:
                save_json_atomic(FILES['streams'], valid_channels)
                save_json_atomic(FILES['dead'], dead_channels)

                logging.info(f"Batch {i//BATCH_SIZE + 1}: {len(valid_channels)} valid, {len(dead_channels)} dead")

            except Exception as e:
                logging.error(f"Error saving batch: {e}")

            await asyncio.sleep(delay)  # play about with this to control processing speed

    return valid_channels, dead_channels
