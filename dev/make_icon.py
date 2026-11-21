"""Draws the BlackBox icon (dark box with an orange bar, like the logo in the web UI) and writes
BlackBox.ico (desktop shortcut) and blackbox/static/favicon.ico. Standard library only.

    python dev/make_icon.py
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INK = (0x16, 0x16, 0x1A, 255)
ACCENT = (0xD2, 0x44, 0x0F, 255)
CLEAR = (0, 0, 0, 0)


def pixels(n: int) -> list[list[tuple]]:
    m = max(1, round(n * 0.06))           # transparent margin
    bx0, bx1 = round(n * 0.25), round(n * 0.75)
    by0 = round(n * 0.45)
    by1 = max(by0 + 1, round(n * 0.57))   # bar at least one pixel high
    rows = []
    for y in range(n):
        row = []
        for x in range(n):
            if not (m <= x < n - m and m <= y < n - m):
                row.append(CLEAR)
            elif bx0 <= x < bx1 and by0 <= y < by1:
                row.append(ACCENT)
            else:
                row.append(INK)
        rows.append(row)
    return rows


def png(n: int) -> bytes:
    raw = b"".join(b"\x00" + bytes(c for px in row for c in px) for row in pixels(n))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", n, n, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def ico(sizes=(16, 24, 32, 48, 64, 128, 256)) -> bytes:
    images = [png(n) for n in sizes]
    head = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries = b""
    for n, data in zip(sizes, images):
        entries += struct.pack("<BBBBHHII", n % 256, n % 256, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    return head + entries + b"".join(images)


if __name__ == "__main__":
    data = ico()
    for path in (ROOT / "BlackBox.ico", ROOT / "blackbox" / "static" / "favicon.ico"):
        path.write_bytes(data)
        print(f"{path}  ({len(data)} bayt)")
