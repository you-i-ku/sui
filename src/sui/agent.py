"""観測の回数から信念と帳面を作り、決定と観測を記録する主体。"""

from collections.abc import Iterable as _Iterable

import numpy as _np

from .clock import Clock as _Clock
from .contracts import require as _require
from .ids import IdSource as _IdSource, Ref as _Ref, RefKind as _RefKind
from .inference import (
    belief as _belief, efe as _efe, expected_A as _expected_A, ledger as _ledger,
    log_likelihood as _log_likelihood, novelty as _novelty,
    policy_posterior as _policy_posterior, select as _select,
)
from .s1_contracts import ACTION, BELIEF, DECISION, ATTEMPT as _ATTEMPT, OUTCOME as _OUTCOME
from .model import GenerativeModel as _GenerativeModel, _readonly
from .records import (
    AttemptStarted as _AttemptStarted, Coverage as _Coverage, Decided as _Decided,
    JobOpened as _JobOpened, Observed as _Observed, Payload as _Payload,
    Prediction as _Prediction, Producer as _Producer, Record as _Record,
    Role as _Role, StateRef as _StateRef, admit as _admit,
)


CODE_VERSION = "s1c"


class Agent:
    """一つのスレッドで信念と帳面の版を管理する。

    学んで持つのは観測の回数だけ、信念と帳面はそこから計算する (S1c)。
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
        self._n: dict[str, _np.ndarray] = {
            action: _np.zeros(len(model.outcomes), dtype=_np.int64)
            for action in model.actions
        }
        self._q, self._a = self._derive(self._n)
        self._revision = 0
        self._belief: _Record | None = None
        self._jobs: dict[_Ref, str] = {}
        self._attempts: dict[_Ref, _Record] = {}
        self._observations: dict[_Ref, _Record] = {}
        self._applied_attempts: set[_Ref] = set()

    @property
    def q(self) -> _np.ndarray:
        """今の信念を読み取り専用のコピーで返す。"""
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

    def _derive(self, n: dict[str, _np.ndarray]) -> tuple[_np.ndarray, dict[str, _np.ndarray]]:
        q = _belief(self._model.D, [
            _log_likelihood(self._model.a[action], n[action],
                            learnable=action in self._model.learnable)
            for action in self._model.actions
        ])
        a = {action: (_ledger(self._model.a[action], n[action])
                      if action in self._model.learnable else self._model.a[action])
             for action in self._model.actions}
        return q, a

    def _belief_record(self, q: _np.ndarray, a: dict[str, _np.ndarray],
                       n: dict[str, _np.ndarray], revision: int,
                       *, clock: _Clock, ids: _IdSource, basis: tuple[_Ref, ...]) -> _Record:
        return _Record(
            id=ids.new(_RefKind.PREDICTION), at=clock.now(), writer=_Role.MODEL,
            producer=self._producer(revision),
            body=_Prediction(target="belief", about=(), basis=basis, contract=BELIEF,
                             content=_Payload.json({
                                 "states": list(self._model.states),
                                 "outcomes": list(self._model.outcomes), "q": q.tolist(),
                                 "a": {action: counts.tolist() for action, counts in a.items()},
                                 "n": {action: counts.tolist() for action, counts in n.items()},
                             })),
        )

    def belief_record(self, *, clock: _Clock, ids: _IdSource,
                      basis: tuple[_Ref, ...] = ()) -> _Record:
        """今の信念を記録し、成功したら最新の記録にする。"""
        record = self._belief_record(self._q, self._a, self._n, self._revision,
                                     clock=clock, ids=ids, basis=basis)
        self._belief = record
        return record

    def decide(self, candidates: _Iterable[str], *, u: float, clock: _Clock,
               ids: _IdSource, basis: _Coverage) -> tuple[_Record, _Record]:
        """現在のモデルで候補を評価し、決定と仕事を記録する。"""
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
            body=_Decided(basis=basis, inputs=(self._belief.id,), contract=DECISION,
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
        self._jobs[job.id] = chosen
        return decided, job

    def started(self, attempt: _Record) -> None:
        """検査済みの試みを仕事につなぎ、同じ ID の付け替えを拒む。"""
        if not isinstance(attempt, _Record) or not isinstance(attempt.body, _AttemptStarted):
            raise TypeError("attempt: expected an AttemptStarted record")
        if attempt.id in self._attempts:
            _admit(self._attempts[attempt.id], attempt)
            return
        _require(_ATTEMPT, attempt.body.contract)
        if attempt.body.content.as_json() != {}:
            raise ValueError("attempt content: expected an empty object")
        if attempt.body.job not in self._jobs:
            raise ValueError("attempt.job: not opened by this agent")
        self._attempts[attempt.id] = attempt

    def observe(self, observed: _Record, *, clock: _Clock,
                ids: _IdSource) -> _Record | None:
        """観測で更新し、新しい信念の記録が完成してから採用する。"""
        if not isinstance(observed, _Record) or not isinstance(observed.body, _Observed):
            raise TypeError("observed: expected an Observed record")
        if observed.id in self._observations:
            _admit(self._observations[observed.id], observed)
            return None
        attempt_id = observed.body.caused_by
        if attempt_id is None or attempt_id not in self._attempts:
            return None
        if attempt_id in self._applied_attempts:
            return None
        _require(_OUTCOME, observed.body.contract)
        content = observed.body.content.as_json()
        if (not isinstance(content, dict) or set(content) != {"outcome"}
                or not isinstance(content["outcome"], str)):
            raise ValueError("observed content: expected exactly one str outcome")
        if content["outcome"] not in self._model.outcomes:
            raise ValueError("outcome: unknown outcome")
        outcome = self._model.outcomes.index(content["outcome"])
        action = self._jobs[self._attempts[attempt_id].body.job]
        n = self._n.copy()
        n[action] = n[action].copy()
        n[action][outcome] += 1
        q, a = self._derive(n)
        revision = self._revision + 1
        belief = self._belief_record(q, a, n, revision, clock=clock, ids=ids,
                                     basis=(observed.id,))
        self._q, self._a, self._n, self._revision = q, a, n, revision
        self._observations[observed.id] = observed
        self._applied_attempts.add(attempt_id)
        self._belief = belief
        return belief
