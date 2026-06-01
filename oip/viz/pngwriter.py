"""Minimal PNG encoder (stdlib only: zlib + struct).

Just enough to write 8-bit truecolor (RGB) images, so the heatmap PNG works
without a matplotlib/numpy dependency.
"""
from __future__ import annotations

import struct
import zlib
from typing import List


class Canvas:
    """A simple RGB pixel buffer with a few drawing primitives."""

    def __init__(self, width: int, height: int, bg=(10, 10, 18)):
        self.w = width
        self.h = height
        self.buf = bytearray()
        row = bytes(bg) * width
        for _ in range(height):
            self.buf += row

    def set(self, x: int, y: int, rgb):
        if 0 <= x < self.w and 0 <= y < self.h:
            i = (y * self.w + x) * 3
            self.buf[i] = rgb[0] & 255
            self.buf[i + 1] = rgb[1] & 255
            self.buf[i + 2] = rgb[2] & 255

    def hline(self, x0, x1, y, rgb, dotted=False):
        if x0 > x1:
            x0, x1 = x1, x0
        for x in range(x0, x1 + 1):
            if dotted and (x // 3) % 2 == 0:
                continue
            self.set(x, y, rgb)

    def vline(self, x, y0, y1, rgb, dotted=False):
        if y0 > y1:
            y0, y1 = y1, y0
        for y in range(y0, y1 + 1):
            if dotted and (y // 3) % 2 == 0:
                continue
            self.set(x, y, rgb)

    def line(self, x0, y0, x1, y1, rgb, dashed=False, thick=1):
        """Bresenham line, optionally dashed and a few px thick."""
        dx = abs(x1 - x0)
        dy = -abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx + dy
        n = 0
        while True:
            if not dashed or (n // 5) % 2 == 0:
                for t in range(thick):
                    self.set(x0, y0 + t, rgb)
                    self.set(x0 + t, y0, rgb)
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy
            n += 1

    def rect(self, x0, y0, x1, y1, rgb):
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                self.set(x, y, rgb)

    def write_png(self, path: str):
        def chunk(tag: bytes, data: bytes) -> bytes:
            c = tag + data
            return (struct.pack(">I", len(data)) + c
                    + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF))

        ihdr = struct.pack(">IIBBBBB", self.w, self.h, 8, 2, 0, 0, 0)
        # add filter byte (0) at the start of each scanline
        raw = bytearray()
        stride = self.w * 3
        for y in range(self.h):
            raw.append(0)
            raw += self.buf[y * stride:(y + 1) * stride]
        idat = zlib.compress(bytes(raw), 9)

        with open(path, "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n")
            f.write(chunk(b"IHDR", ihdr))
            f.write(chunk(b"IDAT", idat))
            f.write(chunk(b"IEND", b""))
