// IPTV Scanner — Phase 3 UI (Tailwind, single responsive shell, paginated fetch)
// Plain-language, big Play CTA, progressive disclosure.

(() => {
    'use strict';

    const PAGE_SIZE = 50;
    const FAVORITES_STORAGE_KEY = 'iptv_scanner_favorites_v1';
    const INFINITE_SCROLL_THRESHOLD_PX = 320;
    const SEARCH_DEBOUNCE_MS = 320;

    const $ = (id) => document.getElementById(id);

    function escapeHtml(text) {
        if (text == null) return '';
        return String(text)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function debounce(fn, ms) {
        let t;
        return (...args) => {
            clearTimeout(t);
            t = setTimeout(() => fn.apply(null, args), ms);
        };
    }

    function formatKbps(bandwidth) {
        const bw = Number(bandwidth || 0);
        if (!bw) return '';
        if (bw >= 1_000_000) return `${(bw / 1_000_000).toFixed(1)} Mbps`;
        return `${Math.round(bw / 1000)} kbps`;
    }

    // -----------------------------------------------------------------------
    // App
    // -----------------------------------------------------------------------
    class LiveTVGuide {
        constructor() {
            this.channels = [];
            this.channelIndex = new Map(); // url -> channel
            this.currentPage = 0;
            this.hasMore = true;
            this.totalChannels = 0;
            this.isFetching = false;
            this.pendingReloadTimer = null;
            this.lastRevision = -1;

            this.mode = 'live'; // live | videos | favorites
            this.includeTest = false;
            this.showPending = false;
            this.search = '';
            this.group = '';
            this.country = '';
            this.sort = 'name';
            this.sortDir = 'asc';

            this.currentChannel = null;
            this.hls = null;
            this._pendingQualityUrl = null;

            this.favorites = this._loadFavorites();

            this._boundOnListScroll = this._onListScroll.bind(this);
            this._boundOnWindowScroll = this._onWindowScroll.bind(this);
        }

        // ------------------------- init -----------------------------------
        init() {
            this._setupIntegrationLinks();
            this._setupHeader();
            this._setupModeTabs();
            this._setupFilters();
            this._setupMoreToggles();
            this._setupPlayerControls();
            this._setupInfiniteScroll();
            this._setupEmptyState();
            this._connectEventStream();
            this._fetchStatus();
            this.reload({ resetScroll: true });
        }

        // ------------------------- favorites ------------------------------
        _loadFavorites() {
            try {
                const raw = localStorage.getItem(FAVORITES_STORAGE_KEY);
                const arr = raw ? JSON.parse(raw) : [];
                return new Set(Array.isArray(arr) ? arr : []);
            } catch {
                return new Set();
            }
        }

        _persistFavorites() {
            try {
                localStorage.setItem(
                    FAVORITES_STORAGE_KEY,
                    JSON.stringify([...this.favorites])
                );
            } catch {
                /* ignore */
            }
        }

        toggleFavorite(url) {
            if (!url) return;
            if (this.favorites.has(url)) {
                this.favorites.delete(url);
                this.notify('Removed from My list');
            } else {
                this.favorites.add(url);
                this.notify('Added to My list');
            }
            this._persistFavorites();

            // Update cards in place
            document
                .querySelectorAll(`[data-channel-url="${CSS.escape(url)}"] .fav-btn`)
                .forEach((btn) => this._syncFavButton(btn, url));

            if (this.mode === 'favorites') {
                this.reload({ resetScroll: false });
            }
        }

        // ------------------------- integrations ---------------------------
        _setupIntegrationLinks() {
            const origin = `${window.location.protocol}//${window.location.host}`;
            const m3u = `${origin}/jellyfin/live.m3u`;
            const jm = $('jellyfinM3u');
            if (jm) jm.textContent = m3u;
            const btn = $('copyM3uBtn');
            if (btn) {
                btn.addEventListener('click', () => {
                    if (navigator.clipboard?.writeText) {
                        navigator.clipboard
                            .writeText(m3u)
                            .then(() => this.notify('Playlist link copied'))
                            .catch(() => this.notify('Could not copy — long-press to copy manually', 'error'));
                    } else {
                        this.notify('Copy not supported here', 'error');
                    }
                });
            }
        }

        // ------------------------- header search --------------------------
        _setupHeader() {
            const inp = $('searchInput');
            if (!inp) return;
            const runSearch = debounce(() => {
                this.search = inp.value.trim();
                this.reload({ resetScroll: true });
            }, SEARCH_DEBOUNCE_MS);
            inp.addEventListener('input', runSearch);
        }

        // ------------------------- mode tabs ------------------------------
        _setupModeTabs() {
            document.querySelectorAll('.mode-tab').forEach((tab) => {
                tab.addEventListener('click', () => {
                    const mode = tab.getAttribute('data-mode');
                    if (!mode || mode === this.mode) return;
                    this.mode = mode;
                    this._syncModeTabs();
                    this.reload({ resetScroll: true });
                });
            });
        }

        _syncModeTabs() {
            document.querySelectorAll('.mode-tab').forEach((tab) => {
                const isActive = tab.getAttribute('data-mode') === this.mode;
                tab.setAttribute('aria-selected', String(isActive));
                if (isActive) {
                    tab.classList.add(
                        'bg-brand-400',
                        'text-ink-950',
                        'ring-brand-300',
                        'shadow-glow'
                    );
                    tab.classList.remove('text-slate-300', 'hover:bg-white/5', 'ring-transparent');
                } else {
                    tab.classList.remove(
                        'bg-brand-400',
                        'text-ink-950',
                        'ring-brand-300',
                        'shadow-glow'
                    );
                    tab.classList.add('text-slate-300', 'hover:bg-white/5', 'ring-transparent');
                }
            });
        }

        // ------------------------- filters --------------------------------
        _setupFilters() {
            const group = $('groupFilter');
            const country = $('countryFilter');
            const sort = $('sortFilter');
            const dir = $('sortDir');

            group?.addEventListener('change', () => {
                this.group = group.value;
                this.reload({ resetScroll: true });
            });
            country?.addEventListener('change', () => {
                this.country = country.value;
                this.reload({ resetScroll: true });
            });
            sort?.addEventListener('change', () => {
                this.sort = sort.value;
                this.reload({ resetScroll: true });
            });
            dir?.addEventListener('change', () => {
                this.sortDir = dir.value;
                this.reload({ resetScroll: true });
            });
        }

        _setupMoreToggles() {
            const t = $('testToggle');
            const p = $('pendingToggle');
            t?.addEventListener('change', () => {
                this.includeTest = t.checked;
                this.reload({ resetScroll: true });
            });
            p?.addEventListener('change', () => {
                this.showPending = p.checked;
                this.reload({ resetScroll: true });
            });
        }

        _setupEmptyState() {
            $('clearFiltersBtn')?.addEventListener('click', () => {
                this.search = '';
                this.group = '';
                this.country = '';
                this.mode = 'live';
                const s = $('searchInput');
                const g = $('groupFilter');
                const c = $('countryFilter');
                if (s) s.value = '';
                if (g) g.value = '';
                if (c) c.value = '';
                this._syncModeTabs();
                this.reload({ resetScroll: true });
            });
        }

        // ------------------------- player + quality -----------------------
        _setupPlayerControls() {
            const q = $('qualitySelect');
            if (!q) return;
            q.addEventListener('change', () => this._onQualityChange(q.value));
        }

        _onQualityChange(value) {
            const v = String(value);
            if (this.hls) {
                if (v === '-1') {
                    this.hls.currentLevel = -1;
                    this.notify('Auto quality');
                } else if (v.startsWith('lvl:')) {
                    const idx = parseInt(v.slice(4), 10);
                    if (!Number.isNaN(idx)) {
                        this.hls.currentLevel = idx;
                    }
                    return;
                }
            }
            if (v.startsWith('var:')) {
                const varUrl = v.slice(4);
                if (varUrl && this.currentChannel) {
                    this._playStream(varUrl, this.currentChannel.name, {
                        keepQualityOptions: true,
                    });
                }
            }
        }

        _resetQualitySelect() {
            const q = $('qualitySelect');
            if (!q) return;
            q.innerHTML = '<option value="-1">Auto quality</option>';
            q.disabled = true;
            q.value = '-1';
        }

        _populateHlsQualityLevels(levels) {
            const q = $('qualitySelect');
            if (!q || !Array.isArray(levels) || !levels.length) return;
            const options = ['<option value="-1">Auto quality</option>'];
            levels.forEach((lvl, i) => {
                const h = lvl.height ? `${lvl.height}p` : `${Math.round(lvl.bitrate / 1000)}k`;
                const bw = lvl.bitrate ? ` (${formatKbps(lvl.bitrate)})` : '';
                options.push(`<option value="lvl:${i}">${escapeHtml(h)}${escapeHtml(bw)}</option>`);
            });
            q.innerHTML = options.join('');
            q.disabled = false;
            q.value = '-1';
        }

        async _populateVariantOptions(channel) {
            const q = $('qualitySelect');
            if (!q || !channel?.url || !channel.quality_count) return;
            try {
                const res = await fetch(
                    `/api/variants?url=${encodeURIComponent(channel.url)}`
                );
                const data = await res.json();
                const list = Array.isArray(data.variants) ? data.variants : [];
                if (!list.length) return;
                // Only replace if we haven't already been populated by hls.js.
                if (q.options.length > 1 && !q.disabled) return;
                const options = ['<option value="-1">Auto quality</option>'];
                list.forEach((v) => {
                    const label = v.resolution || (v.bandwidth ? formatKbps(v.bandwidth) : 'Variant');
                    options.push(
                        `<option value="var:${escapeHtml(v.url)}">${escapeHtml(label)}</option>`
                    );
                });
                q.innerHTML = options.join('');
                q.disabled = false;
                q.value = '-1';
            } catch {
                /* ignore */
            }
        }

        _teardownHls() {
            if (this.hls) {
                try {
                    this.hls.destroy();
                } catch {
                    /* ignore */
                }
                this.hls = null;
            }
        }

        _attachPlayer(video, playUrl, originalUrl) {
            this._teardownHls();
            if (!video) return;
            video.removeAttribute('src');
            video.querySelectorAll('source').forEach((s) => s.remove());

            const path = (originalUrl || '').split(/[?#]/)[0].toLowerCase();
            const progressive = /\.(mp4|webm|ogv)$/i.test(path);

            if (progressive) {
                video.src = playUrl;
                return;
            }

            // Prefer hls.js so we get quality control on Chromium / Firefox.
            if (typeof Hls !== 'undefined' && Hls.isSupported()) {
                const hls = new Hls({
                    enableWorker: true,
                    lowLatencyMode: false,
                    maxBufferLength: 30,
                    backBufferLength: 30,
                });
                this.hls = hls;
                hls.loadSource(playUrl);
                hls.attachMedia(video);
                hls.on(Hls.Events.MANIFEST_PARSED, (_, data) => {
                    if (data?.levels?.length) {
                        this._populateHlsQualityLevels(data.levels);
                    }
                });
                hls.on(Hls.Events.ERROR, (_, data) => {
                    if (!data?.fatal) return;
                    if (data.type === Hls.ErrorTypes.NETWORK_ERROR) {
                        hls.startLoad();
                    } else if (data.type === Hls.ErrorTypes.MEDIA_ERROR) {
                        hls.recoverMediaError();
                    } else {
                        this.notify('This stream stopped — try another channel', 'error');
                    }
                });
                return;
            }

            // Native (Safari / iOS): no per-level quality control, but plays HLS.
            if (
                video.canPlayType('application/vnd.apple.mpegurl') ||
                video.canPlayType('application/x-mpegURL')
            ) {
                video.src = playUrl;
                return;
            }

            video.src = playUrl;
        }

        _playStream(url, name, opts = {}) {
            const wrap = $('videoPlayer');
            if (!wrap) return;
            const placeholder = $('playerPlaceholder');
            if (placeholder) placeholder.classList.add('hidden');

            const isYT = url.includes('youtube.com') || url.includes('youtu.be');
            const isTwitch = url.includes('twitch.tv');
            const proxied = `/proxy/stream?url=${encodeURIComponent(url)}`;

            if (isYT || isTwitch) {
                this._teardownHls();
                this._resetQualitySelect();
                wrap.innerHTML = `
                    <iframe
                        class="absolute inset-0 h-full w-full"
                        src="${proxied}&autoplay=1"
                        allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; fullscreen"
                        allowfullscreen></iframe>
                `;
                return;
            }

            if (!opts.keepQualityOptions) {
                this._resetQualitySelect();
            }

            wrap.innerHTML = `
                <video class="absolute inset-0 h-full w-full bg-black" controls autoplay muted playsinline></video>
            `;
            const video = wrap.querySelector('video');
            this._attachPlayer(video, proxied, url);
            video?.addEventListener(
                'canplay',
                () => {
                    video.muted = false;
                    video.play().catch(() => {});
                },
                { once: true }
            );
        }

        selectAndPlay(channel) {
            if (!channel) return;
            this.currentChannel = channel;

            // Meta
            const nm = $('currentChannelName');
            const inf = $('currentChannelInfo');
            let host = channel.url;
            try {
                host = new URL(channel.url).hostname;
            } catch {
                /* keep */
            }
            const nowLine = channel.playing_now
                ? channel.playing_now
                : `Streaming from ${host}`;
            const parts = [];
            if (channel.group_title) parts.push(channel.group_title);
            if (channel.country) parts.push(channel.country);
            const meta = parts.join(' · ') || nowLine;
            if (nm) nm.textContent = channel.name || 'Untitled channel';
            if (inf) inf.textContent = meta;

            this._playStream(channel.url, channel.name || '');

            // If HLS variants are known on the server, list them too (Safari can use them).
            if (channel.quality_count && channel.quality_count > 0) {
                this._populateVariantOptions(channel);
            }

            // Highlight active card
            document.querySelectorAll('.channel-card').forEach((card) => {
                const isActive =
                    card.getAttribute('data-channel-url') === channel.url;
                card.classList.toggle('ring-2', isActive);
                card.classList.toggle('ring-brand-400', isActive);
            });

            this.notify(`Now playing: ${channel.name || 'stream'}`);
        }

        // ------------------------- fetching -------------------------------
        _buildQuery(page) {
            const params = new URLSearchParams();
            params.set('page', String(page));
            params.set('limit', String(PAGE_SIZE));
            if (this.search) params.set('q', this.search);
            if (this.group) params.set('group', this.group);
            if (this.country) params.set('country', this.country);
            if (this.sort) params.set('sort', this.sort);
            if (this.sortDir) params.set('sort_dir', this.sortDir);

            if (this.mode === 'videos') {
                params.set('videos', '1');
            } else if (this.mode === 'live') {
                params.set('media_type', 'live');
            }
            if (this.includeTest) params.set('include_test', '1');
            if (this.showPending) params.set('pending', '1');
            return params.toString();
        }

        async reload(opts = {}) {
            const resetScroll = opts.resetScroll !== false;
            this.currentPage = 0;
            this.hasMore = true;
            this.channels = [];
            this.channelIndex.clear();

            const list = $('channelsList');
            if (list) {
                list.setAttribute('aria-busy', 'true');
                list.innerHTML = `
                    <div class="rounded-xl border border-white/10 bg-ink-800/60 p-6 text-center">
                        <div class="animate-pulse text-slate-400 text-sm">Loading channels…</div>
                    </div>
                `;
                if (resetScroll) list.scrollTop = 0;
            }
            this._hideEmpty();

            await this._fetchNextPage({ replace: true });
        }

        async _fetchNextPage(opts = {}) {
            if (this.isFetching || !this.hasMore) return;
            this.isFetching = true;
            try {
                const nextPage = this.currentPage + 1;
                const url = `/channels?${this._buildQuery(nextPage)}`;
                const res = await fetch(url);
                const data = await res.json();

                const list = Array.isArray(data.channels) ? data.channels : [];
                this.currentPage = data.current_page || nextPage;
                this.hasMore = Boolean(data.has_more);
                this.totalChannels = Number(data.total_channels || 0);

                if (typeof data.revision === 'number') {
                    this.lastRevision = data.revision;
                }

                // My list: filter to favorites only (client-side; API has no favorites endpoint).
                let payload = list;
                if (this.mode === 'favorites') {
                    payload = list.filter((c) => this.favorites.has(c.url));
                }

                if (opts.replace) {
                    this.channels = [];
                    this.channelIndex.clear();
                }

                for (const ch of payload) {
                    if (ch?.url && !this.channelIndex.has(ch.url)) {
                        this.channelIndex.set(ch.url, ch);
                        this.channels.push(ch);
                    }
                }

                this._populateFilterOptions(data);

                if (opts.replace) {
                    this._renderList();
                } else {
                    this._appendCards(payload);
                }

                // Auto-fetch more if this page collapsed to nothing in favorites mode.
                if (
                    this.mode === 'favorites' &&
                    this.hasMore &&
                    payload.length === 0 &&
                    this.currentPage < 50
                ) {
                    this.isFetching = false;
                    await this._fetchNextPage();
                    return;
                }

                this._updateVisibleCount();

                if (!this.channels.length) {
                    this._showEmpty();
                } else {
                    this._hideEmpty();
                }
            } catch (err) {
                console.error('Load failed:', err);
                this.notify('Could not load channels — check connection', 'error');
            } finally {
                this.isFetching = false;
                const list = $('channelsList');
                if (list) list.removeAttribute('aria-busy');
            }
        }

        _populateFilterOptions(data) {
            const groups = Array.isArray(data.groups) ? data.groups : [];
            const countries = Array.isArray(data.countries) ? data.countries : [];
            const g = $('groupFilter');
            const c = $('countryFilter');
            const toLabel = (v) => {
                if (v == null) return '';
                if (typeof v === 'string' || typeof v === 'number') return String(v);
                if (typeof v === 'object') return String(v.name || v.code || v.label || '');
                return String(v);
            };
            const fill = (sel, values, placeholder, current) => {
                if (!sel) return;
                const labels = values.map(toLabel).filter(Boolean);
                // Pin Test at bottom if present
                const testIdx = labels.findIndex((x) => x === 'Test');
                if (testIdx >= 0) {
                    labels.splice(testIdx, 1);
                    labels.sort((a, b) => a.localeCompare(b));
                    labels.push('Test');
                } else {
                    labels.sort((a, b) => a.localeCompare(b));
                }
                const known = new Set(labels);
                const preserve = current && known.has(current) ? current : '';
                sel.innerHTML =
                    `<option value="">${placeholder}</option>` +
                    labels
                        .map(
                            (v) =>
                                `<option value="${escapeHtml(v)}">${escapeHtml(v)}</option>`
                        )
                        .join('');
                if (preserve) sel.value = preserve;
            };
            fill(g, groups, 'All groups', this.group);
            fill(c, countries, 'All countries', this.country);
        }

        // ------------------------- rendering ------------------------------
        _renderList() {
            const list = $('channelsList');
            if (!list) return;
            list.innerHTML = '';
            if (!this.channels.length) return;
            const frag = document.createDocumentFragment();
            for (const ch of this.channels) {
                frag.appendChild(this._createChannelCard(ch));
            }
            list.appendChild(frag);
        }

        _appendCards(items) {
            const list = $('channelsList');
            if (!list || !items?.length) return;
            const frag = document.createDocumentFragment();
            for (const ch of items) {
                if (!ch?.url) continue;
                if (this.mode === 'favorites' && !this.favorites.has(ch.url)) continue;
                frag.appendChild(this._createChannelCard(ch));
            }
            list.appendChild(frag);
        }

        _createChannelCard(channel) {
            const card = document.createElement('article');
            const isActive =
                this.currentChannel && this.currentChannel.url === channel.url;
            card.className = [
                'channel-card',
                'group',
                'relative',
                'rounded-xl',
                'border',
                'border-white/10',
                'bg-ink-800/60',
                'hover:bg-ink-800',
                'hover:border-brand-400/40',
                'transition',
                'p-3',
                isActive ? 'ring-2 ring-brand-400' : '',
            ]
                .filter(Boolean)
                .join(' ');
            card.setAttribute('data-channel-url', channel.url);

            const name = channel.name || 'Untitled channel';
            const initial = name.trim().charAt(0).toUpperCase() || '?';
            const group = channel.group_title || '';
            const country = channel.country || '';
            const nowLine =
                channel.playing_now && String(channel.playing_now).trim()
                    ? channel.playing_now
                    : [group, country].filter(Boolean).join(' · ') || 'Live stream';

            const status = String(channel.status || 'unknown').toLowerCase();
            const statusMap = {
                online: 'bg-emerald-400',
                offline: 'bg-rose-500',
                error: 'bg-amber-500',
                pending: 'bg-slate-400',
                unknown: 'bg-slate-500',
            };
            const statusDot = statusMap[status] || 'bg-slate-500';
            const statusText =
                status === 'online'
                    ? 'Live now'
                    : status === 'offline'
                      ? 'Offline'
                      : status === 'pending'
                        ? 'Checking…'
                        : status === 'error'
                          ? 'Trouble'
                          : 'Unknown';

            const quality =
                channel.quality_count && channel.quality_count > 1
                    ? `<span class="inline-flex items-center gap-1 rounded-full bg-brand-500/10 text-brand-200 text-[10px] font-semibold px-1.5 py-0.5 ring-1 ring-brand-500/20">HD</span>`
                    : '';

            const isFav = this.favorites.has(channel.url);

            const logoHtml = channel.icon_url
                ? `<img src="${escapeHtml(channel.icon_url)}" alt="" loading="lazy"
                        class="h-10 w-10 rounded-lg object-contain bg-black/40 ring-1 ring-white/5"
                        onerror="this.style.display='none';this.nextElementSibling.style.display='grid';">
                   <span style="display:none" class="h-10 w-10 rounded-lg bg-brand-400/15 text-brand-200 font-display font-semibold place-items-center ring-1 ring-brand-400/20">${escapeHtml(initial)}</span>`
                : `<span class="h-10 w-10 rounded-lg bg-brand-400/15 text-brand-200 font-display font-semibold grid place-items-center ring-1 ring-brand-400/20">${escapeHtml(initial)}</span>`;

            card.innerHTML = `
                <div class="flex items-center gap-3 min-w-0">
                    <div class="shrink-0">${logoHtml}</div>
                    <div class="min-w-0 flex-1">
                        <div class="flex items-center gap-2">
                            <h4 class="font-display font-semibold text-slate-100 truncate">${escapeHtml(name)}</h4>
                            ${quality}
                        </div>
                        <div class="mt-0.5 flex items-center gap-2 text-xs text-slate-400 min-w-0">
                            <span class="inline-flex items-center gap-1 shrink-0">
                                <span class="h-1.5 w-1.5 rounded-full ${statusDot}"></span>
                                ${escapeHtml(statusText)}
                            </span>
                            <span class="truncate">${escapeHtml(nowLine)}</span>
                        </div>
                    </div>
                    <div class="flex items-center gap-1 shrink-0">
                        <button type="button" class="play-btn inline-flex items-center gap-1.5 rounded-full bg-brand-400 hover:bg-brand-300 text-ink-950 font-semibold text-sm px-3.5 py-2 shadow-glow focus:outline-none focus:ring-2 focus:ring-brand-300/50" aria-label="Play ${escapeHtml(name)}">
                            <svg viewBox="0 0 24 24" class="h-3.5 w-3.5" fill="currentColor" aria-hidden="true"><path d="M8 5v14l11-7z"/></svg>
                            Play
                        </button>
                        <details class="relative more-menu">
                            <summary class="list-none cursor-pointer inline-grid place-items-center h-9 w-9 rounded-full text-slate-300 hover:text-slate-100 hover:bg-white/5 ring-1 ring-white/10 focus:outline-none focus:ring-2 focus:ring-brand-400/40" aria-label="More actions" title="More">
                                <svg viewBox="0 0 24 24" class="h-4 w-4" fill="currentColor" aria-hidden="true"><circle cx="5" cy="12" r="1.6"/><circle cx="12" cy="12" r="1.6"/><circle cx="19" cy="12" r="1.6"/></svg>
                            </summary>
                            <div class="absolute right-0 mt-1 w-44 rounded-xl border border-white/10 bg-ink-800/95 backdrop-blur shadow-2xl p-1 z-20">
                                <button type="button" data-action="fav" class="fav-btn w-full text-left rounded-lg px-2.5 py-1.5 text-sm hover:bg-white/5 flex items-center gap-2">
                                    <svg viewBox="0 0 24 24" class="h-4 w-4 ${isFav ? 'text-amber-300' : 'text-slate-400'}" fill="currentColor"><path d="M12 17.3 6.2 21l1.5-6.6L2.5 9.9l6.7-.6L12 3l2.8 6.3 6.7.6-5.2 4.5L17.8 21z"/></svg>
                                    <span class="fav-label">${isFav ? 'Remove from My list' : 'Add to My list'}</span>
                                </button>
                                <button type="button" data-action="copy" class="w-full text-left rounded-lg px-2.5 py-1.5 text-sm hover:bg-white/5 flex items-center gap-2">
                                    <svg viewBox="0 0 24 24" class="h-4 w-4 text-slate-400" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15V6a2 2 0 0 1 2-2h9"/></svg>
                                    Copy stream link
                                </button>
                                <button type="button" data-action="vlc" class="w-full text-left rounded-lg px-2.5 py-1.5 text-sm hover:bg-white/5 flex items-center gap-2">
                                    <svg viewBox="0 0 24 24" class="h-4 w-4 text-slate-400" fill="currentColor"><path d="M12 3 4 20h16Z"/></svg>
                                    Open in VLC
                                </button>
                                <button type="button" data-action="web" class="w-full text-left rounded-lg px-2.5 py-1.5 text-sm hover:bg-white/5 flex items-center gap-2">
                                    <svg viewBox="0 0 24 24" class="h-4 w-4 text-slate-400" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a15 15 0 0 1 0 18M12 3a15 15 0 0 0 0 18"/></svg>
                                    Open in new tab
                                </button>
                            </div>
                        </details>
                    </div>
                </div>
            `;

            const playBtn = card.querySelector('.play-btn');
            playBtn?.addEventListener('click', (e) => {
                e.stopPropagation();
                this.selectAndPlay(channel);
            });

            card.querySelector('[data-action="fav"]')?.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                this.toggleFavorite(channel.url);
            });
            card.querySelector('[data-action="copy"]')?.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                if (navigator.clipboard?.writeText) {
                    navigator.clipboard
                        .writeText(channel.url)
                        .then(() => this.notify('Stream link copied'))
                        .catch(() =>
                            this.notify('Could not copy — long-press to copy manually', 'error')
                        );
                } else {
                    this.notify('Copy not supported here', 'error');
                }
            });
            card.querySelector('[data-action="vlc"]')?.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                try {
                    window.open(`vlc://${channel.url}`, '_blank');
                    this.notify(`Opening ${channel.name || 'stream'} in VLC…`);
                } catch {
                    this.notify('Could not launch VLC', 'error');
                }
            });
            card.querySelector('[data-action="web"]')?.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                window.open(channel.url, '_blank', 'noopener');
            });

            // Whole-card click plays too (but not on nested buttons/menus).
            card.addEventListener('click', (e) => {
                if (e.target.closest('button') || e.target.closest('details')) return;
                this.selectAndPlay(channel);
            });

            return card;
        }

        _syncFavButton(btn, url) {
            const isFav = this.favorites.has(url);
            const icon = btn.querySelector('svg');
            const label = btn.querySelector('.fav-label');
            if (icon) {
                icon.classList.toggle('text-amber-300', isFav);
                icon.classList.toggle('text-slate-400', !isFav);
            }
            if (label) label.textContent = isFav ? 'Remove from My list' : 'Add to My list';
        }

        // ------------------------- infinite scroll ------------------------
        _setupInfiniteScroll() {
            const list = $('channelsList');
            list?.addEventListener('scroll', this._boundOnListScroll, { passive: true });
            window.addEventListener('scroll', this._boundOnWindowScroll, { passive: true });
        }

        _onListScroll(e) {
            const el = e.target;
            if (!el) return;
            const nearBottom =
                el.scrollTop + el.clientHeight >= el.scrollHeight - INFINITE_SCROLL_THRESHOLD_PX;
            if (nearBottom) this._fetchNextPage();
        }

        _onWindowScroll() {
            // On mobile the list is not itself scrollable; the page scrolls.
            const isDesktop = window.matchMedia('(min-width: 1024px)').matches;
            if (isDesktop) return;
            const nearBottom =
                window.innerHeight + window.scrollY >=
                document.documentElement.scrollHeight - INFINITE_SCROLL_THRESHOLD_PX;
            if (nearBottom) this._fetchNextPage();
        }

        // ------------------------- status + events ------------------------
        _connectEventStream() {
            if (!('EventSource' in window)) {
                this._startPollingFallback();
                return;
            }
            try {
                const es = new EventSource('/api/events');
                es.onmessage = (ev) => {
                    try {
                        const d = JSON.parse(ev.data);
                        if (d.error) return;
                        this._applyStatus(d);
                        if (
                            typeof d.revision === 'number' &&
                            d.revision !== this.lastRevision
                        ) {
                            this._scheduleQuietReload();
                        }
                    } catch {
                        /* ignore */
                    }
                };
                es.onerror = () => {
                    es.close();
                    this._startPollingFallback();
                };
            } catch {
                this._startPollingFallback();
            }
        }

        _startPollingFallback() {
            if (this._pollId) return;
            this._pollId = setInterval(() => this._fetchStatus(), 10000);
        }

        async _fetchStatus() {
            try {
                const r = await fetch('/status');
                const d = await r.json();
                this._applyStatus(d);
                if (typeof d.revision === 'number' && d.revision !== this.lastRevision) {
                    this._scheduleQuietReload();
                }
            } catch {
                /* ignore */
            }
        }

        _scheduleQuietReload() {
            clearTimeout(this.pendingReloadTimer);
            this.pendingReloadTimer = setTimeout(() => {
                this.reload({ resetScroll: false });
            }, 1500);
        }

        _applyStatus(d) {
            if (typeof d.total_channels === 'number') {
                const el = $('channelCount');
                const em = $('channelCountMob');
                if (el) el.textContent = d.total_channels;
                if (em) em.textContent = d.total_channels;
            }
            if (typeof d.online_channels === 'number') {
                const el = $('onlineCount');
                const em = $('onlineCountMob');
                if (el) el.textContent = d.online_channels;
                if (em) em.textContent = d.online_channels;
            }
            const scan = $('scanStatus');
            const scanM = $('scanStatusMob');
            const label = d.scanning ? 'Updating…' : 'Ready';
            if (scan) scan.textContent = label;
            if (scanM) scanM.textContent = label;
        }

        _updateVisibleCount() {
            const el = $('visibleCount');
            if (!el) return;
            const shown = this.channels.length;
            const total = this.totalChannels || shown;
            if (this.mode === 'favorites') {
                el.textContent = String(shown);
            } else if (shown < total) {
                el.textContent = `${shown} of ${total}`;
            } else {
                el.textContent = String(total);
            }
        }

        _showEmpty() {
            const es = $('emptyState');
            if (es) es.classList.remove('hidden');
            const list = $('channelsList');
            if (list) list.innerHTML = '';
        }

        _hideEmpty() {
            const es = $('emptyState');
            if (es) es.classList.add('hidden');
        }

        // ------------------------- notify ---------------------------------
        notify(message, type = 'info') {
            const host = $('notifyHost');
            if (!host) return;
            const el = document.createElement('div');
            const base =
                'pointer-events-auto max-w-xs rounded-xl px-3.5 py-2 text-sm font-medium shadow-2xl ring-1 backdrop-blur';
            const styles =
                type === 'error'
                    ? 'bg-rose-500/90 text-white ring-rose-300/50'
                    : type === 'success'
                      ? 'bg-emerald-500/90 text-white ring-emerald-300/50'
                      : 'bg-ink-800/95 text-slate-100 ring-white/10';
            el.className = `${base} ${styles} translate-x-2 opacity-0 transition duration-200`;
            el.textContent = message;
            host.appendChild(el);
            requestAnimationFrame(() => {
                el.classList.remove('translate-x-2', 'opacity-0');
            });
            setTimeout(() => {
                el.classList.add('translate-x-2', 'opacity-0');
                setTimeout(() => el.remove(), 220);
            }, 2600);
        }
    }

    // -----------------------------------------------------------------------
    document.addEventListener('DOMContentLoaded', () => {
        const app = new LiveTVGuide();
        window.iptvScanner = app;
        app.init();
    });
})();
