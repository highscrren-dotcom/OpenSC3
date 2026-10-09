#!/usr/bin/env python3
"""Разбор сырой записи входа SC3 (S16_LE, 48 кГц, 2 канала): как ведёт себя встроенный гейт.

  python3 -I gate-stats.py запись.raw
"""
import sys

import numpy as np

RATE = 48000
x = np.fromfile(sys.argv[1], dtype="<i2").reshape(-1, 2).astype(np.int32)
L, R = x[:, 0], x[:, 1]
n = len(L)
print(f"длина {n / RATE:.1f} с, сэмплов {n}")
print(f"L != R: {np.count_nonzero(L != R)} сэмплов; максимум |L-R| = {np.abs(L - R).max()}")
m = L  # каналы сравнили выше; дальше — левый
z = m == 0
print(f"точные нули: {z.mean() * 100:.1f} %")
print(f"пик {np.abs(m).max()} ({20 * np.log10(np.abs(m).max() / 32768 + 1e-12):.1f} dBFS); "
      f"у предела ±32767: {np.count_nonzero(np.abs(m) >= 32767)}")

# Серии нулей (гейт закрыт) и серии ненулевых (открыт). Короткие нули внутри сигнала — переходы через ноль.
MIN_CLOSED = int(0.020 * RATE)  # ≥ 20 мс подряд нулей = гейт закрыт
edges = np.flatnonzero(np.diff(np.r_[0, z.astype(np.int8), 0]))
runs = list(zip(edges[::2], edges[1::2]))  # [начало, конец) серий нулей
closed = [(a, b) for a, b in runs if b - a >= MIN_CLOSED]
print(f"закрытий гейта (≥20 мс нулей): {len(closed)}")
if closed:
    d = np.array([b - a for a, b in closed]) / RATE
    print(f"  длительность закрытий: мин {d.min() * 1000:.0f} мс, медиана {np.median(d) * 1000:.0f} мс, макс {d.max():.1f} с")
opened = []
prev_end = 0
for a, b in closed:
    if a > prev_end:
        opened.append((prev_end, a))
    prev_end = b
if prev_end < n:
    opened.append((prev_end, n))
print(f"открытий (между закрытиями): {len(opened)}")


def db(v):
    return 20 * np.log10(v / 32768 + 1e-12)


W = int(0.010 * RATE)  # окна по 10 мс
if opened:
    rms_open = []
    for a, b in opened:
        seg = m[a:b].astype(np.float64)
        k = len(seg) // W
        if k:
            rms_open.extend(np.sqrt((seg[: k * W].reshape(k, W) ** 2).mean(axis=1)))
    rms_open = np.array(rms_open)
    if rms_open.size:
        q = np.percentile(rms_open, [1, 10, 50, 90, 99])
        print("RMS открытого сигнала (окна 10 мс), dBFS: 1%/10%/50%/90%/99% = "
              + " / ".join(f"{db(v):.1f}" for v in q))
    dc = [m[a:b].mean() for a, b in opened if b - a > W]
    if dc:
        print(f"постоянная составляющая в открытых участках: медиана {np.median(dc):.1f} отсчётов")

    # Как гейт закрывается: огибающая за 50 мс до серии нулей и как открывается: первые 20 мс после
    def env(seg):
        k = len(seg) // (RATE // 1000)
        if not k:
            return []
        s = seg[: k * (RATE // 1000)].astype(np.float64).reshape(k, -1)
        return [db(v) for v in np.sqrt((s ** 2).mean(axis=1))]

    tails, heads, last_abs = [], [], []
    for a, b in closed:
        if a >= int(0.05 * RATE):
            tails.append(env(m[a - int(0.05 * RATE): a]))
            last_abs.append(int(np.abs(m[a - 48: a]).max()))
        if b + int(0.02 * RATE) <= n:
            heads.append(env(m[b: b + int(0.02 * RATE)]))
    if tails:
        t = np.median(np.array(tails), axis=0)
        print("закрытие, огибающая по 1 мс за 50 мс до нулей (медиана), dBFS:")
        print("  " + " ".join(f"{v:.0f}" for v in t[::5]) + "  … последние 5 мс: " + " ".join(f"{v:.0f}" for v in t[-5:]))
        print(f"  макс |отсчёт| в последнюю 1 мс перед нулями (медиана по закрытиям): {int(np.median(last_abs))}")
    if heads:
        h = np.median(np.array(heads), axis=0)
        print("открытие, первые 20 мс по 1 мс (медиана), dBFS: " + " ".join(f"{v:.0f}" for v in h))
    # Уровень, при котором гейт открывается: RMS первых 10 мс после открытия
    starts = [db(np.sqrt((m[b: b + W].astype(np.float64) ** 2).mean())) for a, b in closed if b + W <= n]
    if starts:
        print("RMS первых 10 мс после открытия, dBFS: мин {:.1f}, 10% {:.1f}, медиана {:.1f}".format(
            min(starts), np.percentile(starts, 10), np.median(starts)))
    ends = [db(np.sqrt((m[a - W: a].astype(np.float64) ** 2).mean())) for a, b in closed if a >= W]
    if ends:
        print("RMS последних 10 мс перед закрытием, dBFS: мин {:.1f}, медиана {:.1f}, 90% {:.1f}".format(
            min(ends), np.median(ends), np.percentile(ends, 90)))
# Младшие биты: есть ли сигнал тише ±4 отсчётов в открытых участках (пол шума АЦП)
nz = m[~z]
if nz.size:
    small = np.count_nonzero(np.abs(nz) <= 4) / nz.size * 100
    print(f"доля ненулевых отсчётов с |x| ≤ 4: {small:.1f} %; минимальный |x| ≠ 0: {np.abs(nz).min()}")
