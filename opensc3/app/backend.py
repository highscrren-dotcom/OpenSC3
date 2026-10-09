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
"""
from __future__ import annotations

import logging
import math
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

from opensc3.model import AppState, AudioState, Link, Live, Sc3State

from . import poll, view
from .core import Core, OpenFailed

log = logging.getLogger("opensc3.app")

LIVE_INTERVAL = 3.0     # статус эфира из OBS
PROBE_FALLBACK = 3.0    # если hotplug.Watcher не завёлся: проверка присутствия (sysfs, не USB) раз в 3 с
AUDIO_INTERVAL = 2.0    # mute источника и поиск узлов SC3 в PipeWire
METER_HZ = 25           # полоса 9 + 9
NOTE_HOLD_MS = 5000     # сколько видна разовая причина отказа («рано: …»)

# Поводы для набора чтений. Отказ гварда показывается только на просьбу пользователя и из-за эфира:
# автоматические поводы сливаются (старт + показ окна + подключение — один набор).
WHY_START, WHY_CONNECT, WHY_SHOW, WHY_USER = "start", "connect", "show", "user"


class ControlWorker(QObject):
    """Поток «sc3-control»: всё, что трогает SC3 (ACP) или спрашивает OBS."""

    probed = Signal(object, object)       # Link, подробность (str | None)
    liveSeen = Signal(object, object, str)  # Live, начало эфира или None, причина гварда для этого эфира
    readStarted = Signal()
    readDone = Signal(object, str)        # Sc3State, что пошло не так («» — ничего)
    readRefused = Signal(str, str)        # причина, повод
    polled = Signal(object)               # dict: поля Sc3State из очередного чтения опроса
    pollChanged = Signal(bool, str)       # опрос идёт?, почему нет («» — без замечаний)

    def __init__(self, core: Core, live_interval: float, full_set_first: bool = True) -> None:
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
        full = self._full_set_first and not self._guard.check(live)
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
        self._session, self._plan = session, poll.Plan(full)
        self._t0 = self._last = time.monotonic()
        self._k, self._fails = 0, 0
        self.polled.emit({"link": Link.CONNECTED, "firmware": "V22", "read_at": time.time()})
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
        if self._slot_timer is not None:
            self._slot_timer.stop()
        session, self._session = self._session, None
        try:
            session.close()
        except Exception as e:  # noqa: BLE001
            log.warning("закрытие SC3: %s", e)
        self._guard.mark()  # SC3 опрашивали: CLI после окна выждет интервал полных наборов
        self.pollChanged.emit(False, note)


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
    trimMic = _prop("trimMic", float, stateChanged)
    trimLineIn = _prop("trimLineIn", float, stateChanged)
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
    profile = _prop("profile", str, stateChanged)
    profiles = _prop("profiles", "QVariantList", stateChanged)

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
        self._props = self._compute()
        self._started = False

        self._control_thread = QThread(self)
        self._control_thread.setObjectName("sc3-control")
        self._control = ControlWorker(core, live_interval, full_set_first)
        self._control.moveToThread(self._control_thread)
        self._control_thread.started.connect(self._control.init)
        self._control.probed.connect(self._on_probed)
        self._control.liveSeen.connect(self._on_live)
        self._control.readStarted.connect(self._on_read_started)
        self._control.readDone.connect(self._on_read_done)
        self._control.readRefused.connect(self._on_read_refused)
        self._control.polled.connect(self._on_polled)
        self._control.pollChanged.connect(self._on_poll_changed)
        self._readRequest.connect(self._control.read)
        self._visibleRequest.connect(self._control.set_visible)
        self._pollRefresh.connect(self._control.refresh_poll)

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
        """Остановить потоки (выход из приложения). Ждёт текущий вызов ядра — не дольше пары секунд."""
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

        Записи в SC3 пока нет (решение 4), поэтому сейчас всегда «pipewire» — mute источника SC3 в PipeWire,
        и в эфире, и вне его. С этапом записи: вне эфира (`self._state.live is Live.OFF`) — «sc3», аппаратный
        Mute (клавиша на корпусе загорится; кадр — через модуль записи с его белым списком и проверкой эфира),
        в эфире — по-прежнему «pipewire».
        """
        return "pipewire"

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
        self._state = replace(self._state, sc3=replace(self._state.sc3, **update))
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
        if link is not Link.CONNECTED:
            # Нет на шине или нет прав: прежние значения уже не про это устройство.
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
