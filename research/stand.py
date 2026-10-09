"""Стенд опроса SC3 (этап 2, docs/PLAN.md): выдержит ли SC3 чтение 0x07 раз в 0,5 с 15 минут без вреда звуку.

Только чтение и только вне эфира. Один `Sc3.open()` на прогон (как держала бы служба), `verify()`, затем лишь `0x07`
(ADC1: mute и цифровая громкость ≈ ползунок Mic) по расписанию от монотонных часов: опоздали — слот пропускается,
догоняющих пачек нет. Весь прогон рядом идёт `pw-top -b` (ERR = xrun узлов SC3, формат, квант); раз в 30 с — журнал
ядра и строка прогресса. Звук нигде не пишется.

Аварийная остановка (SC3 закрывается сразу, код 2): 3 неудачи чтения подряд; SC3 пропал с шины (sysfs, каждый слот);
OBS не OFF (раз в 10 с; UNKNOWN — тоже стоп). Ctrl+C — чистое закрытие, код 130; отказ до старта — код 3. Итог —
таблица и `dumps/stand-<дата-время>.json` (dumps/ вне git). «Зелёный» (код 0): 0 неудач, 0 новых строк ядра про
USB/SC3, 0 новых xrun у узлов SC3; иначе код 1.

  python3 -I -B research/stand.py                         # настоящий SC3, 900 с: вне эфира, вместе с владельцем
  python3 -I -B research/stand.py --fake [--fault fail]   # логика без устройства, время виртуальное
"""
from __future__ import annotations

import argparse
import json
import math
import random
import re
import statistics
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # `-I` не кладёт в путь ни каталог скрипта, ни текущий: пакет — из этого репо

from opensc3 import hotplug, obs, pipewire
from opensc3 import layouts as L
from opensc3 import protocol as P
from opensc3.device import Sc3
from opensc3.guard import MIN_INTERVAL_FLOOR
from opensc3.model import Link, Live

ADC1, MAX_FAILS, LIVE_EVERY, REPORT_EVERY = 0x07, 3, 10.0, 30.0
FAULTS = ("none", "fail", "unplug", "live", "xrun", "kernel")


def num(x: float, d: int = 1) -> str:
    return f"{x:.{d}f}".replace(".", ",")


def stats(xs: list[float]) -> dict:
    """Секунды → мс: min/med/p99/max; пусто — {}."""
    if not xs:
        return {}
    s = sorted(1000 * x for x in xs)
    p99 = s[min(len(s) - 1, math.ceil(0.99 * len(s)) - 1)]
    return {k: round(v, 2) for k, v in (("min", s[0]), ("med", statistics.median(s)), ("p99", p99), ("max", s[-1]))}


class Counted:
    """Обёртка транспорта: считает посылки SET_REPORT (повторы чтения = посылок − 1). Кадры не строит и не меняет."""

    def __init__(self, t):
        self.t, self.sends = t, 0

    def set_output(self, frame: bytes) -> None:
        self.sends += 1
        self.t.set_output(frame)

    def __getattr__(self, name):
        return getattr(self.t, name)


class PwTop:
    """Строки `pw-top -b` → узлы SC3 по имени: {state, quant, rate, err, format, measured}. Первые итерации pw-top —
    без замеров (квант 0, «???», ≈ 4 с), поэтому «до» (`base`) у каждого узла своё — его первый замер в работе.
    Узел, ни разу не работавший (выход SC3 спит, пока в наушники ничего не играет), в `base` не попадает: его xrun
    не видны. `done` — последняя полная итерация, `grow` — наибольший рост ERR от «до»."""

    def __init__(self, names):
        self.names, self.lock, self.proc = {n for n in names if n}, threading.Lock(), None
        self.iters, self.cur, self.done, self.base, self.grow = 0, {}, {}, {}, {}

    def feed(self, line: str) -> None:
        p = line.split()
        if len(p) > 1 and p[1] == "ID":  # заголовок: началась новая итерация, прошлая полна (первая — пустая)
            with self.lock:
                if self.iters >= 2:
                    self.done = self.cur
                    for n, v in self.cur.items():
                        if v["measured"]:
                            self.base.setdefault(n, v)
                    for n, v in self.base.items():
                        self.grow[n] = max(self.grow.get(n, 0), self.cur.get(n, v)["err"] - v["err"])
                self.iters, self.cur = self.iters + 1, {}
        elif len(p) >= 10 and p[-1] in self.names and p[8].isdigit():
            rest = p[9:-1]  # формат («S16LE 2 48000», у спящего пусто) и «+» у ведомого узла
            self.cur[p[-1]] = {"state": p[0], "quant": int(p[2]), "rate": int(p[3]), "err": int(p[8]),
                               "format": " ".join(x for x in rest if x != "+"),
                               "measured": p[0] == "R" and p[6] not in ("???", "---")}  # W/Q: есть замер

    def ready(self) -> bool:
        """У каждого работающего узла SC3 уже есть «до»."""
        with self.lock:
            return bool(self.done) and all(n in self.base for n, v in self.done.items() if v["state"] == "R")

    def snap(self) -> tuple[dict, dict, dict]:
        with self.lock:
            return dict(self.base), dict(self.done), dict(self.grow)

    def spawn(self) -> None:
        """Настоящий `pw-top -b` в своём потоке до stop(). Нет pw-top — xrun останутся не проверены."""
        try:
            self.proc = subprocess.Popen(["pw-top", "-b"], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                         stderr=subprocess.DEVNULL, text=True, errors="replace")
        except OSError:
            return
        out = self.proc.stdout
        threading.Thread(target=lambda: [self.feed(ln) for ln in out], name="pw-top", daemon=True).start()

    def stop(self) -> None:
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()


def journal(after: str | None) -> tuple[list[str], str | None]:
    """Новые строки журнала ядра после курсора и новый курсор; after=None — только курсор «сейчас»."""
    cmd = ["journalctl", "-k", "-q", "--no-pager", "-o", "short-iso", "--show-cursor"]
    try:
        r = subprocess.run(cmd + ([f"--after-cursor={after}"] if after else ["-n", "0"]), capture_output=True,
                           text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return [], after
    lines = [ln for ln in r.stdout.splitlines() if ln.strip() and not ln.startswith("-- cursor: ")]
    cur = [ln.removeprefix("-- cursor: ").strip() for ln in r.stdout.splitlines() if ln.startswith("-- cursor: ")]
    return lines, (cur[-1] if cur else after)


class Real:
    """Настоящие SC3, OBS, sysfs, PipeWire, журнал ядра. OBS и PipeWire — только чтение."""
    clock, sleep, kernel = time.monotonic, time.sleep, staticmethod(journal)
    open, nodes = staticmethod(Sc3.open), staticmethod(pipewire.find_sc3)
    live = staticmethod(lambda: obs.live_status()[0])  # GetStreamStatus + GetRecordStatus
    probe = staticmethod(lambda: hotplug.probe()[0])   # только sysfs и права, к устройству не обращается
    usb = staticmethod(lambda: getattr(hotplug.usb_device(), "name", "?"))

    def watch(self, top: PwTop) -> None:
        top.spawn()


class Fake(Real):
    """tests/fake.py вместо SC3 + подделки OBS, sysfs, pw-dump, pw-top, journalctl. Часы виртуальные: sleep их
    двигает, чтение «длится» 10–16 мс, раз в секунду — итерация pw-top. Сбой `fault` — с середины прогона."""
    NAMES = ("alsa_input.fake-sc3", "alsa_output.fake-sc3")
    TOP = ("S   ID  QUANT   RATE    WAIT    BUSY   W/Q   B/Q  ERR FORMAT           NAME",
           "R   56   {q}  {r} 145.2us   2.0us  {wq}  {wq}  {err}    S16LE 2 48000 alsa_input.fake-sc3",
           "R   38      0      0  12.0us   3.1us  {wq}  {wq}    0  + S16LE 2 48000 alsa_output.fake-sc3")
    KERNEL = ("2026-10-08T21:00:00+05:00 s1dPC kernel: audit: type=1400 apparmor=\"DENIED\" (не про USB)",
              "2026-10-08T21:00:00+05:00 s1dPC kernel: usb 3-13: reset full-speed USB device number 7 using xhci_hcd")

    def __init__(self, fault: str, seconds: float):
        self.now, self.tick, self.top, self.fault, self.at = 0.0, 0, None, fault, seconds / 2
        self.rnd = random.Random(1)
        self.live = lambda: Live.ON if self.broke("live") else Live.OFF
        self.probe = lambda: Link.DISCONNECTED if self.broke("unplug") else Link.CONNECTED
        self.nodes = lambda: pipewire.Sc3Nodes(56, self.NAMES[0], 38, self.NAMES[1])
        self.usb = lambda: "3-13"

    def clock(self) -> float:
        return self.now

    def broke(self, kind: str) -> bool:
        return self.fault == kind and self.now >= self.at

    def sleep(self, dt: float) -> None:
        end = self.now + max(dt, 0.0)
        while self.top and self.tick + 1 <= end:
            self.tick += 1
            m = self.tick > 3  # первые итерации, как у настоящего pw-top, — без замера: квант 0, W/Q «???»
            for ln in self.TOP:
                self.top.feed(ln.format(q=1024 * m, r=48000 * m, wq="0.01" if m else "???", err=int(self.broke("xrun"))))
        self.now = end

    def watch(self, top: PwTop) -> None:
        self.top = top

    def kernel(self, after):
        return (list(self.KERNEL), "k1") if self.broke("kernel") and after != "k1" else ([], after or "k0")

    def open(self) -> Sc3:
        from tests.fake import FakeTransport
        env = self

        class T(FakeTransport):
            def set_output(t, frame):
                vol, mute = 132 * (31 - int(env.now // 60) % 3), int(env.now // 150) % 2  # «владелец двигает Mic»
                t.blocks[ADC1] = b"\xff" + struct.pack("<10H", 3, mute, vol, vol, 7, 0, 0, 0, 0, 1)
                super().set_output(frame)

            def get_input(t):
                env.now += env.rnd.uniform(0.010, 0.016)  # пауза Sc3.DELAY + обмен (настоящей паузы в фейке нет)
                if env.broke("fail"):
                    env.now += 0.25
                    raise P.ProtocolError("control 0xa1/0x01: LIBUSB_ERROR_TIMEOUT")
                return super().get_input()

        sc3 = Sc3(T())
        sc3.DELAY = 0.0
        return sc3


def run(env: Real, seconds: float, interval: float, out: Path, tag: str = "") -> int:
    if not interval >= MIN_INTERVAL_FLOOR:  # `not >=` ловит и NaN
        raise ValueError(f"интервал {interval} с < {MIN_INTERVAL_FLOOR} с: так часто SC3 опрашивать нельзя")
    if not seconds > 0:
        raise ValueError(f"длительность {seconds} с — нужна > 0")
    live, link = env.live(), env.probe()
    if live is not Live.OFF or link is not Link.CONNECTED:
        print(f"✗ отказ до старта: OBS {live.value}, SC3 {link.value} — нужно off и connected")
        return 3
    started, nodes, usb = time.strftime("%Y-%m-%d %H:%M:%S"), env.nodes(), env.usb()
    usb_re = re.compile(rf"(?i)\b{re.escape(usb)}\b|3142|sc3|xhci|urb|usbfs|snd.usb")
    top = PwTop((nodes.source_name, nodes.sink_name) if nodes else ())
    sc3, reason, code, cursor, k_ok, prev, el = None, "", 2, None, False, None, 0.0
    lat, changes, kall, notes = [], [], [], []
    ok = fail = row = retries = missed = 0
    env.watch(top)
    try:
        _, cursor = env.kernel(None)  # курсор «сейчас»: дальше — только новые строки
        k_ok = cursor is not None
        for _ in range(50):  # замеры pw-top для «до» приходят не сразу (≈ 4–5 с)
            if top.ready():
                break
            env.sleep(0.2)
        print(f"{tag}стенд: 0x07 раз в {num(interval)} с, {num(seconds, 0)} с; SC3 {usb}; OBS off; Ctrl+C — стоп")
        base, now_ = top.snap()[:2]
        for n in sorted(top.names):
            v = base.get(n) or now_.get(n) or {"state": "нет в pw-top"}
            print(f"  до: {n}: {v['state']}" + (f", квант {v['quant']}/{v['rate']}, {v['format']}, ERR {v['err']}"
                                                if n in base else " — xrun не видны (в наушники ничего не играет?)"))
        if (live := env.live()) is not Live.OFF:  # правило 3 — ещё раз прямо перед открытием (pw-top ждали до 10 с)
            raise P.ProtocolError(f"OBS {live.value} — SC3 не открыт")
        sc3 = env.open()
        t = sc3.t = Counted(sc3.t)
        sc3.verify()
        t0 = env.clock()
        k, next_live, next_rep = 0, t0 + LIVE_EVERY, t0 + REPORT_EVERY
        while k * interval < seconds:
            env.sleep(max(0.0, t0 + k * interval - env.clock()))
            if env.probe() is not Link.CONNECTED:
                reason = "SC3 пропал с шины"
                break
            n0, a = t.sends, env.clock()
            try:
                body = sc3.read(ADC1)
            except P.ProtocolError:  # транспорт порвался (SET_REPORT); молчание — это None из Sc3
                body = None
            lat.append(env.clock() - a)
            retries, el = retries + max(t.sends - n0 - 1, 0), env.clock() - t0
            if body is None:
                fail, row = fail + 1, row + 1
                if row >= MAX_FAILS:
                    reason = f"{MAX_FAILS} неудачи чтения подряд"
                    break
            else:
                ok, row, adc = ok + 1, 0, L.adc(body)
                if (adc["mute"], adc["vol_l"]) != prev:
                    prev = (adc["mute"], adc["vol_l"])
                    changes.append([round(el, 1), *prev])
            if env.clock() >= next_live:
                next_live += LIVE_EVERY
                if (live := env.live()) is not Live.OFF:
                    reason = f"OBS: {live.value} — эфир, запись или статус неизвестен"
                    break
            if env.clock() >= next_rep:
                next_rep += REPORT_EVERY
                new, cursor = env.kernel(cursor)
                kall += new
                for ln in filter(usb_re.search, new):
                    print(f"  ⚠ ядро: {ln}")
                s, g = stats(lat), top.snap()[2]
                mic = f"mute {'вкл.' if prev[0] else 'выкл.'}, громкость {prev[1]}" if prev else "—"
                print(f"{int(el) // 60:2d}:{int(el) % 60:02d}  ok {ok}  неудач {fail}  повторов {retries}  задержка "
                      f"мед {num(s['med'])} / p99 {num(s['p99'])} / макс {num(s['max'])} мс  Mic: {mic}  ядро USB/SC3 "
                      f"+{sum(1 for x in kall if usb_re.search(x))}  xrun SC3 +{sum(g.values()) if g else '?'}",
                      flush=True)
            nk = max(k + 1, math.ceil((env.clock() - t0) / interval))  # опоздали — пропуск слотов, а не пачка
            missed, k = missed + nk - k - 1, nk
        else:
            code = 0
    except KeyboardInterrupt:
        reason, code = "прервано (Ctrl+C)", 130
    except P.ProtocolError as e:
        reason = f"до опроса (OBS, открытие, verify): {e}"
    finally:
        if sc3 is not None:
            sc3.close()
        print(f"{tag}SC3 {'закрыт' if sc3 else 'не открывался'}" + (f" — {reason}" if reason else ""))
        try:
            env.sleep(1.5)  # устройство уже закрыто: журнал и pw-top дописывают последнее
            kall += env.kernel(cursor)[0] if k_ok else []
        except KeyboardInterrupt:
            pass
        top.stop()
    base, after, grow = top.snap()
    kflag = [x for x in kall if usb_re.search(x)]
    for n in sorted(top.names - base.keys()):
        notes.append(f"{n}: ни разу не работал под pw-top — его xrun не проверены (включи звук в наушники)")
    for n, v in base.items():
        w = after.get(n)
        if w and w["measured"] and (v["quant"], v["format"]) != (w["quant"], w["format"]):
            notes.append(f"{n}: квант/формат {v['quant']} {v['format']!r} → {w['quant']} {w['format']!r}")
    if ok and len(changes) <= 1:
        notes.append("0x07 ни разу не менялся: свежесть ответов не доказана (ответ SC3 может быть кэшем) — "
                     "подвигай ползунок Mic или нажми Mute MIC во время прогона")
    why = [f"остановлен: {reason}"] if reason else []
    why += [f"неудач {fail}"] if fail else []
    why += ["журнал ядра не прочитан"] if not k_ok else [f"строк ядра про USB/SC3: {len(kflag)}"] if kflag else []
    why += ["xrun SC3 не проверены (нет pw-top или узлов SC3)"] if not grow else []
    why += [f"xrun SC3: {grow}"] if any(grow.values()) else []
    res = {"started": started, "fake": bool(tag), "seconds": seconds, "interval": interval, "elapsed": round(el, 1),
           "stopped": reason or "по времени", "reads": ok + fail, "ok": ok, "fail": fail, "retries": retries,
           "missed_slots": missed, "latency_ms": stats(lat), "adc1_changes": changes,
           "pipewire": {"before": base, "after": after, "xrun_growth": grow},
           "kernel": {"checked": k_ok, "new": kall, "usb_sc3": kflag}, "green": not why, "why_not": why, "notes": notes}
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"stand-{'fake-' if tag else ''}{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    summary(res, path, tag)
    return code if code else (0 if not why else 1)


def summary(r: dict, path: Path, tag: str) -> None:
    ch = " → ".join(f"{int(c[0]) // 60}:{int(c[0]) % 60:02d} {'mute' if c[1] else 'звук'}/{c[2]}"
                    for c in r["adc1_changes"][:8]) + (" …" if len(r["adc1_changes"]) > 8 else "")
    k = r["kernel"]
    print(f"\n{tag}итог {r['started']}: {num(r['elapsed'], 0)} из {num(r['seconds'], 0)} с, раз в {num(r['interval'])} с "
          f"— {r['stopped']}\n"
          f"  чтений {r['reads']}: ok {r['ok']}, неудач {r['fail']}, повторов {r['retries']}, "
          f"пропущено слотов {r['missed_slots']}\n"
          f"  задержка, мс: " + "  ".join(f"{n} {num(v, 2)}" for n, v in r["latency_ms"].items()) + "\n"
          f"  0x07 (mute/громкость), смен {len(r['adc1_changes'])}: {ch}\n"
          f"  xrun SC3 (рост ERR в pw-top): {r['pipewire']['xrun_growth'] or 'не проверены'}\n"
          f"  ядро: новых строк {len(k['new'])}, про USB/SC3 {len(k['usb_sc3'])}"
          + ("" if k["checked"] else " (журнал не прочитан)"))
    for n in r["notes"]:
        print(f"  ! {n}")
    print(("ЗЕЛЁНЫЙ" if r["green"] else "НЕ ЗЕЛЁНЫЙ: " + "; ".join(r["why_not"])) + f"\n  {path}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Стенд опроса SC3: только 0x07 по расписанию, pw-top, журнал ядра.")
    ap.add_argument("--seconds", type=float, default=900.0, help="длительность, с (900)")
    ap.add_argument("--interval", type=float, default=0.5, help=f"интервал, с; не меньше {MIN_INTERVAL_FLOOR}")
    ap.add_argument("--fake", action="store_true", help="без устройства: tests/fake.py, подделки, виртуальное время")
    ap.add_argument("--fault", choices=FAULTS, default="none", help="только с --fake: сбой с середины прогона")
    ap.add_argument("--out", type=Path, default=ROOT / "dumps", help="каталог для JSON (dumps/ вне git)")
    a = ap.parse_args()
    if a.fault != "none" and not a.fake:
        ap.error("--fault — только вместе с --fake")
    env = Fake(a.fault, a.seconds) if a.fake else Real()
    return run(env, a.seconds, a.interval, a.out, tag="[фейк] " if a.fake else "")


if __name__ == "__main__":
    sys.exit(main())
