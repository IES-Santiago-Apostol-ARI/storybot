"""WS2812B SPI byte encoder + thin SpiWriter.
The encoder is PURE (no spidev, no I/O, x86-runnable).
SpiWriter lazily imports spidev inside __init__ (aarch64-only dep, D-05).
"""

import numpy as np

# Frozen constants (D-11)
# 6.4 MHz = 156.25 ns/bit -> 1.25 us/byte = 1 WS bit period
SPI_HZ = 6_400_000
# 0b11000000 -> T0H approx 2/8 * 1.25us = 0.3125us (~0.4us target)
ZERO_BYTE = 0xC0
# 0b11111100 -> T1H approx 6/8 * 1.25us = 0.9375us (~0.8us target)
ONE_BYTE = 0xFC
# 60 * 1.25us = 75us > 50us RES latch (D-02)
RESET_BYTES = 60


def _gamma_lut(gamma: float) -> np.ndarray:
    """
    Deterministic 256-entry gamma lookup table.
    Same input exponent -> identical bytes (stable tests).
    """
    idx = np.arange(256, dtype=np.float32)
    return np.round(255.0 * (idx / 255.0) ** gamma).astype(np.uint8)


def _channel_to_spi_lut() -> np.ndarray:
    """
    Build a (256, 8) uint8 array where row v is the 8 SPI bytes encoding
    WS bit pattern of the 8 bits of v (MSB first).
    """
    lut = np.zeros((256, 8), dtype=np.uint8)
    for v in range(256):
        bits = [(ONE_BYTE if (v >> (7 - i)) & 1 else ZERO_BYTE) for i in range(8)]
        lut[v] = bits
    return lut


def encode_ws2812(
    pixels,
    *,
    count: int,
    cap: float,
    gamma: float,
    order: str = "GRB",
    speed_hz: int = SPI_HZ,
) -> bytes:
    """
    Pure encoder. No spidev, no I/O. Returns the exact SPI byte stream.
    Implements frozen pipeline (D-08): RGB -> xcap -> gamma LUT -> GRB -> cells
    -> latch.

    Args:
        pixels: List of (R, G, B) tuples.
        count: Number of pixels to encode.
        cap: Brightness cap [0, 1] fraction (D-09).
        gamma: Gamma exponent (e.g., 2.2).
        order: Color order, defaults to "GRB" (WS2812B standard).
        speed_hz: SPI clock speed, defaults to 6.4 MHz.

    Returns:
        The exact SPI byte stream for the specified number of LEDs.
    """
    # 1. RGB source, truncate to count
    arr = np.asarray(pixels[:count], dtype=np.uint8)

    # 2. Cap before gamma (D-08).
    # cap is a [0,1] FRACTION per D-09. Formula: arr * cap.
    # Correct: round(255 * 0.30) = 76.
    # Wrong (divisor variant): uint8(255 * (0.30/255)) = uint8(0.3) = 0 -> BLACK.
    arr = np.round(np.clip((arr.astype(np.float32) * cap), 0, 255)).astype(np.uint8)

    # 3. Gamma LUT
    arr = _gamma_lut(gamma)[arr]

    # 4. GRB reorder (D-13)
    if order == "GRB":
        arr = arr[:, [1, 0, 2]]

    # 5. SPI cells
    spi_lut = _channel_to_spi_lut()
    flat = arr.reshape(-1)
    out = spi_lut[flat].reshape(-1)

    # 6. Reset latch (>= 50us)
    return bytes(out) + bytes(RESET_BYTES)


class SpiWriter:
    """
    Thin wrapper over spidev. Lazy import - x86-safe (D-05).
    Clone of printer_handler.py shape.
    """

    def __init__(
        self, bus: int, dev: int, speed_hz: int, mode: int = 0, bits_per_word: int = 8
    ):
        try:
            import spidev
        except ImportError as e:
            raise RuntimeError("spidev not available (aarch64-only dep)") from e

        self._spi = spidev.SpiDev()
        self._spi.open(bus, dev)
        self._spi.max_speed_hz = speed_hz
        self._spi.mode = mode
        self._spi.bits_per_word = bits_per_word

    def write(self, data) -> None:
        """
        Write data to SPI device. Accepts numpy arrays via buffer protocol.
        """
        # writebytes2 accepts numpy byte arrays directly (no .tolist() needed).
        self._spi.writebytes2(data)

    def close(self) -> None:
        """Close the SPI connection."""
        self._spi.close()
