#!/usr/bin/env python3
"""Generate the Qinux wallpapers.

Every wallpaper is drawn from scratch rather than shipped as a bitmap, so the
distribution carries the recipe and not several megabytes of PNG. Run it once
at package build time and the generated files go into the package.

The design is a vertical gradient from Qinux Ink to Qinux Deep, with the Qinux
mark's ring drawn as a geometric accent. Deterministic: the same inputs always
produce byte-identical output, which is what lets the package be reproducible.

Usage:
    generate.py --theme dark --size 3840x2160 --output ../images_dark
    generate.py --theme light --size 1920x1080 --output ../images
"""

from __future__ import annotations

import argparse
import struct
import sys
import zlib
from pathlib import Path

# Palette, from the branding repository. Duplicated rather than imported so
# that this script has no dependencies beyond the standard library and runs
# during a package build with nothing installed yet.
PALETTE = {
    "ink": (0x0D, 0x11, 0x17),
    "deep": (0x16, 0x3A, 0x7A),
    "blue": (0x2C, 0x6B, 0xED),
    "mist": (0xE2, 0xE8, 0xF0),
    "paper": (0xFF, 0xFF, 0xFF),
}


def lerp(a: tuple[int, int, int], b: tuple[int, int, int], t: float):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def render_rows(width: int, height: int, theme: str):
    """Yield each scanline as a bytes object. Row at a time, not the whole
    image, so a 4K wallpaper needs a few megabytes of memory rather than tens."""
    top = PALETTE["ink"] if theme == "dark" else PALETTE["paper"]
    bottom = PALETTE["deep"] if theme == "dark" else PALETTE["mist"]
    accent = PALETTE["blue"]

    # The mark's ring, positioned to the right of centre like the logo.
    cx = int(width * 0.72)
    cy = int(height * 0.5)
    outer = int(min(width, height) * 0.16)
    inner = int(outer * 0.82)

    # Anti-alias width, in pixels, for the ring edge.
    aa = 2.0

    for y in range(height):
        t = y / max(1, height - 1)
        base = lerp(top, bottom, t)

        dy = y - cy
        row = bytearray()

        # Only the rows that intersect the ring need per-pixel work. The +1 lets a row
        # one pixel past the ring still be handled, so the clamp on the radicand
        # is what keeps it from going negative.
        if abs(dy) <= outer + 1:
            half = int(max(0, outer * outer - dy * dy) ** 0.5)
            inner_half = (
                int(max(0, inner * inner - dy * dy) ** 0.5)
                if abs(dy) <= inner
                else 0
            )
            ring_start = cx - half
            ring_end = cx + half
            inner_start = cx - inner_half
            inner_end = cx + inner_half
        else:
            ring_start = ring_end = inner_start = inner_end = -1

        if ring_end < 0:
            # Row misses the ring entirely: one flat fill.
            row.extend(bytes(base) * width)
            yield bytes(row)
            continue

        row.extend(bytes(base) * ring_start)

        for x in range(ring_start, ring_end):
            if inner_start <= x <= inner_end:
                row.extend(bytes(base))
                continue
            # Coverage at the edge, so the ring does not look jagged.
            dx = x - cx
            dist = (dx * dx + dy * dy) ** 0.5
            if dist > outer + aa:
                row.extend(bytes(base))
                continue
            if dist < inner - aa:
                row.extend(bytes(accent))
                continue
            edge = min(1.0, max(0.0, (outer + aa - dist) / aa))
            row.extend(bytes(lerp(base, accent, edge)))

        # Rest of the row.
        used = len(row) // 3
        row.extend(bytes(base) * (width - used))
        if len(row) % 3:
            row.extend(b"\x00" * (3 - len(row) % 3))
        yield bytes(row)


def write_png(path: Path, width: int, height: int, theme: str) -> None:
    """Write a minimal 24-bit PNG. No filtering, so the encoder stays simple
    and the output is byte-identical for identical input."""
    raw = bytearray()
    for row in render_rows(width, height, theme):
        raw.append(0)  # filter type 0: None
        raw.extend(row)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as fh:
        fh.write(b"\x89PNG\r\n\x1a\n")
        fh.write(chunk(b"IHDR", header))
        # compress_level fixed so the output does not vary with the zlib build.
        fh.write(chunk(b"IDAT", zlib.compress(bytes(raw), 9)))
        fh.write(chunk(b"IEND", b""))


def parse_size(text: str) -> tuple[int, int]:
    try:
        w, h = text.lower().split("x")
        width, height = int(w), int(h)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected WIDTHxHEIGHT, got: {text}")
    if width < 16 or height < 16:
        raise argparse.ArgumentTypeError(f"too small: {text}")
    return width, height


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--theme", choices=["dark", "light"], default="dark")
    parser.add_argument("--size", type=parse_size, default=(3840, 2160))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    width, height = args.size
    target = args.output / f"{width}x{height}.png"

    try:
        write_png(target, width, height, args.theme)
    except MemoryError:
        print(f"error: {width}x{height} did not fit in memory", file=sys.stderr)
        return 1

    print(f"wrote {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())