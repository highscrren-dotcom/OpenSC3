"""Раскладка блоков и узлов ACP по открытому SDK MVsilicon BP10 v0.1.12 (communication.c), сверенная с SC3.

Только расшифровка того, что прочитано, — ничего не шлёт. Источники полей — docs/RESEARCH.md, разделы 4.2 и 12.
"""
from __future__ import annotations

import math
import struct

from .protocol import SAMPLE_RATES


def words(body: bytes) -> list[int]:
    """Тело блока `FF <u16> <u16> …` → беззнаковые слова."""
    rest = body[1:] if body[:1] == b"\xff" else body
    k = len(rest) // 2
    return list(struct.unpack(f"<{k}H", rest[: 2 * k]))


def _named(fields: tuple[str, ...], body: bytes) -> dict:
    return dict(zip(fields, words(body)))


def version(body: bytes) -> dict:
    return {"chip": body[0], "effects": tuple(body[1:4]), "library": tuple(body[4:7])}


SYSTEM_FIELDS = ("sys_mode", "sys_reset", "sr_enable", "sr_index", "mclk_enable", "mclk_src", "default_set")
ADC_FIELDS = ("channels", "mute", "vol_l", "vol_r", "sr_index", "lr_swap", "hpf", "fade", "mclk_src",
              "dc_blocker")
PGA1_FIELDS = ("mic1_en", "mic2_en", "mic1_gain", "mic1_boost", "mic2_gain", "mic2_boost", "mic_line_sel",
               "mic1_pin", "mic2_pin")
AGC_FIELDS = ("mode", "max_level", "target_level", "max_gain", "min_gain", "gain_offset", "frame_time",
              "hold_time", "attack_time", "decay_time", "gate_en", "gate_threshold", "gate_mode", "gate_hold")

# Усиление PGA микрофона, дБ, по индексу регистра (регистр = 31 − значение в ACP); таблица из audio_adc.h SDK.
MIC_PGA_DB = (21.14, 19.76, 18.29, 17.04, 15.94, 14.67, 13.56, 12.12, 10.89, 9.48, 7.98, 6.48, 5.19, 4.07,
              2.78, 1.52, 0.42, -0.86, -1.98, -3.19, -4.46, -5.57, -6.85, -8.1, -9.3, -10.56, -11.82, -13.08,
              -14.42, -15.7, -17.0, -18.29)
# boost в ACP 0…4 → MIC_BOOST_LIST = (4 «выкл.», 0, 1, 2, 3) → 0/6/12/20 дБ
MIC_BOOST = ("выкл.", "0 дБ", "+6 дБ", "+12 дБ", "+20 дБ")
ADC_HPF = ("20 Гц", "40 Гц", "40 Гц (при 32 кГц)")


def system(body: bytes) -> dict:
    return _named(SYSTEM_FIELDS, body)


def adc(body: bytes) -> dict:
    return _named(ADC_FIELDS, body)


def pga1(body: bytes) -> dict:
    return _named(PGA1_FIELDS, body)


def agc(body: bytes) -> dict:
    return _named(AGC_FIELDS, body)


def query(body: bytes) -> dict:
    """0x02: `FF <ОЗУ u16> <MCPS u16> <AutoRefresh u8> <макс. МГц u16> <макс. ОЗУ u16>`."""
    ram, mcps, auto, mhz, ram_max = struct.unpack_from("<HHBHH", body, 1)
    return {"ram_kb": ram, "mcps": mcps, "auto_refresh": auto, "cpu_mhz": mhz, "ram_max_kb": ram_max}


def sample_rate(index: int) -> int | None:
    return SAMPLE_RATES[index] if 0 <= index < len(SAMPLE_RATES) else None


def mic_pga_db(acp_gain: int) -> float | None:
    reg = 31 - acp_gain
    return MIC_PGA_DB[reg] if 0 <= reg < len(MIC_PGA_DB) else None


def adc_vol_db(v: int) -> float:
    """Цифровая громкость АЦП: линейно, 0 = тишина, 0xFFF = 0 дБ, до 0x3FFF."""
    return -math.inf if v <= 0 else 20 * math.log10(v / 0xFFF)


def q12_db(g: int) -> float:
    """Узел усиления: Q12, 4096 = 0 дБ."""
    return -math.inf if g <= 0 else 20 * math.log10(g / 4096)


EQ_TYPES = ("peak", "lowshelf", "highshelf", "lowpass", "highpass", "bandpass", "notch")


def eq(values: list[int]) -> dict:
    """Узел EQ (тип 4): [enable, pregain Q8.8, count, 10 × (en, type, f0, Q Q6.10, gain Q8.8)]."""
    filters = []
    for k in range(10):
        en, t, f0, q, g = values[3 + 5 * k: 8 + 5 * k]
        if en:
            filters.append({"type": EQ_TYPES[t] if 0 <= t < len(EQ_TYPES) else t, "f0": f0,
                            "q": round(q / 1024, 2), "gain_db": round(g / 256, 1)})
    return {"enable": values[0], "pregain_db": round(values[1] / 256, 1), "filters": filters}


AUTOTUNE_KEYS = {"a": "A♭", "A": "A", "b": "B♭", "B": "B", "C": "C", "d": "D♭", "D": "D", "e": "E♭", "E": "E",
                 "F": "F", "g": "G♭", "G": "G", "X": "хроматический"}


def autotune(values: list[int]) -> dict:
    """Узел Auto Tune (тип 0): [enable, key (буква ASCII), snap (n/u/l), точность]."""
    key = chr(values[1]) if 0 < values[1] < 128 else "?"
    snap = chr(values[2]) if 0 < values[2] < 128 else "?"
    return {"enable": values[0], "key": AUTOTUNE_KEYS.get(key, key), "snap": snap, "accuracy": values[3]}
