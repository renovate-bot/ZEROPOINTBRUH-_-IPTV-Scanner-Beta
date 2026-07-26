// IPTV Scanner — Phase 3 UI (Tailwind, single responsive shell, paginated fetch)
// Plain-language, big Play CTA, progressive disclosure.

(() => {
    'use strict';

    const PAGE_SIZE = 50;
    const FAVORITES_STORAGE_KEY = 'iptv_scanner_favorites_v1';
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

    /** ISO 3166-1 alpha-2 → regional-indicator flag emoji (e.g. US → 🇺🇸). */
    function countryFlagEmoji(code) {
        if (!code) return '🌐';
        let c = String(code).trim().toUpperCase();
        if (c === 'UK') c = 'GB';
        if (c === 'EL') c = 'GR';
        if (!c || c === 'XX' || c === 'ZZ' || c === 'GLOBAL' || c === 'UNKNOWN' || c === 'UNDEFINED') {
            return '🌐';
        }
        if (!/^[A-Z]{2}$/.test(c)) return '🌐';
        const A = 0x1f1e6;
        return String.fromCodePoint(A + (c.charCodeAt(0) - 65), A + (c.charCodeAt(1) - 65));
    }

    function channelTitleWithFlag(channel) {
        const name = (channel && channel.name) || 'Untitled channel';
        const flag = countryFlagEmoji(channel && channel.country);
        return `${flag} ${name}`;
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
            this.totalPages = 1;
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
            this.sort = 'trending';
            this.sortDir = 'desc';

            this.currentChannel = null;
            this.hls = null;
            this._pendingQualityUrl = null;

            this.favorites = this._loadFavorites();

            this._channelMenu = null;
            this._channelMenuChannel = null;
            this._channelMenuTrigger = null;
            this._boundCloseChannelMenu = this._closeChannelMenu.bind(this);
            this._aliveReported = new Set();
            this._watchReported = new Set();
            this._filterSheetKind = null;
            this._filterSheetOptions = [];
        }

        // ------------------------- init -----------------------------------
        init() {
            this._setupIntegrationLinks();
            this._setupHeader();
            this._setupModeTabs();
            this._setupFilters();
            this._setupMoreToggles();
            this._setupPlayerControls();
            this._setupChannelMenu();
            this._setupFilterSheet();
            this._setupPager();
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

            // Update cards in place (fav lives in the floating menu now;
            // if open for this url, refresh its label too).
            if (this._channelMenu && !this._channelMenu.hidden && this._channelMenuChannel?.url === url) {
                const favBtn = this._channelMenu.querySelector('[data-action="fav"]');
                if (favBtn) this._syncFavButton(favBtn, url);
            }

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
            const sort = $('sortFilter');
            const dir = $('sortDir');

            sort?.addEventListener('change', () => {
                this.sort = sort.value;
                if (
                    ['trending', 'popular', 'trend_score', 'watch_count'].includes(
                        sort.value
                    ) &&
                    dir
                ) {
                    dir.value = 'desc';
                    this.sortDir = 'desc';
                }
                this.reload({ resetScroll: true });
            });
            dir?.addEventListener('change', () => {
                this.sortDir = dir.value;
                this.reload({ resetScroll: true });
            });

            $('groupFilterBtn')?.addEventListener('click', () => this._openFilterSheet('group'));
            $('countryFilterBtn')?.addEventListener('click', () => this._openFilterSheet('country'));
            this._syncFilterLabels();
        }

        _setupFilterSheet() {
            const sheet = $('filterSheet');
            if (!sheet) return;
            sheet.querySelectorAll('[data-sheet-dismiss]').forEach((el) => {
                el.addEventListener('click', () => this._closeFilterSheet());
            });
            const search = $('filterSheetSearch');
            search?.addEventListener('input', () => this._renderFilterSheetList(search.value));
            document.addEventListener('keydown', (e) => {
                if (e.key === 'Escape' && sheet && !sheet.classList.contains('hidden')) {
                    this._closeFilterSheet();
                }
            });
        }

        _syncFilterLabels() {
            const gLab = $('groupFilterLabel');
            const cLab = $('countryFilterLabel');
            const g = $('groupFilter');
            const c = $('countryFilter');
            if (g) g.value = this.group || '';
            if (c) c.value = this.country || '';
            if (gLab) {
                const opt = g?.selectedOptions?.[0];
                gLab.textContent = opt?.textContent || this.group || 'All categories';
            }
            if (cLab) {
                if (!this.country) {
                    cLab.textContent = 'All countries';
                } else {
                    const opt = c?.selectedOptions?.[0];
                    const name = opt?.textContent || this.country;
                    cLab.textContent = `${countryFlagEmoji(this.country)} ${name}`;
                }
            }
        }

        _openFilterSheet(kind) {
            const sheet = $('filterSheet');
            const title = $('filterSheetTitle');
            const search = $('filterSheetSearch');
            if (!sheet) return;
            this._filterSheetKind = kind;
            if (title) title.textContent = kind === 'country' ? 'Country' : 'Category';
            if (search) search.value = '';

            const sel = $(kind === 'country' ? 'countryFilter' : 'groupFilter');
            const options = [];
            if (sel) {
                Array.from(sel.options).forEach((opt) => {
                    options.push({ value: opt.value, label: opt.textContent || opt.value });
                });
            }
            this._filterSheetOptions = options;
            this._renderFilterSheetList('');
            sheet.classList.remove('hidden');
            sheet.setAttribute('aria-hidden', 'false');
            document.body.classList.add('overflow-hidden');
            setTimeout(() => search?.focus(), 50);
        }

        _closeFilterSheet() {
            const sheet = $('filterSheet');
            if (!sheet) return;
            sheet.classList.add('hidden');
            sheet.setAttribute('aria-hidden', 'true');
            document.body.classList.remove('overflow-hidden');
            this._filterSheetKind = null;
        }

        _renderFilterSheetList(query) {
            const list = $('filterSheetList');
            if (!list) return;
            const q = String(query || '').trim().toLowerCase();
            const current =
                this._filterSheetKind === 'country' ? this.country || '' : this.group || '';
            const opts = this._filterSheetOptions.filter((o) => {
                if (!q) return true;
                return (
                    String(o.label || '').toLowerCase().includes(q) ||
                    String(o.value || '').toLowerCase().includes(q)
                );
            });
            list.innerHTML = '';
            if (!opts.length) {
                list.innerHTML =
                    '<p class="text-sm text-slate-400 text-center py-8">No matches</p>';
                return;
            }
            const frag = document.createDocumentFragment();
            for (const o of opts) {
                const btn = document.createElement('button');
                btn.type = 'button';
                const selected = o.value === current;
                btn.className = [
                    'w-full min-h-[48px] rounded-xl px-3 py-3 text-left text-sm flex items-center justify-between gap-2',
                    selected
                        ? 'bg-brand-400/15 text-brand-100 ring-1 ring-brand-400/40'
                        : 'hover:bg-white/5 text-slate-100',
                ].join(' ');
                const label =
                    this._filterSheetKind === 'country' && o.value
                        ? `${countryFlagEmoji(o.value)} ${o.label}`
                        : o.label;
                btn.innerHTML = `<span class="truncate">${escapeHtml(label)}</span>${
                    selected
                        ? '<svg viewBox="0 0 24 24" class="h-5 w-5 shrink-0 text-brand-300" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 12l5 5L20 7"/></svg>'
                        : ''
                }`;
                btn.addEventListener('click', () => {
                    if (this._filterSheetKind === 'country') {
                        this.country = o.value;
                    } else {
                        this.group = o.value;
                    }
                    this._syncFilterLabels();
                    this._closeFilterSheet();
                    this.reload({ resetScroll: true });
                });
                frag.appendChild(btn);
            }
            list.appendChild(frag);
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
                this._syncFilterLabels();
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
            this._setAudioOnlyUi(false);

            const path = (originalUrl || '').split(/[?#]/)[0].toLowerCase();
            const progressive = /\.(mp4|webm|ogv|mp3|aac|m4a|ogg|wav)$/i.test(path);
            const audioFile = /\.(mp3|aac|m4a|ogg|wav)$/i.test(path);

            // Decide audio-only from real video dimensions after playback starts —
            // HLS.js often omits videoCodec/height at MANIFEST_PARSED (false positives).
            const watchDimensions = () => {
                const reveal = () => {
                    if (!video.isConnected) return;
                    if (video.videoWidth > 0 && video.videoHeight > 0) {
                        this._setAudioOnlyUi(false);
                        this._maybeReportAlive();
                        return;
                    }
                    if (!video.paused && video.currentTime > 0.25 && video.videoWidth === 0) {
                        this._setAudioOnlyUi(true);
                        this._maybeReportAlive();
                    }
                };
                video.addEventListener('loadeddata', reveal);
                video.addEventListener('playing', () => {
                    this._maybeReportAlive();
                    setTimeout(reveal, 400);
                });
                video.addEventListener('resize', reveal);
            };

            if (progressive) {
                video.src = playUrl;
                if (audioFile) this._setAudioOnlyUi(true);
                else watchDimensions();
                return;
            }

            // Prefer hls.js so we get quality control on Chromium / Firefox.
            if (typeof Hls !== 'undefined' && Hls.isSupported()) {
                const hls = new Hls({
                    enableWorker: true,
                    lowLatencyMode: false,
                    maxBufferLength: 30,
                    backBufferLength: 30,
                    xhrSetup: (xhr) => {
                        try {
                            xhr.withCredentials = false;
                        } catch {
                            /* ignore */
                        }
                    },
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
                watchDimensions();
                return;
            }

            // Native (Safari / iOS): no per-level quality control, but plays HLS.
            if (
                video.canPlayType('application/vnd.apple.mpegurl') ||
                video.canPlayType('application/x-mpegURL')
            ) {
                video.src = playUrl;
                watchDimensions();
                return;
            }

            video.src = playUrl;
            watchDimensions();
        }

        _setAudioOnlyUi(on) {
            const wrap = $('videoPlayer');
            if (!wrap) return;
            let badge = wrap.querySelector('[data-audio-only]');
            if (!on) {
                badge?.remove();
                return;
            }
            if (!badge) {
                badge = document.createElement('div');
                badge.setAttribute('data-audio-only', '1');
                badge.className =
                    'pointer-events-none absolute inset-0 grid place-items-center bg-gradient-to-b from-ink-900/40 to-ink-950/80';
                badge.innerHTML = `
                    <div class="text-center px-4">
                        <div class="mx-auto mb-3 grid h-16 w-16 place-items-center rounded-full bg-brand-400/15 ring-1 ring-brand-400/30 text-brand-300">
                            <svg viewBox="0 0 24 24" class="h-8 w-8" fill="currentColor" aria-hidden="true"><path d="M12 3v10.55A4 4 0 1 0 14 17V7h4V3h-6z"/></svg>
                        </div>
                        <p class="font-display text-base font-semibold text-slate-100">Audio stream</p>
                        <p class="text-sm text-slate-400 mt-1">This channel has sound only — no video.</p>
                    </div>`;
                wrap.appendChild(badge);
            }
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
            if (nm) nm.textContent = channelTitleWithFlag(channel);
            if (inf) inf.textContent = meta;

            this._playStream(channel.url, channel.name || '');
            this._recordWatch(channel);

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

        _recordWatch(channel) {
            const url = channel?.url;
            if (!url || this._watchReported.has(url)) return;
            this._watchReported.add(url);
            fetch('/api/watch', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url }),
            }).catch(() => {
                this._watchReported.delete(url);
            });
        }

        _maybeReportAlive() {
            const ch = this.currentChannel;
            if (!ch?.url) return;
            const status = String(ch.status || '').toLowerCase();
            // Already live in catalog — nothing to promote.
            if (status === 'online') return;
            if (this._aliveReported.has(ch.url)) return;
            this._aliveReported.add(ch.url);

            fetch('/api/report-alive', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url: ch.url }),
            })
                .then((r) => r.json())
                .then((data) => {
                    if (!data?.ok) return;
                    ch.status = 'online';
                    if (data.promoted) {
                        this.notify('Stream verified — now listed as live for everyone');
                    }
                    // Update the card status chip in place.
                    const card = document.querySelector(
                        `.channel-card[data-channel-url="${CSS.escape(ch.url)}"]`
                    );
                    if (card) {
                        const chip = card.querySelector('.mt-0\\.5 span span.h-1\\.5');
                        // fallback: re-render is heavier; patch text if present
                        const statusRow = card.querySelector('.mt-0\\.5');
                        if (statusRow) {
                            const label = statusRow.querySelector('span.inline-flex');
                            if (label) {
                                label.innerHTML =
                                    '<span class="h-1.5 w-1.5 rounded-full bg-emerald-400"></span> Live now';
                            }
                        }
                    }
                    if (typeof data.revision === 'number') {
                        this.lastRevision = data.revision;
                    }
                })
                .catch(() => {
                    this._aliveReported.delete(ch.url);
                });
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
            this.totalPages = 1;
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
            this._updatePager();

            await this._loadPage(1, { replace: true, resetScroll });
        }

        /**
         * Background refresh when the catalog revision changes.
         * Stays on the current page, keeps scroll position, does not touch the player.
         */
        async _softRefresh() {
            if (this.isFetching) {
                this._scheduleQuietReload();
                return;
            }
            const page = Math.max(1, this.currentPage || 1);
            const listEl = $('channelsList');
            const savedListScroll = listEl ? listEl.scrollTop : 0;
            const savedWinScroll = window.scrollY || document.documentElement.scrollTop || 0;
            const prevSig = this.channels
                .map((c) => `${c.url}\0${c.status || ''}\0${c.name || ''}`)
                .join('\n');

            this.isFetching = true;
            try {
                const res = await fetch(`/channels?${this._buildQuery(page)}`);
                const data = await res.json();
                let payload = Array.isArray(data.channels) ? data.channels : [];
                if (this.mode === 'favorites') {
                    payload = payload.filter((c) => this.favorites.has(c.url));
                }

                this.currentPage = data.current_page || page;
                this.totalPages = Math.max(1, Number(data.total_pages) || 1);
                this.hasMore = Boolean(data.has_more);
                this.totalChannels = Number(data.total_channels || 0);
                if (typeof data.revision === 'number') {
                    this.lastRevision = data.revision;
                }

                // Catalog shrank — quietly clamp to last page without a hard jump flash.
                if (this.currentPage > this.totalPages) {
                    this.isFetching = false;
                    await this._loadPage(this.totalPages, { resetScroll: false });
                    return;
                }

                this.channels = [];
                this.channelIndex.clear();
                for (const ch of payload) {
                    if (ch?.url && !this.channelIndex.has(ch.url)) {
                        this.channelIndex.set(ch.url, ch);
                        this.channels.push(ch);
                    }
                }

                this._populateFilterOptions(data);

                const nextSig = this.channels
                    .map((c) => `${c.url}\0${c.status || ''}\0${c.name || ''}`)
                    .join('\n');

                if (nextSig !== prevSig) {
                    this._renderList();
                    if (listEl) listEl.scrollTop = savedListScroll;
                    window.scrollTo(0, savedWinScroll);
                }

                this._updateVisibleCount();
                this._updatePager();

                if (!this.channels.length) {
                    this._showEmpty();
                } else {
                    this._hideEmpty();
                }
            } catch (err) {
                console.error('Soft refresh failed:', err);
            } finally {
                this.isFetching = false;
                this._updatePager();
            }
        }

        async _loadPage(page, opts = {}) {
            if (this.isFetching) return;
            const target = Math.max(1, Number(page) || 1);
            const resetScroll = opts.resetScroll !== false;
            this.isFetching = true;
            try {
                const url = `/channels?${this._buildQuery(target)}`;
                const res = await fetch(url);
                const data = await res.json();

                const list = Array.isArray(data.channels) ? data.channels : [];
                this.currentPage = data.current_page || target;
                this.totalPages = Math.max(1, Number(data.total_pages) || 1);
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

                this.channels = [];
                this.channelIndex.clear();
                for (const ch of payload) {
                    if (ch?.url && !this.channelIndex.has(ch.url)) {
                        this.channelIndex.set(ch.url, ch);
                        this.channels.push(ch);
                    }
                }

                this._populateFilterOptions(data);
                this._renderList();
                this._updateVisibleCount();
                this._updatePager();

                if (!this.channels.length) {
                    this._showEmpty();
                } else {
                    this._hideEmpty();
                }

                if (resetScroll) {
                    const el = $('channelsList');
                    if (el) el.scrollTop = 0;
                    if (typeof window !== 'undefined' && window.matchMedia('(max-width: 1023px)').matches) {
                        el?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
                    }
                }
            } catch (err) {
                console.error('Load failed:', err);
                this.notify('Could not load channels — check connection', 'error');
            } finally {
                this.isFetching = false;
                const list = $('channelsList');
                if (list) list.removeAttribute('aria-busy');
                this._updatePager();
            }
        }

        _populateFilterOptions(data) {
            const groups = Array.isArray(data.groups) ? data.groups : [];
            const countries = Array.isArray(data.countries) ? data.countries : [];
            const g = $('groupFilter');
            const c = $('countryFilter');

            const fillGroups = (sel, values, placeholder, current) => {
                if (!sel) return;
                const labels = values
                    .map((v) => {
                        if (v == null) return '';
                        if (typeof v === 'string' || typeof v === 'number') return String(v);
                        if (typeof v === 'object') return String(v.name || v.label || '');
                        return String(v);
                    })
                    .filter(Boolean);
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

            const fillCountries = (sel, values, placeholder, current) => {
                if (!sel) return;
                const opts = values
                    .map((v) => {
                        if (v == null) return null;
                        if (typeof v === 'string' || typeof v === 'number') {
                            const s = String(v);
                            return { value: s, label: s };
                        }
                        if (typeof v === 'object') {
                            const code = String(v.code || v.value || '').trim();
                            const name = String(v.name || v.label || code).trim();
                            if (!code && !name) return null;
                            return {
                                value: code || name,
                                label: name && code && name !== code ? name : name || code,
                            };
                        }
                        return null;
                    })
                    .filter(Boolean);
                opts.sort((a, b) => a.label.localeCompare(b.label));
                const known = new Set(opts.map((o) => o.value));
                const preserve = current && known.has(current) ? current : '';
                sel.innerHTML =
                    `<option value="">${placeholder}</option>` +
                    opts
                        .map(
                            (o) =>
                                `<option value="${escapeHtml(o.value)}">${escapeHtml(o.label)}</option>`
                        )
                        .join('');
                if (preserve) sel.value = preserve;
            };

            fillGroups(g, groups, 'All categories', this.group);
            fillCountries(c, countries, 'All countries', this.country);
            this._syncFilterLabels();
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
            const flag = countryFlagEmoji(country);
            const nowLine =
                channel.playing_now && String(channel.playing_now).trim()
                    ? channel.playing_now
                    : [group, country && country !== 'GLOBAL' ? country : '']
                          .filter(Boolean)
                          .join(' · ') || 'Live stream';

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
                        <div class="flex items-center gap-2 min-w-0">
                            <h4 class="font-display font-semibold text-slate-100 truncate"><span class="mr-1" aria-hidden="true">${flag}</span>${escapeHtml(name)}</h4>
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
                        <button type="button" class="more-btn inline-grid place-items-center h-9 w-9 rounded-full text-slate-300 hover:text-slate-100 hover:bg-white/5 ring-1 ring-white/10 focus:outline-none focus:ring-2 focus:ring-brand-400/40" aria-label="More actions" aria-haspopup="menu" title="More">
                            <svg viewBox="0 0 24 24" class="h-4 w-4" fill="currentColor" aria-hidden="true"><circle cx="5" cy="12" r="1.6"/><circle cx="12" cy="12" r="1.6"/><circle cx="19" cy="12" r="1.6"/></svg>
                        </button>
                    </div>
                </div>
            `;

            const playBtn = card.querySelector('.play-btn');
            playBtn?.addEventListener('click', (e) => {
                e.stopPropagation();
                this.selectAndPlay(channel);
            });

            card.querySelector('.more-btn')?.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                this._openChannelMenu(e.currentTarget, channel);
            });

            // Whole-card click plays too (but not on nested buttons).
            card.addEventListener('click', (e) => {
                if (e.target.closest('button')) return;
                this.selectAndPlay(channel);
            });

            return card;
        }

        // ------------------------- floating channel menu ------------------
        _setupChannelMenu() {
            if (this._channelMenu) return;
            const menu = document.createElement('div');
            menu.id = 'channelActionMenu';
            menu.setAttribute('role', 'menu');
            menu.hidden = true;
            menu.className =
                'fixed z-[100] w-48 rounded-xl border border-white/10 bg-ink-800/95 backdrop-blur shadow-2xl p-1';
            document.body.appendChild(menu);
            this._channelMenu = menu;

            document.addEventListener('pointerdown', (e) => {
                if (menu.hidden) return;
                if (menu.contains(e.target)) return;
                if (this._channelMenuTrigger?.contains(e.target)) return;
                this._closeChannelMenu();
            });
            document.addEventListener('keydown', (e) => {
                if (e.key === 'Escape') this._closeChannelMenu();
            });
            window.addEventListener('resize', this._boundCloseChannelMenu);
            $('channelsList')?.addEventListener('scroll', this._boundCloseChannelMenu, {
                passive: true,
            });
            window.addEventListener('scroll', this._boundCloseChannelMenu, { passive: true });
        }

        _closeChannelMenu() {
            const menu = this._channelMenu;
            if (!menu || menu.hidden) return;
            menu.hidden = true;
            menu.innerHTML = '';
            this._channelMenuChannel = null;
            this._channelMenuTrigger = null;
        }

        _repositionChannelMenu() {
            const menu = this._channelMenu;
            const trigger = this._channelMenuTrigger;
            if (!menu || menu.hidden || !trigger) return;
            const rect = trigger.getBoundingClientRect();
            const mw = menu.offsetWidth || 192;
            const mh = menu.offsetHeight || 168;
            let top = rect.bottom + 6;
            let left = rect.right - mw;
            if (left < 8) left = 8;
            if (left + mw > window.innerWidth - 8) left = Math.max(8, window.innerWidth - mw - 8);
            if (top + mh > window.innerHeight - 8) {
                top = Math.max(8, rect.top - mh - 6);
            }
            menu.style.top = `${Math.round(top)}px`;
            menu.style.left = `${Math.round(left)}px`;
        }

        _openChannelMenu(trigger, channel) {
            this._setupChannelMenu();
            const menu = this._channelMenu;
            if (!menu || !channel?.url) return;

            // Toggle closed if same trigger re-clicked.
            if (!menu.hidden && this._channelMenuTrigger === trigger) {
                this._closeChannelMenu();
                return;
            }

            const isFav = this.favorites.has(channel.url);
            menu.innerHTML = `
                <button type="button" role="menuitem" data-action="fav" class="fav-btn w-full text-left rounded-lg px-2.5 py-1.5 text-sm hover:bg-white/5 flex items-center gap-2">
                    <svg viewBox="0 0 24 24" class="h-4 w-4 ${isFav ? 'text-amber-300' : 'text-slate-400'}" fill="currentColor"><path d="M12 17.3 6.2 21l1.5-6.6L2.5 9.9l6.7-.6L12 3l2.8 6.3 6.7.6-5.2 4.5L17.8 21z"/></svg>
                    <span class="fav-label">${isFav ? 'Remove from My list' : 'Add to My list'}</span>
                </button>
                <button type="button" role="menuitem" data-action="copy" class="w-full text-left rounded-lg px-2.5 py-1.5 text-sm hover:bg-white/5 flex items-center gap-2">
                    <svg viewBox="0 0 24 24" class="h-4 w-4 text-slate-400" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15V6a2 2 0 0 1 2-2h9"/></svg>
                    Copy stream link
                </button>
                <button type="button" role="menuitem" data-action="vlc" class="w-full text-left rounded-lg px-2.5 py-1.5 text-sm hover:bg-white/5 flex items-center gap-2">
                    <svg viewBox="0 0 24 24" class="h-4 w-4 text-slate-400" fill="currentColor"><path d="M12 3 4 20h16Z"/></svg>
                    Open in VLC
                </button>
                <button type="button" role="menuitem" data-action="web" class="w-full text-left rounded-lg px-2.5 py-1.5 text-sm hover:bg-white/5 flex items-center gap-2">
                    <svg viewBox="0 0 24 24" class="h-4 w-4 text-slate-400" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a15 15 0 0 1 0 18M12 3a15 15 0 0 0 0 18"/></svg>
                    Open in new tab
                </button>
            `;

            menu.querySelector('[data-action="fav"]')?.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                this.toggleFavorite(channel.url);
                this._closeChannelMenu();
            });
            menu.querySelector('[data-action="copy"]')?.addEventListener('click', (e) => {
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
                this._closeChannelMenu();
            });
            menu.querySelector('[data-action="vlc"]')?.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                try {
                    window.open(`vlc://${channel.url}`, '_blank');
                    this.notify(`Opening ${channel.name || 'stream'} in VLC…`);
                } catch {
                    this.notify('Could not launch VLC', 'error');
                }
                this._closeChannelMenu();
            });
            menu.querySelector('[data-action="web"]')?.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                window.open(channel.url, '_blank', 'noopener');
                this._closeChannelMenu();
            });

            this._channelMenuChannel = channel;
            this._channelMenuTrigger = trigger;
            menu.hidden = false;
            this._repositionChannelMenu();
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

        // ------------------------- page controls --------------------------
        _setupPager() {
            $('pagePrevBtn')?.addEventListener('click', () => {
                if (this.currentPage > 1) this._loadPage(this.currentPage - 1);
            });
            $('pageNextBtn')?.addEventListener('click', () => {
                if (this.currentPage < this.totalPages) this._loadPage(this.currentPage + 1);
            });
            this._updatePager();
        }

        _updatePager() {
            const prev = $('pagePrevBtn');
            const next = $('pageNextBtn');
            const label = $('pageLabel');
            const page = Math.max(1, this.currentPage || 1);
            const total = Math.max(1, this.totalPages || 1);
            if (label) label.textContent = `Page ${page} of ${total}`;
            if (prev) prev.disabled = page <= 1 || this.isFetching;
            if (next) next.disabled = page >= total || this.isFetching;
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
                this._softRefresh();
            }, 2000);
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
            const page = Math.max(1, this.currentPage || 1);
            const total = this.totalChannels || shown;
            if (this.mode === 'favorites') {
                el.textContent = `${shown} on page ${page}`;
            } else {
                el.textContent = `${shown} on page ${page} · ${total} total`;
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
