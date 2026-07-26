// IPTV Scanner service worker — caches the app shell ONLY.
// Streams (/proxy/stream), /channels, /status, /api/*, and /icons/* are always network.
// JS/CSS use network-first so UI fixes apply without fighting a stale cache.

const SHELL_CACHE = 'iptv-shell-v8';
const SHELL_URLS = [
    '/',
    '/js/scripts.js',
    '/css/styles.css',
    '/manifest.webmanifest',
];

self.addEventListener('install', (event) => {
    event.waitUntil(
        caches
            .open(SHELL_CACHE)
            .then((cache) =>
                Promise.all(
                    SHELL_URLS.map((u) =>
                        cache
                            .add(new Request(u, { cache: 'reload' }))
                            .catch(() => null)
                    )
                )
            )
            .then(() => self.skipWaiting())
    );
});

self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches
            .keys()
            .then((keys) =>
                Promise.all(
                    keys
                        .filter((k) => k !== SHELL_CACHE)
                        .map((k) => caches.delete(k))
                )
            )
            .then(() => self.clients.claim())
    );
});

function isShellRequest(url) {
    if (url.pathname === '/' || url.pathname === '/index.html') return true;
    if (url.pathname === '/manifest.webmanifest') return true;
    if (url.pathname === '/js/scripts.js') return true;
    if (url.pathname.startsWith('/css/')) return true;
    if (url.pathname.startsWith('/fonts/')) return true;
    return false;
}

function isBypass(url) {
    if (url.pathname.startsWith('/proxy/')) return true;
    if (url.pathname === '/channels') return true;
    if (url.pathname === '/status') return true;
    if (url.pathname.startsWith('/api/')) return true;
    if (url.pathname.startsWith('/icons/')) return true;
    if (url.pathname === '/sw.js') return true;
    return false;
}

function isVolatileShell(url) {
    // Always try network first for scripts/styles so deploys show up.
    return url.pathname === '/js/scripts.js' || url.pathname.startsWith('/css/');
}

self.addEventListener('fetch', (event) => {
    const req = event.request;
    if (req.method !== 'GET') return;

    let url;
    try {
        url = new URL(req.url);
    } catch {
        return;
    }
    if (url.origin !== self.location.origin) return;
    if (isBypass(url)) return;

    if (isShellRequest(url) && isVolatileShell(url)) {
        event.respondWith(
            fetch(req)
                .then((res) => {
                    if (res && res.ok) {
                        const clone = res.clone();
                        caches
                            .open(SHELL_CACHE)
                            .then((c) => c.put(req, clone))
                            .catch(() => {});
                    }
                    return res;
                })
                .catch(() => caches.match(req))
        );
        return;
    }

    if (isShellRequest(url)) {
        event.respondWith(
            caches.match(req).then((cached) => {
                const fetcher = fetch(req)
                    .then((res) => {
                        if (res && res.ok) {
                            const clone = res.clone();
                            caches
                                .open(SHELL_CACHE)
                                .then((c) => c.put(req, clone))
                                .catch(() => {});
                        }
                        return res;
                    })
                    .catch(() => cached);
                return cached || fetcher;
            })
        );
        return;
    }

    if (
        url.hostname === 'fonts.googleapis.com' ||
        url.hostname === 'fonts.gstatic.com' ||
        url.hostname === 'cdn.tailwindcss.com'
    ) {
        event.respondWith(
            caches.match(req).then(
                (cached) =>
                    cached ||
                    fetch(req)
                        .then((res) => {
                            if (res && res.ok) {
                                const clone = res.clone();
                                caches
                                    .open(SHELL_CACHE)
                                    .then((c) => c.put(req, clone))
                                    .catch(() => {});
                            }
                            return res;
                        })
                        .catch(() => cached)
            )
        );
    }
});
