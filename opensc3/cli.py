"""sc3 — командная строка к микшеру fifine SC3. Чтение; запись — только по белому списку (docs/WRITE.md).

  sc3 doctor              подключён ли SC3, есть ли права (udev), всё ли на месте — ничего не шлёт устройству
  sc3 status              сводка: сборка, микрофон, гейт, эффекты, EQ, усиления (~20 чтений ACP)
  sc3 dump [-o файл]      всё, что читается (~123 чтения): блоки, типы, имена и значения 54 узлов
  sc3 descriptor          только стандартный GET_DESCRIPTOR интерфейса 4
  sc3 listen [секунд]     что шлют кнопки: evdev (без захвата) + сырой hidraw + громкость PipeWire по умолчанию
  sc3 live                идёт ли эфир или запись в OBS (GetStreamStatus, GetRecordStatus) — к SC3 не обращается
  sc3 state               состояние для окна (JSON): эфир → разрешение на ACP → один набор чтений (8) + PipeWire
  sc3 install [--autostart] [--dry-run]   ярлык, значки (и автозапуск в трей) в ~/.local/share — без sudo; udev —
                          только проверка и команды для fish (install.py)
  sc3 uninstall [--dry-run]               убрать ровно поставленное (по манифесту ~/.local/share/opensc3/installed.json)

Запись (этап 3; по умолчанию — сухой прогон: план и кадры, к SC3 не обращается; отправка — только с --write):
  sc3 params              что можно писать: ключи белого списка, узлы, границы
  sc3 set <ключ> <знач.>  один параметр, например `sc3 set mic.trim 1`; --from дамп.json — «как было» из дампа
  sc3 profile show|diff|apply <имя>   профиль (podcast): значения / сравнение с SC3 или дампом / запись
  sc3 undo                вернуть исходные значения последнего сеанса записи (по журналу)

status, dump, descriptor, state, profile diff и запись идут к SC3 только вне эфира (OBS: OFF) и не чаще раза в 5 с
(отметка общая с окном) — иначе отказ до открытия USB, код 3 (state — JSON с acp_note). Обхода нет. Запись — ещё и
не чаще одного кадра за 0,5 с, с чтением назад и откатом (write.py).

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
SYSTEM_RULE = Path("/usr/lib/udev/rules.d/70-fifine-sc3.rules")  # так его ставит пакет (packaging/arch)
REPO_RULE = Path(__file__).resolve().parent.parent / "udev" / "70-fifine-sc3.rules"


def _usb_dev() -> Path | None:
    from .hotplug import usb_device
    return usb_device()


def _rules(p: Path) -> list[str]:
    """Действующие строки правила udev — без комментариев и пустых строк."""
    return [ln.strip() for ln in p.read_text().splitlines() if ln.strip() and not ln.lstrip().startswith("#")]


def _rule() -> Path | None:
    """Действующее правило udev: /etc перекрывает /usr/lib (пакет) с тем же именем."""
    return next((p for p in (RULE, SYSTEM_RULE) if p.exists()), None)


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
    rule = _rule()
    line(rule is not None, f"правило udev {rule or RULE}", f"sudo install -m 644 {REPO_RULE} /etc/udev/rules.d/")
    if rule is not None and REPO_RULE.exists():
        line(_rules(rule) == _rules(REPO_RULE), "правило совпадает с udev/ в репо (без комментариев)",
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


def _state_from(path: str | None) -> dict[int, list[int]] | None:
    """Снимок узлов из дампа `sc3 dump` (без обращения к SC3) или None."""
    if path is None:
        return None
    from .write import state_from_dump
    return state_from_dump(json.loads(Path(path).read_text(encoding="utf-8")))


def _show_plan(plan, state_known: bool) -> None:
    for line in plan.lines():
        print("  " + line)
    if not plan.writes:
        print("  писать нечего: всё уже так")
        return
    if state_known:
        print("откат («как было»), в обратном порядке:")
        for w in reversed(plan.writes):
            print("  " + w.undo().describe())
    else:
        print("исходные значения неизвестны: снимок узлов снимается перед записью, по нему же уточнится порядок "
              "(--from дамп.json — посмотреть заранее)")
    n = len(plan.writes)
    print(f"кадров записи: {n} — не чаще одного за 0,5 с, после каждого чтение назад (≈ {n * 0.5:.0f} с)")


def _write(plan, what: str, undoes: str | None = None) -> int:
    """Отправка: эфир (OBS) → AcpGuard → открыть SC3 → write.apply (verify, типы узлов, снимок, по кадру раз в 0,5 с,
    чтение назад, откат при расхождении, журнал). Отказ — до открытия USB. Перед каждым кадром apply спрашивает
    OBS заново (`live_status`), а не верит ответу, полученному здесь."""
    from . import write as W
    from .guard import AcpGuard, default_stamp
    from .obs import live_status
    live, _since = live_status()
    guard = AcpGuard(stamp=default_stamp())
    note = guard.check(live)
    if note:
        raise Refused(note)
    journal = W.Journal(W.default_journal(), what=what, undoes=undoes)
    try:
        with _open() as s:
            res = W.apply(s, plan, live=lambda: live_status()[0], guard=guard, journal=journal)
    except W.WriteRefused as e:
        for d in e.done:
            print(f"  записано до отказа: {d.write.describe()}")
        if e.done:
            print("вернуть после эфира: sc3 undo --write")
        raise Refused(str(e)) from None
    for d in res.done:
        print(f"✓ {d.write.describe()}" + ("" if d.ack else "   (без подтверждения; чтение назад сошлось)"))
    for w in res.skipped:
        print(f"• {w.param.key}: пропуск — сейчас {w.param.fmt(w.before)}, сеанс оставил {w.param.fmt(w.expect)}; "
              "не трогаю")
    if not res.done and not res.skipped:
        print("писать было нечего: всё уже так")
    if res.done:
        print(f"записано кадров: {len(res.done)}; журнал: {journal.path}" +
              (f" — НЕ ДОПИСАН ({journal.broken}): исходные значения — в строках выше" if journal.broken else ""))
        print("снова применить отменённое: sc3 undo --write" if undoes else "вернуть как было: sc3 undo --write",
              end="; полный сброс — выдернуть USB (вне эфира)\n")
    return 0


def cmd_params(_a) -> int:
    from .write import PARAMS, human
    for p in PARAMS:
        if p.key.startswith("eq.") and p.key.split(".")[1] != "1":
            continue
        lo, hi = human(p.unit, p.lo), human(p.unit, p.hi)
        print(f"{p.key:<14} {p.addr:#04x}[{p.idx:>2}]  {lo} … {hi:<14} {p.text}")
    print("eq.N.* — фильтры N = 1…10 (показан первый). Включённый фильтр — всегда с частотой 20…20000 Гц и Q 0,3…8")
    return 0


def cmd_set(a) -> int:
    from .write import plan_write
    state = _state_from(a.source)
    plan = plan_write([(a.key, a.value)], state)
    if a.write:
        return _write(plan, f"set {a.key} {a.value}")
    print("сухой прогон — к SC3 не обращаюсь (отправить: --write)")
    _show_plan(plan, state is not None)
    return 0


def cmd_profile(a) -> int:
    from .profiles import PROFILES, diff, lines
    from .write import plan_write
    prof = PROFILES.get(a.name)
    if prof is None:
        print(f"✗ профиля «{a.name}» нет; есть: {', '.join(PROFILES)}", file=sys.stderr)
        return 1
    if a.action == "show":
        print(f"{prof.title} ({prof.name}){' — черновик' if prof.draft else ''}:")
        for line in lines(prof):
            print("  " + line)
        for n in prof.notes:
            print("• " + n)
        return 0
    state = _state_from(a.source)
    if a.action == "diff":
        if state is None:  # только чтение: те же эфир и AcpGuard, что у status
            from .write import snapshot, target
            with _acp() as s:
                s.verify()
                state = snapshot(s, {target(k, v).param.addr for k, v in prof.items})
        rows = diff(prof, state)
        for r in rows:
            print(f"  {'=' if r.same else '≠'} {r.key:<14} сейчас {r.now:<14} в профиле {r.target}")
        print(f"отличается: {sum(not r.same for r in rows)} из {len(rows)}")
        return 0
    plan = plan_write(prof.items, state)
    if a.write:
        return _write(plan, f"profile {prof.name}")
    print(f"сухой прогон профиля «{prof.title}» — к SC3 не обращаюсь (отправить: --write)")
    _show_plan(plan, state is not None)
    return 0


def cmd_undo(a) -> int:
    from .write import default_journal, last_session, plan_write, undo_writes
    rows = last_session(default_journal())
    writes = undo_writes(rows)
    if not writes:
        print("возвращать нечего: журнал пуст или последний сеанс ничего не изменил")
        return 0
    plan = plan_write(writes)
    session = rows[0]["session"]
    if a.write:
        return _write(plan, f"undo {session}", undoes=session)
    print(f"сухой прогон отката сеанса {session} ({rows[0].get('what') or '?'}) — к SC3 не обращаюсь "
          "(отправить: --write)")
    for w in plan.writes:
        print(f"  {w.param.key:<14} → {w.param.fmt(w.value)} (если сейчас {w.param.fmt(w.expect)})   {w.hex()}")
    return 0


def _udev_check() -> None:
    """Правило udev ставит владелец (sudo): `sc3 install` его только проверяет и печатает команды для fish."""
    import shlex
    rule = _rule()
    if rule is not None and (not REPO_RULE.exists() or _rules(rule) == _rules(REPO_RULE)):
        print(f"✓ правило udev {rule}")
        return
    state = f"{rule} отличается от udev/ в репо" if rule else "не стоит"
    print(f"✗ правило udev {state} — его ставит владелец (sudo), команды для fish:")
    if REPO_RULE.exists():
        print(f"    sudo install -m 644 {shlex.quote(str(REPO_RULE))} /etc/udev/rules.d/")
    print("    sudo udevadm control --reload")
    print("    sudo udevadm trigger --action=change --attr-match=idVendor=3142 --attr-match=idProduct=0c33")


def _not_root() -> bool:
    if os.geteuid() == 0:
        print("✗ не под sudo: ставится в домашний каталог пользователя (~/.local, ~/.config)", file=sys.stderr)
        return False
    return True


def cmd_install(a) -> int:
    from . import install as I
    if not _not_root():
        return 1
    try:
        rc = I.install(I.plan(autostart=a.autostart), dry_run=a.dry_run)
    except I.InstallError as e:
        print(f"✗ {e}", file=sys.stderr)
        return 1
    system = Path("/usr/share/applications/opensc3.desktop")
    if rc == 0 and system.exists():
        print(f"• есть и системный {system} (пакет): ярлык из ~/.local перекрывает его")
    _udev_check()
    return rc


def cmd_uninstall(a) -> int:
    from . import install as I
    if not _not_root():
        return 1
    try:
        return I.uninstall(I.manifest_path(), dry_run=a.dry_run)
    except I.InstallError as e:
        print(f"✗ {e}", file=sys.stderr)
        return 1


def _send_flags(p) -> None:
    g = p.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true", help="только план и кадры (по умолчанию)")
    g.add_argument("--write", action="store_true", help="отправить в SC3 (вне эфира)")


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
    sub.add_parser("params").set_defaults(fn=cmd_params)
    st = sub.add_parser("set")
    st.add_argument("key")
    st.add_argument("value")
    st.add_argument("--from", dest="source", metavar="ДАМП")
    _send_flags(st)
    st.set_defaults(fn=cmd_set)
    pr = sub.add_parser("profile")
    pr.add_argument("action", choices=("show", "diff", "apply"))
    pr.add_argument("name")
    pr.add_argument("--from", dest="source", metavar="ДАМП")
    _send_flags(pr)
    pr.set_defaults(fn=cmd_profile)
    un = sub.add_parser("undo")
    _send_flags(un)
    un.set_defaults(fn=cmd_undo)
    ins = sub.add_parser("install", help="ярлык, значки, автозапуск — для пользователя, без sudo")
    ins.add_argument("--autostart", action="store_true", help="ещё и автозапуск в трей (~/.config/autostart)")
    ins.add_argument("--dry-run", action="store_true", help="только список: что и куда, ничего не пишет")
    ins.set_defaults(fn=cmd_install)
    uni = sub.add_parser("uninstall", help="убрать поставленное `sc3 install` (по манифесту)")
    uni.add_argument("--dry-run", action="store_true", help="только список, ничего не удаляет")
    uni.set_defaults(fn=cmd_uninstall)
    a = ap.parse_args(argv)
    if getattr(a, "write", False) and getattr(a, "source", None):
        ap.error("--from — только для сухого прогона: перед записью снимок снимается с самого SC3")
    try:
        return a.fn(a)
    except Refused as e:
        print(f"✗ к SC3 не обращаюсь: {e}", file=sys.stderr)
        return 3
    except P.ProtocolError as e:
        print(f"✗ {e}", file=sys.stderr)
        return 1
