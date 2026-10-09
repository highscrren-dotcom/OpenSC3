#!/usr/bin/env python3
"""Draw the SC3 tray icons as Plasma "symbolic" SVGs (the source of opensc3/app/icons/sc3-*.svg).

    python3 -B design/panel/icons/draw.py

The mark is the SC3 seen from above, simplified: a rounded body in the device's 164:113 proportion
with four fader slots (dimmed) and their caps at different heights. States:

    connected     the mark
    muted         the mark cut by a NegativeText slash (as Plasma's own "microphone muted")
    disconnected  the mark at 40 % opacity, a small cross in the bottom-right corner
    onair         the mark with a NegativeText dot in the top-right corner (a REC light)
    onair-muted   on air with the microphone muted in PipeWire: the slash and the REC dot together

Colours follow the Plasma convention (class ColorScheme-Text / ColorScheme-NegativeText with
fill="currentColor"), so Plasma recolours them for the panel theme. Plasma renders icons with QtSvg
(no masks), so every gap around the slash, the dot and the cross is cut into the paths here, with
QPainterPath boolean operations. Those flatten curves with a tolerance fixed in path units, so they
run on coordinates scaled by GRID_SCALE: x4 turns each 2-3 px corner into 7 segments (a chamfer at
x1, ~60 points at x64). The REC dot is never cut, so it is written as true SVG arcs.

Everything the eye reads as a line sits on the pixel grid of its own size: one SVG per size (22, 32).
The caps are placed so that the slash and the dot never cut them.
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QPainterPath, QPolygonF

HERE = Path(__file__).resolve().parent
ICONS = HERE.parents[2] / "opensc3" / "app" / "icons"  # the app ships them
GRID_SCALE = 4  # boolean ops run on a 4x finer grid, coordinates are divided back on output
STATES = ("connected", "muted", "disconnected", "onair", "onair-muted")
STYLE = ('<style id="current-color-scheme" type="text/css">.ColorScheme-Text { color:#fcfcfc; } '
         ".ColorScheme-NegativeText { color:#da4453; }</style>")


@dataclass(frozen=True)
class Size:
    px: int
    body: tuple[float, float, float, float, float]  # x, y, w, h, corner radius (1 px outline)
    cols: tuple[int, ...]  # left edge of each fader slot
    caps: tuple[int, ...]  # top edge of each cap
    slot: tuple[int, int, int]  # slot width, top, bottom
    cap: tuple[int, int]  # cap width, height
    slash: tuple[float, float, float, float, float, float]  # x0, y0, x1, y1, thickness, gap
    dot: tuple[float, float, float, float]  # cx, cy, r, gap
    cross: tuple[float, float, float, float, tuple[int, int, int, int]]  # cx, cy, half-arm, thickness, cut box
    slot_opacity: float = 0.5
    dim: float = 0.4


SIZES = (
    # 22 px: body 19 x 13 (1.46 : 1). Four caps 3 px wide on 1 px slots, 4 px apart - an odd 15 px span,
    # so the body is odd as well and sits half a pixel left of centre (room for the corner badges).
    # The slash is 1.5 px (1 px read as too faint at this size), so its gap is only 0.6 px.
    Size(22, body=(1, 5, 19, 13, 2), cols=(4, 8, 12, 16), caps=(11, 13, 8, 9), slot=(1, 7, 16), cap=(3, 2),
         slash=(2.5, 3.5, 18.5, 19.5, 1.5, 0.6), dot=(19, 4, 3, 1),
         cross=(18, 18, 2.75, 1.0, (14, 14, 8, 8))),
    # 32 px: body 28 x 19 (1.47 : 1), centred. Caps 4 x 3 on 2 px slots, 6 px apart.
    Size(32, body=(2, 6, 28, 19, 3), cols=(6, 12, 18, 24), caps=(14, 18, 10, 12), slot=(2, 9, 22), cap=(4, 3),
         slash=(3.5, 3.5, 27.5, 27.5, 1.5, 1.0), dot=(27.5, 5.5, 4, 1),
         cross=(26, 26, 3.5, 1.5, (21, 21, 11, 11))),
)


# --- geometry on the fine grid ---------------------------------------------------------------------

def _rect(x: float, y: float, w: float, h: float, r: float = 0) -> QPainterPath:
    k = GRID_SCALE
    p = QPainterPath()
    if r:
        p.addRoundedRect(QRectF(x * k, y * k, w * k, h * k), r * k, r * k)
    else:
        p.addRect(QRectF(x * k, y * k, w * k, h * k))
    return p


def _circle(cx: float, cy: float, r: float) -> QPainterPath:
    k = GRID_SCALE
    p = QPainterPath()
    p.addEllipse(QPointF(cx * k, cy * k), r * k, r * k)
    return p


def _bar(x0: float, y0: float, x1: float, y1: float, t: float) -> QPainterPath:
    """A straight stroke with flat ends, as a filled polygon."""
    k = GRID_SCALE
    n = math.hypot(x1 - x0, y1 - y0)
    ox, oy = -(y1 - y0) / n * t / 2, (x1 - x0) / n * t / 2
    pts = [(x0 + ox, y0 + oy), (x1 + ox, y1 + oy), (x1 - ox, y1 - oy), (x0 - ox, y0 - oy)]
    p = QPainterPath()
    p.addPolygon(QPolygonF([QPointF(x * k, y * k) for x, y in pts]))
    p.closeSubpath()
    return p


def _union(paths: list[QPainterPath]) -> QPainterPath:
    out = QPainterPath()
    for p in paths:
        out = out.united(p)
    return out


def _num(v: float) -> str:
    s = f"{v / GRID_SCALE:.3f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def _circle_data(cx: float, cy: float, r: float) -> str:
    k = GRID_SCALE
    return (f"M{_num((cx - r) * k)} {_num(cy * k)}a{r:g} {r:g} 0 1 0 {2 * r:g} 0"
            f"a{r:g} {r:g} 0 1 0 {-2 * r:g} 0z")


def _path_data(path: QPainterPath) -> str:
    """SVG path data; polygons only (boolean ops have already flattened the curves)."""
    out: list[str] = []
    for poly in path.simplified().toSubpathPolygons():
        pts = [(p.x(), p.y()) for p in poly]
        if len(pts) > 1 and pts[0] == pts[-1]:
            pts.pop()
        # drop collinear points left over from the boolean ops
        keep = []
        for i, (x, y) in enumerate(pts):
            px, py = pts[i - 1]
            nx, ny = pts[(i + 1) % len(pts)]
            if abs((x - px) * (ny - y) - (y - py) * (nx - x)) > 1e-6 * GRID_SCALE * GRID_SCALE:
                keep.append((x, y))
        if len(keep) < 3:
            continue
        out.append("M" + " ".join(f"{_num(x)} {_num(y)}" for x, y in keep) + "z")
    return "".join(out)


# --- the icon --------------------------------------------------------------------------------------

def _mark(s: Size) -> tuple[QPainterPath, list[QPainterPath], list[tuple[float, float, float, float]]]:
    x, y, w, h, r = s.body
    outline = _rect(x, y, w, h, r).subtracted(_rect(x + 1, y + 1, w - 2, h - 2, r - 1))
    sw, top, bottom = s.slot
    cw, ch = s.cap
    caps, slots = [], []
    for col, cap_top in zip(s.cols, s.caps, strict=True):
        cx = col + sw / 2
        caps.append(_rect(cx - cw / 2, cap_top, cw, ch))
        slots.append((col, top, sw, bottom - top))
    return outline, caps, slots


def _cut_slots(slots, cut: QPainterPath, snap: bool) -> QPainterPath:
    """Slots minus the cut. With snap, a slot is shortened to the next whole pixel below the cut
    instead of ending in a slanted, half-covered pixel (used for the round badge)."""
    k = GRID_SCALE
    out = []
    for col, top, sw, length in slots:
        slot = _rect(col, top, sw, length)
        if snap and slot.intersects(cut):
            low = cut.intersected(slot).boundingRect().bottom() / k
            new_top = math.ceil(low - 1e-6)
            slot = _rect(col, new_top, sw, top + length - new_top)
        else:
            slot = slot.subtracted(cut)
        out.append(slot)
    return _union(out)


def svg(s: Size, state: str) -> str:
    outline, caps, slots = _mark(s)
    solid = _union([outline, *caps])
    cuts: list[tuple[QPainterPath, bool]] = []  # (cut, snap slots to whole pixels)
    red_parts: list[str] = []
    badge = None
    if state in ("muted", "onair-muted"):
        x0, y0, x1, y1, t, gap = s.slash
        red_parts.append(_path_data(_bar(x0, y0, x1, y1, t)))
        dx, dy = x1 - x0, y1 - y0
        cuts.append((_bar(x0 - dx, y0 - dy, x1 + dx, y1 + dy, t + 2 * gap), False))
    if state in ("onair", "onair-muted"):
        cx, cy, r, gap = s.dot
        red_parts.append(_circle_data(cx, cy, r))
        cuts.append((_circle(cx, cy, r + gap), True))
    if state == "disconnected":
        cx, cy, a, t, box = s.cross
        badge = _union([_bar(cx - a, cy - a, cx + a, cy + a, t), _bar(cx - a, cy + a, cx + a, cy - a, t)])
        cuts.append((_rect(*box), False))
    red = "".join(red_parts) or None
    if cuts:
        cut = _union([c for c, _ in cuts])
        if not cut.intersected(_union(caps)).isEmpty():
            raise SystemExit(f"draw: the {state} cut touches a cap at {s.px} px; move the caps")
        solid = solid.subtracted(cut)
        snapped = [c for c, snap in cuts if snap]
        slot_path = _cut_slots(slots, _union(snapped), True) if snapped else _union([_rect(*sl) for sl in slots])
        for c, snap in cuts:
            if not snap:
                slot_path = slot_path.subtracted(c)
    else:
        slot_path = _union([_rect(*sl) for sl in slots])

    dim = f' opacity="{s.dim:g}"' if state == "disconnected" else ""
    lines = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{s.px}" height="{s.px}" viewBox="0 0 {s.px} {s.px}">',
             f"  {STYLE}",
             f'  <g class="ColorScheme-Text" fill="currentColor" fill-rule="evenodd"{dim}>',
             f'    <path d="{_path_data(solid)}"/>',
             f'    <path opacity="{s.slot_opacity:g}" d="{_path_data(slot_path)}"/>',
             "  </g>"]
    if badge is not None:
        lines.append(f'  <path class="ColorScheme-Text" fill="currentColor" fill-rule="evenodd" d="{_path_data(badge)}"/>')
    if red is not None:
        lines.append(f'  <path class="ColorScheme-NegativeText" fill="currentColor" fill-rule="evenodd" d="{red}"/>')
    lines.append("</svg>")
    return "\n".join(lines) + "\n"


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ICONS
    out.mkdir(parents=True, exist_ok=True)
    for size in SIZES:
        for state in STATES:
            target = out / f"sc3-{state}-{size.px}.svg"
            target.write_text(svg(size, state), encoding="utf-8")
            print(f"ok   {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
