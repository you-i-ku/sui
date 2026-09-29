"""単一の窓口と、窓口の外で考え・作用を実行するホスト (S3)。"""

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from queue import Empty, Queue
from threading import Lock, Thread
from time import monotonic
from types import MappingProxyType
from typing import Protocol

from .agent import Agent, Commit as Prepared, Draft, View, _read_jobs, plan, read
from .clock import Clock
from .contracts import ContractRef
from .ids import IdSource, Ref, RefKind
from .ledger import Ledger
from .records import AttemptStarted, Decided, Observed, Payload, Producer, Record, Role
from .s1_contracts import ATTEMPT, OUTCOME
from .s3_contracts import ABANDON, ENDED


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
class Envelope:
    number: int
    event: object


@dataclass(frozen=True, slots=True, kw_only=True)
class Think:
    work: str
    view: View
    candidates: tuple[str, ...]
    u: float


@dataclass(frozen=True, slots=True, kw_only=True)
class Act:
    attempt: Ref
    action: str


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


Item = Commit | Released | Observe | Start


@dataclass
class Pledges:
    """未完の引き受けをホストが保つ。窓口を作り直しても捨てない。

    記録は書く前に預け、効き目が済んでから外す。預かった記録は再作成しない。
    信念の葉は預けず、プロセスをまたぐ永続化もしない (K1〜K14)。
    """

    items: list[Item] = field(default_factory=list)
    thinking: dict[str, Think] = field(default_factory=dict)
    waiting: list[Reconsider] = field(default_factory=list)
    requests: list[Reconsider | Abandon] = field(default_factory=list)
    notices: list[object] = field(default_factory=list)
    abandons: dict[Ref, Record] = field(default_factory=dict)
    issued: int = 0


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
        records = self.ledger.snapshot(self.ledger.heads()).records
        jobs = _read_jobs(self.agent._model, records)
        attempted = {r.body.job for r in records if isinstance(r.body, AttemptStarted)}
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
        return jobs, queued, awaiting, used, read(self.agent._model, records)

    def status(self) -> Status:
        """時計に触れず、台帳から数えた読み取り専用の写し (W2・W4・W6・R1)。"""
        _, queued, awaiting, used, reading = self._reading()
        return Status(frontier=self.agent.frontier,
                      pending=tuple(sorted(reading.pending, key=str)),
                      awaiting=tuple(sorted(awaiting, key=str)),
                      queued=tuple(r.id for r in queued),
                      thinking=len(self.pledges.thinking), waiting=len(self.pledges.waiting),
                      used=used, capacity=self.capacity)

    def _observation(self, *, route, content, contract, caused_by=None, source_id=None):
        return Record(id=self.ids.new(RefKind.OBSERVATION), at=self.clock.now(),
                      writer=Role.MEMBRANE, producer=self.membrane,
                      body=Observed(route=route, content=content, contract=contract,
                                    caused_by=caused_by, source_id=source_id))

    def accept(self, envelope: Envelope) -> None:
        """全部作ってから預け、書かない。例外なら同じ封筒で再試行 (K11)。

        二度目の Thought・結果は知らせも預けない (W8)。Arrived は受け取りごと
        別の事実で、試みへ対応づけない (W9・K8・K8b)。Tick は知らせだけ。
        """
        event, p = envelope.event, self.pledges
        item = None
        if isinstance(event, Tick):
            pass
        elif isinstance(event, Arrived):
            item = Observe(record=self._observation(
                route=event.route, content=event.content, contract=event.contract,
                source_id=event.source_id))
        elif isinstance(event, Thought):
            if event.work not in p.thinking or any(
                    isinstance(i, (Commit, Released)) and i.work == event.work for i in p.items):
                return
            item = (Commit(work=event.work, commit=self.agent.prepare(
                event.draft, clock=self.clock, ids=self.ids)) if event.draft is not None
                else Released(work=event.work))
        elif isinstance(event, (Done, Failed)):
            if event.attempt not in self.status().awaiting or any(
                    isinstance(i, Observe) and i.record.body.caused_by == event.attempt
                    for i in p.items):
                return
            content, contract = (({"outcome": event.outcome}, OUTCOME) if isinstance(event, Done)
                                 else ({"error": event.error}, ENDED))
            item = Observe(record=self._observation(
                route=self.route, content=Payload.json(content), contract=contract,
                caused_by=event.attempt))
        else:
            raise TypeError("accept: expected a host or worker event")
        if item is not None:
            p.items.append(item)
        p.notices.append(event)

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
                work = Think(work=f"think:{p.issued + 1}", view=self.agent.view(),
                             candidates=request.candidates, u=request.u)
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
        return Done(attempt=work.attempt, outcome=hand.execute(work.action))
    except Exception as exc:
        return Failed(attempt=work.attempt, error=type(exc).__name__)


class ThreadHost:
    """SQLite の接続を開いたスレッドが run_until を呼ぶ。書く接続は一つ。"""

    def __init__(self, make_window: Callable[[Pledges], Window]) -> None:
        self._make_window = make_window
        self.pledges = Pledges()
        self.window: Window | None = None
        self._queue: Queue[Envelope] = Queue()
        self._current: Envelope | None = None
        self._unstarted: list[tuple[Think | Act, Hand]] = []
        self._number = 0
        self._lock = Lock()

    def post(self, event) -> None:
        with self._lock:
            self._number += 1
            self._queue.put(Envelope(number=self._number, event=event))

    def _collect(self):
        if self.window is not None:
            self._unstarted.extend((work, self.window.hand) for work in self.window.drain())

    def _worker(self, work, hand):
        self.post(_perform(work, hand))

    def _start(self):
        while self._unstarted:
            work, hand = self._unstarted[0]
            Thread(target=self._worker, args=(work, hand), daemon=True).start()
            self._unstarted.pop(0)

    def _window_failed(self, original):
        self._collect()
        self.window = None
        try:
            self._start()
        except Exception as start_error:
            start_error.__context__ = None
            original.__context__ = start_error

    def run_until(self, done: Callable[[Status], bool], *, timeout: float) -> bool:
        """作り直し→回収→開始→終了判定→受信待ちの順。

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
