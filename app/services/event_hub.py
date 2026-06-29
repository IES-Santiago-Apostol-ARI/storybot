"""EventHub — fan-out hub for the kiosk server→browser SSE channel.

A single ``asyncio.Queue`` delivers each item to exactly ONE consumer, so when
more than one page is connected to ``/api/system/events`` (a reconnected or
leftover Firefox tab, a zombie SSE connection, or a debug ``curl``) interrupt /
image events get stolen from the tab actually playing a story. EventHub instead
gives every subscriber its OWN queue and broadcasts each published event to all
of them, so every connected kiosk page receives every event.

The publisher (GpioDispatcher) keeps using ``put_nowait`` — EventHub is a
drop-in replacement for the old shared queue on the producer side. Each SSE
connection calls :meth:`subscribe` to get its queue and :meth:`unsubscribe` on
disconnect.
"""

import asyncio


class EventHub:
    """One publisher, many SSE subscribers; each gets every event."""

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue] = set()

    def subscribe(self) -> asyncio.Queue:
        """Register a new subscriber and return its dedicated queue."""
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        """Remove a subscriber (idempotent — safe to call on disconnect)."""
        self._subscribers.discard(queue)

    def put_nowait(self, event: dict) -> None:
        """Broadcast *event* to every current subscriber's queue.

        Named ``put_nowait`` so it is a drop-in for the previous single
        ``asyncio.Queue`` on the producer side (GpioDispatcher). A snapshot of
        the subscriber set is iterated so concurrent (un)subscribe is safe.
        """
        for queue in list(self._subscribers):
            queue.put_nowait(event)
