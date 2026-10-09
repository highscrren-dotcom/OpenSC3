"""sc3 — командная строка к микшеру fifine SC3. Только чтение.

  sc3 doctor              подключён ли SC3, есть ли права (udev), всё ли на месте — ничего не шлёт устройству
  sc3 status              сводка: сборка, микрофон, гейт, эффекты, EQ, усиления (~20 чтений ACP)
  sc3 dump [-o файл]      всё, что читается (~123 чтения): блоки, типы, имена и значения 54 узлов
  sc3 descriptor          только стандартный GET_DESCRIPTOR интерфейса 4
  sc3 listen [секунд]     что шлют кнопки: evdev (без захвата) + сырой hidraw + громкость PipeWire по умолчанию
  sc3 live                идёт ли эфир или запись в OBS (GetStreamStatus, GetRecordStatus) — к SC3 не обращается
  sc3 state               состояние для окна (JSON): эфир → разрешение на ACP → один набор чтений (8) + PipeWire

status, dump, descriptor и state идут к SC3 только вне эфира (OBS: OFF) и не чаще раза в 5 с (отметка общая
с окном) — иначе отказ до открытия USB, код 3 (state — JSON с acp_note). Обхода нет.

Запуск из каталога проекта: python3 -m opensc3 <команда>.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import select
import subprocess
import sys
import time
from pathlib import Path

from . import layouts as L
from . import protocol as P

BY_ID = Path("/dev/input/by-id")
EVENT = BY_ID / "usb-MV-SILICON_fifine_SC3_20190808-event-if03"
HIDRAW = BY_ID / "usb-MV-SILICON_fifine_SC3_20190808-if03-hidraw"
RULE = Path("/etc/udev/rules.d/70-fifine-sc3.rules")
REPO_RULE = Path(__file__).resolve().parent.parent / "udev" / "70-fifine-sc3.rules"


def _usb_dev() -> Path | None:
    from .hotplug import usb_device
    return usb_device()


def _rules(p: Path) -> list[str]:
    """Действующие строки правила udev — без комментариев и пустых строк."""
    return [ln.strip() for ln in p.read_text().splitlines() if ln.strip() and not ln.lstrip().startswith("#")]


def cmd_doctor(_a) -> int:
    bad = 0

    def line(ok: bool, text: str, hint: str = "") -> None:
        nonlocal bad
        bad += not ok
        print(f"{'✓' if ok else '✗'} {text}" + (f"\n    → {hint}" if hint and not ok else ""))

    dev = _usb_dev()
    line(dev is not None, "SC3 подключён (USB 3142:0c33)", "воткни USB")
    if dev is None:
        return 1
    bus, num = int((dev / "busnum").read_text()), int((dev / "devnum").read_text())
    node = Path(f"/dev/bus/usb/{bus:03d}/{num:03d}")
    print(f"  {dev.name}: шина {bus}, адрес {num}, {(dev / 'speed').read_text().strip()} Мбит/с")
    for i in (3, 4):
        drv = dev / f"{dev.name}:1.{i}" / "driver"
        name = os.path.basename(os.readlink(drv)) if drv.exists() else "нет"
        print(f"  интерфейс {i}: драйвер {name}")
    line(RULE.exists(), f"правило udev {RULE}", f"sudo install -m 644 {REPO_RULE} /etc/udev/rules.d/")
    if RULE.exists() and REPO_RULE.exists():
        line(_rules(RULE) == _rules(REPO_RULE), "правило совпадает с udev/ в репо (без комментариев)",
             "переустановить из репо и sudo udevadm control --reload")
    for p, what in ((EVENT, "кнопки (evdev)"), (HIDRAW, "кнопки (hidraw)")):
        line(p.exists() and os.access(p, os.R_OK), f"{what}: {p.name}",
             "sudo udevadm trigger --action=change " + str(p))
    line(os.access(node, os.W_OK), f"USB-узел {node} для ACP (нужна запись)",
         "этап 2 правила; sudo udevadm trigger --action=change --attr-match=idVendor=3142 --attr-match=idProduct=0c33")
    try:
        import ctypes
        ctypes.CDLL("libusb-1.0.so.0")
        line(True, "libusb-1.0")
    except OSError:
        line(False, "libusb-1.0", "sudo pacman -S libusb")
    try:
        import evdev  # noqa: F401
        line(True, "python-evdev (для кнопок)")
    except ImportError:
        line(False, "python-evdev (для кнопок)", "sudo pacman -S python-evdev")
    card = Path("/proc/asound/SC3")
    line(card.exists(), "звуковая карта ALSA «SC3»")
    print("всё в порядке" if not bad else f"проблем: {bad}")
    return 1 if bad else 0


SC3_BUSY = P.Sc3Busy.TEXT  # интерфейс 4 держит другой процесс — окно опрашивает SC3 (решение 9)


def _open():
    """SC3 для набора чтений. Занят окном — `Sc3Busy` (его текст и печатается)."""
    from .device import Sc3
    return Sc3.open()


class Refused(Exception):
    """К SC3 сейчас нельзя: эфир, неизвестный эфир или правило 4. Обхода нет."""


@contextlib.contextmanager
def _acp():
    """Сессия ACP для status/dump/descriptor: свежий статус OBS → AcpGuard (общая отметка с окном и `sc3 state`)
    → открыть SC3. Отказ — до открытия USB. Отметка ставится и при неудачном открытии/чтении."""
    from .guard import AcpGuard, default_stamp
    from .obs import live_status
    live, _since = live_status()
    guard = AcpGuard(stamp=default_stamp())
    note = guard.check(live)
    if note:
        raise Refused(note)
    try:
        with _open() as s:
            yield s
    finally:
        guard.mark()


def cmd_descriptor(_a) -> int:
    with _acp() as s:
        parsed = s.check_descriptor()
        print(f"дескриптор интерфейса 4 ({len(s.descriptor)} байт): {s.descriptor.hex(' ')}")
        print(f"  страница {parsed['page']:#06x}, usage {parsed['usage']:#06x}, Report ID {parsed['report_ids'] or 'нет'}, "
              f"вход {parsed['in'] // 8}, выход {parsed['out'] // 8}, feature {parsed['feature'] // 8} байт")
    return 0


def _onoff(v: int) -> str:
    return "вкл." if v else "выкл."


def cmd_status(_a) -> int:
    with _acp() as s:
        v = L.version(s.verify())
        q = L.query(s.read(0x02) or b"\xff" + bytes(9))
        sysb = L.system(s.read(0x01) or b"")
        adc1 = L.adc(s.read(0x07) or b"")
        pga1 = L.pga1(s.read(0x06) or b"")
        agc1 = L.agc(s.read(0x08) or b"")
        nodes = {a: s.node(a) for a in (0x82, 0x83, 0x85, 0x86, 0x87, 0x88, 0x89, 0x8A, 0xA2, 0xA5, 0xAB, 0xB0, 0xB6)}
        ok, fail = s.ok, s.fail
    sr = L.sample_rate(sysb.get("sr_index", -1))
    load = f"{q['mcps']}/{q['cpu_mhz']} МГц ({100 * q['mcps'] // max(q['cpu_mhz'], 1)} %)" if q["cpu_mhz"] else "?"
    print(f"SC3: сборка V22 (чип {v['chip']:#04x}, эффекты {'.'.join(map(str, v['effects']))}, "
          f"библиотека {'.'.join(map(str, v['library']))}); DSP {sr or '?'} Гц, загрузка {load}")
    vol = adc1.get("vol_l", 0)
    # MUTE MIC лишь обнуляет эту громкость (флаг mute в 0x07 не меняется): 0 — MUTE или ползунок внизу (§14)
    where = " — MUTE или ползунок внизу" if vol == 0 else f" — ползунок Mic, ступень {round(vol / 132)}/31"
    pga = L.mic_pga_db(pga1.get("mic1_gain", -1))
    print(f"Микрофон: цифровая громкость {vol} ({L.adc_vol_db(vol):+.1f} дБ){where}; "
          f"PGA {pga:+.2f} дБ, boost {L.MIC_BOOST[pga1.get('mic1_boost', 0)]}; ФВЧ {L.ADC_HPF[adc1.get('hpf', 0)]}, "
          f"DC-блокер {_onoff(adc1.get('dc_blocker', 0))}")
    ns = nodes[0x82] or [0, 0, 0, 0, 0]
    print(f"Гейт AGC1: {_onoff(agc1.get('gate_en', 0))} (порог {agc1.get('gate_threshold')}); AGC {_onoff(agc1.get('mode', 0))}; "
          f"шумодав 0x82: {_onoff(ns[0])} ({ns[1] / 100:.0f} дБ, {ns[2]}:1)")
    fx = []
    if nodes[0x85] and nodes[0x85][0]:
        fx.append(f"сдвиг высоты {nodes[0x85][1]}")
    for a, label in ((0x83, "сдвиг частоты"), (0x87, "voice changer"), (0x88, "voice changer pro"),
                     (0x89, "эхо"), (0x8A, "реверберация")):
        if nodes[a] and nodes[a][0]:
            fx.append(label)
    at = L.autotune(nodes[0x86]) if nodes[0x86] else None
    if at and at["enable"]:
        fx.append(f"автотюн (по SDK {at['key']}, привязка {at['snap']})")
    print("Эффекты голоса: " + (", ".join(fx) if fx else "все выключены")
          + (f"; тональность автотюна по SDK {at['key']}" if at and not at["enable"] else ""))
    from .reader import electric_key, voice
    vc = voice(nodes[0x85]) if nodes[0x85] and len(nodes[0x85]) > 1 else None
    ek = electric_key(nodes[0x86]) if nodes[0x86] and len(nodes[0x86]) > 1 else None
    print(f"Панель: CHANGE VOICE {vc or ('выкл.' if vc == '' else '?')}, "
          f"ELECTRIC {ek or ('выкл.' if ek == '' else '?')} (подпись как на панели)")
    for a in (0xA2, 0xA5):
        if nodes[a]:
            e = L.eq(nodes[a])
            fl = "; ".join(f"{f['type']} {f['f0']} Гц {f['gain_db']:+.1f} дБ" for f in e["filters"]) or "фильтров нет"
            print(f"EQ {a:#04x}: {_onoff(e['enable'])}: {fl}")
    g = {a: (nodes[a][2] if nodes[a] else 0) for a in (0xAB, 0xB0, 0xB6)}
    print(f"Усиления: 0xAB {g[0xAB]} ({L.q12_db(g[0xAB]):+.1f} дБ), 0xB0 {g[0xB0]} ({L.q12_db(g[0xB0]):+.1f} дБ), "
          f"Line In 0xB6 {g[0xB6]} (ступень {round(g[0xB6] / 132)}/31; 0 — MUTE LINE IN или ползунок внизу)")
    print(f"чтений: {ok} ok, {fail} неудач")
    return 0 if not fail else 2


def cmd_dump(a) -> int:
    with _acp() as s:
        s.verify()
        res = s.dump()
    text = json.dumps(res, ensure_ascii=False, indent=1)
    if a.output:
        Path(a.output).write_text(text, encoding="utf-8")
        print(f"сохранено: {a.output}; чтений {res['counters']['ok']} ok, {res['counters']['fail']} неудач")
    else:
        print(text)
    return 0 if not res["counters"]["fail"] else 2


def cmd_listen(a) -> int:
    try:
        import evdev
        from evdev import ecodes
    except ImportError:
        sys.exit("✗ нужен python-evdev: sudo pacman -S python-evdev")
    dev = evdev.InputDevice(str(EVENT))  # без grab: KDE видит то же, что и мы
    hr = os.open(HIDRAW, os.O_RDONLY | os.O_NONBLOCK)
    t0 = time.monotonic()

    def ts() -> str:
        return f"{time.monotonic() - t0:7.2f}s  {time.strftime('%H:%M:%S')}"

    def vol(target: str) -> str:
        try:
            return subprocess.run(["wpctl", "get-volume", target], capture_output=True, text=True,
                                  timeout=2, check=False).stdout.strip()
        except (OSError, subprocess.SubprocessError) as e:
            return f"? {e}"

    last = {t: vol(t) for t in ("@DEFAULT_AUDIO_SINK@", "@DEFAULT_AUDIO_SOURCE@")}
    print(ts(), f"слушаю {a.seconds:.0f} с: {dev.name}; громкость: {last}", flush=True)
    n_ev = n_hr = 0
    next_poll = 0.0
    try:
        while (now := time.monotonic() - t0) < a.seconds:
            r, _, _ = select.select([dev.fd, hr], [], [], 0.25)
            if dev.fd in r:
                for e in dev.read():
                    if e.type == ecodes.EV_SYN:
                        continue
                    n_ev += 1
                    if e.type == ecodes.EV_KEY:
                        state = {0: "отпущена", 1: "нажата", 2: "повтор"}.get(e.value, e.value)
                        print(ts(), "evdev", ecodes.KEY.get(e.code, e.code), state, flush=True)
                    elif e.type == ecodes.EV_MSC:
                        print(ts(), f"evdev MSC scan={e.value:#x}", flush=True)
            if hr in r:
                try:
                    data = os.read(hr, 64)
                except BlockingIOError:
                    data = b""
                if data:
                    n_hr += 1
                    print(ts(), "hidraw", data.hex(" "), f"(биты {data[0]:08b})", flush=True)
            if now >= next_poll:
                next_poll = now + 0.5
                for t, was in list(last.items()):
                    v = vol(t)
                    if v != was:
                        print(ts(), "PipeWire", t, was, "->", v, flush=True)
                        last[t] = v
    except KeyboardInterrupt:
        pass
    finally:
        os.close(hr)
    print(ts(), f"конец: событий evdev {n_ev}, отчётов hidraw {n_hr}")
    return 0


def _clock(t: float) -> str:
    return time.strftime("%H:%M:%S", time.localtime(t))


def cmd_live(_a) -> int:
    from .obs import live_status
    live, since = live_status()
    text = {"off": "не идёт", "on": "идёт эфир или запись", "unknown": "неизвестно — OBS не отвечает"}[live.value]
    if since is not None:
        m, sec = divmod(int(time.time() - since), 60)
        text += f", с {_clock(since)} ({m // 60}:{m % 60:02d}:{sec:02d})"
    print(f"эфир: {live.value.upper()} — {text}")
    return 0


def _jsonable(x):
    """dataclass/Enum → JSON: Enum — значением, остальное как есть."""
    import dataclasses
    import enum
    if dataclasses.is_dataclass(x):
        return {f.name: _jsonable(getattr(x, f.name)) for f in dataclasses.fields(x)}
    if isinstance(x, enum.Enum):
        return x.value
    return x


def cmd_state(_a) -> int:
    """Один кадр AppState. ACP — только если OBS сказала OFF, интервал правила 4 выдержан и есть права."""
    from . import pipewire as PW
    from .guard import AcpGuard, default_stamp
    from .hotplug import probe
    from .model import AppState, AudioState, Link, Sc3State
    from .obs import live_status
    from .reader import read_state

    live, since = live_status()
    guard = AcpGuard(stamp=default_stamp())
    link, node = probe()
    sc3, note = Sc3State(link=link), guard.check(live)
    if link is Link.DISCONNECTED:
        note = "SC3 не подключён"
    elif link is Link.NO_ACCESS:
        note = f"нет прав на {node} (правило udev, этап 2)"
    elif not note:
        try:
            with _open() as s:  # открытие — уже не обращение к ACP; первый кадр шлёт verify() в read_state
                sc3 = read_state(s, time.time())
        except P.ProtocolError as e:
            sc3, note = Sc3State(link=Link.ERROR), str(e)
        finally:
            guard.mark()
        if sc3.link is Link.FOREIGN:
            note = "сборка прошивки не V22 — ACP не трогаю"
        elif sc3.link is Link.ERROR and not note:
            note = "чтения ACP не прошли"
    nodes = PW.find_sc3()
    muted = PW.get_mute(nodes.source_id) if nodes and nodes.source_id else None
    app = AppState(sc3=sc3, audio=AudioState(present=nodes is not None, pw_muted=muted), live=live,
                   live_since=since, acp_note=note)
    out = _jsonable(app)
    out["pipewire"] = _jsonable(nodes)  # узлы SC3 (вне AppState: окну они нужны для mute и индикаторов)
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0 if sc3.link in (Link.CONNECTED, Link.DISCONNECTED, Link.NO_ACCESS) else 2


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="sc3", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor").set_defaults(fn=cmd_doctor)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    sub.add_parser("descriptor").set_defaults(fn=cmd_descriptor)
    d = sub.add_parser("dump")
    d.add_argument("-o", "--output")
    d.set_defaults(fn=cmd_dump)
    li = sub.add_parser("listen")
    li.add_argument("seconds", nargs="?", type=float, default=180.0)
    li.set_defaults(fn=cmd_listen)
    sub.add_parser("live").set_defaults(fn=cmd_live)
    sub.add_parser("state").set_defaults(fn=cmd_state)
    a = ap.parse_args(argv)
    try:
        return a.fn(a)
    except Refused as e:
        print(f"✗ к SC3 не обращаюсь: {e}", file=sys.stderr)
        return 3
    except P.ProtocolError as e:
        print(f"✗ {e}", file=sys.stderr)
        return 1
