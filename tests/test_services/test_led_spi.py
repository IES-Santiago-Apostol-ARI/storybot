"""Unit tests for app.services.led_spi — pure WS2812B SPI byte encoder.
No hardware, no spidev import. Golden-vector assertions lock the encoder pipeline
(D-08: RGB -> xcap -> gamma LUT -> GRB -> 0xC0/0xFC cells -> reset latch).
"""

from app.services.led_spi import (
    ONE_BYTE,
    RESET_BYTES,
    SPI_HZ,
    ZERO_BYTE,
    encode_ws2812,
)


class TestEncoderGoldenVectors:
    def test_full_red_emits_red_channel_in_grb_order(self):
        """
        Input [(255,0,0)], count=1, cap=1.0, gamma=2.2, order="GRB" ->
        out[0:8] == bytes([ZERO_BYTE]*8) (green channel first = 0 under GRB order),
        out[8:16] == bytes([ONE_BYTE]*8) (red = 255),
        out[16:24] == bytes([ZERO_BYTE]*8) (blue = 0),
        out[24:] == bytes(RESET_BYTES).
        BYTE TRUTH per 31-PATTERNS.md lines 283-293.
        """
        out = encode_ws2812([(255, 0, 0)], count=1, cap=1.0, gamma=2.2, order="GRB")

        # GRB order: Green (0), Red (255), Blue (0)
        assert out[0:8] == bytes([ZERO_BYTE] * 8), "Green channel should be 0"
        assert out[8:16] == bytes([ONE_BYTE] * 8), "Red channel should be 255"
        assert out[16:24] == bytes([ZERO_BYTE] * 8), "Blue channel should be 0"
        assert out[24:] == bytes(RESET_BYTES), "Missing or incorrect reset latch"

    def test_off_emits_all_zero_bytes_plus_latch(self):
        """
        encode_ws2812([(0,0,0)], count=1, ...) -> out[0:24] == bytes([ZERO_BYTE]*24)
        and out[24:] == bytes(RESET_BYTES).
        """
        out = encode_ws2812([(0, 0, 0)], count=1, cap=1.0, gamma=2.2, order="GRB")
        assert out[0:24] == bytes([ZERO_BYTE] * 24)
        assert out[24:] == bytes(RESET_BYTES)

    def test_total_length_for_n_leds(self):
        """
        len(encode_ws2812([(0,0,0)]*21, count=21, ...)) == 21*24 + RESET_BYTES
        (assert exactly 564).
        """
        out = encode_ws2812([(0, 0, 0)] * 21, count=21, cap=1.0, gamma=2.2, order="GRB")
        assert len(out) == 21 * 24 + RESET_BYTES
        assert len(out) == 564


class TestEncoderOrder:
    def test_grb_order_green_before_red(self):
        """
        A red-only pixel must emit the green-channel cell pattern FIRST (8 bytes at
        out[0:8]) before the red channel.
        """
        out = encode_ws2812([(255, 0, 0)], count=1, cap=1.0, gamma=2.2, order="GRB")
        # Green is index 0 in GRB. For Red pixel, Green=0.
        assert out[0:8] == bytes([ZERO_BYTE] * 8)
        # Red is index 1 in GRB. For Red pixel, Red=255.
        assert out[8:16] == bytes([ONE_BYTE] * 8)


class TestEncoderGamma:
    def test_gamma_deterministic(self):
        """
        Two calls with identical args produce identical bytes; gamma LUT is rebuilt
        identically each call.
        """
        args = {
            "pixels": [(128, 64, 32)],
            "count": 1,
            "cap": 0.8,
            "gamma": 2.2,
            "order": "GRB",
        }
        out1 = encode_ws2812(**args)
        out2 = encode_ws2812(**args)
        assert out1 == out2


class TestEncoderBrightnessCap:
    def test_cap_applied_before_gamma(self):
        """
        encode_ws2812([(255,0,0)], cap=0.5, gamma=2.2) ==
        encode_ws2812([(round(255*0.5),0,0)], cap=1.0, gamma=2.2)
        The cap is a hue-preserving global scalar BEFORE the gamma LUT (D-08).
        """
        out_capped = encode_ws2812(
            [(255, 0, 0)], count=1, cap=0.5, gamma=2.2, order="GRB"
        )
        out_pre_scaled = encode_ws2812(
            [(round(255 * 0.5), 0, 0)], count=1, cap=1.0, gamma=2.2, order="GRB"
        )
        assert out_capped == out_pre_scaled

    def test_cap_default_value_produces_nonzero_pre_gamma(self):
        """
        NON-TRIVIAL CAP regression catcher (BLOCKER-1): cap=0.30 on full-white input.
        Pre-gamma per-channel value MUST be round(255 * 0.30) = 76.
        Post-gamma byte gamma_lut[76] = round(255 * (76/255)**2.2) = 18.
        The SPI cells for 18 are NOT all ZERO_BYTE.
        """
        # If wrong formula arr * (cap/255) is used, pre-gamma = uint8(0.30) = 0 ->
        # all ZERO_BYTE.
        out = encode_ws2812(
            [(255, 255, 255)], count=1, cap=0.30, gamma=2.2, order="GRB"
        )

        # Assert it's not just a stream of zeros (which happens if cap is
        # applied as /255)
        assert out[0:24] != bytes(
            [ZERO_BYTE] * 24
        ), "Cap formula regression: output is all ZERO_BYTE"

        # Verify the specific post-gamma value is 18 (0b00010010)
        # We can verify this by checking that the SPI cells for the first channel
        # are not all 0 or 1.
        first_channel = out[0:8]
        assert first_channel != bytes([ZERO_BYTE] * 8)
        assert first_channel != bytes([ONE_BYTE] * 8)

        # Deep verification using the private helper (permitted by plan)
        from app.services.led_spi import _gamma_lut

        lut = _gamma_lut(2.2)
        pre_gamma_val = round(255 * 0.30)  # 76
        assert pre_gamma_val == 76
        assert lut[pre_gamma_val] == 18


class TestEncoderResetLatch:
    def test_reset_latch_at_least_50us(self):
        """
        out ends with RESET_BYTES trailing zero bytes AND
        RESET_BYTES * 1.25 >= 50.
        """
        out = encode_ws2812([(0, 0, 0)], count=1, cap=1.0, gamma=2.2, order="GRB")
        assert out[-RESET_BYTES:] == bytes(RESET_BYTES)
        assert RESET_BYTES * 1.25 >= 50


class TestEncoderConstants:
    def test_frozen_constants(self):
        """
        ONE_BYTE == 0xFC, ZERO_BYTE == 0xC0, RESET_BYTES == 60,
        SPI_HZ == 6_400_000.
        """
        assert ONE_BYTE == 0xFC
        assert ZERO_BYTE == 0xC0
        assert RESET_BYTES == 60
        assert SPI_HZ == 6_400_000


class TestImportSafety:
    def test_led_spi_imports_without_spidev(self):
        """
        Importing the module on x86 (where spidev is absent) succeeds.
        The encoder itself must be callable without spidev installed.
        """
        # If this test is running, the import at top of file already succeeded.
        # Now verify calling the encoder doesn't trigger an import.
        out = encode_ws2812([(255, 0, 0)], count=1, cap=1.0, gamma=2.2)
        assert isinstance(out, bytes)
