"""Лёгкий опрос SC3 окном (решение 9): что читать в очередном слоте, когда слот и как разобрать ответ.

Без Qt и без ввода-вывода — это решает и разбирает, а читает рабочий поток бэкенда (backend.ControlWorker).
Слот — одно чтение ACP раз в 0,5 с по сетке монотонных часов. В начале сессии — голос и нота (`0x85`, `0x86`: по
ним видно нажатие кнопки), потом узлы обработки голоса (`reader.DSP_NODES`: поправка `0xAC`, EQ `0xA2`, шумодав
`0x82`; их меняют только окно, CLI и пресет кнопки, в круге их нет), затем остаток полного набора `reader.FULL_SET` —
по одному чтению на слот, а не пачкой; затем круг
`reader.POLL_CYCLE` (Mic, голос, Mic, ELECTRIC, Mic, Line In). «Обновить» ставит в очередь то, чего в круге нет
(загрузку DSP): оно занимает ближайший слот, пачки нет. Разбор — функциями `reader`, результат — поля `Sc3State`
(`merge`).

Пресет кнопки (docs/GOTCHAS.md): кнопка голоса или ELECTRIC переписывает все узлы. Круг видит её по смене голоса
(`0x85`) или ноты (`0x86`) — и ставит в очередь перечитать `DSP_NODES`, по одному на слот (`preset_pending`).
Ответ такого чтения несёт ещё и `preset` — значения пресета (по ним окно отличает «заводской» от «своего»).

Запись из окна (ручка-поправка MIC, профиль) занимает те же слоты: каждое обращение сеанса `write.apply` — чтение
типов, снимок, кадр, чтение назад — ждёт свой слот (`Sc3.pace`), а `WriteGuard` отдаёт apply правило слотов вместо
правила полных наборов (раз в 5 с).

Догадка «MUTE» (`MuteGuess`): аппаратный MUTE лишь обнуляет громкость канала, и одно чтение его не отличит от
«ползунок внизу» (docs/RESEARCH.md §14). Но MUTE обнуляет её скачком, а рука ведёт ползунок через промежуточные
ступени: громкость упала с ≥ 10 % до 0 между двумя соседними чтениями канала — вероятно, MUTE.
"""
from __future__ import annotations

import math
import struct
import time
from dataclasses import replace

from opensc3 import profiles as PR
from opensc3 import protocol as P
from opensc3 import reader as R
from opensc3 import write as W
from opensc3.guard import POLL_INTERVAL
from opensc3.model import Channel, Live, Sc3State

MAX_FAILS = 3   # неудачи подряд → опрос выключен до переподключения SC3
# «Обновить» в опросе: чего нет в круге (0x02). Поправку MIC оно не перечитывает: её меняют только окно и CLI, а
# CLI, пока окно держит SC3, к нему не попадёт — поправка читается в начале сессии и после записи.
REFRESH = tuple(c for c in R.FULL_SET if c not in R.POLL_CYCLE and c not in R.DSP_NODES)
META = ("preset", "preset_changed", "written")  # поля обновления не для Sc3State, а для бэкенда (подпись профиля)
_UNSET = object()
TRIM_STEP = 0.5   # шаг ручки-поправки, дБ (границы — write.TRIM_DB)
MUTE_DROP = 0.10  # с какого положения обнуление считается скачком MUTE, а не концом пути ползунка
MUTE_SLACK = 0.1  # запас на дрожание слотов


def cycle_gap(ctrl: int, cycle: tuple[int, ...] = R.POLL_CYCLE, interval: float = POLL_INTERVAL) -> float:
    """Наибольший промежуток между соседними чтениями `ctrl` в круге опроса, с."""
    pos = [i for i, c in enumerate(cycle) if c == ctrl]
    if not pos:
        raise ValueError(f"{ctrl:#04x} нет в круге опроса")
    n = len(cycle)
    return max((pos[(k + 1) % len(pos)] - p) % n or n for k, p in enumerate(pos)) * interval


# Соседние чтения канала не дальше этого — иначе скачок мог быть и рукой. Из круга: Mic — 1,1 с, Line In — 3,1 с.
MUTE_GAP = {c: cycle_gap(c) + MUTE_SLACK for c in (R.ADC1, R.LINE_IN)}


class MuteGuess:
    """Догадка «MUTE» по двум соседним чтениям одного канала. Без ввода-вывода, время — от вызывающего.

    - громкость упала с ≥ MUTE_DROP до 0 не дольше чем за `max_gap` → `muted=True, muted_guess=True`, колпачок
      остаётся на последнем ненулевом положении;
    - пока 0 — догадка держится; громкость вернулась (ровно к прежней — MUTE снят; к другой — это был ползунок) —
      обычное чтение;
    - плавный спуск, первое чтение, долгий перерыв — ползунок: `fader=0, muted=None`.
    Ноль — это `muted is None` из reader (сырая громкость 0), а не `fader == 0`: малое усиление Line In
    округляется до ступени 0, но MUTE это не он (`muted=False`).
    """

    def __init__(self, max_gap: float) -> None:
        self.max_gap = max_gap
        self.prev: float | None = None
        self.prev_at: float | None = None
        self.held: float | None = None   # положение колпачка до MUTE; None — догадки нет

    def feed(self, ch: Channel, now: float) -> Channel:
        prev, prev_at = self.prev, self.prev_at
        self.prev, self.prev_at = ch.fader, now
        if ch.fader is None:
            self.held = None
            return ch
        zero = ch.muted is None   # reader: сырая громкость 0 — MUTE или ползунок внизу
        if self.held is not None:
            if zero:
                return replace(ch, fader=self.held, muted=True, muted_guess=True)
            self.held = None
            return ch
        if zero and prev is not None and prev >= MUTE_DROP and 0 <= now - prev_at <= self.max_gap:
            self.held = prev
            return replace(ch, fader=prev, muted=True, muted_guess=True)
        return ch


class BadReply(ValueError):
    """Ответ пришёл, но разобрать его нельзя (короче раскладки) — считается неудачей чтения."""


class Plan:
    def __init__(self, full_set_first: bool = True, dsp: bool = False) -> None:
        """`full_set_first` — сначала полный набор по одному чтению на слот; `dsp` — узлы обработки голоса первыми
        (окно: без них ручка неактивна и ящик MIC пуст), даже без полного набора — пока окно было скрыто, их мог
        поменять CLI или кнопка. Перед ними — голос и нота: нажатие кнопки после этих чтений круг увидит как смену
        и перечитает узлы (иначе пресет, нажатый между чтением узлов и первым чтением голоса, остался бы незамеченным)."""
        start = list(R.FULL_SET) if full_set_first else []
        if dsp:
            first = [R.PITCH, R.AUTOTUNE, *R.DSP_NODES]
            start = first + [c for c in start if c not in first]
        self.queue: list[int] = start
        self.turn = 0
        self.mute = {ctrl: MuteGuess(gap) for ctrl, gap in MUTE_GAP.items()}
        self.nodes: dict[int, tuple[int, ...]] = {}   # последние чтения DSP_NODES (для числа кадров профиля)
        self.preset_pending: set[int] = set()          # перечитать после смены пресета; запись ждёт их
        self._seen = {"voice": _UNSET, "electric_key": _UNSET}

    def reread(self, ctrls, preset: bool = False) -> None:
        """В начало очереди, по порядку — по одному чтению на слот, без повторов: после записи или пресета эти узлы
        важнее остатка полного набора. `preset` — это значения нового пресета кнопки."""
        ctrls = list(ctrls)
        self.queue = ctrls + [c for c in self.queue if c not in ctrls]
        if preset:
            self.preset_pending.update(ctrls)

    def ready_to_write(self) -> bool:
        """Запись может занять слот: узлы обработки голоса прочитаны в этой сессии и пресет кнопки не ждёт
        перечитывания (писать поверх неизвестного пресета незачем, а «12 из 24» без узлов не посчитать)."""
        return not self.preset_pending and all(c in self.nodes for c in R.DSP_NODES)

    def nodes_state(self) -> dict[int, list[int]]:
        """Снимок прочитанных узлов в форме write.plan_write / profiles.diff."""
        return {a: list(v) for a, v in self.nodes.items()}

    def _preset(self, field: str, value) -> bool:
        """Голос или нота сменились по сравнению с прошлым чтением — значит, нажата кнопка и пресет переписал узлы:
        перечитать DSP_NODES (по одному на слот). Первое чтение — не смена."""
        was, self._seen[field] = self._seen[field], value
        if was is _UNSET or was == value:
            return False
        self.reread(R.DSP_NODES, preset=True)
        return True

    def next(self) -> int:
        """Адрес для очередного слота."""
        if self.queue:
            return self.queue.pop(0)
        ctrl = R.POLL_CYCLE[self.turn % len(R.POLL_CYCLE)]
        self.turn += 1
        return ctrl

    def retry(self, ctrl: int) -> None:
        """Чтение из очереди не удалось — вернуть его в начало (круг просто пойдёт дальше)."""
        if ctrl not in R.POLL_CYCLE and ctrl not in self.queue:
            self.queue.insert(0, ctrl)

    def refresh(self) -> None:
        """«Обновить» в опросе: то, чего нет в круге, — в ближайший слот. Пока в очереди что-то есть (идёт полный
        набор, повтор) — ничего: эти чтения и так свежие. Пачки не бывает: очередь отдаёт одно чтение на слот."""
        if self.queue:
            return
        self.queue.extend(REFRESH)

    def parse(self, ctrl: int, body: bytes, now: float | None = None) -> dict:
        """Ответ → поля `Sc3State`, которые он обновляет. `now` — time.monotonic() чтения (для догадки MUTE)."""
        now = time.monotonic() if now is None else now
        try:
            if ctrl == R.ADC1:
                return {"mic": self.mute[ctrl].feed(R.mic_channel(body), now)}
            if ctrl == R.QUERY:
                return {"dsp_load": R.dsp_load(body)}
            values = P.node_values(body)
            if len(values) < R.NEED.get(ctrl, 1):
                raise BadReply(f"узел {ctrl:#04x}: {len(values)} значений")
            if ctrl == R.LINE_IN:
                return {"line_in": self.mute[ctrl].feed(R.line_in_channel(values), now)}
            if ctrl in (R.AUTOTUNE, R.PITCH):
                field = "electric_key" if ctrl == R.AUTOTUNE else "voice"
                up = {field: R.electric_key(values) if ctrl == R.AUTOTUNE else R.voice(values)}
                if self._preset(field, up[field]):
                    up["preset_changed"] = True
                return up
            if ctrl in R.DSP_NODES:
                vals = tuple(values)
                self.nodes[ctrl] = vals
                up = {"nodes": {ctrl: vals}}
                if ctrl == R.MIC_TRIM:
                    up["mic_trim"] = R.mic_trim(values)
                if ctrl in self.preset_pending:
                    self.preset_pending.discard(ctrl)
                    up["preset"] = {ctrl: vals}
                return up
        except (KeyError, IndexError, struct.error) as e:
            raise BadReply(f"{ctrl:#04x}: {e}") from None
        raise BadReply(f"{ctrl:#04x}: не из набора опроса")


def merge(st: Sc3State, update: dict) -> Sc3State:
    """Поля из чтения опроса (или итога записи) → новое `Sc3State`. Чтение `0x07` даёт канал Mic без поправки —
    прочитанная поправка остаётся; `mic_trim` — поправка MIC в дБ (None — неизвестна); `nodes` — прочитанные узлы
    целиком, к уже известным. Поля META сюда не попадают (их забирает бэкенд)."""
    update = {k: v for k, v in update.items() if k not in META}
    trim = update.pop("mic_trim", st.mic.trim_db)
    mic = update.pop("mic", st.mic)
    nodes = {**st.nodes, **update.pop("nodes", {})}
    return replace(st, mic=replace(mic, trim_db=trim), nodes=nodes, **update)


# --- подпись профиля в шапке ----------------------------------------------------------------------------

PODCAST_LABEL = PR.PODCAST.title
BASE_CONNECT, BASE_PRESET, BASE_KNOWN, BASE_WRITTEN = "connect", "preset", "known", "written"


def journal_written(rows: list[dict]) -> dict[str, int]:
    """Последний сеанс журнала → {ключ: значение, которое он оставил} для параметров, которые он изменил. Сеанс-откат
    (`undoes`) — {}: он возвращает исходное, своё в SC3 после него не остаётся."""
    if not rows or any(r.get("undoes") for r in rows):
        return {}
    return {w.param.key: w.expect for w in W.undo_writes(rows)}


def written_matches(written: dict[str, int], nodes: dict[int, tuple[int, ...]]) -> bool:
    """В SC3 сейчас ровно то, что оставил последний сеанс записи (по всем его параметрам)."""
    state = {a: list(v) for a, v in nodes.items()}
    return bool(written) and all(W.current(W.BY_KEY[k], state) == v for k, v in written.items())


def podcast_matches(nodes: dict[int, tuple[int, ...]]) -> bool:
    """Все параметры «Подкаста» в SC3 такие, как в профиле (`profiles.diff` без отличий)."""
    return all(r.same for r in PR.diff(PR.PODCAST, {a: list(v) for a, v in nodes.items()}))


def profile_label(nodes: dict[int, tuple[int, ...]], base_mode: str, base: dict | None) -> str:
    """Подпись профиля в шапке. «» — ещё не ясно (узлы не прочитаны или окно не решило, чей это набор).
    - «Подкаст»: все параметры профиля совпадают;
    - «заводской»: в SC3 пресет панели (заводской обычный режим или голос/ELECTRIC с кнопки) — набор равен
      прочитанному сразу после подключения или нажатия кнопки, либо кнопку только что нажали;
    - «свой»: с тех пор что-то записали (окном или CLI)."""
    if any(c not in nodes for c in R.DSP_NODES) or base_mode == BASE_CONNECT:
        return ""
    if podcast_matches(nodes):
        return PODCAST_LABEL
    if base_mode == BASE_PRESET:
        return "заводской"
    if base_mode == BASE_KNOWN and base is not None:
        return "заводской" if all(nodes.get(c) == base.get(c) for c in R.DSP_NODES) else "свой"
    return "свой"


def trim_step(db: float, lo: float, hi: float) -> float:
    """Значение ручки → ближайший шаг 0,5 дБ в границах [lo, hi]."""
    return min(max(round(db / TRIM_STEP) * TRIM_STEP, lo), hi)


class WriteGuard:
    """Гвард, который окно отдаёт `write.apply` вместо AcpGuard. Эфир — те же проверки AcpGuard (`check_live`; ON и
    UNKNOWN — отказ). Интервал — правило лёгкого опроса, а не полных наборов: перед сеансом слот должен быть
    свободен (`check_poll`), а каждое обращение внутри сеанса само ждёт свой слот и отмечает его (`Sc3.pace`).
    Отметку полного набора (`mark`) сеанс записи не ставит: полного набора не было, слоты уже отмечены."""

    def __init__(self, guard) -> None:
        self.guard = guard

    def check(self, live: Live) -> str:
        return self.guard.check_poll(live)

    def check_live(self, live: Live) -> str:
        return self.guard.check_live(live)

    def mark(self) -> None:
        pass


def next_slot(t0: float, k: int, now: float, last: float, interval: float = POLL_INTERVAL) -> tuple[int, float]:
    """После слота k: номер и время следующего — по сетке t0 + n·interval и не раньше last + interval
    (last — начало прошлого чтения). Опоздали — пропущенные слоты не догоняются пачкой."""
    n = max(k + 1, math.ceil((now - t0) / interval - 1e-9))
    return n, max(t0 + n * interval, last + interval)

