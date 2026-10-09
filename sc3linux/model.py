"""Модель состояния панели — договор между ядром (SC3, PipeWire, OBS) и любым интерфейсом (окно, трей, CLI).

Без Qt и без ввода-вывода: только неизменяемые данные. Всё, чего ядро пока не знает, — `None` («неизвестно»):
интерфейс рисует такой элемент нейтрально и ничего не додумывает. Смысл полей и откуда они берутся —
`design/BRIEF.md`, `docs/RESEARCH.md` §3.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field

VOICES = ("male", "female", "robot", "monster", "baby", "elder")  # порядок как на корпусе: верхний ряд, нижний ряд
KEYS = ("A", "Bb", "B", "C", "Db", "D", "Ab", "G", "Gb", "F", "E", "Eb")  # точки ELECTRIC: верхний ряд, нижний ряд


class Link(enum.Enum):
    DISCONNECTED = "disconnected"  # SC3 нет на шине
    NO_ACCESS = "no_access"        # есть, но нет прав на USB-узел (правило udev)
    CONNECTED = "connected"        # есть и прошёл verify() — сборка V22
    FOREIGN = "foreign"            # есть, но сборка не та — ACP не трогаем
    ERROR = "error"                # чтения не проходят


class Live(enum.Enum):
    OFF = "off"          # OBS не ведёт ни эфир, ни запись (или OBS не запущена)
    ON = "on"            # эфир или запись идут — к SC3 по ACP не обращаемся вовсе
    UNKNOWN = "unknown"  # OBS запущена, но статус не узнать — ведём себя как при ON


@dataclass(frozen=True)
class Channel:
    """Канал под ползунком. `locked` — с ПК его не прочитать и не поменять (Headphone, Line Out).

    Аппаратный MUTE у SC3 лишь обнуляет громкость канала — по одному чтению он неотличим от «ползунок внизу»
    (docs/RESEARCH.md §14). Поэтому `muted` из чтения: громкость > 0 — False, ровно 0 — None; True бывает только
    догадкой опроса по резкому обнулению (`muted_guess=True`; `fader` тогда — последнее ненулевое положение)."""
    fader: float | None = None    # 0..1 — зеркало настоящего ползунка
    muted: bool | None = None     # аппаратный Mute SC3 (клавиша на корпусе); None — не узнать
    trim_db: float | None = None  # программная поправка; None, пока нет записи (решение 4)
    locked: bool = False
    muted_guess: bool = False     # `muted` — догадка по ходу громкости во времени, а не прочитанный факт


@dataclass(frozen=True)
class Sc3State:
    """Что известно о самом SC3. Обновляется редко: только по чтениям ACP вне эфира (правила 3 и 4)."""
    link: Link = Link.DISCONNECTED
    firmware: str | None = None   # «V22»
    dsp_load: float | None = None  # 0..1, загрузка процессора
    read_at: float | None = None  # time.time() последнего удачного набора чтений; в эфире — «данные на …»
    mic: Channel = field(default_factory=Channel)
    line_in: Channel = field(default_factory=Channel)
    headphone: Channel = field(default_factory=lambda: Channel(locked=True))
    line_out: Channel = field(default_factory=lambda: Channel(locked=True))
    mic_monitor: bool | None = None
    voice: str | None = None         # один из VOICES; "" — выключено; None — неизвестно
    electric_key: str | None = None  # один из KEYS; "" — выключено; None — неизвестно


@dataclass(frozen=True)
class AudioState:
    """Что видно в PipeWire. Можно обновлять часто: SC3 при этом не опрашивается."""
    present: bool = False              # узлы SC3 есть в PipeWire
    to_pc_db: float | None = None      # пик того, что SC3 отдаёт в ПК (голос), dBFS
    from_pc_db: float | None = None    # пик того, что ПК шлёт в SC3 (наушники), dBFS
    pw_muted: bool | None = None       # mute входа SC3 в PipeWire (решение 8)


@dataclass(frozen=True)
class AppState:
    sc3: Sc3State = field(default_factory=Sc3State)
    audio: AudioState = field(default_factory=AudioState)
    live: Live = Live.UNKNOWN
    live_since: float | None = None   # time.time() начала эфира/записи, если OBS сказала
    profile: str | None = None        # имя профиля; профилей пока нет (этап 3–4)
    acp_note: str = ""                # почему SC3 сейчас не читается: «идёт эфир», «рано: раз в 5 с» и т. п.
