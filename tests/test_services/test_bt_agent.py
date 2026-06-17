"""Tests for bt_agent — the BlueZ org.bluez.Agent1 ServiceInterface.

This is the only net-new D-Bus *service* pattern in Phase 27 (the repo only
*calls* D-Bus methods elsewhere; here we *export* a service object). Verified
against dbus-fast 5.0.22's ``dbus_fast.service`` API (RESEARCH lines 54-60).

Two test scopes:
  - ``BluezAgent`` ServiceInterface subclass with NoInputNoOutput auto-approve
    (BT-02): ``RequestAuthorization``/``AuthorizeService`` return ``None``
    without raising (returning normally == approve); PIN/passkey dummies.
  - ``register_agent`` exports the agent on the caller-supplied system bus and
    calls ``AgentManager1.RegisterAgent`` + ``RequestDefaultAgent`` on that
    SAME bus (Pitfall 1 — never constructs its own MessageBus).

The module MUST stay importable on CI machines without dbus-fast/BlueZ via the
lazy-import guard mirrored from ``bt_manager.py``.
"""

import inspect

import pytest

from app.services.bt_agent import (
    AGENT_PATH,
    CAPABILITY,
    BluezAgent,
    register_agent,
)

# ---------------------------------------------------------------------------
# Module constants (CI-safe — no live BT stack required)
# ---------------------------------------------------------------------------


class TestModuleConstants:
    def test_agent_path(self) -> None:
        assert AGENT_PATH == "/storybot/agent"

    def test_capability_is_no_input_no_output(self) -> None:
        # BT-02: headless auto-pair capability.
        assert CAPABILITY == "NoInputNoOutput"


# ---------------------------------------------------------------------------
# BluezAgent ServiceInterface (Task 1)
# ---------------------------------------------------------------------------


class TestBluezAgentInterface:
    def test_is_service_interface_subclass(self) -> None:
        # dbus_fast.service.ServiceInterface — imported lazily inside the
        # module; when absent (CI without dbus-fast) we still want the class
        # to define, so only assert the inheritance when the base is present.
        from app.services import bt_agent

        if bt_agent._DBUS_FAST_AVAILABLE:
            from dbus_fast.service import ServiceInterface

            assert issubclass(BluezAgent, ServiceInterface)

    def test_service_name_is_org_bluez_agent1(self) -> None:
        # The ServiceInterface base stores the well-known name; introspect the
        # MRO-built ``name`` attribute that dbus_fast.ServiceInterface sets in
        # __init__ (the ``super().__init__("org.bluez.Agent1")`` call).
        from app.services import bt_agent

        if not bt_agent._DBUS_FAST_AVAILABLE:
            pytest.skip("dbus-fast not available on this machine")
        agent = BluezAgent()
        # dbus_fast.service.ServiceInterface exposes the name via ``.name``.
        assert getattr(agent, "name", None) == "org.bluez.Agent1"


class TestAutoApprove:
    """BT-02: RequestAuthorization + AuthorizeService auto-approve by returning
    normally (no raise). Belt-and-suspenders with Trusted=true set in plan 05.
    """

    _DEV = "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF"
    _A2DP = "0000110b-0000-1000-8000-00805f9b34fb"

    def test_request_authorization_returns_none(self) -> None:
        agent = BluezAgent()
        # returning normally == approve; raising == reject.
        result = agent.RequestAuthorization(self._DEV)
        assert result is None

    def test_authorize_service_returns_none(self) -> None:
        agent = BluezAgent()
        result = agent.AuthorizeService(self._DEV, self._A2DP)
        assert result is None


class TestNoInputNoOutputDummies:
    """NoInputNoOutput capability: these should never fire for a speaker, but
    BlueZ requires the methods to exist. Return deterministic dummies.
    """

    _DEV = "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF"

    def test_request_pin_code_returns_zero_string(self) -> None:
        assert BluezAgent().RequestPinCode(self._DEV) == "0000"

    def test_request_passkey_returns_zero(self) -> None:
        assert BluezAgent().RequestPasskey(self._DEV) == 0

    def test_request_confirmation_returns_none(self) -> None:
        assert BluezAgent().RequestConfirmation(self._DEV, 123) is None

    def test_cancel_returns_none(self) -> None:
        assert BluezAgent().Cancel() is None

    def test_release_returns_none(self) -> None:
        assert BluezAgent().Release() is None


class TestDisplayMethodsAreNoOps:
    """DisplayPinCode / DisplayPasskey are server→client notifications; for a
    kiosk they are no-ops that must not raise.
    """

    _DEV = "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF"

    def test_display_pin_code(self) -> None:
        assert BluezAgent().DisplayPinCode(self._DEV, "1234") is None

    def test_display_passkey(self) -> None:
        assert BluezAgent().DisplayPasskey(self._DEV, 123456, 3) is None


# ---------------------------------------------------------------------------
# register_agent (Task 2)
# ---------------------------------------------------------------------------


class _Recorder:
    """Async-call recorder for the fake AgentManager1 interface."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple]] = []

    async def call_register_agent(self, path: str, capability: str) -> None:
        self.calls.append(("call_register_agent", (path, capability)))

    async def call_request_default_agent(self, path: str) -> None:
        self.calls.append(("call_request_default_agent", (path,)))


class _FakeProxyObject:
    def __init__(self, mgr: _Recorder) -> None:
        self._mgr = mgr

    def get_interface(self, name: str):
        if name == "org.bluez.AgentManager1":
            return self._mgr
        raise AssertionError(f"unexpected get_interface({name!r})")


class _FakeBus:
    """Minimal stand-in for a dbus_fast.aio.MessageBus.

    Captures export() calls and returns the fake proxy/introspect shape that
    ``register_agent`` needs. Implements ONLY the methods register_agent uses.
    """

    def __init__(self) -> None:
        self.exported: list[tuple[str, object]] = []
        self.introspect_calls: list[tuple[str, str]] = []
        self._mgr = _Recorder()
        self._proxy = _FakeProxyObject(self._mgr)

    async def introspect(self, service: str, path: str) -> None:
        self.introspect_calls.append((service, path))

    def get_proxy_object(self, service: str, path: str, intro) -> _FakeProxyObject:
        return self._proxy

    def export(self, path: str, obj: object) -> None:
        self.exported.append((path, obj))


@pytest.mark.asyncio
class TestRegisterAgent:
    async def test_exports_and_registers_agent(self) -> None:
        bus = _FakeBus()
        await register_agent(bus)

        # 1. export the BluezAgent at AGENT_PATH
        assert len(bus.exported) == 1
        path, obj = bus.exported[0]
        assert path == AGENT_PATH
        assert isinstance(obj, BluezAgent)

        # 2. introspect org.bluez at /org/bluez
        assert ("org.bluez", "/org/bluez") in bus.introspect_calls

        # 3. RegisterAgent(AGENT_PATH, CAPABILITY) then RequestDefaultAgent(AGENT_PATH)
        assert ("call_register_agent", (AGENT_PATH, CAPABILITY)) in bus._mgr.calls
        assert ("call_request_default_agent", (AGENT_PATH,)) in bus._mgr.calls
        # ordering: register before request_default
        names = [c[0] for c in bus._mgr.calls]
        assert names.index("call_register_agent") < names.index(
            "call_request_default_agent"
        )

    async def test_uses_caller_supplied_bus_no_new_messagebus(self) -> None:
        # Pitfall 1: register_agent must NOT construct its own MessageBus.
        # Assert the function signature accepts ``bus`` as a parameter.
        sig = inspect.signature(register_agent)
        assert "bus" in sig.parameters
        # And the source must not instantiate MessageBus inside register_agent.
        # The register_agent function body should not call MessageBus(...)
        # (the module-level lazy import is fine; we check the function body).
        func_src = inspect.getsource(register_agent)
        assert (
            "MessageBus(" not in func_src
        ), "register_agent must not construct a new MessageBus (Pitfall 1)"
