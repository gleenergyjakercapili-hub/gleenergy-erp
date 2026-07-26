/* Gleenergy ERP service worker — deliberately minimal.
   Exists to satisfy PWA installability on browsers that still require one.
   NO caching: every request goes straight to the network, so the app can never
   serve a stale copy of itself after an update. */
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", () => { /* network passthrough — default browser handling */ });
