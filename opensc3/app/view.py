"""Представление `AppState` для окна и трея — чистые функции: без Qt и без ввода-вывода.

Окно получает плоские свойства; их имена и смысл совпадают с `design/panel/scenes/DemoState.qml` (макеты рисуют
те же QML-компоненты с демо-данными). Всё, чего ядро не знает (`None` в model.py), попадает в словарь `unknown`
и рисуется нейтрально: без огня, без колпачка-догадки. Значение рядом с таким именем — лишь заглушка нужного типа.
"""
from __future__ import annotations

import time

from opensc3 import reader as R
from opensc3 import write as W
from opensc3.layouts import EQ_TYPES, q12_db
from opensc3.model import VOICES, AppState, Link, Live, Sc3State

METER_FLOOR_DB = -54.0   # низ полосы из 9 светодиодов: 6 дБ на светодиод, верхний — 0 dBFS
METER_FALL_PER_S = 1.6   # спад показаний: вся полоса за ~0,6 с (подъём — мгновенный)

LINK_WORDS = {  # для подсказки трея; окно пишет своё в Header.qml
    Link.CONNECTED: "подключён",
    Link.DISCONNECTED: "отключён",
    Link.NO_ACCESS: "нет прав на USB",
    Link.FOREIGN: "чужая сборка прошивки",
    Link.ERROR: "не отвечает на чтения",
}


def db_to_level(db: float | None) -> float:
    """Пик в dBFS → доля половины полосы 0..1 (линейно по децибелам). `None` — тишина."""
    if db is None:
        return 0.0
    return min(1.0, max(0.0, (db - METER_FLOOR_DB) / -METER_FLOOR_DB))


def meter_step(shown: float, target: float, dt: float) -> float:
    """Баллистика полосы: вверх сразу, вниз — плавно (бриф №9: светодиоды мягко гаснут)."""
    return target if target >= shown else max(target, shown - METER_FALL_PER_S * max(dt, 0.0))


def clock_text(ts: float | None) -> str:
    """time.time() → «ЧЧ:ММ» по местному времени; «» — не было."""
    return "" if ts is None else time.strftime("%H:%M", time.localtime(ts))


def duration_text(seconds: float) -> str:
    """Сколько идёт эфир: «1:23:45»."""
    s = max(0, int(seconds))
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"


def printed_voice(v: str) -> str:
    """Голос из model.VOICES («male») → как напечатано на корпусе («Male»)."""
    return v.capitalize() if v in VOICES else v


def on_air_time(st: AppState, now: float) -> str:
    return duration_text(now - st.live_since) if st.live is Live.ON and st.live_since is not None else ""


def qml_state(st: AppState, now: float) -> dict:
    """Свойства окна, кроме уровней (их отдаёт `levels`) и `busy` (это знает только бэкенд)."""
    s = st.sc3
    unknown: dict[str, bool] = {}

    def known(name: str, value, stub):
        if value is None:
            unknown[name] = True
            return stub
        return value

    voice = known("voice", s.voice, "")
    props = {
        "link": s.link.value,
        "connected": s.link is Link.CONNECTED,
        "firmware": s.firmware or "",
        "faderMic": float(known("faderMic", s.mic.fader, 0.5)),
        "faderLineIn": float(known("faderLineIn", s.line_in.fader, 0.5)),
        "faderHeadphone": float(known("faderHeadphone", s.headphone.fader, 0.5)),
        "faderLineOut": float(known("faderLineOut", s.line_out.fader, 0.5)),
        "muteMic": bool(known("muteMic", s.mic.muted, False)),
        "muteLineIn": bool(known("muteLineIn", s.line_in.muted, False)),
        "muteLineOut": bool(known("muteLineOut", s.line_out.muted, False)),
        "micMonitor": bool(known("micMonitor", s.mic_monitor, False)),
        "phantom": bool(known("phantom", None, False)),      # 48V с ПК не узнать
        "electricKey": known("electricKey", s.electric_key, ""),
        "voice": printed_voice(voice),
        "customLit": known("customLit", None, ""),           # звуковые пэды CUSTOM — только корпус
        "trimMic": float(known("trimMic", s.mic.trim_db, 0.0)),
        "trimLineIn": float(known("trimLineIn", s.line_in.trim_db, 0.0)),
        "unknown": unknown,
        "guess": {k: True for k, ch in (("muteMic", s.mic), ("muteLineIn", s.line_in))
                  if ch.muted is True and ch.muted_guess},   # клавиша горит по догадке опроса — «≈»
        "dsp": drawer_dsp(s),                                 # ящик MIC: EQ, шумодав, поправка (голоса — позже)
        "lastPoll": clock_text(s.read_at),
        "acpNote": st.acp_note,
        "audioPresent": st.audio.present,
        "pipewireMute": st.audio.pw_muted is True,
        "live": st.live.value,
        "onAir": st.live is Live.ON,
        "frozen": st.live is not Live.OFF,
        "onAirTime": on_air_time(st, now),
        "profile": st.profile or "",
        "profiles": [],                                       # профили — этап 3–4
    }
    return props


# --- ящик MIC: узлы обработки голоса (форма — design/panel/scenes/demo-dsp.js) ------------------------------

EQ_KIND = {"peak": "pk", "lowshelf": "ls", "highshelf": "hs", "lowpass": "lp", "highpass": "hp", "bandpass": "bp",
           "notch": "notch"}
EQ_NAME = {"peak": "пик", "lowshelf": "полка НЧ", "highshelf": "полка ВЧ", "lowpass": "ФНЧ", "highpass": "ФВЧ",
           "bandpass": "полоса", "notch": "режекция"}
GATE_SCALE = 80.0   # шкала порога шумодава: −80…0 дБ
TRIM_LO, TRIM_HI = W.TRIM_DB


def _frac(x: float) -> float:
    return min(1.0, max(0.0, x))


def _hz(f: int) -> str:
    """80 Гц, 4 кГц, 1,5 кГц."""
    if f < 1000:
        return f"{f} Гц"
    k = f / 1000
    return (f"{k:.0f}" if k == int(k) else f"{k:.1f}".replace(".", ",")) + " кГц"


def eq_data(values) -> dict:
    """Узел EQ голоса `0xA2` → карточка: 10 слотов (тип, частота, Q, усиление, вкл.) и `bands` — включённые фильтры
    для кривой (весь EQ выключен — кривая ровная). Пустой слот — частота или Q равны 0."""
    on, slots, bands = bool(values[0]), [], []
    for k in range(10):
        en, t, f0, q, g = values[3 + 5 * k: 8 + 5 * k]
        kind = EQ_TYPES[t] if 0 <= t < len(EQ_TYPES) else None
        empty = f0 <= 0 or q <= 0 or kind is None
        slot = {"n": k + 1, "on": bool(en) and not empty, "empty": empty, "kind": EQ_KIND.get(kind, ""),
                "name": EQ_NAME.get(kind, "?"), "f": f0, "q": q / 1024, "g": g / 256,
                "freq": _hz(f0), "qText": W.human("q", q), "gain": W.human("eqgain", g),
                "shaped": kind in ("peak", "lowshelf", "highshelf")}   # у этих типов усиление что-то значит
        slots.append(slot)
        if slot["on"]:
            bands.append({"n": k + 1, "kind": slot["kind"], "f": f0, "q": q / 1024, "g": g / 256, "name": slot["name"]})
    return {"on": on, "bands": bands if on else [], "slots": slots}


def gate_data(values) -> dict:
    """Шумодав `0x82` (экспандер): [вкл., порог 0,01 дБ, степень, атака мс, спад мс] → карточка «Гейт»."""
    on, thr, ratio, attack, release = values[:5]
    return {"on": bool(on), "threshold": _frac((thr / 100 + GATE_SCALE) / GATE_SCALE),
            "rows": [{"label": "Порог", "value": W.human("cdb", thr), "fraction": _frac((thr / 100 + 80) / 80)},
                     {"label": "Степень", "value": f"1:{ratio}", "fraction": _frac((ratio - 1) / 9)},
                     {"label": "Атака", "value": W.human("ms", attack), "fraction": _frac(attack / 100)},
                     {"label": "Спад", "value": W.human("ms", release), "fraction": _frac(release / 2000)}]}


def trim_data(values) -> dict:
    """Поправка MIC `0xAC` → карточка: значение и где оно на шкале −20…+10 дБ (0 дБ — `centre`)."""
    raw = values[2]
    span = TRIM_HI - TRIM_LO
    db = q12_db(raw) if raw > 0 else TRIM_LO
    return {"value": W.human("gain", raw), "fraction": _frac((db - TRIM_LO) / span), "centre": -TRIM_LO / span,
            "ticks": [{"text": "−20", "fraction": 0.0}, {"text": "0", "fraction": -TRIM_LO / span},
                      {"text": "+10", "fraction": 1.0}]}


def drawer_dsp(s: Sc3State) -> dict:
    """Что ящик MIC знает из прочитанных узлов: `eq`, `gate`, `gain` (поправка). Не прочитано — ключа нет, карточка
    пишет «появится позже». Компрессора на пути в ПК нет (DRC микрофона по SDK — только в мониторе)."""
    out, n = {}, s.nodes
    for key, ctrl, build in (("eq", R.VOICE_EQ, eq_data), ("gate", R.GATE, gate_data), ("gain", R.MIC_TRIM, trim_data)):
        if ctrl in n and len(n[ctrl]) >= R.NEED[ctrl]:
            out[key] = build(n[ctrl])
    return out


def levels(st: AppState) -> tuple[float, float]:
    """(в ПК, из ПК) — доли половин полосы 9 + 9."""
    return db_to_level(st.audio.to_pc_db), db_to_level(st.audio.from_pc_db)


# --- трей ------------------------------------------------------------------------------------------------

def mic_muted(st: AppState) -> bool:
    """Микрофон заглушён хоть где-то: клавишей на корпусе или в PipeWire."""
    return st.audio.pw_muted is True or (st.sc3.link is Link.CONNECTED and st.sc3.mic.muted is True)


def tray_icon(st: AppState) -> str:
    """Имя значка в `icons/`: connected | muted | disconnected | onair | onair-muted.
    «Эфир» — только когда OBS сказала ON; неизвестный эфир значок не красит (подсказка скажет)."""
    if st.sc3.link is Link.DISCONNECTED:
        return "disconnected"
    muted = mic_muted(st)
    if st.live is Live.ON:
        return "onair-muted" if muted else "onair"
    return "muted" if muted else "connected"


def tray_tooltip(st: AppState, now: float) -> str:
    lines = [f"SC3 {LINK_WORDS[st.sc3.link]}"]
    if st.sc3.link is not Link.DISCONNECTED:
        if st.audio.pw_muted is True:
            lines.append("микрофон заглушён (PipeWire)")
        elif mic_muted(st):
            lines.append("микрофон заглушён на корпусе" + (" (по догадке)" if st.sc3.mic.muted_guess else ""))
        else:
            lines.append("микрофон открыт")
    if st.live is Live.ON:
        t = on_air_time(st, now)
        lines.append("в эфире" + (f" · {t}" if t else ""))
    elif st.live is Live.UNKNOWN:
        lines.append("эфир не определён — SC3 не трогаем")
    if st.acp_note:
        lines.append(st.acp_note)
    return "\n".join(lines)
