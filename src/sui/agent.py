"""事実から信念と帳面を作り、決定を記録する主体。"""

from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from dataclasses import dataclass as _dataclass, field as _field
from types import MappingProxyType as _MappingProxyType
import math as _math

import numpy as _np

from .clock import Clock as _Clock
from .ids import IdSource as _IdSource, Ref as _Ref, RefKind as _RefKind
from .inference import (
    ModelViolation as _ModelViolation, belief as _belief, efe as _efe, expected_A as _expected_A, ledger as _ledger,
    log_likelihood as _log_likelihood, novelty as _novelty,
    policy_posterior as _policy_posterior, select as _select,
    reachable as _reachable, filter_log as _filter_log, arrival_posterior as _arrival_posterior,
    _log_A, _log_predict, _log_probability, _log_update,
)
from .s1_contracts import ACTION, BELIEF, DECISION, ATTEMPT as _ATTEMPT, OUTCOME as _OUTCOME
from .s3_contracts import ABANDON as _ABANDON
from .s4_contracts import BOOT as _BOOT, LISTEN as _LISTEN, BELIEF as _TIME_BELIEF, DECISION as _TIME_DECISION
from .timeline import (Timeline as _Timeline, TimelineError as _TimelineError,
                       ArrivalStats as _ArrivalStats, timeline as _timeline,
                       _facts, _membrane, _listen, _arrivals)
from .model import GenerativeModel as _GenerativeModel, model_ref as _model_ref, _readonly
from .ledger import Ledger as _Ledger, DerivedParent as _DerivedParent, UnknownEntry as _UnknownEntry
from .records import (
    AttemptStarted as _AttemptStarted, Decided as _Decided,
    JobOpened as _JobOpened, Observed as _Observed, Payload as _Payload,
    Prediction as _Prediction, Producer as _Producer, Record as _Record,
    Role as _Role, StateRef as _StateRef,
)


CODE_VERSION = "s3"


class ModelMismatch(ValueError):
    """保存されたモデルの参照が異なる。"""


class RebuildMismatch(ValueError):
    def __init__(self, *, fields: tuple[str, ...]) -> None:
        self.fields = fields
        super().__init__(f"rebuilt content differs in {fields!r}")


class ModelFalsified(ValueError):
    """読めた事実の組をモデルのどの仮説も説明できない。"""


@_dataclass(frozen=True, slots=True, kw_only=True)
class Reading:
    n: _Mapping[str, _np.ndarray]
    unread: _Mapping[_Ref, str]
    pending: _Mapping[_Ref, str]
    timeline: _Timeline | None = None
    sequence: tuple[tuple[int, int, int, _Ref, str, str], ...] = ()
    arrivals: _Mapping[str, _ArrivalStats] = _field(default_factory=dict)
    _clock_issues: tuple[dict, ...] = ()

    def __post_init__(self) -> None:
        counts = {}
        for action, value in self.n.items():
            copy = _np.array(value, dtype=_np.int64, copy=True)
            copy.setflags(write=False)
            counts[action] = copy
        object.__setattr__(self, "n", _MappingProxyType(counts))
        object.__setattr__(self, "unread", _MappingProxyType(dict(self.unread)))
        object.__setattr__(self, "pending", _MappingProxyType(dict(self.pending)))
        object.__setattr__(self, "arrivals", _MappingProxyType(dict(self.arrivals)))
        object.__setattr__(self, "_clock_issues", tuple(
            _MappingProxyType(dict(issue)) for issue in self._clock_issues))


def _json_content(content: _Payload):
    try:
        return content.as_json()
    except (ValueError, UnicodeError):
        return None


def _named_content(content, key):
    data = _json_content(content)
    if isinstance(data, dict) and set(data) == {key} and isinstance(data[key], str):
        return data[key]
    return None


def _read_jobs(model: _GenerativeModel, records: _Iterable[_Record]) -> dict[_Ref, str]:
    jobs = {}
    for record in records:
        if isinstance(record.body, _JobOpened) and record.body.contract == ACTION:
            action = _named_content(record.body.content, "action")
            if action in model.actions:
                jobs[record.id] = action
    return jobs


def read(model: _GenerativeModel, records: _Iterable[_Record]) -> Reading:
    """事実の集合から読む。順番待ちも pending、観測は約束を問わず終端。

    ABANDON は対応する仕事だけを pending から外す。
    静的な読みはS3のまま。時間の読みは受信順・到達可能性・開閉から
    作り直す。時刻不明を補わず、Qなしの結果は回数として読む。
    到着の本文は問わない (T7・T7b・Q9〜Q13・H1〜H10)。
    """
    records = _facts(records)
    timed = _timed(model)
    axis, issues, arrivals, counted = None, (), {}, set()
    if timed:
        try:
            axis = _timeline(records)
            arrivals, counted = _arrivals(records, axis, model.arrivals)
        except _TimelineError as exc:
            issues = exc.clock_issues
            arrivals = {route: _ArrivalStats(N=0, T_ns=0) for route in model.arrivals}
    support = model.D > 0 if model.Q is None else _reachable(model.D, model.Q)
    jobs = _read_jobs(model, records)
    arrived = {r.body.caused_by for r in records if isinstance(r.body, _Observed)}
    finished = {r.body.job for r in records
                if isinstance(r.body, _AttemptStarted) and r.id in arrived}
    abandoned = {r.body.inputs[0] for r in records
                 if isinstance(r.body, _Decided) and r.body.contract == _ABANDON
                 and len(r.body.inputs) == 1
                 and _named_content(r.body.content, "job") == str(r.body.inputs[0])}
    attempts = {}
    for record in records:
        if isinstance(record.body, _AttemptStarted):
            body = record.body
            attempts[record.id] = (jobs.get(body.job)
                                   if body.contract == _ATTEMPT and
                                   _json_content(body.content) == {} else None)
    n = {action: _np.zeros(len(model.outcomes), dtype=_np.int64) for action in model.actions}
    unread, readable = {}, {}
    by_id = {record.id: record for record in records}
    for record in records:
        if not isinstance(record.body, _Observed):
            continue
        body, reason = record.body, None
        if timed:
            if ((_membrane(record, _BOOT) and _json_content(body.content) != {})
                    or (_membrane(record, _LISTEN) and _listen(record) is None)):
                unread[record.id] = "content"
                continue
            needs_time = ((model.Q is not None and body.caused_by is not None)
                          or _membrane(record, _BOOT) or _membrane(record, _LISTEN)
                          or (body.caused_by is None and body.route in model.arrivals))
            if needs_time:
                if body.received_ns is None:
                    unread[record.id] = "no_receipt_time"
                    continue
                if axis is None or record.at.run not in axis.runs:
                    unread[record.id] = "no_clock"
                    continue
            if _membrane(record, _BOOT) or _membrane(record, _LISTEN):
                continue
            if record.id in counted:
                continue
        outcome = _named_content(body.content, "outcome")
        action = attempts.get(body.caused_by)
        if body.caused_by is None:
            reason = "no_attempt"
        elif body.caused_by not in attempts:
            reason = "unknown_attempt"
        elif action is None:
            reason = "unreadable_attempt"
        elif body.contract != _OUTCOME:
            reason = "contract"
        elif outcome is None:
            reason = "content"
        elif outcome not in model.outcomes:
            reason = "unknown_outcome"
        elif not _np.any(support & (model.a[action][model.outcomes.index(outcome)] > 0)):
            reason = "impossible"
        if reason is not None:
            unread[record.id] = reason
        else:
            readable.setdefault(body.caused_by, []).append((record.id, action, outcome))
    sequence = []
    for observations in readable.values():
        if len(observations) > 1:
            for ref, _, _ in observations:
                unread[ref] = "ambiguous_attempt"
        else:
            ref, action, outcome = observations[0]
            n[action][model.outcomes.index(outcome)] += 1
            if axis is not None and ref in axis.received_ns:
                record = by_id[ref]
                sequence.append((axis.received_ns[ref], record.at.run_index, record.at.seq,
                                 ref, action, outcome))
    return Reading(n=n, unread=unread,
                   pending={j: action for j, action in jobs.items()
                            if j not in finished and j not in abandoned},
                   timeline=axis, sequence=tuple(sorted(sequence, key=lambda item:
                       (item[0], item[1], item[2], str(item[3])))),
                   arrivals=arrivals, _clock_issues=issues)


@_dataclass(frozen=True, slots=True, kw_only=True)
class View:
    model: _GenerativeModel
    frontier: frozenset[str]
    belief: _Ref
    reading: Reading
    now_ns: int | None = None


@_dataclass(frozen=True, slots=True, kw_only=True)
class Draft:
    parents: frozenset[str]
    belief: _Ref
    content: _Payload


@_dataclass(frozen=True, slots=True, kw_only=True)
class Commit:
    parents: frozenset[str]
    decided: _Record
    job: _Record


def _derive(model, n):
    try:
        q = _belief(model.D, [
            _log_likelihood(model.a[action], n[action], learnable=action in model.learnable)
            for action in model.actions
        ])
    except _ModelViolation:
        q = None
    a = {action: (_ledger(model.a[action], n[action])
                  if action in model.learnable else model.a[action])
         for action in model.actions}
    return q, a


def _timed(model):
    return model.Q is not None or bool(model.arrivals)


def _anchor(reading):
    axis = reading.timeline
    if axis is None or axis.origin is None:
        return None, None
    if reading.sequence:
        return reading.sequence[-1][3], reading.sequence[-1][0]
    return axis.origin, axis.received_ns[axis.origin]


def _filtered(model, reading):
    logs = {action: _log_A(model.a[action]) for action in model.actions}
    return _filter_log(model.D, model.Q,
        ((ns, logs[action][model.outcomes.index(outcome)])
         for ns, _, _, _, action, outcome in reading.sequence))


def _derive_reading(model, reading):
    if model.Q is None:
        q, a = _derive(model, reading.n)
    else:
        a = dict(model.a)
        try:
            q = _log_probability(_filtered(model, reading))
        except _ModelViolation:
            q = None
    if reading._clock_issues:
        q = None
    return q, a


def plan(view: View, candidates: _Iterable[str], *, u: float) -> Draft:
    """予測の枝で成分ごとに平均し、その G から一度だけ選ぶ純粋な計算。

    仮の回数を事実にせず、到着はモデルどおり必ず起こると仮定する。
    進行中なしは S1c と同じ計算順。失敗は例外、状態は持たない。
    P3・P3b・P4・P5・P6・P7・P8・P9、W1・W5。
    Qありはanchorからnowへ進め、枝は今を測る近似として記す (Q1・Q6・Q11)。
    Qなしは起動もnowも要らず、timeを加えない (T7b)。
    """
    model = view.model
    time = None
    if model.Q is not None:
        anchor, anchor_ns = _anchor(view.reading)
        if anchor is None:
            raise ValueError("plan: an adopted boot is required")
        if type(view.now_ns) is not int:
            raise ValueError("plan: now_ns is required in integer nanoseconds")
        if view.now_ns < anchor_ns:
            raise ValueError("plan: now_ns precedes anchor")
        time = {"anchor": str(anchor), "anchor_ns": anchor_ns,
                "now_ns": view.now_ns, "dt_s": (view.now_ns - anchor_ns) / 1e9,
                "pending_measures": "now"}
    unique = set()
    for action in candidates:
        if not isinstance(action, str):
            raise TypeError("candidate: expected str")
        if action not in model.actions:
            raise ValueError("candidate: unknown or empty action")
        unique.add(action)
    if not unique:
        raise ValueError("candidates: expected at least one action")
    actions = sorted(unique)
    pending = sorted(view.reading.pending.items(), key=lambda item: str(item[0]))

    def expectation(n, index, action):
        q, a = _derive(model, n)
        if q is None:
            raise ModelFalsified("the model cannot explain the facts")
        if index == len(pending):
            risk, ambiguity, q_o = _efe(q, _expected_A(a[action]), model.log_C)
            novelty = _novelty(q, a[action]) if action in model.learnable else 0.0
            return risk, ambiguity, novelty, q_o
        waiting_action = pending[index][1]
        _, _, predicted = _efe(q, _expected_A(a[waiting_action]), model.log_C)
        risk, ambiguity, novelty = 0.0, 0.0, 0.0
        q_o = _np.zeros(len(model.outcomes))
        for outcome, probability in enumerate(predicted):
            if probability > 0:
                branch = dict(n)
                branch[waiting_action] = n[waiting_action].copy()
                branch[waiting_action][outcome] += 1
                r, a_value, nov, obs = expectation(branch, index + 1, action)
                risk += probability * r
                ambiguity += probability * a_value
                novelty += probability * nov
                q_o += probability * obs
        return risk, ambiguity, novelty, q_o

    def changing_expectation(log_q, index, action):
        try:
            q = _log_probability(log_q)
        except _ModelViolation as exc:
            raise ModelFalsified("the model cannot explain the facts") from exc
        if index == len(pending):
            risk, ambiguity, q_o = _efe(q, _expected_A(model.a[action]), model.log_C)
            return risk, ambiguity, 0.0, q_o
        waiting = pending[index][1]
        _, _, predicted = _efe(q, _expected_A(model.a[waiting]), model.log_C)
        likelihoods = _log_A(model.a[waiting])
        risk, ambiguity = 0.0, 0.0
        q_o = _np.zeros(len(model.outcomes))
        for outcome, probability in enumerate(predicted):
            if probability > 0:
                r, a_value, _, obs = changing_expectation(
                    _log_update(log_q, likelihoods[outcome]), index + 1, action)
                risk += probability * r
                ambiguity += probability * a_value
                q_o += probability * obs
        return risk, ambiguity, 0.0, q_o

    if view.reading._clock_issues:
        raise ModelFalsified("the timeline cannot explain the facts")
    if model.Q is not None:
        now_log = _log_predict(_filtered(model, view.reading), model.Q, time["dt_s"])

    risks, ambiguities, novelties, outcomes = [], [], [], []
    for action in actions:
        risk, ambiguity, novelty, q_o = (expectation(view.reading.n, 0, action)
            if model.Q is None else changing_expectation(now_log, 0, action))
        risks.append(risk)
        ambiguities.append(ambiguity)
        novelties.append(novelty)
        outcomes.append(q_o.tolist())
    G = _np.array(risks) + _np.array(ambiguities) - _np.array(novelties)
    q_pi = _policy_posterior(G, model.gamma)
    chosen = actions[_select(q_pi, u)]
    content = {
        "candidates": actions, "risk": risks, "ambiguity": ambiguities,
        "novelty": novelties, "G": G.tolist(), "q_o": outcomes,
        "q_pi": q_pi.tolist(), "gamma": float(model.gamma), "u": float(u),
        "chosen": chosen,
        "pending": [{"job": str(j), "action": action} for j, action in pending],
    }
    if time is not None:
        content["time"] = time
    return Draft(parents=view.frontier, belief=view.belief, content=_Payload.json(content))


_REASONS = frozenset({"no_attempt", "unknown_attempt", "unreadable_attempt", "contract",
                      "content", "unknown_outcome", "impossible", "ambiguous_attempt",
                      "no_clock", "no_receipt_time"})


def _check_belief_content(data, *, timed=False) -> None:
    def numbers(values, *, integers=False):
        return isinstance(values, list) and all(
            (type(value) is int and value >= 0) if integers else
            (type(value) in (int, float) and _math.isfinite(value)) for value in values)

    def names(values):
        return isinstance(values, list) and all(isinstance(value, str) for value in values)

    keys = {"model", "states", "outcomes", "q", "a", "n", "unread"}
    if timed:
        keys |= {"time", "arrivals"}
    if not isinstance(data, dict) or set(data) != keys:
        raise ValueError("belief content: expected exactly the schema keys")
    if timed:
        time, arrivals = data["time"], data["arrivals"]
        if (not isinstance(time, dict) or set(time) != {"anchor", "anchor_ns", "clock_issues"}
                or not (time["anchor"] is None or isinstance(time["anchor"], str))
                or not (time["anchor_ns"] is None or type(time["anchor_ns"]) is int)
                or (time["anchor"] is None) != (time["anchor_ns"] is None)
                or not isinstance(time["clock_issues"], list)
                or any(not isinstance(issue, dict) for issue in time["clock_issues"])):
            raise ValueError("belief content: invalid time")
        if not isinstance(arrivals, dict):
            raise ValueError("belief content: invalid arrivals")
        for route, stats in arrivals.items():
            if (not isinstance(route, str) or not isinstance(stats, dict)
                    or set(stats) != {"N", "T_ns", "alpha", "beta_s", "outside"}
                    or any(type(stats[k]) is not int or stats[k] < 0 for k in ("N", "T_ns"))
                    or any(type(stats[k]) is not float or not _math.isfinite(stats[k])
                           or stats[k] <= 0 for k in ("alpha", "beta_s"))
                    or not names(stats["outside"])):
                raise ValueError("belief content: invalid arrival statistics")
    if not isinstance(data["model"], str) or not names(data["states"]) or not names(data["outcomes"]):
        raise ValueError("belief content: invalid model or named axes")
    if data["q"] is not None and not numbers(data["q"]):
        raise ValueError("belief content: q must be a numeric list or null")
    if data["q"] is not None and len(data["q"]) != len(data["states"]):
        raise ValueError("belief content: q must match the states axis")
    if not isinstance(data["n"], dict) or any(
            not isinstance(key, str) or not numbers(value, integers=True) for key, value in data["n"].items()):
        raise ValueError("belief content: invalid n")
    if not isinstance(data["a"], dict) or any(
            not isinstance(key, str) or not isinstance(value, list) or
            any(not numbers(row) for row in value) for key, value in data["a"].items()):
        raise ValueError("belief content: invalid a")
    if any(len(value) != len(data["outcomes"]) for value in data["n"].values()):
        raise ValueError("belief content: n must match the outcomes axis")
    if any(len(value) != len(data["outcomes"]) or
           any(len(row) != len(data["states"]) for row in value)
           for value in data["a"].values()):
        raise ValueError("belief content: a must match the outcomes and states axes")
    if not isinstance(data["unread"], list):
        raise ValueError("belief content: unread must be a list")
    for item in data["unread"]:
        if (not isinstance(item, dict) or set(item) != {"id", "reason"}
                or not isinstance(item["id"], str) or not isinstance(item["reason"], str)
                or item["reason"] not in _REASONS):
            raise ValueError("belief content: invalid unread item")
        try:
            kind, value = item["id"].split(":", 1)
            ref = _Ref(_RefKind(kind), value)
            if ref.kind is not _RefKind.OBSERVATION:
                raise ValueError("unread id must be an observation")
        except ValueError as exc:
            raise ValueError("belief content: invalid unread id") from exc


class Agent:
    """一つのスレッドで信念と帳面の版を管理する。

    正となる状態は先端。読み・信念・帳面はその下の事実の集合から作り直す。
    """

    def __init__(self, *, model: _GenerativeModel, lineage: str,
                 component: str = "sui.agent") -> None:
        if not isinstance(model, _GenerativeModel):
            raise TypeError("model: expected GenerativeModel")
        _Producer(component=component, code_version=CODE_VERSION,
                  state=_StateRef(lineage=lineage, revision=0))
        self._model = model
        self._lineage = lineage
        self._component = component
        self._frontier: frozenset[str] = frozenset()
        self._model_ref = _model_ref(model)
        self._reading = read(model, ())
        self._q, self._a = _derive_reading(model, self._reading)
        self._revision = 0
        self._belief: _Record | None = None

    @property
    def frontier(self) -> frozenset[str]:
        return self._frontier

    @property
    def model_ref(self) -> str:
        return self._model_ref

    @property
    def unread(self) -> tuple[tuple[_Ref, str], ...]:
        return tuple(sorted(self._reading.unread.items(), key=lambda item: str(item[0])))

    @property
    def q(self) -> _np.ndarray:
        """今の信念を読み取り専用のコピーで返す。"""
        if self._q is None:
            raise ModelFalsified("the model cannot explain the facts")
        return _readonly(self._q)

    def counts(self, action: str) -> _np.ndarray:
        """行動の数え上げを読み取り専用のコピーで返す。"""
        if not isinstance(action, str):
            raise TypeError("action: expected str")
        if action not in self._a:
            raise ValueError("action: unknown action")
        return _readonly(self._a[action])

    @property
    def revision(self) -> int:
        return self._revision

    @property
    def producer(self) -> _Producer:
        return self._producer(self._revision)

    def _producer(self, revision: int) -> _Producer:
        return _Producer(component=self._component, code_version=CODE_VERSION,
                         state=_StateRef(lineage=self._lineage, revision=revision))

    def _content(self, reading, q, a) -> dict:
        content = {
            "model": self.model_ref, "states": list(self._model.states),
            "outcomes": list(self._model.outcomes), "q": None if q is None else q.tolist(),
            "a": {action: counts.tolist() for action, counts in a.items()},
            "n": {action: counts.tolist() for action, counts in reading.n.items()},
            "unread": [{"id": str(ref), "reason": reason}
                       for ref, reason in sorted(reading.unread.items(), key=lambda item: str(item[0]))],
        }
        if _timed(self._model):
            anchor, ns = _anchor(reading)
            issues = reading._clock_issues if reading.timeline is None else reading.timeline.clock_issues
            content["time"] = {"anchor": None if anchor is None else str(anchor),
                               "anchor_ns": ns, "clock_issues": [
                                   {key: list(value) if isinstance(value, tuple) else value
                                    for key, value in issue.items()} for issue in issues]}
            content["arrivals"] = {}
            for route, stats in reading.arrivals.items():
                alpha, beta = _arrival_posterior(self._model.arrivals[route], stats)
                content["arrivals"][route] = {"N": stats.N, "T_ns": stats.T_ns,
                    "alpha": alpha, "beta_s": beta, "outside": list(map(str, stats.outside))}
        return content

    def _belief_record(self, reading, q, a, revision, *, clock, ids) -> _Record:
        return _Record(
            id=ids.new(_RefKind.PREDICTION), at=clock.now(), writer=_Role.MODEL,
            producer=self._producer(revision),
            body=_Prediction(target="belief", about=(), basis=(),
                             contract=_TIME_BELIEF if _timed(self._model) else BELIEF,
                             content=_Payload.json(self._content(reading, q, a))),
        )

    def belief_record(self, *, clock: _Clock, ids: _IdSource, ledger: _Ledger) -> _Record:
        """現在の信念を葉として書き、成功した時だけ最新の記録にする。"""
        record = self._belief_record(self._reading, self._q, self._a, self.revision,
                                     clock=clock, ids=ids)
        ledger.append(record, self.frontier)
        self._belief = record
        return record

    def view(self, *, now_ns: int | None = None) -> View:
        """今の先端の変わらない入力。信念が無い・説明不能なら例外 (P9・W10)。"""
        if self._q is None:
            raise ModelFalsified("the model cannot explain the facts")
        if self._belief is None:
            raise ValueError("view: a belief record is required")
        return View(model=self._model, frontier=self.frontier,
                    belief=self._belief.id, reading=self._reading, now_ns=now_ns)

    def prepare(self, draft: Draft, *, clock: _Clock, ids: _IdSource) -> Commit:
        """両記録を作るだけ。見た親を保ち、台帳・主体を変えない (P10・K4・W12)。"""
        decided = _Record(
            id=ids.new(_RefKind.DECISION), at=clock.now(), writer=_Role.MODEL,
            producer=self.producer,
            body=_Decided(inputs=(draft.belief,),
                          contract=_TIME_DECISION if self._model.Q is not None else DECISION,
                          content=draft.content),
        )
        job = _Record(
            id=ids.new(_RefKind.JOB), at=clock.now(), writer=_Role.MODEL,
            producer=self.producer,
            body=_JobOpened(decision=decided.id, step=0, contract=ACTION,
                            content=_Payload.json({"action": draft.content.as_json()["chosen"]})),
        )
        return Commit(parents=draft.parents, decided=decided, job=job)

    def commit(self, prepared: Commit, *, ledger: _Ledger) -> None:
        """親と信念の親を先に検査し、決定→仕事を書く。主体は変えない。

        検査失敗は無書き込み。同じ Commit の再試行で途中から続く (P10・K4・W12)。
        """
        for cid in prepared.parents:
            try:
                parent = ledger.entry(cid)
            except _UnknownEntry as exc:
                raise ValueError("commit: missing parent") from exc
            if not parent.is_event:
                raise ValueError("commit: parents must be events")
        inputs = prepared.decided.body.inputs
        if len(inputs) != 1:
            raise ValueError("commit: one belief is required")
        beliefs = ledger.entries_of(inputs[0])
        if not beliefs or not any(
                isinstance(ledger.record(entry.cid).body, _Prediction)
                and ledger.record(entry.cid).body.target == "belief"
                and ledger.record(entry.cid).body.contract ==
                    (_TIME_BELIEF if _timed(self._model) else BELIEF)
                and entry.parents == prepared.parents for entry in beliefs):
            raise ValueError("commit: belief parents differ")
        entry = ledger.append(prepared.decided, prepared.parents)
        ledger.append(prepared.job, {entry.cid})

    def decide(self, candidates: _Iterable[str], *, u: float, clock: _Clock,
               ids: _IdSource, ledger: _Ledger,
               now_mono_ns: int | None = None) -> tuple[_Record, _Record]:
        """同期もview→plan→prepare→commit。Qありは今のrunの起動が要る (T5・T7b・J4)。"""
        now = None
        if self._model.Q is not None:
            axis = self._reading.timeline
            if axis is None or clock.run not in axis.runs or type(now_mono_ns) is not int:
                raise ValueError("decide: current run boot and now_mono_ns are required")
            now = axis.to_axis(clock.run, now_mono_ns)
        prepared = self.prepare(plan(self.view(now_ns=now), candidates, u=u), clock=clock, ids=ids)
        self.commit(prepared, ledger=ledger)
        return prepared.decided, prepared.job

    def adopt(self, ledger: _Ledger, *, clock: _Clock, ids: _IdSource,
              through: _Iterable[str] | None = None) -> _Record | None:
        """先端の下の事実を読み直し、葉の保存後にだけ全状態を採用する。"""
        target = ledger.heads() if through is None else ledger.maximal(through)
        for cid in target:
            if not ledger.entry(cid).is_event:
                raise _DerivedParent(cid)
        new, old = ledger.ancestors(target), ledger.ancestors(self.frontier)
        if not old <= new:
            raise ValueError("adopt: cannot move behind the current frontier")
        if new == old:
            return None
        reading = read(self._model, ledger.snapshot(target).records)
        q, a = _derive_reading(self._model, reading)
        revision = self.revision + 1
        record = self._belief_record(reading, q, a, revision, clock=clock, ids=ids)
        ledger.append(record, target)
        self._frontier, self._reading, self._q, self._a, self._revision, self._belief = (
            target, reading, q, a, revision, record)
        return record

    @classmethod
    def restore(cls, *, model: _GenerativeModel, lineage: str, ledger: _Ledger,
                belief: str, component: str = "sui.agent") -> "Agent":
        """葉の親とモデルから復元し、保存値の全キーと完全一致で照合する。"""
        entry = ledger.entry(belief)
        record = ledger.record(belief)
        if not isinstance(record.body, _Prediction) or record.body.target != "belief":
            raise ValueError("belief: expected Prediction with target belief")
        if record.body.contract != (_TIME_BELIEF if _timed(model) else BELIEF):
            raise ValueError("belief: incompatible contract")
        if record.producer.state is None:
            raise ValueError("belief: producer.state is required")
        data = _json_content(record.body.content)
        _check_belief_content(data, timed=_timed(model))
        subject = cls(model=model, lineage=lineage, component=component)
        if data["model"] != subject.model_ref:
            raise ModelMismatch("belief: model reference differs")
        reading = read(model, ledger.snapshot(entry.parents).records)
        q, a = _derive_reading(model, reading)
        rebuilt = subject._content(reading, q, a)
        differences = tuple(sorted(key for key in rebuilt if rebuilt[key] != data[key]
            or (key in ("time", "arrivals")
                and _Payload.json(rebuilt[key]) != _Payload.json(data[key]))))
        if differences:
            raise RebuildMismatch(fields=differences)
        subject._frontier, subject._reading, subject._q, subject._a = entry.parents, reading, q, a
        subject._revision, subject._belief = record.producer.state.revision, record
        return subject
