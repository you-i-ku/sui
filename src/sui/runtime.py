"""単一の窓口と、受信時刻を押し外で仕事を実行するホスト (S3・S4a)。"""

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from queue import Empty, Queue
from threading import Lock, Thread
from time import monotonic
from types import MappingProxyType
from typing import Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from .action_types import Command, DecisionReading
    from .dispatch import WaitDispatcher
    from .clock_contracts import ClockSource

from .agent import Agent, Commit as Prepared, Draft, View, _read_jobs, _evaluation_ns, plan, read
from .clock import Clock
from .contracts import ContractRef
from .ids import IdSource, Ref, RefKind
from .ledger import Ledger
from .records import AttemptStarted, Decided, Observed, Payload, Producer, Record, Role
from .s1_contracts import ATTEMPT, OUTCOME
from .s3_contracts import ABANDON, ENDED
from .s4_contracts import BOOT as _BOOT, LISTEN as _LISTEN
from .model import evaluation_timing, _is_action_model
from .action_runtime import ActionDone
from .dispatch import DispatchNotice


class Hand(Protocol):
    """資源の宣言はホストの生存中固定。execute の例外は結果なしの終了。"""

    def resources(self, action: str) -> frozenset[str]: ...
    def execute(self, action: str) -> str: ...


class Drive(Protocol):
    """返事は有限。例外の後は同じ出来事を再び聞かれうる (K1)。"""

    def react(self, status: "Status", event: object) -> Iterable["Reconsider | Abandon"]: ...


@dataclass(frozen=True, slots=True, kw_only=True)
class Reconsider:
    candidates: tuple[str, ...]
    u: float


@dataclass(frozen=True, slots=True, kw_only=True)
class Abandon:
    job: Ref


@dataclass(frozen=True, slots=True, kw_only=True)
class Arrived:
    route: str
    content: Payload
    contract: ContractRef
    source_id: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class Tick:
    mono_ns: int


@dataclass(frozen=True, slots=True, kw_only=True)
class Thought:
    work: str
    draft: Draft | None = None
    error: str | None = None
    decision_reading: "DecisionReading | None" = None
    _command: "Command | None" = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if (self.draft is None) == (self.error is None):
            raise ValueError("Thought: exactly one of draft and error is required")


@dataclass(frozen=True, slots=True, kw_only=True)
class Done:
    attempt: Ref
    outcome: str


@dataclass(frozen=True, slots=True, kw_only=True)
class Failed:
    attempt: Ref
    error: str


@dataclass(frozen=True, slots=True, kw_only=True)
class Boot:
    pass


@dataclass(frozen=True, slots=True, kw_only=True)
class Listen:
    route: str
    open: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class Envelope:
    number: int
    event: object
    received_ns: int


@dataclass(frozen=True, slots=True, kw_only=True)
class Think:
    work: str
    view: View
    candidates: tuple[str, ...]
    u: float
    now_ns: int | None = None
    observed_ns: int | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class Act:
    attempt: Ref
    action: str
    command: "Command | None" = None


@dataclass(frozen=True, slots=True, kw_only=True)
class Status:
    frontier: frozenset[str]
    pending: tuple[Ref, ...]
    awaiting: tuple[Ref, ...]
    queued: tuple[Ref, ...]
    thinking: int
    waiting: int
    used: Mapping[str, int]
    capacity: Mapping[str, int]

    def __post_init__(self) -> None:
        object.__setattr__(self, "used", MappingProxyType(dict(self.used)))
        object.__setattr__(self, "capacity", MappingProxyType(dict(self.capacity)))


@dataclass(frozen=True, slots=True, kw_only=True)
class Commit:
    work: str
    commit: Prepared


@dataclass(frozen=True, slots=True, kw_only=True)
class Released:
    work: str


@dataclass(frozen=True, slots=True, kw_only=True)
class Observe:
    record: Record


@dataclass(frozen=True, slots=True, kw_only=True)
class Start:
    job: Ref
    attempt: Record
    act: Act
    reservation: Record | None = None


Item = Commit | Released | Observe | Start


@dataclass
class Pledges:
    """未完の引き受けをホストが保つ。窓口を作り直しても捨てない。

    記録は書く前に預け、効き目が済んでから外す。預かった記録は再作成しない。
    信念の葉は預けず、プロセスをまたぐ永続化もしない (K1〜K14)。
    latest_nsは最後に成功した受け付け。Thinkのnowも作り直しで保つ (J2・J3・J5)。
    所要ありは評価nowと未到着observedを分け、両方を保つ (J7・J13)。
    """

    items: list[Item] = field(default_factory=list)
    thinking: dict[str, Think] = field(default_factory=dict)
    waiting: list[Reconsider] = field(default_factory=list)
    requests: list[Reconsider | Abandon] = field(default_factory=list)
    notices: list[object] = field(default_factory=list)
    abandons: dict[Ref, Record] = field(default_factory=dict)
    issued: int = 0
    latest_ns: tuple[Ref, int] | None = None
    latest_check_events: tuple = ()
    commands: dict[Ref, tuple] = field(default_factory=dict)
    bindings: dict[str, tuple] = field(default_factory=dict)


class Window:
    """唯一の書き手。派生する列・資源は毎回台帳から読む (W11・K12)。

    呼ぶスレッドは一つ。可変な実行状態は送り箱・採用の印だけで、
    未完の約束はホストの Pledges に置く。capacity と資源の宣言は固定。
    """

    def __init__(self, *, agent: Agent, ledger: Ledger, clock: Clock, ids: IdSource,
                 membrane: Producer, route: str, hand: Hand, drive: Drive,
                 capacity: Mapping[str, int], pledges: Pledges) -> None:
        if agent._belief is None:
            raise ValueError("Window: a belief record is required")
        if "think" not in capacity or any(type(n) is not int or n <= 0
                                          for n in capacity.values()):
            raise ValueError("capacity: positive integers including think are required")
        self.agent, self.ledger, self.clock, self.ids = agent, ledger, clock, ids
        self.membrane, self.route, self.hand, self.drive = membrane, route, hand, drive
        self.capacity = MappingProxyType(dict(capacity))
        self.pledges = pledges
        self._outbox: list[Think | Act] = []
        self._needs_adopt = True
        for action in agent._model.actions:
            self._resources(action)
        self.status()  # 過剰な貸し出しは作り直す時にも検査する。書き込みはしない。

    def _resources(self, action):
        resources = self.hand.resources(action)
        if not resources <= self.capacity.keys():
            raise ValueError("hand: an undeclared capacity is required")
        return resources

    def _reading(self):
        snapshot = self.ledger.snapshot(self.ledger.heads())
        records = snapshot.records
        jobs = _read_jobs(self.agent._model, records)
        attempted = {r.body.job for r in records if isinstance(r.body, AttemptStarted)}
        if _is_action_model(self.agent._model):
            from .s4b_action_contracts import REPORT
            arrived = {r.body.caused_by for r in records if isinstance(r.body, Observed)
                       and r.body.contract in (REPORT, ENDED)}
        else:
            arrived = {r.body.caused_by for r in records if isinstance(r.body, Observed)}
        awaiting = {r.id: jobs[r.body.job] for r in records
                    if isinstance(r.body, AttemptStarted) and r.body.job in jobs
                    and r.id not in arrived}
        queued = [r for r in records if r.id in jobs and r.id not in attempted]
        queued.sort(key=lambda r: (r.at.run_index, r.at.seq,
                                  self.ledger.entries_of(r.id)[0].cid))
        used = {name: 0 for name in self.capacity}
        used["think"] = len(self.pledges.thinking)
        for action in awaiting.values():
            for name in self._resources(action):
                used[name] += 1
        if any(used[name] > self.capacity[name] for name in used):
            raise ValueError("capacity: outstanding work exceeds capacity")
        return jobs, queued, awaiting, used, read(
            self.agent._model, records, unread_preferences=snapshot.unread_preferences)

    def status(self) -> Status:
        """時計に触れず、台帳から数えた読み取り専用の写し (W2・W4・W6・R1)。"""
        _, queued, awaiting, used, reading = self._reading()
        return Status(frontier=self.agent.frontier,
                      pending=tuple(sorted(reading.pending, key=str)),
                      awaiting=tuple(sorted(awaiting, key=str)),
                      queued=tuple(r.id for r in queued),
                      thinking=len(self.pledges.thinking), waiting=len(self.pledges.waiting),
                      used=used, capacity=self.capacity)

    def _observation(self, *, route, content, contract, received_ns,
                     caused_by=None, source_id=None):
        return Record(id=self.ids.new(RefKind.OBSERVATION), at=self.clock.now(),
                      writer=Role.MEMBRANE, producer=self.membrane,
                      body=Observed(route=route, content=content, contract=contract,
                                    caused_by=caused_by, source_id=source_id,
                                    received_ns=received_ns))

    def declare_clock_source(self, source: "ClockSource") -> None:
        """Queue provenance after BOOT, without a world/nonarrival checkpoint.

        Pledges retains the same record across a window reconstruction. This is
        metadata, so it does not change latest_ns, check_events or drive notices.
        """
        from .clock_contracts import ClockSource, SOURCE
        from .action_types import ActionInputError
        if not isinstance(source, ClockSource) or source.run != self.clock.run:
            raise ActionInputError(reason="schema", detail="clock source must belong to the host run")
        self.pledges.items.append(Observe(record=self._observation(
            route="sui.clock", contract=SOURCE, content=Payload.json(source.as_json()),
            received_ns=None)))

    def accept(self, envelope: Envelope) -> None:
        """全部作ってから預け、書かない。例外なら同じ封筒で再試行 (K11)。

        二度目のThoughtだけは知らせない。結果は毎回別の名札で残す (R10〜R13)。
        ホストの受信時刻を使い、成功時だけlatest_nsを確定する (J2・J3・J5)。
        起動・開閉はモデルによらず残し、駆動の依頼は受け付けない (P11)。
        """
        event, p = envelope.event, self.pledges
        after = (sorted(self.ledger.heads()) if evaluation_timing(self.agent._model).needs_check_events
                 and isinstance(event, (Tick, Thought)) else None)
        item = None
        if isinstance(event, Tick):
            pass
        elif isinstance(event, (Boot, Listen)):
            item = Observe(record=self._observation(
                route="membrane", content=Payload.json({} if isinstance(event, Boot)
                    else {"route": event.route, "open": event.open}),
                contract=_BOOT if isinstance(event, Boot) else _LISTEN,
                received_ns=envelope.received_ns))
        elif isinstance(event, Arrived):
            item = Observe(record=self._observation(
                route=event.route, content=event.content, contract=event.contract,
                source_id=event.source_id, received_ns=envelope.received_ns))
            if _is_action_model(self.agent._model):
                from .clock_contracts import SOURCE
                if event.contract == SOURCE:
                    p.items.append(item)
                    return
        elif isinstance(event, Thought):
            if event.work not in p.thinking or any(
                    isinstance(i, (Commit, Released)) and i.work == event.work for i in p.items):
                p.latest_ns = (self.clock.run, envelope.received_ns)
                if evaluation_timing(self.agent._model).needs_check_events:
                    p.latest_check_events = ({"unrecorded": {"kind": "thought", "reading": envelope.received_ns,
                                                           "after": after}},)
                return
            if event.draft is not None and _is_action_model(self.agent._model):
                from .action_runtime import bind
                from .action_types import ActionInputError
                work = p.thinking[event.work]
                if event.decision_reading is None or event.decision_reading.run != self.clock.run:
                    raise ActionInputError(reason='schema', detail='model.8 Thought requires the worker decision reading')
                if event.draft.parents != work.view.frontier or event.draft.belief != work.view.belief:
                    raise ActionInputError(reason='schema', detail='Thought Draft differs from frozen Think')
                if event.work not in p.bindings:
                    command = event._command if event._command is not None else bind(work, event.draft, event.decision_reading)
                    p.bindings[event.work] = (command, event.decision_reading)
                prepared = self.agent.prepare(event.draft, clock=self.clock, ids=self.ids)
                p.commands[prepared.job.id] = p.bindings[event.work]
                item = Commit(work=event.work, commit=prepared)
            else:
                item = (Commit(work=event.work, commit=self.agent.prepare(
                    event.draft, clock=self.clock, ids=self.ids)) if event.draft is not None
                    else Released(work=event.work))
        elif isinstance(event, DispatchNotice):
            from .action_runtime import confirmation
            item = Observe(record=confirmation(self, event, envelope.received_ns))
        elif isinstance(event, ActionDone):
            from .action_runtime import completion
            item = Observe(record=completion(self, event, envelope.received_ns))
        elif isinstance(event, (Done, Failed)):
            content, contract = (({"outcome": event.outcome}, OUTCOME) if isinstance(event, Done)
                                 else ({"error": event.error}, ENDED))
            item = Observe(record=self._observation(
                route=self.route, content=Payload.json(content), contract=contract,
                caused_by=event.attempt, received_ns=envelope.received_ns))
        else:
            raise TypeError("accept: expected a host or worker event")
        if item is not None:
            p.items.append(item)
        p.notices.append(event)
        p.latest_ns = (self.clock.run, envelope.received_ns)
        if evaluation_timing(self.agent._model).needs_check_events:
            p.latest_check_events = (({"fact": str(item.record.id)},) if isinstance(item, Observe) else
                ({"unrecorded": {"kind": "tick" if isinstance(event, Tick) else "thought",
                                 "reading": envelope.received_ns, "after": after}},))

    def _write_items(self):
        p = self.pledges
        while p.items:
            item = p.items[0]
            if isinstance(item, Commit):
                self.agent.commit(item.commit, ledger=self.ledger)
                p.thinking.pop(item.work)
            elif isinstance(item, Released):
                p.thinking.pop(item.work)
            elif isinstance(item, Observe):
                self.ledger.accept(item.record)
                self._needs_adopt = True
            elif isinstance(item, Start):
                self.ledger.accept(item.attempt)
                if item.reservation is not None:
                    self.ledger.accept(item.reservation)
                if item.act.command is not None:
                    self._needs_adopt = True
                self._outbox.append(item.act)
            p.items.pop(0)

    def _adopt(self):
        if self.agent.frontier != self.ledger.heads():
            self.agent.adopt(self.ledger, clock=self.clock, ids=self.ids)

    def settle(self) -> None:
        """書く→採用→作用の開始→知らせ→依頼→思考の開始を安定するまで。

        採用の印は観測・ABANDON・構築時だけ。先端が同じでも印を下ろす (R1)。
        考える前・ABANDON の判定前は先端が違えば採用 (W5・W6b・K6b)。
        例外なら窓口を捨て、drain 後、同じ預かり箱でこの手順を続ける。
        記録・作用・成功した知らせを二重にしない (K1〜K14)。
        """
        p = self.pledges
        while True:
            changed = bool(p.items)
            self._write_items()
            if self._needs_adopt:
                self._adopt()
                self._needs_adopt = False
                changed = True
            jobs, queued, _, used, _ = self._reading()
            for job in queued:
                action = jobs[job.id]
                resources = self._resources(action)
                if all(used[name] < self.capacity[name] for name in resources):
                    if _is_action_model(self.agent._model):
                        from .action_runtime import start
                        p.items.append(start(self, job, action))
                    else:
                        attempt = Record(
                            id=self.ids.new(RefKind.ATTEMPT), at=self.clock.now(),
                            writer=Role.MEMBRANE, producer=self.membrane,
                            body=AttemptStarted(job=job.id, content=Payload.json({}), contract=ATTEMPT))
                        p.items.append(Start(job=job.id, attempt=attempt,
                                             act=Act(attempt=attempt.id, action=action)))
                    self._write_items()
                    for name in resources:
                        used[name] += 1
                    changed = True
            while p.notices:
                requests = tuple(self.drive.react(self.status(), p.notices[0]))
                p.requests.extend(requests)
                p.notices.pop(0)
                changed = True
            while p.requests:
                request = p.requests[0]
                if isinstance(request, Reconsider):
                    p.waiting.append(request)
                elif isinstance(request, Abandon):
                    self._adopt()
                    if request.job in self.agent._reading.pending:
                        if request.job not in p.abandons:
                            p.abandons[request.job] = Record(
                                id=self.ids.new(RefKind.DECISION), at=self.clock.now(),
                                writer=Role.MODEL, producer=self.agent.producer,
                                body=Decided(inputs=(request.job,), contract=ABANDON,
                                             content=Payload.json({"job": str(request.job)})))
                        self.ledger.append(p.abandons[request.job], self.agent.frontier)
                        self._needs_adopt = True
                    p.abandons.pop(request.job, None)
                else:
                    raise TypeError("drive: expected Reconsider or Abandon")
                p.requests.pop(0)
                changed = True
            while p.waiting and self.status().used["think"] < self.capacity["think"]:
                request = p.waiting[0]
                self._adopt()
                now, observed = None, None
                requirements = evaluation_timing(self.agent._model)
                if requirements.needs_axis:
                    axis = self.agent._reading.timeline
                    if (axis is None or self.clock.run not in axis.runs
                            or p.latest_ns is None or p.latest_ns[0] != self.clock.run):
                        raise ValueError("Think: current run boot and received time are required")
                    now = axis.to_axis(*p.latest_ns)
                    if _is_action_model(self.agent._model):
                        # Model.8 clock-process declarations and command thresholds
                        # use run-local raw readings, not the cross-run display axis.
                        now = p.latest_ns[1]
                    if requirements.needs_receipt_boundary:
                        observed = now
                        now = _evaluation_ns(self.agent._reading, self.clock.run, now)
                options = {}
                if requirements.needs_check_events:
                    sources = tuple(source if "fact" in source else {"unrecorded": {
                        "kind": source["unrecorded"]["kind"],
                        "reading": (source["unrecorded"]["reading"] if _is_action_model(self.agent._model)
                                    else axis.to_axis(self.clock.run, source["unrecorded"]["reading"])),
                        "after": source["unrecorded"]["after"]}}
                        for source in p.latest_check_events)
                    options["check_events"] = sources
                work = Think(work=f"think:{p.issued + 1}",
                             view=self.agent.view(now_ns=now, observed_ns=observed, **options),
                             candidates=request.candidates, u=request.u,
                             now_ns=now, observed_ns=observed)
                p.thinking[work.work] = work
                self._outbox.append(work)
                p.issued += 1
                p.waiting.pop(0)
                changed = True
            if not changed:
                return

    def drain(self) -> tuple[Think | Act, ...]:
        """未配送の仕事を全部渡して空にする。失敗した窓口も回収する (K3・K13b)。"""
        work = tuple(self._outbox)
        self._outbox.clear()
        return work


def _perform(work: Think | Act, hand: Hand) -> Thought | Done | Failed:
    """係が持つのは入力と手だけ。台帳・主体・時計に触らない。"""
    if isinstance(work, Think):
        try:
            return Thought(work=work.work, draft=plan(work.view, work.candidates, u=work.u))
        except Exception as exc:
            return Thought(work=work.work, error=type(exc).__name__)
    try:
        if work.command is not None:
            from .action_types import ActionIncomplete
            raise ActionIncomplete(reason="algorithm_unavailable", detail="command execution belongs to stage 3")
        return Done(attempt=work.attempt, outcome=hand.execute(work.action))
    except Exception as exc:
        return Failed(attempt=work.attempt, error=type(exc).__name__)


class ThreadHost:
    """SQLite の接続を開いたスレッドが run_until を呼ぶ。書く接続は一つ。"""

    def __init__(self, make_window: Callable[[Pledges], Window], *, clock: Clock,
                 dispatcher: "WaitDispatcher | None" = None,
                 clock_source: "ClockSource | None" = None) -> None:
        self._dispatcher = dispatcher
        self._clock_source = clock_source
        self._source_queued = False
        self._make_window = make_window
        self.pledges = Pledges()
        self.window: Window | None = None
        self._queue: Queue[Envelope] = Queue()
        self._current: Envelope | None = None
        self._unstarted: list[tuple[Think | Act, Hand]] = []
        self._number = 1
        self._lock = Lock()
        self._clock = clock
        self._boot_pending = True
        self._current = Envelope(number=1, event=Boot(), received_ns=clock.mono_ns())

    def post(self, event) -> None:
        with self._lock:
            self._number += 1
            self._queue.put(Envelope(number=self._number, event=event,
                                     received_ns=self._clock.mono_ns()))

    def _collect(self):
        if self.window is not None:
            self._unstarted.extend((work, self.window.hand) for work in self.window.drain())

    def _worker(self, work, hand):
        if isinstance(work, Think) and _is_action_model(work.view.model):
            from .action_runtime import think
            self.post(think(work, self._clock, plan))
        elif isinstance(work, Act) and work.command is not None:
            from .action_runtime import execute
            self.post(execute(work, hand, self._dispatcher, self.post))
        else:
            self.post(_perform(work, hand))

    def _start(self):
        while self._unstarted:
            work, hand = self._unstarted[0]
            Thread(target=self._worker, args=(work, hand), daemon=True).start()
            self._unstarted.pop(0)

    def _window_failed(self, original):
        self._collect()
        self.window = None
        if self._boot_pending:
            return
        try:
            self._start()
        except Exception as start_error:
            start_error.__context__ = None
            original.__context__ = start_error

    def run_until(self, done: Callable[[Status], bool], *, timeout: float) -> bool:
        """作り直し→回収→開始→終了判定→受信待ちの順。

        最初のBootはこの順序より先に受け付けて片づける。完了まで仕事は始めない (T9)。

        本体の直接検証は R2・R4〜R8 と本体版 K9/K14
        (test_k9_thread…・test_k14_thread…)。R3 は SQLite の接続スレッド制約。
        R1 は ManualHost 経由の窓口と同期の一致、K11 は手動ホストの封筒再配送。

        accept 成功時だけ封筒を離す。窓口の例外では回収して窓口を捨て、
        開始も試して元の例外を上げる。開始の失敗は __context__ に残す。
        開始だけの失敗は窓口を保つ。次の呼び出しで未完の同じ仕事を続ける。
        手・思考は daemon スレッド、結果は post だけで返し、手を止めない。
        """
        deadline = monotonic() + timeout
        while True:
            if self._boot_pending:
                try:
                    if self.window is None:
                        self.window = self._make_window(self.pledges)
                    if self._clock_source is None and _is_action_model(self.window.agent._model):
                        from .clock import SystemClock
                        if isinstance(self._clock, SystemClock):
                            from .clock_contracts import system_clock_source
                            self._clock_source = system_clock_source(self._clock)
                    if self._current is not None:
                        self.window.accept(self._current)
                        self._current = None
                    if self._clock_source is not None and not self._source_queued:
                        self.window.declare_clock_source(self._clock_source)
                        self._source_queued = True
                    self.window.settle()
                    self._boot_pending = False
                except Exception as exc:
                    self._window_failed(exc)
                    raise
            if self.window is None:
                try:
                    self.window = self._make_window(self.pledges)
                    self.window.settle()
                except Exception as exc:
                    self._window_failed(exc)
                    raise
            self._collect()
            self._start()
            if done(self.window.status()):
                return True
            if self._current is None:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    return False
                try:
                    self._current = self._queue.get(timeout=remaining)
                except Empty:
                    return False
            try:
                self.window.accept(self._current)
                self._current = None
                self.window.settle()
            except Exception as exc:
                self._window_failed(exc)
                raise
