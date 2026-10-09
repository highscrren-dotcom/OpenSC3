"""Профили звука SC3 — наборы значений из белого списка записи (write.py) в единицах для людей.

Профиль — только данные: применить его — `write.plan_write(profile.items)` → `write.apply(...)`. Запись живёт до
отключения питания, и любая кнопка голоса / ELECTRIC на панели перепишет узлы своим пресетом (docs/GOTCHAS.md) —
служба этапа 4 будет применять профиль заново. Обоснование значений — docs/WRITE.md, «Профиль «Подкаст»».
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from . import write as W


@dataclass(frozen=True)
class Profile:
    name: str
    title: str
    items: tuple[tuple[str, object], ...]  # (ключ белого списка, значение для людей) — в порядке записи
    notes: tuple[str, ...] = ()
    draft: bool = True                     # черновик: владелец ещё не утвердил на слух


# «Подкаст» — голос владельца как в живой цепочке PipeWire (~/dev/stream-style/audio/pipewire/s1dd1-voice.conf),
# но в самом SC3: обработанный голос получат все, включая Discord, который берёт SC3 напрямую. Всё — в узлах,
# которые по графу SDK стоят на пути в USB: шумодав 0x82 → EQ голоса 0xA2 → поправка 0xAC (docs/WRITE.md).
PODCAST = Profile(
    name="podcast",
    title="Подкаст",
    items=(
        # срез низа 80 Гц в две ступени (≈ 24 дБ/окт, как hp1 + hp2): гул, стук по столу, дыхание; заводской
        # фильтр 1 (ФВЧ 50 Гц, выключен) становится первой ступенью, пустой слот 4 — второй
        ("eq.1.freq", 80), ("eq.1.q", 0.7), ("eq.1.on", "on"),
        ("eq.4.type", "highpass"), ("eq.4.freq", 80), ("eq.4.q", 0.7), ("eq.4.on", "on"),
        # «бочка» близкого голоса: −3 дБ на 300 Гц (Q 1) вместо заводской полки +2 дБ ниже 350 Гц (фильтр 3)
        ("eq.3.type", "peak"), ("eq.3.freq", 300), ("eq.3.q", 1.0), ("eq.3.gain", -3), ("eq.3.on", "on"),
        # разборчивость: +3 дБ на 4 кГц (Q 0,8) — голос «впереди» игры
        ("eq.5.type", "peak"), ("eq.5.freq", 4000), ("eq.5.q", 0.8), ("eq.5.gain", 3), ("eq.5.on", "on"),
        # «воздух»: полка +2 дБ от 10 кГц — AM8T сам заваливает верх; ФНЧ 16 кГц (фильтр 2) — как с завода
        ("eq.6.type", "highshelf"), ("eq.6.freq", 10000), ("eq.6.q", 0.7), ("eq.6.gain", 2), ("eq.6.on", "on"),
        # шумодав: мягкий экспандер на заводских порогах (−45 дБ, 1:2) — комнатный шум (≈ −62 dBFS) тише ещё
        # на ~17 дБ, речь выше порога не трогается; спад длиннее заводского, чтобы не «дышал» на хвостах слов
        ("gate.threshold", -45), ("gate.ratio", 2), ("gate.attack", 3), ("gate.release", 120), ("gate.on", "on"),
        # уровень: речь в ПК сейчас около −29 dBFS; OBS добавляет +10 дБ — здесь +6 (дальше 0xB0 даёт ещё +5 дБ,
        # а лимитера до USB нет — запас на смех и крик)
        ("mic.trim", 6),
    ),
    notes=(
        "Черновик: значения утверждает владелец на слух, вне эфира.",
        ("Пока профиль в SC3, эквалайзер PipeWire (s1dd1-voice.conf) и «Усиление» OBS обрабатывают голос второй "
         "раз — их нужно ослабить или выключить (решение владельца)."),
        "Компрессора в профиле нет: по SDK DRC микрофона стоит только в мониторе наушников, не на пути в ПК.",
        "Кнопка голоса или ELECTRIC на панели перепишет профиль заводским пресетом.",
    ),
)

PROFILES = {p.name: p for p in (PODCAST,)}


@dataclass(frozen=True)
class Row:
    key: str
    now: str      # сейчас (для людей); «?» — неизвестно
    target: str   # в профиле
    same: bool


def diff(profile: Profile, state: dict[int, Sequence[int]] | None) -> list[Row]:
    """Профиль против снимка {узел: [enable, p1, …]}: по строке на ключ, в порядке профиля."""
    rows = []
    for key, value in profile.items:
        w = W.target(key, value)
        now = W.current(w.param, state)
        rows.append(Row(key, w.param.fmt(now), w.param.fmt(w.value), now == w.value))
    return rows


def lines(profile: Profile) -> list[str]:
    """Профиль для людей: ключ, значение, что это."""
    out = []
    for key, value in profile.items:
        w = W.target(key, value)
        out.append(f"{key:<14} {w.param.fmt(w.value):<14} {w.param.text}")
    return out
