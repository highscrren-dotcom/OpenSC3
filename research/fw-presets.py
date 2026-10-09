#!/usr/bin/env python3
"""Ищет в расшифрованном образе SC3 вшитые пресеты — цепочки ACP-кадров `A5 5A ctrl len … 16`.

  python3 -I fw-presets.py plain.bin дамп.json
"""
import json
import struct
import sys

img = open(sys.argv[1], "rb").read()
dev = json.load(open(sys.argv[2]))["nodes"]
NAMES = {int(k, 16): v["name"] for k, v in dev.items()}


def frames_at(off):
    out = []
    while off + 5 <= len(img) and img[off] == 0xA5 and img[off + 1] == 0x5A:
        ctrl, ln = img[off + 2], img[off + 3]
        end = off + 4 + ln
        if end >= len(img) or img[end] != 0x16:
            break
        out.append((off, ctrl, img[off + 4: end]))
        off = end + 1
    return out, off


starts, i = [], 0
while (i := img.find(b"\xA5\x5A", i)) != -1:
    starts.append(i)
    i += 1

seen, chains = set(), []
for s in starts:
    if s in seen:
        continue
    fr, end = frames_at(s)
    for o, _, _ in fr:
        seen.add(o)
    if len(fr) >= 2:
        chains.append((s, end, fr))

print(f"цепочек из ≥2 кадров: {len(chains)}")
for s, end, fr in chains:
    ctrls = [c for _, c, _ in fr]
    head = fr[0]
    print(f"\n{s:#08x}–{end:#08x}: {len(fr)} кадров, {end - s} байт; первый кадр ctrl={head[1]:#04x} "
          f"тело={head[2].hex(' ')[:40]}")
    nodes = [c for c in ctrls if 0x81 <= c <= 0xB6]
    if nodes:
        print("  узлы: " + ", ".join(f"{c:#04x}" for c in nodes[:60]) + (" …" if len(nodes) > 60 else ""))
    for _, c, body in fr:
        if c in (0x83, 0x85, 0x86, 0x87, 0x88, 0x89, 0x8A, 0x82, 0x9E, 0xA2, 0xA5, 0xB0, 0xAB):
            vals = list(struct.unpack(f"<{(len(body) - 1) // 2}h", body[1: 1 + (len(body) - 1) // 2 * 2])) if body[:1] == b"\xff" else body.hex(" ")
            print(f"    {c:#04x} {NAMES.get(c, '?'):<26} {vals if not isinstance(vals, list) else vals[:12]}")
