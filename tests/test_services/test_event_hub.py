"""Tests for EventHub — the fan-out hub behind the kiosk SSE channel.

The kiosk → browser event channel must deliver every event to EVERY connected
page, not to whichever single consumer happens to win a shared queue. A second
SSE consumer (a reconnected/leftover Firefox page, a zombie connection, or a
debug curl) must NOT be able to steal an interrupt from the tab playing a story.
"""

from app.services.event_hub import EventHub


def test_fans_out_to_all_subscribers():
    """One publish reaches every subscriber's own queue (no stealing)."""
    hub = EventHub()
    q1 = hub.subscribe()
    q2 = hub.subscribe()

    hub.put_nowait({"type": "interrupt"})

    assert q1.get_nowait() == {"type": "interrupt"}
    assert q2.get_nowait() == {"type": "interrupt"}


def test_unsubscribe_stops_delivery():
    """After unsubscribe, a queue no longer receives published events."""
    hub = EventHub()
    q1 = hub.subscribe()
    q2 = hub.subscribe()

    hub.unsubscribe(q2)
    hub.put_nowait({"type": "image", "url": "/x.png"})

    assert q1.get_nowait() == {"type": "image", "url": "/x.png"}
    assert q2.empty()


def test_publish_with_no_subscribers_is_safe():
    """Publishing with nobody listening must not raise."""
    hub = EventHub()
    hub.put_nowait({"type": "interrupt"})  # no subscribers — must be a no-op
