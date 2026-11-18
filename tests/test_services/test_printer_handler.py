"""Wave 0 RED stubs for app.services.printer_handler (D-18).

Plan 16-04 turns these GREEN.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip(
    "app.services.printer_handler", reason="Wave 0 RED stub: implemented in Plan 16-04"
)

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
        png.write_bytes(
            b"\x89PNG\r\n\x1a\n"
        )  # PNG magic only — content irrelevant for mock
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
        events = [
            json.loads(line)
            for line in captured.err.strip().split("\n")
            if line.strip()
        ]
        assert any(e["event"] == "print_mock" and e["path"] == str(png) for e in events)

    def test_is_mock_true(self):
        assert MockPrinterService().is_mock is True


def _status_frame(status_type: int, phase: int = 0, err1: int = 0, err2: int = 0):
    """32-byte QL-8xx status reply (only the bytes the service reads)."""
    f = bytearray(32)
    f[0], f[1] = 0x80, 0x20
    f[8], f[9], f[10], f[11] = err1, err2, 62, 0x0A
    f[18], f[19] = status_type, phase
    return bytes(f)


def _fake_socket(*frames):
    sock = MagicMock()
    sock.recv.side_effect = list(frames) + [b""]
    return sock


class TestRealPrinterService:
    @pytest.mark.asyncio
    async def test_sends_raster_over_bluetooth_rfcomm(self, tmp_path):
        png = tmp_path / "cover-print.png"
        png.write_bytes(b"\x89PNG\r\n\x1a\n")
        sock = _fake_socket(_status_frame(0x06, phase=0x01), _status_frame(0x01))
        with (
            patch("app.services.printer_handler.socket.socket", return_value=sock),
            patch("app.services.printer_handler.convert") as mock_convert,
            patch("app.services.printer_handler.BrotherQLRaster") as mock_raster,
        ):
            mock_raster.return_value = MagicMock(data=b"raw")
            real = RealPrinterService()
            real._available = True  # bypass availability probe in unit test
            await real.print_sticker(png)
            mock_raster.assert_called_once_with("QL-820NWB")
            kwargs = mock_convert.call_args.kwargs
            # The loaded DK-22251 black/red roll rejects black-only jobs.
            assert kwargs.get("label") == "62red"
            assert kwargs.get("red") is True
            assert kwargs.get("dither") is False
            sock.connect.assert_called_once_with(("04:68:74:2F:17:5C", 1))
            sock.sendall.assert_called_once_with(b"raw")
            sock.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_error_status_raises(self, tmp_path):
        png = tmp_path / "cover-print.png"
        png.write_bytes(b"\x89PNG\r\n\x1a\n")
        sock = _fake_socket(_status_frame(0x02, err1=0x01))  # 0x02 = error
        with (
            patch("app.services.printer_handler.socket.socket", return_value=sock),
            patch("app.services.printer_handler.convert"),
            patch("app.services.printer_handler.BrotherQLRaster") as mock_raster,
        ):
            mock_raster.return_value = MagicMock(data=b"raw")
            real = RealPrinterService()
            real._available = True
            with pytest.raises(RuntimeError, match="printer error"):
                await real.print_sticker(png)
            sock.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_unreachable_printer_raises(self, tmp_path):
        png = tmp_path / "cover-print.png"
        png.write_bytes(b"\x89PNG\r\n\x1a\n")
        sock = MagicMock()
        sock.connect.side_effect = OSError(112, "Host is down")
        with (
            patch("app.services.printer_handler.socket.socket", return_value=sock),
            patch("app.services.printer_handler.convert"),
            patch("app.services.printer_handler.BrotherQLRaster") as mock_raster,
        ):
            mock_raster.return_value = MagicMock(data=b"raw")
            real = RealPrinterService()
            real._available = True
            with pytest.raises(OSError):
                await real.print_sticker(png)
            sock.close.assert_called_once()

    def test_real_conversion_builds_62mm_continuous_raster(self, tmp_path):
        """Unmocked brother_ql conversion: catches unknown model names and
        Pillow incompatibilities (Image.ANTIALIAS removed in Pillow 10)."""
        pytest.importorskip("brother_ql")
        from PIL import Image

        png = tmp_path / "cover-print.png"
        Image.new("RGB", (512, 512), "white").save(png)  # forces a resize
        sock = _fake_socket(_status_frame(0x01))
        with patch("app.services.printer_handler.socket.socket", return_value=sock):
            RealPrinterService()._print_sync(png)
        data = sock.sendall.call_args.args[0]
        i = data.find(b"\x1biz")
        assert i >= 0
        assert data[i + 4] == 0x0A  # continuous media
        assert data[i + 5] == 62  # 62 mm wide

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
