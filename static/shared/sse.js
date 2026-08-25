/**
 * Reconnecting EventSource for the unattended kiosk.
 *
 * A plain EventSource only self-heals when the *connection drops*: readyState
 * goes to CONNECTING and the browser retries on its own. When the server
 * answers with an HTTP error instead — nginx returning 502 for the few seconds
 * `systemctl restart storybot` takes — the spec says the user agent "fails the
 * connection": readyState goes to CLOSED and no further retry is ever made.
 *
 * The kiosk has nobody to press reload, so that leaves a page that looks
 * healthy while silently ignoring every NFC tap. This helper watches for the
 * CLOSED case and rebuilds the stream with an exponential backoff, forever.
 *
 * Behaviour is covered by tests/js/sse_reconnect.test.cjs.
 */

(function (root) {
    'use strict';

    /**
     * Open an EventSource that survives server restarts.
     *
     * @param {string} url            stream to connect to
     * @param {object} [options]
     * @param {object} [options.listeners]      {eventName: handler} re-registered on every reconnect
     * @param {function} [options.onOpen]       called on each successful connection
     * @param {function} [options.EventSourceCtor] injectable for tests
     * @param {function} [options.scheduler]       injectable setTimeout
     * @param {function} [options.cancelScheduled] injectable clearTimeout
     * @param {number} [options.baseDelayMs]    first retry delay
     * @param {number} [options.maxDelayMs]     backoff cap
     * @returns {{close: function}} handle that stops reconnecting
     */
    function createReconnectingEventSource(url, options) {
        const opts = options || {};
        const Ctor = opts.EventSourceCtor || root.EventSource;
        const schedule = opts.scheduler || root.setTimeout;
        const cancel = opts.cancelScheduled || root.clearTimeout;
        const listeners = opts.listeners || {};
        const baseDelayMs = opts.baseDelayMs || 1000;
        const maxDelayMs = opts.maxDelayMs || 30000;

        // CLOSED is 2 in every browser; read it off the ctor so a stub can differ.
        const CLOSED = Ctor.CLOSED !== undefined ? Ctor.CLOSED : 2;

        let source = null;
        let attempt = 0;
        let pendingTimer = null;
        let stopped = false;

        function connect() {
            pendingTimer = null;
            source = new Ctor(url);

            source.addEventListener('open', function () {
                // Reset only on a real connection, so a server that flaps
                // still walks the backoff up instead of hammering.
                attempt = 0;
                if (opts.onOpen) opts.onOpen();
            });

            source.addEventListener('error', function () {
                if (stopped) return;
                // readyState CONNECTING means the browser is already retrying;
                // reconnecting here would open a second, duplicate stream.
                if (source.readyState !== CLOSED) return;
                scheduleReconnect();
            });

            Object.keys(listeners).forEach(function (eventName) {
                source.addEventListener(eventName, listeners[eventName]);
            });
        }

        function scheduleReconnect() {
            if (pendingTimer !== null) return;
            const delay = Math.min(baseDelayMs * Math.pow(2, attempt), maxDelayMs);
            attempt++;
            pendingTimer = schedule(function () {
                if (stopped) return;
                // Free the dead connection before opening its replacement.
                if (source) source.close();
                connect();
            }, delay);
        }

        connect();

        return {
            close: function () {
                stopped = true;
                if (pendingTimer !== null) {
                    cancel(pendingTimer);
                    pendingTimer = null;
                }
                if (source) source.close();
            },
        };
    }

    root.createReconnectingEventSource = createReconnectingEventSource;

    if (typeof module !== 'undefined' && module.exports) {
        module.exports = { createReconnectingEventSource };
    }
})(typeof globalThis !== 'undefined' ? globalThis : this);
