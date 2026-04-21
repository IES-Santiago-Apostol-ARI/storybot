"""Session manager for accumulating parameter card taps."""

import threading
import time


class SessionManager:
    """Manages parameter card tap sessions for story generation.

    Single global instance — one kiosk = one session.
    Sessions are in-memory and ephemeral.
    """

    def __init__(self, timeout_seconds: int = 30) -> None:
        self._params: list[dict] = []
        self._last_tap: float = 0
        self._timeout = timeout_seconds
        self._lock = threading.Lock()

    def add_parameter(self, card: dict) -> list[dict]:
        """Add a parameter card to the session. Returns current params."""
        with self._lock:
            self._check_expired()
            self._params.append(card)
            self._last_tap = time.time()
            return list(self._params)

    def get_session(self) -> dict:
        """Get current session state. Auto-expires if timed out."""
        with self._lock:
            self._check_expired()
            return {
                "parameters": list(self._params),
                "is_active": len(self._params) > 0,
            }

    def clear(self) -> None:
        """Clear the session."""
        with self._lock:
            self._params = []
            self._last_tap = 0

    def get_and_clear(self) -> list[dict]:
        """Return current params and clear session (for go card)."""
        with self._lock:
            params = list(self._params)
            self._params = []
            self._last_tap = 0
            return params

    def _check_expired(self) -> None:
        """Clear session if timeout has elapsed (caller must hold lock)."""
        if self._params and self._last_tap > 0:
            if time.time() - self._last_tap > self._timeout:
                self._params = []
                self._last_tap = 0
