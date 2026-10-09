"""Бэкенд окна: один `AppState`, его свойства для QML и рабочие потоки ядра.

Потоки (ни одного ввода-вывода в потоке интерфейса):
- главный — только состояние, свойства и сигналы;
- «sc3-control» — SC3 и OBS: hotplug (QSocketNotifier на `hotplug.Watcher`), статус эфира раз в 3 с, чтения ACP.
  Все решения гварда — здесь же, в одном потоке с чтением (CLAUDE.md, правила 3 и 4);
- «sc3-audio» — PipeWire: узлы SC3, mute источника, уровни ~25 Гц (это PipeWire, SC3 не опрашивается).

Как читается SC3 (решение 9, `guard.CONTINUOUS_POLLING`):
- **окно видно и эфир OFF** — лёгкий опрос: SC3 открыт один раз на весь опрос, перед открытием — свежий
  `live_status()`; дальше ровно одно чтение раз в 0,5 с по сетке монотонных часов (`poll.py`: сначала полный
  набор по одному чтению на слот, затем круг 07/07/07/B6), каждое — через `AcpGuard.check_poll()`. Стоп и
  закрытие: окно скрыто, эфир не OFF (статус — раз в 3 с), SC3 пропал, 3 неудачи подряд (тогда — до
  переподключения). «Обновить» не добавляет чтений: узлы голосов и ELECTRIC занимают ближайшие слоты;
- **окно скрыто** — полный набор `read_state` по событию (старт, переподключение), не чаще раза в 5 с.
Причина, по которой SC3 сейчас не читается, — `AppState.acp_note` (видна в шапке).

Запись (решения 4 и 9, docs/WRITE.md): ручка-поправка MIC (`mic.trim`), профиль «Подкаст» и «Вернуть как было»
(как `sc3 undo`) из меню профиля — только в идущем опросе, в том же потоке и той же сессии SC3. Просьба ждёт
ближайшего слота (значения ручки сливаются — пишется последнее; после смены пресета кнопкой — сперва перечитать
узлы), и слот вместо чтения отдаётся `write.apply` — из ОДНОГО места окна, `ControlWorker._apply_plan` (сторож:
tests/test_safety.py). Внутри сеанса каждое обращение к SC3 — типы узлов, снимок, кадр, чтение назад — занимает свой
слот 0,5 с (`Sc3.pace`), перед сеансом и перед кадром OBS спрашивается заново. «Стоп» — стоп и откат записанного
в этом сеансе; эфир посреди сеанса — стоп без отката, как в CLI. Журнал — общий с CLI `writes.jsonl`.
Предохранитель «Разрешить запись в SC3» (меню-шестерёнка) по умолчанию выключен и хранится в настройках окна.

Подпись профиля в шапке — `poll.profile_label`: «Подкаст», «заводской» (пресет панели: как после подключения или
нажатия кнопки) или «свой» (с тех пор записывали); чей набор был в SC3 при подключении — по журналу записи.
"""
from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import replace

from PySide6.QtCore import (
    Property,
    QMetaObject,
    QObject,
    QSocketNotifier,
    Qt,
    QThread,
    QTimer,
    Signal,
    Slot,
)

from opensc3 import reader as R
from opensc3 import write as W
from opensc3.model import AppState, AudioState, Link, Live, Sc3State
from opensc3.write import TRIM_DB

from . import poll, view
from .core import WRITE_KEY, Core, OpenFailed

log = logging.getLogger("opensc3.app")

LIVE_INTERVAL = 3.0     # статус эфира из OBS
PROBE_FALLBACK = 3.0    # если hotplug.Watcher не завёлся: проверка присутствия (sysfs, не USB) раз в 3 с
AUDIO_INTERVAL = 2.0    # mute источника и поиск узлов SC3 в PipeWire
METER_HZ = 25           # полоса 9 + 9
NOTE_HOLD_MS = 5000     # сколько видна разовая причина отказа («рано: …»)

# Поводы для набора чтений. Отказ гварда показывается только на просьбу пользователя и из-за эфира:
# автоматические поводы сливаются (старт + показ окна + подключение — один набор).
WHY_START, WHY_CONNECT, WHY_SHOW, WHY_USER = "start", "connect", "show", "user"

WRITE_OFF = "Запись в SC3 выключена — включите в настройках"
TRIM_WHAT = "window mic.trim"   # `what` в журнале записи: так `sc3 undo` называет сеанс окна
PODCAST, UNDO, FACTORY = "podcast", "undo", "factory"   # действия меню профиля
JOB_TITLE = {PODCAST: "Подкаст", UNDO: "Возврат"}


class WriteStopped(Exception):
    """«Стоп» из окна посреди сеанса записи: `write.apply` откатывает записанное и отдаёт это исключение дальше."""


class ProgressJournal(W.Journal):
    """Журнал записи (тот же `writes.jsonl`), который ещё и сообщает о каждом кадре: прогресс в шапке и прочитанное
    назад значение (ящик MIC меняется по ходу записи, а не только после неё)."""

    def __init__(self, path, *, what: str, undoes: str | None, step) -> None:
        super().__init__(path, what=what, undoes=undoes)
        self.step = step

    def add(self, op, w, ack, back):
        e = super().add(op, w, ack, back)
        self.step(op, sum(1 for x in self.entries if x.get("op") == op),
                  sum(1 for x in self.entries if x.get("op") == "write"), w.param, back)
        return e


class ControlWorker(QObject):
    """Поток «sc3-control»: всё, что трогает SC3 (ACP) или спрашивает OBS."""

    probed = Signal(object, object)       # Link, подробность (str | None)
    liveSeen = Signal(object, object, str)  # Live, начало эфира или None, причина гварда для этого эфира
    readStarted = Signal()
    readDone = Signal(object, str)        # Sc3State, что пошло не так («» — ничего)
    readRefused = Signal(str, str)        # причина, повод
    polled = Signal(object)               # dict: поля Sc3State из очередного чтения опроса (poll.merge)
    pollChanged = Signal(bool, str)       # опрос идёт?, почему нет («» — без замечаний)
    trimDone = Signal(float, object, str)  # просили (дБ), прочитано назад (дБ | None), что не так («» — ничего)
    jobDone = Signal(str, str, bool)      # профиль/возврат: заголовок, итог для шапки, удалось ли
    writeProgress = Signal(str, int, int)  # заголовок («Подкаст», «Подкаст — откат»), сделано, всего (0 — неизвестно)

    def __init__(self, core: Core, live_interval: float, full_set_first: bool = True,
                 write_enabled: bool = False) -> None:
        super().__init__()
        self._core = core
        self._live_interval = live_interval
        self._full_set_first = full_set_first
        self._guard = None
        self._watcher = None
        self._notifier: QSocketNotifier | None = None
        self._timers: list[QTimer] = []
        self._link = Link.DISCONNECTED
        self._live = Live.UNKNOWN
        # лёгкий опрос (решение 9)
        self._visible = False
        self._session = None
        self._plan: poll.Plan | None = None
        self._slot_timer: QTimer | None = None
        self._t0 = self._at = self._last = 0.0
        self._k = 0
        self._fails = 0
        self._blocked = ""   # почему опрос выключен до переподключения SC3
        # запись из окна: ручка-поправка MIC
        self._write_enabled = write_enabled
        self._trim_want: float | None = None   # последнее значение ручки, ждёт слота (значения сливаются)
        self._trim_since = -math.inf            # просьбы до этой неудачи — мимо: ручка уже вернулась к прочитанному
        self._job: str | None = None             # профиль или возврат из меню, ждёт слота
        self._stop = threading.Event()           # «Стоп» из окна: ставится из потока интерфейса (request_stop)
        self._stopping = False                   # этот сеанс уже останавливается — откат не прерывать

    def _every(self, seconds: float, slot) -> None:
        t = QTimer(self)
        t.setInterval(int(seconds * 1000))
        t.timeout.connect(slot)
        t.start()
        self._timers.append(t)

    @Slot()
    def init(self) -> None:
        self._guard = self._core.guard()
        self._slot_timer = QTimer(self)
        self._slot_timer.setSingleShot(True)
        self._slot_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._slot_timer.timeout.connect(self._slot)
        try:
            self._watcher = self._core.watcher()
            self._notifier = QSocketNotifier(self._watcher.fileno(), QSocketNotifier.Type.Read, self)
            self._notifier.activated.connect(self._on_hotplug)
        except Exception as e:  # noqa: BLE001 — без udev-событий окно живёт, просто узнаёт о SC3 медленнее
            log.warning("hotplug: %s — проверяю присутствие SC3 раз в %g с", e, PROBE_FALLBACK)
            self._every(PROBE_FALLBACK, self._probe)
        self._probe()
        self._every(self._live_interval, self._poll_live)
        self._poll_live()

    @Slot()
    def shutdown(self) -> None:
        self._stop_poll("")
        for t in self._timers:
            t.stop()
        if self._notifier is not None:
            self._notifier.setEnabled(False)
        close = getattr(self._watcher, "close", None)
        if close is not None:
            close()

    def _on_hotplug(self, *_args) -> None:
        try:
            changed = self._watcher.poll()
        except Exception as e:  # noqa: BLE001
            log.warning("hotplug: %s", e)
            changed = True
        if changed:
            self._probe()

    def _probe(self) -> None:
        try:
            link, detail = self._core.probe()
        except Exception as e:  # noqa: BLE001
            link, detail = Link.ERROR, f"проверка присутствия SC3: {e}"
        self._link = link
        if link is not Link.CONNECTED:
            self._blocked = ""  # «до переподключения»: SC3 пропал — следующее подключение снова можно опрашивать
        self.probed.emit(link, detail)
        self._update_poll()

    def _live_status(self) -> tuple[Live, float | None]:
        """Свежий статус эфира из OBS (ошибка — UNKNOWN, то есть как в эфире); его видит и интерфейс."""
        try:
            live, since = self._core.live_status()
        except Exception as e:  # noqa: BLE001 — не знаем, значит как в эфире
            log.warning("OBS: %s", e)
            live, since = Live.UNKNOWN, None
        self._live = live
        # Для ON/UNKNOWN check() отвечает сразу, не глядя на отметку времени.
        self.liveSeen.emit(live, since, "" if live is Live.OFF else self._guard.check(live))
        return live, since

    def _poll_live(self) -> None:
        self._live_status()
        self._update_poll()

    @Slot(str)
    def read(self, why: str) -> None:
        """Полный набор чтений по событию (окно скрыто или постоянного опроса нет)."""
        if self._session is not None:  # SC3 и так опрашивается: набор пачкой не нужен
            self.readRefused.emit("", why)
            return
        if self._link is not Link.CONNECTED:
            self.readRefused.emit(f"SC3 {view.LINK_WORDS[self._link]}", why)
            return
        live, _since = self._live_status()  # свежий статус: правило «Эфир» — перед КАЖДЫМ обращением к SC3
        note = self._guard.check(live)
        if note:
            self.readRefused.emit(note, why)
            return
        self.readStarted.emit()
        problem = ""
        try:
            st = self._core.read_state(time.time())
        except Exception as e:  # noqa: BLE001 — открыть/прочитать не вышло: показать, но не падать
            st, problem = Sc3State(link=Link.ERROR), str(e)
        finally:
            self._guard.mark()
        if st.link is Link.ERROR and not problem:
            problem = "чтения ACP не прошли"
        self.readDone.emit(st, problem)

    # --- лёгкий опрос (решение 9) ---------------------------------------------------------------------

    @Slot(bool)
    def set_visible(self, visible: bool) -> None:
        self._visible = visible
        self._update_poll()

    @Slot()
    def refresh_poll(self) -> None:
        """«Обновить» при видимом окне: в идущем опросе — то, чего нет в круге (poll.REFRESH), в ближайший слот
        (без пачки; голос и ELECTRIC и так в круге); если опрос стоял — попробовать начать его сейчас."""
        if self._session is not None:
            self._plan.refresh()
        elif self._blocked:
            self.pollChanged.emit(False, self._blocked)
        else:
            self._update_poll(user=True)

    def _poll_unwanted(self) -> str:
        """«» — опрос нужен и можно; иначе почему нет."""
        if not self._core.continuous_polling:
            return "постоянный опрос выключен"
        if not self._visible:
            return "окно скрыто"
        if self._link is not Link.CONNECTED:
            return "SC3 не на связи"
        if self._blocked:
            return self._blocked
        if self._live is not Live.OFF:
            return "эфир"
        return ""

    def _update_poll(self, user: bool = False) -> None:
        if self._guard is None:
            return
        unwanted = self._poll_unwanted()
        if unwanted and self._session is not None:
            self._stop_poll("")
        elif not unwanted and self._session is None:
            self._start_poll(user)

    def _start_poll(self, user: bool) -> None:
        live, _since = self._live_status()  # правило 3 — прямо перед открытием
        if live is not Live.OFF:
            return
        note = self._guard.check_poll(live)
        if note:
            if user:
                self.pollChanged.emit(False, note)
            return  # следующая попытка — на ближайшем тике статуса эфира
        # Первые слоты — полный набор (по одному чтению на слот), если его разрешает правило полных наборов
        # (раз в 5 с, отметка общая с CLI); иначе — сразу круг 07/07/07/B6 (окно только что спрятали и показали).
        full = self._full_set_first and not self._guard.check(live)  # поправка MIC — в любом случае, первой
        self._guard.mark_poll()  # verify() читает 0x00 — это первый слот
        try:
            session = self._core.open_sc3()
        except OpenFailed as e:
            self._guard.mark()
            if e.link is not None:  # чужая сборка или verify не прошёл — до переподключения
                self._blocked = e.note
                self.readDone.emit(Sc3State(link=e.link), e.note)
            self.pollChanged.emit(False, e.note)
            return
        except Exception as e:  # noqa: BLE001
            self._guard.mark()
            self.pollChanged.emit(False, f"SC3 не открылся: {e}")
            return
        if full:
            self._guard.mark()
        self._session, self._plan = session, poll.Plan(full, dsp=True)
        self._t0 = self._last = time.monotonic()
        self._k, self._fails = 0, 0
        self.polled.emit({"link": Link.CONNECTED, "firmware": "V22", "read_at": time.time(),
                          "written": self._journal_written()})
        self.pollChanged.emit(True, "")
        self._schedule()

    def _schedule(self) -> None:
        self._k, self._at = poll.next_slot(self._t0, self._k, time.monotonic(), self._last)
        self._arm()

    def _arm(self) -> None:
        self._slot_timer.start(max(0, math.ceil((self._at - time.monotonic()) * 1000)))

    def _slot(self) -> None:
        if self._session is None:
            return
        if time.monotonic() < self._at:  # таймер пришёл чуть раньше слота
            self._arm()
            return
        note = self._guard.check_poll(self._live)
        if note:
            if self._live is not Live.OFF:
                self._stop_poll("")
            else:  # слот раньше разрешённого (прошлое чтение началось позже своего слота): подождать остаток
                self._at = self._last + poll.POLL_INTERVAL
                self._arm()
            return
        if (self._job is not None or self._trim_want is not None) and self._plan.ready_to_write():
            self._run_job()  # слот — записи (узлы прочитаны, пресет кнопки перечитан)
            if self._session is not None:
                self._schedule()
            return
        ctrl = self._plan.next()
        self._guard.mark_poll()
        self._last = time.monotonic()
        try:
            body = self._session.read(ctrl)
        except Exception as e:  # noqa: BLE001 — транспорт порвался (SET_REPORT): та же неудача, что молчание
            log.info("опрос %#04x: %s", ctrl, e)
            body = None
        update = None
        if body is not None:
            try:
                update = self._plan.parse(ctrl, body)
            except poll.BadReply as e:
                log.info("опрос: %s", e)
        if update is None:
            self._plan.retry(ctrl)
            self._fails += 1
            if self._fails >= poll.MAX_FAILS:
                self._blocked = f"{poll.MAX_FAILS} неудачи чтения подряд — опрос SC3 выключен до переподключения"
                self._stop_poll(self._blocked)
                self.readDone.emit(Sc3State(link=Link.ERROR, firmware="V22"), self._blocked)
                return
        else:
            self._fails = 0
            if update:
                update["read_at"] = time.time()
                self.polled.emit(update)
        self._schedule()

    def _stop_poll(self, note: str) -> None:
        if self._session is None:
            return
        self._drop_writes(note or self._poll_unwanted() or "опрос SC3 остановлен")
        if self._slot_timer is not None:
            self._slot_timer.stop()
        session, self._session = self._session, None
        try:
            session.close()
        except Exception as e:  # noqa: BLE001
            log.warning("закрытие SC3: %s", e)
        self._guard.mark()  # SC3 опрашивали: CLI после окна выждет интервал полных наборов
        self.pollChanged.emit(False, note)

    # --- запись: ручка-поправка MIC, профиль, возврат --------------------------------------------------

    @Slot(bool)
    def set_write_enabled(self, enabled: bool) -> None:
        """Предохранитель записи (меню окна). Выключили — ждущие просьбы не пишутся."""
        self._write_enabled = enabled
        if not enabled:
            self._drop_writes("запись в SC3 выключена")

    def request_stop(self) -> None:
        """«Стоп» — ЗОВЁТСЯ ИЗ ПОТОКА ИНТЕРФЕЙСА напрямую, не сигналом: сеанс записи держит этот поток, и сигнал дошёл
        бы только после него. `threading.Event` потокобезопасен; сеанс увидит флаг перед следующим кадром."""
        self._stop.set()

    @Slot(float, float)
    def want_trim(self, db: float, asked_at: float) -> None:
        """Ручка-поправка MIC: значение ждёт ближайшего слота опроса; новое заменяет старое (пишется последнее).
        `asked_at` — time.monotonic() просьбы: просьбы, отправленные до неудачи записи, уже не нужны."""
        if asked_at < self._trim_since:
            return
        if why := self._write_unwanted():
            self.trimDone.emit(db, None, f"поправка MIC не записана: {why}")
            return
        self._trim_want = db

    @Slot(str)
    def want_job(self, job: str) -> None:
        """Меню профиля: `podcast` — записать «Подкаст», `undo` — вернуть последний сеанс журнала (как `sc3 undo`)."""
        title = JOB_TITLE[job]
        if why := self._write_unwanted():
            self.jobDone.emit(title, f"{title}: не записано — {why}", False)
        elif self._job is not None:
            self.jobDone.emit(title, f"{title}: уже ждёт слота", False)
        else:
            self._job = job

    def _write_unwanted(self) -> str:
        """«» — писать можно (предохранитель включён, SC3 опрашивается, эфира нет); иначе — почему нет."""
        if not self._write_enabled:
            return WRITE_OFF
        if self._session is None:
            return self._poll_unwanted() or "SC3 сейчас не опрашивается"
        if self._live is not Live.OFF:
            return "эфир"
        return ""

    def _drop_writes(self, why: str) -> None:
        """Ждущие просьбы — мимо (опрос остановлен, предохранитель выключен): сказать окну."""
        if self._trim_want is not None:
            db, self._trim_want = self._trim_want, None
            self.trimDone.emit(db, None, f"поправка MIC не записана: {why}")
        if self._job is not None:
            title, self._job = JOB_TITLE[self._job], None
            self.jobDone.emit(title, f"{title}: не записано — {why}", False)

    def _journal_written(self) -> dict[str, int]:
        """Что оставил последний сеанс журнала записи (для подписи профиля): чтение файла — здесь, не в интерфейсе."""
        path = self._core.journal_path()
        try:
            return poll.journal_written(W.last_session(path)) if path is not None else {}
        except Exception as e:  # noqa: BLE001 — журнал не прочитался: подпись просто будет осторожнее
            log.info("журнал записи: %s", e)
            return {}

    def _run_job(self) -> None:
        """Слот — записи: сначала профиль или возврат из меню, иначе ручка MIC. План — здесь, запись — `_apply_plan`."""
        from opensc3 import profiles as PR
        if self._job is None:
            db, self._trim_want = self._trim_want, None
            self._apply_plan(W.plan_write([("mic.trim", db)]), TRIM_WHAT, trim=db)
            return
        job, self._job = self._job, None
        title = JOB_TITLE[job]
        try:
            if job == UNDO:   # тот же путь, что `sc3 undo --write`
                path = self._core.journal_path()
                rows = W.last_session(path) if path is not None else []
                writes = W.undo_writes(rows)
                if not writes:
                    self.jobDone.emit(title, "Возвращать нечего: журнал пуст или последний сеанс ничего не изменил",
                                      True)
                    return
                sid = rows[0]["session"]
                plan, what, undoes = W.plan_write(writes), f"window undo {sid}", sid
            else:
                prof = PR.PROFILES[job]
                plan, what, undoes = W.plan_write(prof.items), f"window profile {prof.name}", None
        except W.WriteError as e:
            self.jobDone.emit(title, f"{title}: не записано — {e}", False)
            return
        self._apply_plan(plan, what, undoes=undoes, title=title)

    def _apply_plan(self, plan, what: str, *, undoes: str | None = None, title: str = "",
                    trim: float | None = None) -> None:
        """ЕДИНСТВЕННОЕ место окна, где зовётся `write.apply` (сторож: tests/test_safety.py, класс Window): ручка MIC
        (`trim`), профиль и возврат (`title`). Тот же путь, что у `sc3 set|profile apply|undo --write`: белый список,
        эфир (OBS спрашивается заново перед сеансом и перед каждым кадром — `_live_before_acp`), verify и типы узлов,
        снимок «до», кадры по одному с чтением назад, откат при расхождении, журнал `writes.jsonl` (`sc3 undo` его
        видит). Темп общий с опросом: каждое обращение сеанса к SC3 ждёт свой слот (`Sc3.pace` → `_pace`) — вместе с
        опросом не больше одного обращения за 0,5 с. «Стоп» (`request_stop`) — перед следующим кадром: стоп и откат
        записанного в этом сеансе; эфир — стоп без отката (вернуть после эфира). Поток всё это время занят."""
        if why := self._write_unwanted():
            if trim is not None:
                self.trimDone.emit(trim, None, f"поправка MIC не записана: {why}")
            else:
                self.jobDone.emit(title, f"{title}: не записано — {why}", False)
            return
        session = self._session
        total = self._frames(plan) if title else 0

        def step(op: str, n: int, written: int, param, back: int | None) -> None:
            if back is not None and param.addr in self._plan.nodes:   # прочитано назад — это чтение узла
                vals = list(self._plan.nodes[param.addr])
                if param.idx < len(vals):
                    vals[param.idx] = back
                    self._plan.nodes[param.addr] = tuple(vals)
                    update = {"nodes": {param.addr: tuple(vals)}}
                    if param.addr == R.MIC_TRIM:
                        update["mic_trim"] = R.mic_trim(vals)
                    self.polled.emit(update)
            if op == "rollback":
                self.writeProgress.emit(f"{title} — откат", n, written)
            else:
                self.writeProgress.emit(title, n, max(total, n))

        journal = ProgressJournal(self._core.journal_path(), what=what, undoes=undoes,
                                  step=step if title else (lambda *_: None))
        self._stop.clear()
        self._stopping = False
        if title:
            self.writeProgress.emit(title, 0, total)
        session.pace = self._pace
        res, err = None, None
        try:
            res = W.apply(session, plan, live=self._live_before_acp, guard=poll.WriteGuard(self._guard),
                          journal=journal)
        except (WriteStopped, W.WriteRefused, W.WriteError) as e:
            err = e
        except Exception as e:  # noqa: BLE001 — сбой транспорта и прочее: показать, поток жив
            log.warning("запись (%s): %s", what, e)
            err = e
        finally:
            session.pace = None
        if trim is not None:
            self._trim_result(trim, res, err)
        else:
            self._job_result(title, total, res, err, journal)
        self._update_poll()  # эфир, увиденный перед кадром, закрывает SC3 сразу, а не на тике статуса

    def _frames(self, plan) -> int:
        """Сколько кадров займёт план по прочитанным узлам (для «12 из 24»); 0 — не знаем."""
        try:
            return len(W.plan_write(plan.targets, self._plan.nodes_state()).writes)
        except W.WriteError:
            return 0

    def _trim_result(self, db: float, res, err) -> None:
        if err is None:
            back = next((d.readback for d in res.done if d.write.param.key == "mic.trim"), None)
            if back is None:  # писать было нечего: в SC3 уже так
                back = W.target("mic.trim", db).value
            update = {"mic_trim": R.mic_trim([0, 0, back]), "read_at": time.time()}
            if R.MIC_TRIM in self._plan.nodes:
                vals = list(self._plan.nodes[R.MIC_TRIM])
                vals[2] = back
                self._plan.nodes[R.MIC_TRIM] = tuple(vals)
                update["nodes"] = {R.MIC_TRIM: tuple(vals)}
            self.polled.emit(update)
            self.trimDone.emit(db, update["mic_trim"], "")
            return
        # не записано: ждущие значения — мимо, поправку — перечитать (ручка вернётся к прочитанному)
        self._trim_want = None
        self._trim_since = time.monotonic()
        if not isinstance(err, W.WriteRefused) and self._plan is not None:
            self._plan.retry(R.MIC_TRIM)
        self.trimDone.emit(db, None, f"поправка MIC не записана: {err}")

    def _job_result(self, title: str, total: int, res, err, journal: W.Journal) -> None:
        """Итог профиля или возврата — в шапку; узлы — перечитать по одному на слот (ящик и подпись профиля)."""
        if self._plan is not None:
            self._plan.reread(R.DSP_NODES)
        if err is None:
            n = len(res.done)
            note = f"{title}: записано кадров — {n}" if n else f"{title}: писать нечего — в SC3 уже так"
            if res.skipped:
                note += "; пропущено (меняли с панели): " + ", ".join(w.param.key for w in res.skipped)
            self.jobDone.emit(title, note, True)
            return
        wrote = sum(1 for e in journal.entries if e.get("op") == "write")
        if isinstance(err, WriteStopped):
            back = sum(1 for e in journal.entries if e.get("op") == "rollback" and e.get("ok"))
            note = (f"{title}: остановлено — ничего не записано" if not wrote
                    else f"{title}: остановлено — записанное в этом сеансе ({wrote}) возвращено" if back == wrote
                    else f"{title}: остановлено, но вернуть удалось не всё — выдерни USB для полного сброса (вне эфира)")
        elif isinstance(err, W.WriteRefused):
            done = len(err.done)
            note = (f"{title}: остановлено — {err}; записано {done} из {total or '?'}, "
                    "вернуть после эфира: «Вернуть как было»" if done else f"{title}: не записано — {err}")
        else:
            note = f"{title}: не записано — {err}"
        self.jobDone.emit(title, note, False)

    def _live_before_acp(self) -> Live:
        """Статус эфира для `write.apply`: сначала дождаться своего слота, потом спросить OBS заново — ответ свежий
        прямо перед обращением к SC3 (правило 3), а не до паузы. Здесь же — «Стоп»: один раз за сеанс, чтобы
        откат (он тоже спрашивает эфир) шёл до конца."""
        self._wait_slot()
        if self._stop.is_set() and not self._stopping:
            self._stopping = True
            raise WriteStopped("остановлено из окна")
        return self._live_status()[0]

    def _wait_slot(self) -> None:
        left = self._last + poll.POLL_INTERVAL - time.monotonic()
        if left > 0:
            time.sleep(left)

    def _pace(self) -> None:
        """`Sc3.pace` на время сеанса записи: обращение к SC3 — не раньше 0,5 с после прошлого (чтения опроса или
        обращения записи), слот отмечается в гварде так же, как чтение опроса."""
        self._wait_slot()
        self._guard.mark_poll()
        self._last = time.monotonic()


class AudioWorker(QObject):
    """Поток «sc3-audio»: PipeWire. SC3 по ACP отсюда не трогается."""

    nodesSeen = Signal(bool)
    muteSeen = Signal(object)             # bool | None
    muteFailed = Signal(str)
    peaksSeen = Signal(object, object)    # dBFS в ПК, из ПК (None — нет данных)

    def __init__(self, core: Core) -> None:
        super().__init__()
        self._core = core
        self._nodes = None
        self._meter = None
        self._meter_wanted = False
        self._slow: QTimer | None = None
        self._fast: QTimer | None = None

    @Slot()
    def init(self) -> None:
        self._slow = QTimer(self)
        self._slow.setInterval(int(AUDIO_INTERVAL * 1000))
        self._slow.timeout.connect(self._tick)
        self._slow.start()
        self._fast = QTimer(self)
        self._fast.setInterval(1000 // METER_HZ)
        self._fast.timeout.connect(self._tick_meter)
        self._scan()

    @Slot()
    def shutdown(self) -> None:
        for t in (self._slow, self._fast):
            if t is not None:
                t.stop()
        self._stop_meter()

    def _scan(self) -> None:
        try:
            nodes = self._core.find_sc3()
        except Exception as e:  # noqa: BLE001
            log.warning("PipeWire: %s", e)
            nodes = None
        if nodes != self._nodes:
            self._nodes = nodes
            self.nodesSeen.emit(nodes is not None)
            self._restart_meter()
        self._read_mute()

    def _read_mute(self) -> None:
        if self._nodes is None:
            self.muteSeen.emit(None)
            return
        try:
            self.muteSeen.emit(self._core.get_mute(self._nodes))
        except Exception as e:  # noqa: BLE001
            log.warning("PipeWire mute: %s", e)
            self.muteSeen.emit(None)

    def _tick(self) -> None:
        if self._nodes is None:
            self._scan()        # SC3 ещё не появился в PipeWire
        else:
            self._read_mute()   # mute могли поменять снаружи (апплет звука KDE)

    @Slot()
    def rescan(self) -> None:
        """После события hotplug: PipeWire заводит узлы не сразу — посмотреть сейчас и ещё дважды."""
        self._scan()
        QTimer.singleShot(1500, self, self._scan)
        QTimer.singleShot(4000, self, self._scan)

    @Slot(bool)
    def set_mute(self, muted: bool) -> None:
        if self._nodes is None:
            self.muteFailed.emit("SC3 нет в PipeWire — заглушить нечего")
            return
        try:
            self._core.set_mute(self._nodes, muted)
        except Exception as e:  # noqa: BLE001
            self.muteFailed.emit(f"PipeWire: {e}")
        self._read_mute()

    @Slot(bool)
    def set_meter(self, wanted: bool) -> None:
        self._meter_wanted = wanted
        self._restart_meter()

    def _stop_meter(self) -> None:
        if self._meter is not None:
            try:
                self._meter.stop()
            except Exception as e:  # noqa: BLE001
                log.warning("уровни: %s", e)
            self._meter = None

    def _restart_meter(self) -> None:
        self._stop_meter()
        if self._fast is not None:
            self._fast.stop()
        if self._meter_wanted and self._nodes is not None:
            try:
                self._meter = self._core.meter(self._nodes)
                self._meter.start()
                self._fast.start()
            except Exception as e:  # noqa: BLE001
                log.warning("уровни: %s", e)
                self._meter = None
        self.peaksSeen.emit(None, None)

    def _tick_meter(self) -> None:
        try:
            a, b = self._meter.peaks()
        except Exception as e:  # noqa: BLE001
            log.warning("уровни: %s", e)
            self._restart_meter()
            return
        self.peaksSeen.emit(a, b)


def _prop(name: str, kind, notify):
    """Свойство QML только для чтения из словаря `_props` (имена — как в DemoState.qml)."""
    return Property(kind, lambda self: self._props[name], notify=notify)


class Backend(QObject):
    """Объект `sc3` для QML (той же формы, что design/panel/scenes/DemoState.qml) и источник состояния трея."""

    stateChanged = Signal()
    levelsChanged = Signal()
    clockChanged = Signal()
    appStateChanged = Signal(object)      # AppState — трею и всем, кто живёт в Python

    _readRequest = Signal(str)
    _visibleRequest = Signal(bool)
    _pollRefresh = Signal()
    _muteRequest = Signal(bool)
    _meterRequest = Signal(bool)
    _rescanRequest = Signal()
    _trimRequest = Signal(float, float)   # дБ, time.monotonic() просьбы
    _writeEnabledRequest = Signal(bool)
    _jobRequest = Signal(str)             # PODCAST | UNDO

    # --- свойства для QML: SC3
    link = _prop("link", str, stateChanged)
    connected = _prop("connected", bool, stateChanged)
    firmware = _prop("firmware", str, stateChanged)
    faderMic = _prop("faderMic", float, stateChanged)
    faderLineIn = _prop("faderLineIn", float, stateChanged)
    faderHeadphone = _prop("faderHeadphone", float, stateChanged)
    faderLineOut = _prop("faderLineOut", float, stateChanged)
    muteMic = _prop("muteMic", bool, stateChanged)
    muteLineIn = _prop("muteLineIn", bool, stateChanged)
    muteLineOut = _prop("muteLineOut", bool, stateChanged)
    micMonitor = _prop("micMonitor", bool, stateChanged)
    phantom = _prop("phantom", bool, stateChanged)
    electricKey = _prop("electricKey", str, stateChanged)
    voice = _prop("voice", str, stateChanged)
    customLit = _prop("customLit", str, stateChanged)
    trimMic = _prop("trimMic", float, stateChanged)            # просьба ручки, пока не подтверждена; потом — чтение
    trimMicPending = _prop("trimMicPending", bool, stateChanged)  # значение ручки ещё пишется
    trimLineIn = _prop("trimLineIn", float, stateChanged)
    writeEnabled = _prop("writeEnabled", bool, stateChanged)   # предохранитель «Разрешить запись в SC3»
    unknown = _prop("unknown", "QVariantMap", stateChanged)
    guess = _prop("guess", "QVariantMap", stateChanged)   # клавиша горит по догадке (Channel.muted_guess)
    dsp = _prop("dsp", "QVariantMap", stateChanged)
    lastPoll = _prop("lastPoll", str, stateChanged)
    acpNote = _prop("acpNote", str, stateChanged)
    busy = _prop("busy", bool, stateChanged)
    polling = _prop("polling", bool, stateChanged)     # идёт лёгкий опрос: данные в реальном времени
    # PipeWire
    audioPresent = _prop("audioPresent", bool, stateChanged)
    pipewireMute = _prop("pipewireMute", bool, stateChanged)
    levelIn = _prop("levelIn", float, levelsChanged)
    levelOut = _prop("levelOut", float, levelsChanged)
    # OBS
    live = _prop("live", str, stateChanged)
    onAir = _prop("onAir", bool, stateChanged)
    frozen = _prop("frozen", bool, stateChanged)
    onAirTime = _prop("onAirTime", str, clockChanged)
    # профили
    profile = _prop("profile", str, stateChanged)            # подпись: «Подкаст» | «заводской» | «свой» | «»
    profiles = _prop("profiles", "QVariantList", stateChanged)  # меню профиля: [{name, note, action, enabled, active}]
    profileHint = _prop("profileHint", str, stateChanged)    # почему пункты меню неактивны («» — активны)
    # идущая запись профиля/возврата: «Подкаст: 12 из 24» и «Стоп»
    writeTitle = _prop("writeTitle", str, stateChanged)      # «» — записи нет
    writeDone = _prop("writeDone", int, stateChanged)
    writeTotal = _prop("writeTotal", int, stateChanged)     # 0 — сколько всего, неизвестно

    def __init__(self, core: Core, parent: QObject | None = None, *, live_interval: float = LIVE_INTERVAL,
                 full_set_first: bool = True) -> None:
        super().__init__(parent)
        self._core = core
        self._continuous = bool(core.continuous_polling)
        self._visible = False
        self._polling = False
        self._state = AppState()            # эфир UNKNOWN до первого ответа OBS — всё под замком
        self._probe_link = Link.DISCONNECTED
        self._busy = False
        self._read_pending = False
        self._note_is_live = False
        self._levels = (0.0, 0.0)
        self._levels_t = time.monotonic()
        self._settings = core.settings()
        self._write_enabled = bool(self._settings.value(WRITE_KEY, False, type=bool))
        self._trim_target: float | None = None   # значение ручки MIC, ещё не подтверждённое чтением назад
        self._progress: tuple[str, int, int] = ("", 0, 0)   # запись профиля: заголовок, сделано, всего
        # подпись профиля (poll.profile_label): чей набор в SC3 — пресета панели или записанный
        self._base_mode = poll.BASE_CONNECT
        self._base: dict | None = None        # узлы пресета (BASE_KNOWN)
        self._base_new: dict = {}             # собираются после нажатия кнопки (BASE_PRESET)
        self._written: dict | None = None     # что оставил последний сеанс журнала (от рабочего потока)
        self._props = self._compute()
        self._started = False

        self._control_thread = QThread(self)
        self._control_thread.setObjectName("sc3-control")
        self._control = ControlWorker(core, live_interval, full_set_first, self._write_enabled)
        self._control.moveToThread(self._control_thread)
        self._control_thread.started.connect(self._control.init)
        self._control.probed.connect(self._on_probed)
        self._control.liveSeen.connect(self._on_live)
        self._control.readStarted.connect(self._on_read_started)
        self._control.readDone.connect(self._on_read_done)
        self._control.readRefused.connect(self._on_read_refused)
        self._control.polled.connect(self._on_polled)
        self._control.pollChanged.connect(self._on_poll_changed)
        self._control.trimDone.connect(self._on_trim_done)
        self._control.jobDone.connect(self._on_job_done)
        self._control.writeProgress.connect(self._on_write_progress)
        self._readRequest.connect(self._control.read)
        self._visibleRequest.connect(self._control.set_visible)
        self._pollRefresh.connect(self._control.refresh_poll)
        self._trimRequest.connect(self._control.want_trim)
        self._writeEnabledRequest.connect(self._control.set_write_enabled)
        self._jobRequest.connect(self._control.want_job)

        self._audio_thread = QThread(self)
        self._audio_thread.setObjectName("sc3-audio")
        self._audio = AudioWorker(core)
        self._audio.moveToThread(self._audio_thread)
        self._audio_thread.started.connect(self._audio.init)
        self._audio.nodesSeen.connect(self._on_nodes)
        self._audio.muteSeen.connect(self._on_mute)
        self._audio.muteFailed.connect(self._on_mute_failed)
        self._audio.peaksSeen.connect(self._on_peaks)
        self._muteRequest.connect(self._audio.set_mute)
        self._meterRequest.connect(self._audio.set_meter)
        self._rescanRequest.connect(self._audio.rescan)

        self._clock = QTimer(self)
        self._clock.setInterval(1000)
        self._clock.timeout.connect(self._on_clock)
        self._note_timer = QTimer(self)
        self._note_timer.setSingleShot(True)
        self._note_timer.setInterval(NOTE_HOLD_MS)
        self._note_timer.timeout.connect(self._clear_transient_note)

    # --- жизнь ----------------------------------------------------------------------------------------

    @property
    def state(self) -> AppState:
        return self._state

    def start(self) -> None:
        """Запустить потоки; первый набор чтений — «при старте» (если гвард разрешит)."""
        if self._started:
            return
        self._started = True
        self._control_thread.start()
        self._audio_thread.start()
        self._clock.start()
        if not self._polls():  # видимое окно опрашивает само, полный набор пачкой ему не нужен
            self._request_read(WHY_START)

    def _polls(self) -> bool:
        """Сейчас SC3 читает лёгкий опрос (а не наборы по событию)."""
        return self._continuous and self._visible

    def stop(self) -> None:
        """Остановить потоки (выход из приложения). Ждёт текущий вызов ядра — не дольше пары секунд; идущая запись
        профиля сперва останавливается с откатом (как «Стоп»), и выход ждёт отката."""
        self._control.request_stop()
        self._clock.stop()
        self._note_timer.stop()
        for worker, thread in ((self._control, self._control_thread), (self._audio, self._audio_thread)):
            if thread.isRunning():
                QMetaObject.invokeMethod(worker, "shutdown", Qt.ConnectionType.BlockingQueuedConnection)
                thread.quit()
                if not thread.wait(3000):
                    log.warning("поток %s не остановился", thread.objectName())
        self._started = False

    def set_window_visible(self, visible: bool) -> None:
        """Окно показали/спрятали: уровни и опрос SC3 нужны только видимому окну (скрыли — SC3 закрывается)."""
        self._visible = visible
        self._meterRequest.emit(visible)
        self._visibleRequest.emit(visible)
        if visible and not self._continuous:
            self._request_read(WHY_SHOW)

    # --- для QML и трея -------------------------------------------------------------------------------

    @Slot()
    def refresh(self) -> None:
        """Кнопка «Обновить»: в опросе — узлы голосов и ELECTRIC в ближайшие слоты; иначе — один набор чтений,
        если гвард разрешит."""
        if self._polls():
            self._pollRefresh.emit()
        else:
            self._request_read(WHY_USER)

    @Slot()
    def toggleMicMute(self) -> None:
        self.setMicMute(self._state.audio.pw_muted is not True)

    @Slot(bool)
    def setMicMute(self, muted: bool) -> None:
        if self._mute_route() == "pipewire":
            self._muteRequest.emit(muted)

    def _mute_route(self) -> str:
        """ЕДИНСТВЕННОЕ место, где решается, чем глушить микрофон (решение 8).

        Аппаратного Mute в белом списке записи нет (решение 4), поэтому сейчас всегда «pipewire» — mute источника
        SC3 в PipeWire, и в эфире, и вне его. Когда (и если) владелец разрешит эту категорию: вне эфира
        (`self._state.live is Live.OFF`) — «sc3», аппаратный Mute (клавиша на корпусе загорится; кадр — через
        модуль записи с его белым списком и проверкой эфира), в эфире — по-прежнему «pipewire».
        """
        return "pipewire"

    # --- запись: предохранитель и ручка-поправка MIC ---------------------------------------------------

    @Slot(bool)
    def setWriteEnabled(self, enabled: bool) -> None:
        """Предохранитель «Разрешить запись в SC3» (меню-шестерёнка в шапке): по умолчанию выключен, хранится в
        настройках окна. Выключили — ждущее значение ручки не пишется."""
        enabled = bool(enabled)
        if enabled == self._write_enabled:
            return
        self._write_enabled = enabled
        self._settings.setValue(WRITE_KEY, enabled)
        sync = getattr(self._settings, "sync", None)
        if sync is not None:
            sync()
        self._writeEnabledRequest.emit(enabled)
        if not enabled:
            self._trim_target = None
        self._publish()

    @Slot(float)
    def setMicTrim(self, db: float) -> None:
        """Ручка-поправка MIC (бриф №5): новое значение, дБ (шаг 0,5, границы белого списка). Пишет рабочий поток в
        ближайшем слоте опроса через `write.apply`; значения сливаются — пишется последнее. Пока запись не
        подтверждена чтением назад, ручка показывает просьбу (`trimMicPending`); не сошлось — вернётся к
        прочитанному, причина — в шапке."""
        if why := self._trim_refusal():
            self._set_note(why, live=False)
            return
        db = poll.trim_step(float(db), *TRIM_DB)
        self._trim_target = db
        self._trimRequest.emit(db, time.monotonic())
        self._publish()

    def _write_refusal(self) -> str:
        """«» — писать в SC3 сейчас можно; иначе — почему нет (то же решает рабочий поток и сам write.apply)."""
        st = self._state
        if not self._write_enabled:
            return WRITE_OFF
        if st.live is not Live.OFF:
            return "идёт эфир — изменения выключены" if st.live is Live.ON else "эфир не определён — изменения выключены"
        if st.sc3.link is not Link.CONNECTED:
            return "SC3 не на связи — записать нельзя"
        if not self._polling:
            return "SC3 сейчас не опрашивается — записать нельзя"
        return ""

    def _trim_refusal(self) -> str:
        """«» — ручку MIC можно крутить; иначе — почему нет."""
        if why := self._write_refusal():
            return why
        if self._progress[0]:
            return f"идёт запись ({self._progress[0]}) — ручка подождёт"
        if self._state.sc3.mic.trim_db is None:
            return "поправка MIC ещё не прочитана"
        return ""

    # --- профиль: меню, прогресс, подпись --------------------------------------------------------------

    @Slot(str)
    def profileAction(self, action: str) -> None:
        """Пункт меню профиля: «Подкаст — применить» (`podcast`), «Вернуть как было» (`undo`, как `sc3 undo`).
        За тем же предохранителем; пишет рабочий поток в ближайшем слоте, прогресс — в шапке."""
        if action == FACTORY:
            self._set_note("«Как с завода» — позже", live=False)
            return
        if action not in JOB_TITLE:
            return
        if why := self._write_refusal():
            self._set_note(why, live=False)
            return
        if self._progress[0]:
            self._set_note(f"запись уже идёт ({self._progress[0]})", live=False)
            return
        self._progress = (JOB_TITLE[action], 0, 0)
        self._jobRequest.emit(action)
        self._publish()

    @Slot()
    def stopWrite(self) -> None:
        """«Стоп»: сеанс записи останавливается перед следующим кадром и откатывает записанное в этом сеансе."""
        if self._progress[0]:
            self._control.request_stop()  # напрямую: поток записи занят сеансом и сигнал не прочтёт
            self._set_note(f"{self._progress[0]}: останавливаю и возвращаю записанное…", live=False)

    def _on_write_progress(self, title: str, done: int, total: int) -> None:
        if title:
            self._progress = (title, done, total)
            self._publish()

    def _on_job_done(self, title: str, note: str, ok: bool) -> None:
        self._progress = ("", 0, 0)
        if note:
            self._set_note(note, live=False)
        else:
            self._publish()

    def _profile_rows(self, label: str) -> list[dict]:
        can = not self._write_refusal() and not self._progress[0]
        return [
            {"name": "Подкаст — применить", "note": "EQ голоса, шумодав, поправка MIC +6 дБ", "action": PODCAST,
             "enabled": can, "active": label == poll.PODCAST_LABEL},
            {"name": "Вернуть как было", "note": "отменить последнюю запись — как sc3 undo", "action": UNDO,
             "enabled": can, "active": False},
            {"name": "Как с завода", "note": "позже", "action": FACTORY, "enabled": False, "active": False},
        ]

    def _base_update(self, update: dict) -> None:
        """Подпись профиля: «заводской» — пока в SC3 пресет панели. Пресет узнаётся по набору, прочитанному сразу
        после нажатия кнопки голоса/ELECTRIC (`preset_changed` → `preset`), а после подключения — по журналу: если
        в SC3 ровно то, что оставил последний сеанс записи, набор свой, иначе это пресет."""
        if "written" in update:
            self._written = update["written"]
        if update.get("preset_changed"):
            self._base_mode, self._base, self._base_new = poll.BASE_PRESET, None, {}
        if "preset" in update and self._base_mode == poll.BASE_PRESET:
            self._base_new.update(update["preset"])
            if all(c in self._base_new for c in R.DSP_NODES):
                self._base_mode, self._base = poll.BASE_KNOWN, dict(self._base_new)
        nodes = self._state.sc3.nodes
        if self._base_mode == poll.BASE_CONNECT and self._written is not None and all(c in nodes for c in R.DSP_NODES):
            if poll.written_matches(self._written, nodes):
                self._base_mode, self._base = poll.BASE_WRITTEN, None
            else:
                self._base_mode, self._base = poll.BASE_KNOWN, dict(nodes)

    def _on_trim_done(self, want: float, got: float | None, note: str) -> None:
        if note:  # не записано: ручка — к прочитанному значению, причина — в шапке
            self._trim_target = None
            self._set_note(note, live=False)
        elif self._trim_target == want:  # подтверждено чтением назад (новую просьбу ещё ждём — её не трогаем)
            self._trim_target = None
            self._publish()

    # --- чтения SC3 -----------------------------------------------------------------------------------

    def _request_read(self, why: str) -> None:
        if not self._started:
            return
        if self._read_pending:  # набор уже в очереди или идёт: повод сливается с ним
            if why == WHY_USER:
                self._set_note("набор чтений уже идёт", live=False)
            return
        self._read_pending = True
        self._readRequest.emit(why)

    def _on_read_started(self) -> None:
        self._busy = True
        self._publish()

    def _on_read_done(self, st: Sc3State, problem: str) -> None:
        self._busy = False
        self._read_pending = False
        if self._probe_link is not Link.CONNECTED:  # SC3 выдернули, пока читали: значения уже не о нём
            self._publish()
            return
        self._note_is_live = False
        self._note_timer.stop()
        self._state = replace(self._state, sc3=st, acp_note=problem)
        self._publish()

    def _on_read_refused(self, note: str, why: str) -> None:
        self._read_pending = False
        if not note:   # SC3 и так опрашивается
            self._publish()
        elif self._state.live is not Live.OFF:
            self._set_note(note, live=True)
        elif why == WHY_USER:
            self._set_note(note, live=False)
        else:
            self._publish()

    def _set_note(self, note: str, *, live: bool) -> None:
        self._note_is_live = live
        self._state = replace(self._state, acp_note=note)
        if live:
            self._note_timer.stop()
        else:
            self._note_timer.start()
        self._publish()

    def _clear_transient_note(self) -> None:
        if not self._note_is_live and self._state.acp_note:
            self._state = replace(self._state, acp_note="")
            self._publish()

    # --- лёгкий опрос ---

    def _on_polled(self, update: dict) -> None:
        if self._probe_link is not Link.CONNECTED:
            return
        self._state = replace(self._state, sc3=poll.merge(self._state.sc3, update))
        self._base_update(update)
        self._publish()

    def _on_poll_changed(self, active: bool, note: str) -> None:
        self._polling = active
        if active and not self._note_is_live:
            self._state = replace(self._state, acp_note="")
            self._note_timer.stop()
        elif note:  # «занят», «3 неудачи…» — видно, пока причина не уйдёт
            self._note_is_live = False
            self._note_timer.stop()
            self._state = replace(self._state, acp_note=note)
        self._publish()

    # --- присутствие и эфир ---------------------------------------------------------------------------

    def _on_probed(self, link: Link, detail: str | None) -> None:
        prev = self._probe_link
        self._probe_link = link
        if link is not prev:  # (пере)подключили или выдернули: после питания в SC3 снова пресет — решать заново
            self._base_mode, self._base, self._base_new, self._written = poll.BASE_CONNECT, None, {}, None
        if link is not Link.CONNECTED:
            # Нет на шине или нет прав: прежние значения уже не про это устройство.
            self._trim_target = None
            self._state = replace(self._state, sc3=Sc3State(link=link))
            self._publish()
        elif prev is not Link.CONNECTED:
            # (Пере)подключили: SC3 после включения — с заводскими значениями, старые не годятся.
            self._state = replace(self._state, sc3=Sc3State(link=Link.CONNECTED))
            self._publish()
            if not self._polls():  # видимое окно начнёт опрос само
                self._request_read(WHY_CONNECT)
        if link is not prev:
            self._rescanRequest.emit()
        if detail:
            log.info("SC3: %s (%s)", link.value, detail)

    def _on_live(self, live: Live, since: float | None, note: str) -> None:
        st = replace(self._state, live=live, live_since=since if live is Live.ON else None)
        if live is not Live.OFF:
            st = replace(st, acp_note=note)
            self._note_is_live = True
            self._note_timer.stop()
        elif self._note_is_live:  # эфир кончился — его причина больше не причина
            st = replace(st, acp_note="")
            self._note_is_live = False
        self._state = st
        self._publish()

    # --- PipeWire -------------------------------------------------------------------------------------

    def _on_nodes(self, present: bool) -> None:
        audio = self._state.audio
        self._state = replace(self._state, audio=replace(audio, present=present) if present else AudioState())
        if not present:
            self._levels = (0.0, 0.0)
            self.levelsChanged.emit()
        self._publish()

    def _on_mute(self, muted: bool | None) -> None:
        if muted != self._state.audio.pw_muted:
            self._state = replace(self._state, audio=replace(self._state.audio, pw_muted=muted))
            self._publish()

    def _on_mute_failed(self, why: str) -> None:
        log.warning("mute: %s", why)
        self._set_note(why, live=False)

    def _on_peaks(self, to_pc: float | None, from_pc: float | None) -> None:
        now = time.monotonic()
        dt, self._levels_t = now - self._levels_t, now
        self._state = replace(self._state, audio=replace(self._state.audio, to_pc_db=to_pc, from_pc_db=from_pc))
        if to_pc is None and from_pc is None:
            new = (0.0, 0.0)  # уровнемер остановлен или узлов нет
        else:
            target = view.levels(self._state)
            new = (view.meter_step(self._levels[0], target[0], dt), view.meter_step(self._levels[1], target[1], dt))
        if new != self._levels:
            self._levels = new
            self._props["levelIn"], self._props["levelOut"] = new
            self.levelsChanged.emit()

    # --- публикация -----------------------------------------------------------------------------------

    def _compute(self) -> dict:
        props = view.qml_state(self._state, time.time())
        props["busy"] = self._busy
        props["polling"] = self._polling
        props["levelIn"], props["levelOut"] = self._levels
        props["writeEnabled"] = self._write_enabled
        props["trimMicPending"] = self._trim_target is not None
        if self._trim_target is not None:
            props["trimMic"] = self._trim_target
        label = poll.profile_label(self._state.sc3.nodes, self._base_mode, self._base)
        props["profile"] = label
        props["profiles"] = self._profile_rows(label)
        props["profileHint"] = "" if self._progress[0] else self._write_refusal()
        props["writeTitle"], props["writeDone"], props["writeTotal"] = self._progress
        return props

    def _publish(self) -> None:
        props = self._compute()
        clock_changed = props["onAirTime"] != self._props.get("onAirTime")
        if props != self._props:
            self._props = props
            self.stateChanged.emit()
        if clock_changed:
            self.clockChanged.emit()
        self.appStateChanged.emit(self._state)

    def _on_clock(self) -> None:
        t = view.on_air_time(self._state, time.time())
        if t != self._props["onAirTime"]:
            self._props["onAirTime"] = t
            self.clockChanged.emit()
