"""Один набор чтений ACP → `Sc3State`. Кадры: 0x00 (в verify), 0x02, 0x07, 0xB6, 0x85, 0x86, 0xAC, 0xA2, 0x82 — девять.

Вызывающий уже открыл устройство и спросил `AcpGuard` (эфир не идёт, интервал выдержан). Здесь только чтение
через `Sc3`; чего по ACP не узнать — `None` (model.py). Карта кнопок проверена 08.10 с владельцем по дампам
(docs/RESEARCH.md §3, §14):
- ползунок Mic — громкость ADC1 `0x07` (4092 = 31 × 132 — верх лестницы из 32 ступеней); ползунок Line In —
  усиление узла `0xB6` (132 на ступень);
- MUTE MIC и MUTE LINE IN только обнуляют эти же громкости (флаг mute в `0x07` не меняется никогда): громкость
  больше 0 — `muted = False` (MUTE всегда даёт 0); ровно 0 — MUTE или «ползунок внизу», из одного чтения не
  отличить: `muted = None`. Догадку по ходу громкости во времени делает опрос окна (app/poll.py);
- CHANGE VOICE — пресет: `0x85` (сдвиг высоты) включён, голос узнаётся по величине сдвига;
- ELECTRIC — `0x86` (автотюн): буква SDK по кругу → точка панели в той же позиции по строкам (`ELECTRIC_KEYS`);
- поправка MIC в ПК — усиление узла `0xAC` (Q12, 4096 = 0 дБ; write.MIC_TRIM): её меняют только окно и CLI, поэтому
  она читается в наборе и после записи, а в круг опроса не входит;
- узлы обработки голоса на пути в ПК (`DSP_NODES`: поправка `0xAC`, EQ голоса `0xA2`, шумодав `0x82`) читаются
  целиком в `Sc3State.nodes` — для ящика MIC и сверки с профилем. Кнопка голоса или ELECTRIC переписывает их пресетом
  (docs/GOTCHAS.md): опрос окна тогда перечитывает их, а в круг они не входят.
MIC MONITOR, MUTE LINE OUT, ползунки Headphone и Line Out, RGB, пэды в ACP не видны — `None`/`locked`.
"""
from __future__ import annotations

import struct
from dataclasses import replace

from . import layouts as L
from . import protocol as P
from .device import Sc3
from .model import KEYS, Channel, Link, Sc3State

ADC1, QUERY = 0x07, 0x02
LINE_IN = 0xB6       # на деле ползунок Line In (проверено 08.10)
PITCH = 0x85         # сдвиг высоты: по нему узнаётся голос CHANGE VOICE
AUTOTUNE = 0x86      # ELECTRIC
MIC_TRIM = 0xAC      # поправка MIC в ПК (write.MIC_TRIM; живая проба 09.10: доходит до ПК ровно на заданные дБ)
VOICE_EQ = 0xA2      # EQ голоса до ответвления в ПК (write.VOICE_EQ): [вкл., предусиление, число, 10 × 5]
GATE = 0x82          # шумодав микрофона, экспандер (write.GATE): [вкл., порог 0,01 дБ, степень, атака, спад]
DSP_NODES = (MIC_TRIM, VOICE_EQ, GATE)  # читаются целиком (Sc3State.nodes); их переписывает пресет кнопки
STEP, STEPS = 132, 31  # у ползунков 32 положения 0…31, шаг 132 (4092 — верх)
# Лёгкий опрос окна (решение 9): одно чтение раз в 0,5 с по кругу (нагрузка как на стенде этапа 2). Кнопки SC3 не
# шлют HID — голос и ELECTRIC окно узнаёт только чтением, поэтому они в круге: Mic — раз в 1 с, голос, ELECTRIC
# и Line In — раз в 3 с. Полный набор `read_state` — отдельно, не чаще раза в 5 с.
POLL_CYCLE = (ADC1, PITCH, ADC1, AUTOTUNE, ADC1, LINE_IN)
FULL_SET = (QUERY, ADC1, LINE_IN, PITCH, AUTOTUNE, *DSP_NODES)  # то, что read_state читает после verify()
NEED = {LINE_IN: 3, PITCH: 2, AUTOTUNE: 2, MIC_TRIM: 3, VOICE_EQ: 53, GATE: 5}  # минимум значений узла

# Голос CHANGE VOICE → сдвиг высоты `0x85` values[1] (дампы 08.10). Выключен — values[0] = 0, а высота остаётся
# от последнего голоса. Прочие узлы пресета для узнавания не нужны.
VOICE_PITCH = {"male": -55, "female": 45, "robot": -100, "monster": -120, "baby": 100, "elder": -40}
PITCH_VOICE = {v: k for k, v in VOICE_PITCH.items()}

# ELECTRIC: короткое нажатие идёт по кругу SDK `a A b B C d D e E F g G` (бемоли строчными), а индикатор панели
# зажигает точки в той же позиции, но по строкам — верхний ряд слева направо, затем нижний слева направо (model.KEYS):
# a → A, A → Bb, b → B, D → Ab, e → G (проверено с владельцем 08.10). Подпись на панели, значит, не всегда совпадает
# с нотой SDK. В модели — подпись как на панели. «X» (хроматический) на панели не выбрать — None.
SDK_CIRCLE = "aAbBCdDeEFgG"
PANEL_ORDER = KEYS
ELECTRIC_KEYS = dict(zip(SDK_CIRCLE, PANEL_ORDER, strict=True))


def _clamp01(x: float) -> float:
    return min(max(x, 0.0), 1.0)


def mic_fader(adc1: dict) -> float:
    """Громкость ADC1 → положение ползунка Mic 0..1 (4092 — верх)."""
    return _clamp01(adc1["vol_l"] / (STEP * STEPS))


def line_in_fader(gain: int) -> float:
    """Усиление `0xB6` → ступень 0…31 → 0..1."""
    return min(max(round(gain / STEP), 0), STEPS) / STEPS


def electric_key(values: list[int]) -> str | None:
    """Узел автотюна → "" (выкл.), подпись тональности как на панели (KEYS) или None (хроматический, непонятное)."""
    if not values[0]:
        return ""
    return ELECTRIC_KEYS.get(chr(values[1])) if 0 < values[1] < 128 else None


def voice(pitch: list[int]) -> str | None:
    """Узел сдвига высоты → "" (выкл.), голос из VOICES или None (включён, но сдвиг не из пресетов)."""
    if not pitch[0]:
        return ""
    return PITCH_VOICE.get(pitch[1])


def _muted(raw: int) -> bool | None:
    """MUTE обнуляет громкость: больше 0 — точно не заглушено; 0 — MUTE или ползунок внизу (None)."""
    return False if raw > 0 else None


def mic_channel(adc1_body: bytes) -> Channel:
    """Тело `0x07` → канал Mic: положение ползунка и mute (False при громкости > 0, иначе None).
    Короткое тело — KeyError/struct.error."""
    a = L.adc(adc1_body)
    return Channel(fader=mic_fader(a), muted=_muted(a["vol_l"]))


def line_in_channel(values: list[int]) -> Channel:
    """Значения узла `0xB6` → канал Line In: положение ползунка и mute — как у Mic."""
    return Channel(fader=line_in_fader(values[2]), muted=_muted(values[2]))


def mic_trim(values: list[int]) -> float | None:
    """Значения узла `0xAC` → поправка MIC в дБ; усиление ≤ 0 (выключено, −∞) — None: ручке показать нечего."""
    return L.q12_db(values[2]) if values[2] > 0 else None


def dsp_load(query_body: bytes) -> float | None:
    """Тело `0x02` → загрузка процессора 0..1 (None — частота не указана)."""
    qd = L.query(query_body)
    return _clamp01(qd["mcps"] / qd["cpu_mhz"]) if qd["cpu_mhz"] else None


def verify_link(sc3: Sc3) -> Link | None:
    """verify(): None — сборка наша, можно читать; иначе FOREIGN (чужая сборка) или ERROR (чтение не прошло)."""
    try:
        sc3.verify()
    except P.ProtocolError:
        return Link.FOREIGN if _foreign(sc3) else Link.ERROR
    return None


def _foreign(sc3: Sc3) -> bool:
    """verify() отказал потому, что это не наша сборка/не тот интерфейс, а не потому, что чтение не прошло."""
    if sc3.version is not None and sc3.version != P.V22_VERSION:
        return True
    return sc3.descriptor is not None and not P.interface4_ok(P.parse_hid(sc3.descriptor))


def read_state(sc3: Sc3, now: float) -> Sc3State:
    """verify() и восемь чтений. Чужая сборка → FOREIGN; сбой транспорта или хоть одно непрочитанное → ERROR
    (без значений: половине набора верить нельзя). `now` — time.time() вызывающего, станет `read_at`."""
    bad = verify_link(sc3)
    if bad is not None:
        return Sc3State(link=bad)
    error = Sc3State(link=Link.ERROR, firmware="V22")
    plan = [(sc3.read, c) if c in (QUERY, ADC1) else (sc3.node, c) for c in FULL_SET]
    got: list = []
    try:  # по порядку и до первой неудачи: молчащее устройство не держим лишними повторами
        for read, ctrl in plan:
            got.append(read(ctrl))
            if got[-1] is None:
                return error
    except P.ProtocolError:
        return error
    q, adc1, line_in, pitch, tune, *dsp = got
    if any(len(v) < NEED[c] for c, v in zip(FULL_SET[2:], got[2:], strict=True)):
        return error
    try:
        load = dsp_load(q)
        nodes = {c: tuple(v) for c, v in zip(DSP_NODES, dsp, strict=True)}
        mic = replace(mic_channel(adc1), trim_db=mic_trim(nodes[MIC_TRIM]))
    except (KeyError, struct.error):  # тело короче раскладки
        return error
    return Sc3State(
        link=Link.CONNECTED,
        firmware="V22",
        dsp_load=load,
        read_at=now,
        mic=mic,
        line_in=line_in_channel(line_in),
        voice=voice(pitch),
        electric_key=electric_key(tune),
        nodes=nodes,
    )
