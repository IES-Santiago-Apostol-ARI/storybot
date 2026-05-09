"""D-18: Brother QL-820NWBc sticker print service.

Real/mock split per the project's hardware-service convention. The factory
NEVER raises — falls back to mock when brother_ql is unavailable or TESTING is set.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Import brother_ql lazily — the module must remain importable on machines
# where brother_ql is not installed (Mock-only environments).
try:
    from brother_ql.backends.helpers import send  # type: ignore
    from brother_ql.conversion import convert  # type: ignore
    from brother_ql.raster import BrotherQLRaster  # type: ignore

    _BROTHER_QL_AVAILABLE = True
except Exception:  # pragma: no cover — exercised on machines without brother_ql
    send = None  # type: ignore
    convert = None  # type: ignore
    BrotherQLRaster = None  # type: ignore
    _BROTHER_QL_AVAILABLE = False


class PrinterService:
    """Base contract for the Brother QL-820NWBc print path."""

    is_mock: bool = False

    async def print_sticker(self, png_path: Path) -> None:
        raise NotImplementedError


class RealPrinterService(PrinterService):
    """Real Brother QL-820NWBc backend via pyusb (D-18)."""

    is_mock: bool = False

    def __init__(self) -> None:
        # _available can be flipped off by the factory if brother_ql import failed.
        self._available: bool = _BROTHER_QL_AVAILABLE

    async def print_sticker(self, png_path: Path) -> None:
        if not self._available or BrotherQLRaster is None:
            raise RuntimeError("brother_ql backend not available")
        qlr = BrotherQLRaster("QL-820NWBc")
        convert(
            qlr=qlr,
            images=[str(png_path)],
            label="62",
            dither=False,
            threshold=70.0,
        )
        send(
            instructions=qlr.data,
            printer_identifier="usb://0x04f9:0x209d",
            backend_identifier="pyusb",
        )


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
