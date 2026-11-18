"""D-18: Brother QL-820NWBc sticker print service.

Real/mock split per the project's hardware-service convention. The factory
NEVER raises — falls back to mock when brother_ql is unavailable or TESTING is set.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import socket
import sys
from pathlib import Path

from app.config import get_settings

# Import brother_ql lazily — the module must remain importable on machines
# where brother_ql is not installed (Mock-only environments).
try:
    from PIL import Image

    # brother_ql 0.9.4 resizes with Image.ANTIALIAS, removed in Pillow 10.
    if not hasattr(Image, "ANTIALIAS"):
        Image.ANTIALIAS = Image.LANCZOS  # type: ignore[attr-defined]

    from brother_ql.conversion import convert  # type: ignore
    from brother_ql.raster import BrotherQLRaster  # type: ignore

    _BROTHER_QL_AVAILABLE = True
except Exception:  # pragma: no cover — exercised on machines without brother_ql
    convert = None  # type: ignore
    BrotherQLRaster = None  # type: ignore
    _BROTHER_QL_AVAILABLE = False

# Cover of the last finished story; the GPIO image button prints this file.
# No extension on purpose: it may hold a PNG or a JPG and PIL sniffs content.
LAST_COVER = Path("content/last-cover")


def save_last_cover(src: Path) -> None:
    """Copy *src* over LAST_COVER atomically (a press mid-copy never reads half
    a file). Never raises: losing the copy must not break playback/generation."""
    try:
        tmp = LAST_COVER.with_name(LAST_COVER.name + ".tmp")
        shutil.copyfile(src, tmp)
        os.replace(tmp, LAST_COVER)
    except Exception as e:
        print(
            json.dumps(
                {
                    "event": "last_cover_save_failed",
                    "src": str(src),
                    "reason": type(e).__name__,
                }
            ),
            file=sys.stderr,
        )


class PrinterService:
    """Base contract for the Brother QL-820NWBc print path."""

    is_mock: bool = False

    async def print_sticker(self, png_path: Path) -> None:
        raise NotImplementedError


class RealPrinterService(PrinterService):
    """Real Brother QL-820NWB backend over Bluetooth RFCOMM (D-18)."""

    is_mock: bool = False

    def __init__(self) -> None:
        # _available can be flipped off by the factory if brother_ql import failed.
        self._available: bool = _BROTHER_QL_AVAILABLE

    async def print_sticker(self, png_path: Path) -> None:
        if not self._available or BrotherQLRaster is None:
            raise RuntimeError("brother_ql backend not available")
        # Blocking USB I/O: keep it off the event loop (buttons, SSE, audio).
        await asyncio.to_thread(self._print_sync, png_path)

    def _print_sync(self, png_path: Path) -> None:
        # Direct RFCOMM send, no spooler: if the printer is off connect() fails
        # and the job is gone, so nothing piles up to print when it powers on.
        # convert() also prefixes every job with invalidate + ESC @ (reset).
        qlr = BrotherQLRaster("QL-820NWB")
        # Two-colour job: the loaded DK-22251 black/red roll rejects black-only
        # jobs ("tipo de rollo incorrecto"); a B/W cover still prints black.
        convert(
            qlr=qlr,
            images=[str(png_path)],
            label="62red",
            red=True,
            dither=False,
            threshold=70.0,
        )
        settings = get_settings()
        sock = socket.socket(_AF_BLUETOOTH, socket.SOCK_STREAM, _BTPROTO_RFCOMM)
        try:
            sock.settimeout(_BT_TIMEOUT_S)
            sock.connect((settings.printer_bt_address, settings.printer_bt_channel))
            sock.sendall(qlr.data)
            _wait_print_result(sock)
        finally:
            sock.close()


# Linux values; some CPython builds (e.g. uv's on the dev box) lack the names.
_AF_BLUETOOTH = getattr(socket, "AF_BLUETOOTH", 31)
_BTPROTO_RFCOMM = getattr(socket, "BTPROTO_RFCOMM", 3)
# Bluetooth connect / status-read timeout (seconds).
_BT_TIMEOUT_S = 20.0
# Status frame byte 18 (status type): 0x01 printing completed, 0x02 error.
_STATUS_DONE = 0x01
_STATUS_ERROR = 0x02


def _wait_print_result(sock: socket.socket) -> None:
    """Read 32-byte status frames until printing completes. Raises on an error
    frame; a silent printer (timeout / closed link) counts as sent."""
    buf = b""
    try:
        while True:
            chunk = sock.recv(64)
            if not chunk:
                return
            buf += chunk
            while len(buf) >= 32:
                frame, buf = buf[:32], buf[32:]
                if frame[18] == _STATUS_ERROR:
                    raise RuntimeError(
                        f"printer error err1=0x{frame[8]:02x} err2=0x{frame[9]:02x}"
                    )
                if frame[18] == _STATUS_DONE:
                    return
    except TimeoutError:
        return


class MockPrinterService(PrinterService):
    """Mock backend for dev / CI / TESTING. Logs JSON to stderr."""

    is_mock: bool = True

    def __init__(self) -> None:
        self._last_printed: Path | None = None

    async def print_sticker(self, png_path: Path) -> None:
        self._last_printed = png_path
        print(
            json.dumps({"event": "print_mock", "path": str(png_path)}),
            file=sys.stderr,
        )


def create_printer_service() -> PrinterService:
    """Factory — never raises. Falls back to mock when:
    - TESTING env is set
    - brother_ql failed to import at module load
    """
    if os.environ.get("TESTING"):
        return MockPrinterService()
    if not _BROTHER_QL_AVAILABLE:
        print(
            json.dumps(
                {"event": "printer_init_fallback", "reason": "brother_ql unavailable"}
            ),
            file=sys.stderr,
        )
        return MockPrinterService()
    return RealPrinterService()
