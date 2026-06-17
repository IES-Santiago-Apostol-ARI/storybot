"""BlueZ ``org.bluez.Agent1`` callback object exported via dbus-fast (BT-02).

This is the only net-new D-Bus *service* pattern in Phase 27: everywhere else
the repo only *calls* D-Bus methods (client); here we *export* a service object
that BlueZ calls back into during the pairing handshake. Verified against
dbus-fast 5.0.22's ``dbus_fast.service`` API (RESEARCH lines 54-60, Pattern 1
lines 136-201).

Purpose: auto-approve incoming pairing/service authorization so
``Device1.Pair()`` (plan 05) completes unattended on a headless kiosk with the
``NoInputNoOutput`` capability. ``RequestAuthorization``/``AuthorizeService``
auto-approve by returning normally (Pitfall 2 — belt-and-suspenders with the
``Trusted=true`` set in plan 05); PIN/passkey methods return deterministic
dummies.

The module mirrors ``bt_manager.py``'s lazy-import guard (lines 19-29) so it
stays importable on CI/Mock-only machines where dbus-fast is absent — the
``BluezAgent`` class still defines against an ``object`` stand-in.

Implementation note on ``agent_method``: dbus-fast's stock ``@method()``
decorator replaces each method with a dispatcher that returns ``None`` on
direct Python call (it targets the D-Bus message-dispatch path). That makes the
agent's value-returning methods (PIN/passkey dummies) untestable by direct
invocation. ``agent_method`` instead runs ``@method()`` once to build the
properly-parsed ``_Method`` (correct in/out signatures from the annotation
strings), then attaches that ``_Method`` to the *plain* function via the
``__DBUS_METHOD`` attribute that ``ServiceInterface._get_methods`` scans for.
Result: dbus-fast still exports the method (identical introspection), AND
direct Python calls return the implementation's value — verified against
``ServiceInterface._get_methods`` discovery on dbus-fast 5.0.22.
"""

import json
import sys

# Lazy hardware import — module stays importable where dbus-fast is absent
# (CI / Mock-only machines). Pattern copied from bt_manager.py lines 19-29.
try:
    from dbus_fast.service import ServiceInterface, method  # type: ignore

    _DBUS_FAST_AVAILABLE = True
except Exception:  # pragma: no cover — exercised on machines without dbus-fast
    # Minimal stand-ins so the class can still define on CI. ``agent_method``
    # becomes a no-op pass-through; ServiceInterface is an ``object`` stand-in.
    # Real decoration only happens when dbus-fast is present (hardware path).
    ServiceInterface = object  # type: ignore

    def method(*a, **kw):  # type: ignore
        return lambda fn: fn

    _DBUS_FAST_AVAILABLE = False


# Object path the agent is exported on (RESEARCH Pattern 1 line 147).
AGENT_PATH = "/storybot/agent"
# Headless auto-pair capability (BT-02). NoInputNoOutput = no passkey prompt.
CAPABILITY = "NoInputNoOutput"


def _log_event(event: str, **kwargs: object) -> None:
    """Structured JSON log to stderr (same pattern as bt_manager._log_event)."""
    print(
        json.dumps({"event": event, **kwargs}),
        file=sys.stderr,
    )


def agent_method(fn):
    """Register ``fn`` as a D-Bus method on ``org.bluez.Agent1`` while keeping
    direct Python calls returning the implementation's value.

    See module docstring: this builds the same ``_Method`` object the stock
    ``@method()`` decorator produces (so dbus-fast's introspection/export is
    identical), but attaches it to the *plain* function instead of wrapping
    the function in the None-returning dispatcher. On machines without
    dbus-fast (``_DBUS_FAST_AVAILABLE is False``) this is a no-op pass-through.
    """
    if not _DBUS_FAST_AVAILABLE:
        return fn
    decorated = method()(fn)
    # ``decorated`` is the dispatcher wrapper; ``decorated.__DBUS_METHOD`` is
    # the ``_Method`` with parsed in/out signatures. Re-attach it to the plain
    # function so ``ServiceInterface._get_methods`` still discovers it.
    fn.__DBUS_METHOD = decorated.__DBUS_METHOD  # type: ignore[attr-defined]
    return fn


class BluezAgent(ServiceInterface):  # type: ignore[misc]
    """The ``org.bluez.Agent1`` callback object (BT-02).

    Auto-approves pairing and service authorization for headless operation
    (``NoInputNoOutput``). PIN/passkey methods return deterministic dummies —
    they should never fire for an A2DP speaker, but BlueZ requires them to
    exist on the Agent1 interface. The Display* methods are server→client
    notifications and are no-ops on a kiosk.
    """

    def __init__(self) -> None:
        super().__init__("org.bluez.Agent1")

    # Auto-approve incoming pairing (no user I/O on a headless kiosk).
    # Returning normally == approve; raising DBusError(org.bluez.Error.Rejected)
    # would deny. D-Bus signature: ``device`` is an object path ("o"); void
    # method omits the return annotation.
    @agent_method
    def RequestAuthorization(self, device: "o"):
        _log_event("bt_agent_authorize", device=str(device))

    # Auto-approve A2DP service connection (belt-and-suspenders with Trusted).
    @agent_method
    def AuthorizeService(self, device: "o", uuid: "s"):
        _log_event("bt_agent_authorize_service", device=str(device), uuid=uuid)

    # NoInputNoOutput dummies — these should never fire for a speaker.
    @agent_method
    def RequestPinCode(self, device: "o") -> "s":
        return "0000"

    @agent_method
    def RequestPasskey(self, device: "o") -> "u":
        return 0

    @agent_method
    def RequestConfirmation(self, device: "o", passkey: "u"):
        pass

    @agent_method
    def DisplayPinCode(self, device: "o", pincode: "s"):
        pass

    @agent_method
    def DisplayPasskey(self, device: "o", passkey: "u", entered: "q"):
        pass

    @agent_method
    def Cancel(self):
        pass

    @agent_method
    def Release(self):
        pass


async def register_agent(bus) -> None:
    """Export ``BluezAgent`` on ``bus`` and register it as the default agent.

    Implements RESEARCH Pattern 1 (lines 188-196): instantiate the agent,
    ``bus.export(AGENT_PATH, agent)``, introspect ``org.bluez`` at
    ``/org/bluez``, then call ``AgentManager1.RegisterAgent`` +
    ``RequestDefaultAgent`` (snake_cased + ``call_``-prefixed per the P26
    convention).

    Pitfall 1 (RESEARCH lines 367-371): the agent MUST be exported on the SAME
    bus connection that will call ``Device1.Pair()`` (plan 05). This function
    therefore takes the bus as a parameter and operates only on it — it must
    NOT construct its own MessageBus.

    Args:
        bus: a connected ``dbus_fast.aio.MessageBus`` (system bus) supplied by
            the caller (the same connection used for Pair/Connect in plan 05).
    """
    agent = BluezAgent()
    bus.export(AGENT_PATH, agent)  # host the callback object
    intro = await bus.introspect("org.bluez", "/org/bluez")
    mgr_obj = bus.get_proxy_object("org.bluez", "/org/bluez", intro)
    mgr = mgr_obj.get_interface("org.bluez.AgentManager1")
    await mgr.call_register_agent(AGENT_PATH, CAPABILITY)
    await mgr.call_request_default_agent(AGENT_PATH)  # make ours the default
