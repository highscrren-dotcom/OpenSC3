#!/usr/bin/env python3
"""Rasterise the tray icons (opensc3/app/icons/*.svg) to PNG, without any window.

    python3 -B design/panel/icons/export.py [--qt]

The icons live with the app (opensc3/app/icons/: the tray uses the PNGs, the mock-ups too).
For every <name>.svg there writes png/<name>-<theme>.png at natural size and
png/<name>-<theme>@2x.png at double size, for both Plasma panel themes:

    dark   ColorScheme-Text #fcfcfc (Breeze Dark panel)
    light  ColorScheme-Text #232629 (Breeze panel)

The colour is swapped in the SVG's current-color-scheme style, the way Plasma recolours symbolic
icons; NegativeText stays #da4453 in both themes. Rasteriser: rsvg-convert, or QtSvg from PySide6
when rsvg-convert is missing or --qt is given (QtSvg is what Plasma itself draws icons with).
PNGs in png/ that no SVG produces any more are removed. Exit code 0 on success.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ICONS = HERE.parents[2] / "opensc3" / "app" / "icons"  # one copy, next to the app
OUT = ICONS / "png"
THEMES = {"dark": "#fcfcfc", "light": "#232629"}
SCALES = {"": 1, "@2x": 2}
TEXT_RULE = re.compile(r"(\.ColorScheme-Text\s*\{\s*color\s*:\s*)#[0-9a-fA-F]{3,8}")
SIZE = re.compile(r'<svg\b[^>]*?\bwidth="(\d+)"[^>]*?\bheight="(\d+)"', re.DOTALL)


def recolour(svg: str, colour: str) -> str:
    new, count = TEXT_RULE.subn(lambda m: m.group(1) + colour, svg)
    if count != 1:
        raise ValueError("expected exactly one .ColorScheme-Text rule in the current-color-scheme style")
    return new


def natural_size(svg: str) -> tuple[int, int]:
    m = SIZE.search(svg)
    if not m:
        raise ValueError("the <svg> element needs integer width and height")
    return int(m.group(1)), int(m.group(2))


def render_rsvg(rsvg: str, svg: str, w: int, h: int, out: Path) -> None:
    subprocess.run([rsvg, "--width", str(w), "--height", str(h), "--format", "png", "--output", str(out)],
                   input=svg.encode("utf-8"), check=True)


def render_qt(svg: str, w: int, h: int, out: Path) -> None:
    from PySide6.QtCore import QByteArray
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer

    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    if not renderer.isValid():
        raise ValueError("QtSvg could not parse the SVG")
    image = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(0)
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()
    if not image.save(str(out)):
        raise OSError(f"cannot write {out}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Rasterise the SC3 tray icons to PNG (dark and light panel).")
    ap.add_argument("--qt", action="store_true", help="use QtSvg (PySide6) instead of rsvg-convert")
    args = ap.parse_args()

    sources = sorted(ICONS.glob("*.svg"))
    if not sources:
        print(f"export: no SVG in {ICONS}", file=sys.stderr)
        return 1
    rsvg = None if args.qt else shutil.which("rsvg-convert")
    OUT.mkdir(exist_ok=True)

    written: set[Path] = set()
    try:
        for src in sources:
            text = src.read_text(encoding="utf-8")
            w, h = natural_size(text)
            for theme, colour in THEMES.items():
                svg = recolour(text, colour)
                for suffix, scale in SCALES.items():
                    out = OUT / f"{src.stem}-{theme}{suffix}.png"
                    if rsvg:
                        render_rsvg(rsvg, svg, w * scale, h * scale, out)
                    else:
                        render_qt(svg, w * scale, h * scale, out)
                    written.add(out)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"export: {src.name}: {exc}", file=sys.stderr)
        return 1

    for stale in OUT.glob("*.png"):
        if stale not in written:
            stale.unlink()
    print(f"ok   {len(written)} PNG from {len(sources)} SVG -> {OUT} ({'rsvg-convert' if rsvg else 'QtSvg'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
