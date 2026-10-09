#!/usr/bin/env python3
"""Потоковое наблюдение за входом SC3 без сохранения звука: каждую минуту — уровни и закрытия гейта.

  parec ... --format=s16le --rate=48000 --channels=2 --raw | python3 -I gate-watch.py СЕКУНД
"""
import sys
import time

import numpy as np

RATE, W = 48000, 480  # окно 10 мс
MIN_CLOSED = 2  # ≥ 2 окон подряд (20 мс) из одних нулей = гейт закрыт
dur = float(sys.argv[1])
inp = sys.stdin.buffer
t0 = time.monotonic()


def db(v):
    return 20 * np.log10(v / 32768 + 1e-12)


minute, rms, zero_run, closures, pre, post, closed_s = 0, [], 0, 0, [], [], 0.0
last_open_rms = None
want_post = False
lr_diff = 0
while time.monotonic() - t0 < dur:
    buf = inp.read(W * 4)
    if len(buf) < W * 4:
        break
    x = np.frombuffer(buf, "<i2").reshape(-1, 2).astype(np.int32)
    lr_diff += int(np.count_nonzero(x[:, 0] != x[:, 1]))
    m = x[:, 0]
    if not m.any():
        zero_run += 1
        closed_s += 0.01
        if zero_run == MIN_CLOSED:
            closures += 1
            if last_open_rms is not None:
                pre.append(last_open_rms)
            want_post = True
        continue
    r = float(np.sqrt((m.astype(np.float64) ** 2).mean()))
    if want_post and zero_run >= MIN_CLOSED:
        post.append(db(r))
    want_post = False
    zero_run = 0
    last_open_rms = db(r)
    rms.append(r)
    t = time.monotonic() - t0
    if t >= (minute + 1) * 60:
        minute += 1
        q = np.percentile(rms, [1, 10, 50, 90, 99]) if rms else [0] * 5
        print(f"{time.strftime('%H:%M:%S')} мин {minute:2d}: RMS 1/10/50/90/99% = "
              + " / ".join(f"{db(v):.0f}" for v in q)
              + f" dBFS; закрытий {closures}, закрыт {closed_s:.1f} с; L≠R {lr_diff}"
              + (f"; перед закрытием мин {min(pre):.0f} медиана {np.median(pre):.0f}" if pre else "")
              + (f"; после открытия мин {min(post):.0f} медиана {np.median(post):.0f}" if post else ""),
              flush=True)
        rms, closures, pre, post, closed_s, lr_diff = [], 0, [], [], 0.0, 0
print(f"{time.strftime('%H:%M:%S')} конец", flush=True)
