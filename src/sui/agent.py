"""観測の回数から信念と帳面を作り、決定と観測を記録する主体。"""

from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from dataclasses import dataclass as _dataclass
from types import MappingProxyType as _MappingProxyType
import math as _math

import numpy as _np

from .clock import Clock as _Clock
from .ids import IdSource as _IdSource, Ref as _Ref, RefKind as _RefKind
from .inference import (
    ModelViolation as _ModelViolation, belief as _belief, efe as _efe, expected_A as _expected_A, ledger as _ledger,
    log_likelihood as _log_likelihood, novelty as _novelty,
    policy_posterior as _policy_posterior, select as _select,
)
from .s1_contracts import ACTION, BELIEF, DECISION, ATTEMPT as _ATTEMPT, OUTCOME as _OUTCOME
from .model import GenerativeModel as _GenerativeModel, model_ref as _model_ref, _readonly
from .ledger import Ledger as _Ledger, DerivedParent as _DerivedParent
from .records import (
    AttemptStarted as _AttemptStarted, Decided as _Decided,
    JobOpened as _JobOpened, Observed as _Observed, Payload as _Payload,
    Prediction as _Prediction, Producer as _Producer, Record as _Record,
    Role as _Role, StateRef as _StateRef,
)


CODE_VERSION = "s2a"


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

    def __post_init__(self) -> None:
        counts = {}
        for action, value in self.n.items():
            copy = _np.array(value, dtype=_np.int64, copy=True)
            copy.setflags(write=False)
            counts[action] = copy
        object.__setattr__(self, "n", _MappingProxyType(counts))
        object.__setattr__(self, "unread", _MappingProxyType(dict(self.unread)))


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


def read(model: _GenerativeModel, records: _Iterable[_Record]) -> Reading:
    """仕事・試み・観測を別々に読み、渡された記録の並びには依存しない。"""
    records = tuple(records)
    jobs = {}
    for record in records:
        if isinstance(record.body, _JobOpened) and record.body.contract == ACTION:
            action = _named_content(record.body.content, "action")
            if action in model.actions:
                jobs[record.id] = action
    attempts = {}
    for record in records:
        if isinstance(record.body, _AttemptStarted):
            body = record.body
            attempts[record.id] = (jobs.get(body.job)
                                   if body.contract == _ATTEMPT and
                                   _json_content(body.content) == {} else None)
    n = {action: _np.zeros(len(model.outcomes), dtype=_np.int64) for action in model.actions}
    unread, readable = {}, {}
    for record in records:
        if not isinstance(record.body, _Observed):
            continue
        body, reason = record.body, None
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
        elif not _np.any((model.D > 0) & (model.a[action][model.outcomes.index(outcome)] > 0)):
            reason = "impossible"
        if reason is not None:
            unread[record.id] = reason
        else:
            readable.setdefault(body.caused_by, []).append((record.id, action, outcome))
    for observations in readable.values():
        if len(observations) > 1:
            for ref, _, _ in observations:
                unread[ref] = "ambiguous_attempt"
        else:
            _, action, outcome = observations[0]
            n[action][model.outcomes.index(outcome)] += 1
    return Reading(n=n, unread=unread)


_REASONS = frozenset({"no_attempt", "unknown_attempt", "unreadable_attempt", "contract",
                      "content", "unknown_outcome", "impossible", "ambiguous_attempt"})


def _check_belief_content(data) -> None:
    def numbers(values, *, integers=False):
        return isinstance(values, list) and all(
            (type(value) is int and value >= 0) if integers else
            (type(value) in (int, float) and _math.isfinite(value)) for value in values)

    def names(values):
        return isinstance(values, list) and all(isinstance(value, str) for value in values)

    if not isinstance(data, dict) or set(data) != {"model", "states", "outcomes", "q", "a", "n", "unread"}:
        raise ValueError("belief content: expected exactly the schema keys")
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
        self._q, self._a = self._derive(self._reading.n)
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

    def _derive(self, n: _Mapping[str, _np.ndarray]) -> tuple[_np.ndarray | None, dict[str, _np.ndarray]]:
        try:
            q = _belief(self._model.D, [
                _log_likelihood(self._model.a[action], n[action],
                                learnable=action in self._model.learnable)
                for action in self._model.actions
            ])
        except _ModelViolation:
            q = None
        a = {action: (_ledger(self._model.a[action], n[action])
                      if action in self._model.learnable else self._model.a[action])
             for action in self._model.actions}
        return q, a

    def _content(self, reading, q, a) -> dict:
        return {
            "model": self.model_ref, "states": list(self._model.states),
            "outcomes": list(self._model.outcomes), "q": None if q is None else q.tolist(),
            "a": {action: counts.tolist() for action, counts in a.items()},
            "n": {action: counts.tolist() for action, counts in reading.n.items()},
            "unread": [{"id": str(ref), "reason": reason}
                       for ref, reason in sorted(reading.unread.items(), key=lambda item: str(item[0]))],
        }

    def _belief_record(self, reading, q, a, revision, *, clock, ids) -> _Record:
        return _Record(
            id=ids.new(_RefKind.PREDICTION), at=clock.now(), writer=_Role.MODEL,
            producer=self._producer(revision),
            body=_Prediction(target="belief", about=(), basis=(), contract=BELIEF,
                             content=_Payload.json(self._content(reading, q, a))),
        )

    def belief_record(self, *, clock: _Clock, ids: _IdSource, ledger: _Ledger) -> _Record:
        """現在の信念を葉として書き、成功した時だけ最新の記録にする。"""
        record = self._belief_record(self._reading, self._q, self._a, self.revision,
                                     clock=clock, ids=ids)
        ledger.append(record, self.frontier)
        self._belief = record
        return record

    def decide(self, candidates: _Iterable[str], *, u: float, clock: _Clock,
               ids: _IdSource, ledger: _Ledger) -> tuple[_Record, _Record]:
        """現在のモデルで候補を評価し、決定と仕事を記録する。"""
        if self._q is None:
            raise ModelFalsified("the model cannot explain the facts")
        if self._belief is None:
            raise ValueError("decide: a belief record is required")
        unique = set()
        for action in candidates:
            if not isinstance(action, str):
                raise TypeError("candidate: expected str")
            if action not in self._a:
                raise ValueError("candidate: unknown or empty action")
            unique.add(action)
        if not unique:
            raise ValueError("candidates: expected at least one action")
        actions = sorted(unique)
        risks, ambiguities, novelties, outcomes = [], [], [], []
        for action in actions:
            risk, ambiguity, q_o = _efe(self._q, _expected_A(self._a[action]),
                                        self._model.log_C)
            risks.append(risk)
            ambiguities.append(ambiguity)
            novelties.append(_novelty(self._q, self._a[action])
                             if action in self._model.learnable else 0.0)
            outcomes.append(q_o.tolist())
        G = _np.array(risks) + _np.array(ambiguities) - _np.array(novelties)
        q_pi = _policy_posterior(G, self._model.gamma)
        chosen = actions[_select(q_pi, u)]
        decided = _Record(
            id=ids.new(_RefKind.DECISION), at=clock.now(), writer=_Role.MODEL,
            producer=self.producer,
            body=_Decided(inputs=(self._belief.id,), contract=DECISION,
                          content=_Payload.json({
                              "candidates": actions, "risk": risks, "ambiguity": ambiguities,
                              "novelty": novelties,
                              "G": G.tolist(), "q_o": outcomes, "q_pi": q_pi.tolist(),
                              "gamma": float(self._model.gamma), "u": float(u), "chosen": chosen,
                          })),
        )
        job = _Record(
            id=ids.new(_RefKind.JOB), at=clock.now(), writer=_Role.MODEL,
            producer=self.producer,
            body=_JobOpened(decision=decided.id, step=0, contract=ACTION,
                            content=_Payload.json({"action": chosen})),
        )
        entry = ledger.append(decided, self.frontier)
        ledger.append(job, {entry.cid})
        return decided, job

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
        q, a = self._derive(reading.n)
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
        if record.body.contract != BELIEF:
            raise ValueError("belief: incompatible contract")
        if record.producer.state is None:
            raise ValueError("belief: producer.state is required")
        data = _json_content(record.body.content)
        _check_belief_content(data)
        subject = cls(model=model, lineage=lineage, component=component)
        if data["model"] != subject.model_ref:
            raise ModelMismatch("belief: model reference differs")
        reading = read(model, ledger.snapshot(entry.parents).records)
        q, a = subject._derive(reading.n)
        rebuilt = subject._content(reading, q, a)
        differences = tuple(sorted(key for key in rebuilt if rebuilt[key] != data[key]))
        if differences:
            raise RebuildMismatch(fields=differences)
        subject._frontier, subject._reading, subject._q, subject._a = entry.parents, reading, q, a
        subject._revision, subject._belief = record.producer.state.revision, record
        return subject
