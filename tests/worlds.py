"""主体から独立した試験の世界と試験用の設定。"""

import math as _math
from contextlib import contextmanager as _contextmanager
from types import SimpleNamespace as _SimpleNamespace

import numpy as _np
from scipy.special import digamma as _digamma

from sui.model import GenerativeModel as _GenerativeModel


@_contextmanager
def _storage(path, backend="sqlite"):
    from sui.ledger import MemoryContents
    from sui.store import MemoryEntries, MemoryModels, SqliteStore
    if backend == "memory":
        yield _SimpleNamespace(entries=MemoryEntries(), contents=MemoryContents(), models=MemoryModels())
    else:
        with SqliteStore.open(path, create=True) as store:
            yield store


def _stored_rig(store, *, model=None, ledger=None):
    from sui.agent import Agent
    from sui.clock import FakeClock
    from sui.ids import Ref, RefKind, SequentialIds
    from sui.ledger import Ledger, SequentialSalts
    from sui.records import Producer
    model = _model(learnable=frozenset({"look1", "look2"})) if model is None else model
    store.models.put(model)
    rig = _SimpleNamespace(
        store=store, model=model, agent=Agent(model=model, lineage="line1"),
        ledger=ledger if ledger is not None else Ledger(
            salts=SequentialSalts(), contents=store.contents, entries=store.entries),
        clock=FakeClock(run=Ref(RefKind.RUN, "r1")), ids=SequentialIds(),
        membrane=Producer(component="test.executor", code_version="1"),
        world=ScriptedWorld({"look1": ["o1", "o0"] * 1000,
                             "look2": ["o0", "o1"] * 1000, "wait": ["none"] * 2000}),
    )
    rig.belief = rig.agent.belief_record(clock=rig.clock, ids=rig.ids, ledger=rig.ledger)
    return rig


def _stored_step(rig):
    from sui.loop import run_step
    return run_step(rig.agent, rig.world, rig.model.actions, u=.5, clock=rig.clock,
                    ids=rig.ids, ledger=rig.ledger, membrane=rig.membrane)


class ScriptedWorld:
    """行動ごとの台本を先頭から返す世界。"""

    def __init__(self, script: dict[str, list[str]]) -> None:
        self._script = {action: list(outcomes) for action, outcomes in script.items()}
        self.calls: list[str] = []

    def execute(self, action: str) -> str:
        """行動を記録し、台本の次の観測を返す。"""
        self.calls.append(action)
        assert self._script.get(action), f"script exhausted: {action}"
        return self._script[action].pop(0)


class SampledWorld:
    """真の状態と観測行列から観測を生成する世界。"""

    def __init__(self, true_state: int, A: dict[str, _np.ndarray], seed: int) -> None:
        self._true_state = true_state
        self._A = {action: value.copy() for action, value in A.items()}
        self._rng = _np.random.default_rng(seed)

    def execute(self, action: str) -> str:
        """試験の観測空間から一つ返す。"""
        outcomes = ("o0", "o1", "none")
        index = self._rng.choice(len(outcomes), p=self._A[action][:, self._true_state])
        return outcomes[int(index)]


def _true_A():
    return {
        "look1": _np.array([[.9, .5], [.1, .5], [0., 0.]]),
        "look2": _np.array([[.5, .1], [.5, .9], [0., 0.]]),
        "wait": _np.array([[0., 0.], [0., 0.], [1., 1.]]),
    }


def _model_kwargs():
    return dict(
        states=("s0", "s1"), outcomes=("o0", "o1", "none"),
        actions=("look1", "look2", "wait"),
        a={action: 10 * value for action, value in _true_A().items()},
        learnable=frozenset(), D=_np.array([.9, .1]),
        log_C=_np.full(3, -_math.log(3)), gamma=64.0,
    )


def _model(**changes):
    values = _model_kwargs()
    values.update(changes)
    return _GenerativeModel(**values)


def _close(actual, expected, atol=1e-12):
    _np.testing.assert_allclose(actual, expected, atol=atol, rtol=0)


def _naive_efe(q, A, log_C):
    q_o = [sum(float(A[o, s]) * float(q[s]) for s in range(len(q)))
           for o in range(len(A))]
    risk = sum(p * (_math.log(p) - float(log_C[o]))
               for o, p in enumerate(q_o) if p > 0)
    ambiguity = 0.0
    for s in range(len(q)):
        for o in range(len(A)):
            if A[o, s] > 0:
                ambiguity -= float(q[s]) * float(A[o, s]) * _math.log(float(A[o, s]))
    return risk, ambiguity, q_o


def _naive_novelty(q, a):
    """正の支持上で Dirichlet KL の一般式を観測・状態ごとに平均する。"""
    result = 0.0
    for state in range(len(q)):
        alpha = [float(value) for value in a[:, state] if value > 0]
        total = sum(alpha)
        for outcome, count in enumerate(alpha):
            updated = alpha.copy()
            updated[outcome] += 1
            updated_total = sum(updated)
            kl = (_math.lgamma(updated_total) - sum(map(_math.lgamma, updated))
                  - _math.lgamma(total) + sum(map(_math.lgamma, alpha)))
            kl += sum((after - before) * (_digamma(after) - _digamma(updated_total))
                      for after, before in zip(updated, alpha))
            result += float(q[state]) * (count / total) * float(kl)
    return result


def _naive_softmax(G, gamma):
    weights = [_math.exp(-gamma * float(g)) for g in G]
    return [weight / sum(weights) for weight in weights]


def _exact_posterior(D, a, learnable, observations):
    """静的な状態の厳密な事後と行動ごとの回数 (独立の lgamma の DM 式)。

    小さな事前・回数の fixture 用。学ばない行動は列の平均を固定の A とする。
    """
    tally = {action: _np.zeros(prior.shape[0], dtype=_np.int64) for action, prior in a.items()}
    for action, outcome in observations:
        tally[action][outcome] += 1
    log_joint = []
    for state, probability in enumerate(D):
        if probability == 0:
            log_joint.append(-_math.inf)
            continue
        terms = [_math.log(probability)]
        for action, prior in a.items():
            column, counts = prior[:, state], tally[action]
            if any(x == 0 and count > 0 for x, count in zip(column, counts)):
                terms.append(-_math.inf)
                break
            total = _math.fsum(column)
            if action in learnable:
                terms.extend([_math.lgamma(total), -_math.lgamma(total + sum(map(int, counts)))])
                terms.extend(_math.lgamma(float(x) + int(count)) - _math.lgamma(x)
                             for x, count in zip(column, counts) if x > 0)
            else:
                terms.extend(int(count) * _math.log(float(x) / total)
                             for x, count in zip(column, counts) if count > 0)
        log_joint.append(_math.fsum(terms))
    maximum = max(log_joint)
    assert _math.isfinite(maximum), "fixture must contain a possible hypothesis"
    weights = [_math.exp(value - maximum) for value in log_joint]
    return _np.array([weight / _math.fsum(weights) for weight in weights]), tally
