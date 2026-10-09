#!/usr/bin/env python3
"""Расшифровка дампа sc3-probe.py по раскладке SDK MVsilicon BP10 v0.1.12."""
import json
import sys

d = json.load(open(sys.argv[1]))
T = {0: "peak", 1: "lowshelf", 2: "highshelf", 3: "lowpass", 4: "highpass", 5: "bandpass", 6: "notch"}
for a in ["0xa0", "0xa1", "0xa2", "0xa3", "0xa4", "0xa5", "0xa6"]:
    n = d["nodes"][a]
    v = n["values"]
    en, pre, cnt = v[0], v[1], v[2]
    fl = []
    for k in range(10):
        e, t, f0, q, g = v[3 + 5 * k: 8 + 5 * k]
        if e:
            fl.append(f"{T.get(t, t)} {f0} Гц Q{q / 1024:.2f} {g / 256:+.1f} дБ")
    name = n["name"]
    print(f"{a} {name:<22} вкл={en} pregain={pre / 256:+.1f} дБ count={cnt}: " + ("; ".join(fl) if fl else "фильтров нет"))
for a in ["0x9d", "0x9e", "0x9f"]:
    n = d["nodes"][a]
    v = n["values"]
    print(a, n["name"], "вкл", v[0], "fc", v[1], "mode", v[2], "q", v[3:5], "thr дБ", [x / 100 for x in v[5:8]],
          "ratio", v[8:11], "att", v[11:14], "rel", v[14:17], "pregain", v[17:19])
for a in ["0x81", "0x82", "0x83", "0x84", "0x85", "0x86", "0x87", "0x88", "0x90"]:
    n = d["nodes"][a]
    print(a, n["name"], n["values"])
