"""Wave 0 RED stubs for app.services.printer_handler (D-18).

Plan 16-04 turns these GREEN.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("app.services.printer_handler", reason="Wave 0 RED stub: implemented in Plan 16-04")

from app.services.printer_handler import (  # noqa: E402
    MockPrinterService,
    PrinterService,
    RealPrinterService,
    create_printer_service,
)


class TestMockPrinterService:
    @pytest.mark.asyncio
    async def test_records_last_printed(self, tmp_path):
        png = tmp_path / "cover-print.png"
        png.write_bytes(b"\x89PNG\r\n\x1a\n")  # PNG magic only — content irrelevant for mock
        mock = MockPrinterService()
        await mock.print_sticker(png)
        assert mock._last_printed == png

    @pytest.mark.asyncio
    async def test_emits_stderr_json(self, tmp_path, capsys):
        png = tmp_path / "cover-print.png"
        png.write_bytes(b"\x89PNG\r\n\x1a\n")
        mock = MockPrinterService()
        await mock.print_sticker(png)
        captured = capsys.readouterr()
        events = [json.loads(line) for line in captured.err.strip().split("\n") if line.strip()]
        assert any(e["event"] == "print_mock" and e["path"] == str(png) for e in events)

    def test_is_mock_true(self):
        assert MockPrinterService().is_mock is True


class TestRealPrinterService:
    @pytest.mark.asyncio
    async def test_invokes_brother_ql_send(self, tmp_path):
        png = tmp_path / "cover-print.png"
        png.write_bytes(b"\x89PNG\r\n\x1a\n")
        with patch("app.services.printer_handler.send") as mock_send, \
             patch("app.services.printer_handler.convert") as mock_convert, \
             patch("app.services.printer_handler.BrotherQLRaster") as mock_raster:
            mock_raster.return_value = MagicMock(data=b"raw")
            real = RealPrinterService()
            real._available = True  # bypass availability probe in unit test
            await real.print_sticker(png)
            mock_convert.assert_called_once()
            kwargs = mock_convert.call_args.kwargs
            assert kwargs.get("label") == "62"
            assert kwargs.get("dither") is False
            mock_send.assert_called_once()
            send_kwargs = mock_send.call_args.kwargs
            assert send_kwargs.get("printer_identifier") == "usb://0x04f9:0x209d"
            assert send_kwargs.get("backend_identifier") == "pyusb"

    def test_is_mock_false(self):
        assert RealPrinterService().is_mock is False


class TestFactory:
    def test_returns_mock_in_testing_env(self, monkeypatch):
        monkeypatch.setenv("TESTING", "1")
        svc = create_printer_service()
        assert isinstance(svc, MockPrinterService)

    def test_returns_mock_when_brother_ql_unavailable(self, monkeypatch):
        monkeypatch.delenv("TESTING", raising=False)
        # Plan 16-04 picks the import-failure detection mechanism;
        # this test just asserts the contract: factory never raises.
        svc = create_printer_service()
        assert isinstance(svc, PrinterService)
