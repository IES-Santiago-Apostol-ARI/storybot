/**
 * Behavioural tests for the reconnecting EventSource helper.
 *
 * The kiosk runs unattended: a `systemctl restart storybot` makes nginx answer
 * the in-flight SSE reconnect with 502, and per the HTML spec an EventSource
 * that receives an HTTP error (or a non-text/event-stream body) *fails the
 * connection* — readyState goes to CLOSED and the browser never retries. The
 * page then looks perfectly healthy while silently ignoring every NFC tap.
 *
 * These tests drive the helper with a fake EventSource and a fake scheduler so
 * the reconnect policy is asserted directly, without a browser.
 */

const test = require('node:test');
const assert = require('node:assert');
const path = require('node:path');

const { createReconnectingEventSource } = require(
    path.join(__dirname, '..', '..', 'static', 'shared', 'sse.js')
);

class FakeEventSource {
    static CONNECTING = 0;
    static OPEN = 1;
    static CLOSED = 2;

    constructor(url) {
        this.url = url;
        this.readyState = FakeEventSource.CONNECTING;
        this.closed = false;
        this._listeners = {};
        FakeEventSource.instances.push(this);
    }

    addEventListener(type, handler) {
        (this._listeners[type] = this._listeners[type] || []).push(handler);
    }

    close() {
        this.closed = true;
        this.readyState = FakeEventSource.CLOSED;
    }

    /** Simulate the browser firing an event at this source. */
    emit(type, event) {
        (this._listeners[type] || []).forEach((handler) => handler(event));
    }

    /** Simulate the spec's "fail the connection" path (HTTP 502, bad MIME). */
    fail() {
        this.readyState = FakeEventSource.CLOSED;
        this.emit('error', {});
    }

    /** Simulate a transient network drop: the browser retries on its own. */
    drop() {
        this.readyState = FakeEventSource.CONNECTING;
        this.emit('error', {});
    }

    open() {
        this.readyState = FakeEventSource.OPEN;
        this.emit('open', {});
    }
}

/** Fake scheduler: records pending timers and fires them on demand. */
function makeScheduler() {
    const pending = [];
    let nextId = 1;
    const scheduler = (fn, delay) => {
        const id = nextId++;
        pending.push({ id, fn, delay });
        return id;
    };
    scheduler.cancel = (id) => {
        const i = pending.findIndex((t) => t.id === id);
        if (i !== -1) pending.splice(i, 1);
    };
    scheduler.pending = pending;
    scheduler.runNext = () => {
        const timer = pending.shift();
        assert.ok(timer, 'expected a scheduled reconnect, found none');
        timer.fn();
        return timer.delay;
    };
    return scheduler;
}

function setup(options = {}) {
    FakeEventSource.instances = [];
    const scheduler = makeScheduler();
    const handle = createReconnectingEventSource('/api/nfc/read', {
        EventSourceCtor: FakeEventSource,
        scheduler,
        cancelScheduled: scheduler.cancel,
        baseDelayMs: 1000,
        maxDelayMs: 30000,
        ...options,
    });
    return { handle, scheduler, instances: FakeEventSource.instances };
}

test('connects immediately to the given url', () => {
    const { instances } = setup();
    assert.strictEqual(instances.length, 1);
    assert.strictEqual(instances[0].url, '/api/nfc/read');
});

test('registers the caller listeners on the initial source', () => {
    const seen = [];
    const { instances } = setup({ listeners: { card: (e) => seen.push(e.data) } });
    instances[0].emit('card', { data: 'C6:97:D7:BD' });
    assert.deepStrictEqual(seen, ['C6:97:D7:BD']);
});

test('reconnects after the connection is failed (the 502 case)', () => {
    const { scheduler, instances } = setup();
    instances[0].fail();

    assert.strictEqual(instances.length, 1, 'must not reconnect synchronously');
    assert.strictEqual(scheduler.pending.length, 1, 'a reconnect must be scheduled');

    scheduler.runNext();
    assert.strictEqual(instances.length, 2, 'a fresh EventSource must be created');
    assert.strictEqual(instances[1].url, '/api/nfc/read');
});

test('does NOT reconnect while the browser is still retrying', () => {
    const { scheduler, instances } = setup();
    instances[0].drop();

    assert.strictEqual(scheduler.pending.length, 0,
        'readyState CONNECTING means the browser retries itself — no double connect');
    assert.strictEqual(instances.length, 1);
});

test('re-registers the caller listeners on the reconnected source', () => {
    const seen = [];
    const { scheduler, instances } = setup({ listeners: { card: (e) => seen.push(e.data) } });

    instances[0].fail();
    scheduler.runNext();
    instances[1].emit('card', { data: 'AA:BB:CC:DD' });

    assert.deepStrictEqual(seen, ['AA:BB:CC:DD'], 'listeners must survive a reconnect');
});

test('backs off exponentially and caps the delay', () => {
    const { scheduler, instances } = setup();
    const delays = [];

    for (let i = 0; i < 8; i++) {
        instances[instances.length - 1].fail();
        delays.push(scheduler.runNext());
    }

    assert.deepStrictEqual(delays.slice(0, 5), [1000, 2000, 4000, 8000, 16000]);
    assert.ok(delays.every((d) => d <= 30000), `delays must be capped: ${delays}`);
    assert.strictEqual(delays[delays.length - 1], 30000, 'must settle at the cap');
});

test('resets the backoff once a connection opens', () => {
    const { scheduler, instances } = setup();

    instances[0].fail();
    assert.strictEqual(scheduler.runNext(), 1000);
    instances[1].fail();
    assert.strictEqual(scheduler.runNext(), 2000);

    instances[2].open();
    instances[2].fail();
    assert.strictEqual(scheduler.runNext(), 1000, 'a successful open must reset the backoff');
});

test('keeps retrying indefinitely — the kiosk is unattended', () => {
    const { scheduler, instances } = setup();
    for (let i = 0; i < 50; i++) {
        instances[instances.length - 1].fail();
        scheduler.runNext();
    }
    assert.strictEqual(instances.length, 51, 'must never give up');
});

test('closes the failed source before opening a new one', () => {
    const { scheduler, instances } = setup();
    instances[0].fail();
    scheduler.runNext();
    assert.ok(instances[0].closed, 'the dead source must be closed to free the connection');
});

test('close() stops reconnecting and closes the live source', () => {
    const { handle, scheduler, instances } = setup();
    handle.close();

    assert.ok(instances[0].closed);
    instances[0].fail();
    assert.strictEqual(scheduler.pending.length, 0, 'no reconnect after close()');
});

test('close() cancels an already scheduled reconnect', () => {
    const { handle, scheduler, instances } = setup();
    instances[0].fail();
    assert.strictEqual(scheduler.pending.length, 1);

    handle.close();
    assert.strictEqual(scheduler.pending.length, 0, 'a pending reconnect must be cancelled');
});

test('onOpen fires on every successful connection', () => {
    let opens = 0;
    const { scheduler, instances } = setup({ onOpen: () => { opens++; } });

    instances[0].open();
    instances[0].fail();
    scheduler.runNext();
    instances[1].open();

    assert.strictEqual(opens, 2);
});
