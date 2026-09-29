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


def _naive_conditional_G(model, pending, candidates=None, *, observations=()):
    """P6: 同時予測のエントロピー差による独立の式 (§6-6)。

    sui.inference・plan を使わず、状態ごとの Pólya の壺と E[H(O|θ)] で計算。
    """
    from itertools import product
    candidates = model.actions if candidates is None else candidates
    q, n = _exact_posterior(model.D, model.a, model.learnable, observations)
    columns = {action: _np.where(prior > 0, prior + n[action][:, None], 0)
               if action in model.learnable else prior
               for action, prior in model.a.items()}

    def joint(actions):
        distribution = []
        for outcomes in product(range(len(model.outcomes)), repeat=len(actions)):
            probability = 0.0
            for state, weight in enumerate(q):
                urns = {action: list(a[:, state]) for action, a in columns.items()}
                p = float(weight)
                for action, outcome in zip(actions, outcomes):
                    urn = urns[action]
                    p *= float(urn[outcome]) / _math.fsum(urn)
                    if action in model.learnable:
                        urn[outcome] += 1
                probability += p
            distribution.append(probability)
        return distribution

    def entropy(distribution):
        return -_math.fsum(p * _math.log(p) for p in distribution if p > 0)

    before = entropy(joint(tuple(pending)))
    result = []
    for action in candidates:
        expected_entropy = 0.0
        for state, weight in enumerate(q):
            alpha = [float(a) for a in columns[action][:, state] if a > 0]
            total = _math.fsum(alpha)
            if action in model.learnable:
                h = float(_digamma(total + 1)) - _math.fsum(
                    a / total * float(_digamma(a + 1)) for a in alpha)
            else:
                h = entropy([a / total for a in alpha])
            expected_entropy += float(weight) * h
        information = entropy(joint(tuple(pending) + (action,))) - before - expected_entropy
        preference = -_math.fsum(p * float(c) for p, c in zip(joint((action,)), model.log_C))
        result.append(preference - information)
    return result


class ScriptDrive:
    """規則は試験が渡す。呼び出し・成功した返事を分けて記録する。"""

    def __init__(self, *rules):
        self.rules = rules
        self.calls = []
        self.successes = []

    def react(self, status, event):
        self.calls.append((status, event))
        replies = []
        for rule in self.rules:
            for request in rule(status, event):
                replies.append(request)
                yield request
        self.successes.append((status, event, tuple(replies)))


class GatedHand:
    """資源・結果の台本。任意の行動を Event で待たせる (必ず時間切れ付き)。"""

    def __init__(self, resources, script, *, gates=None):
        from threading import Event, Lock
        self._resources = {action: frozenset(names) for action, names in resources.items()}
        self._script = {action: list(values) for action, values in script.items()}
        self.gates = {} if gates is None else dict(gates)
        self.calls = []
        self.threads = {}
        self.entered = {action: Event() for action in resources}
        self._lock = Lock()

    def resources(self, action):
        return self._resources[action]

    def execute(self, action):
        from threading import current_thread
        with self._lock:
            self.calls.append(action)
            self.threads[action] = current_thread()
            result = self._script[action].pop(0)
            self.entered[action].set()
        gate = self.gates.get(action)
        if gate is not None and not gate.wait(timeout=5):
            raise TimeoutError("test hand gate timed out")
        if isinstance(result, Exception):
            raise result
        return result


class WriteCounts:
    """二つの置き場に共通の書き込みの計数器。"""

    def __init__(self):
        from threading import Lock
        self._lock = Lock()
        self.threads = []
        self.active = 0
        self.maximum = 0

    @_contextmanager
    def writing(self):
        from threading import get_ident
        with self._lock:
            self.threads.append(get_ident())
            self.active += 1
            self.maximum = max(self.maximum, self.active)
        try:
            yield
        finally:
            with self._lock:
                self.active -= 1


class _CountingStore:
    def __init__(self, delegate, counts=None):
        self.delegate = delegate
        self.counts = WriteCounts() if counts is None else counts

    def __getattr__(self, name):
        return getattr(self.delegate, name)


class CountingEntries(_CountingStore):
    def add(self, *args):
        with self.counts.writing():
            return self.delegate.add(*args)


class CountingContents(_CountingStore):
    def put(self, *args):
        with self.counts.writing():
            return self.delegate.put(*args)


class _FlakyStore:
    def __init__(self, delegate, fail_on=()):
        self.delegate = delegate
        self.fail_on = set(fail_on)
        self.calls = 0

    def __getattr__(self, name):
        return getattr(self.delegate, name)

    def fail_next(self, offset=1):
        self.fail_on.add(self.calls + offset)

    def _write(self, method, *args):
        from sui.store import StorageFull
        self.calls += 1
        if self.calls in self.fail_on:
            raise StorageFull("injected write failure")
        return getattr(self.delegate, method)(*args)


class FlakyEntries(_FlakyStore):
    def add(self, *args):
        return self._write("add", *args)


class FlakyContents(_FlakyStore):
    def put(self, *args):
        return self._write("put", *args)


class ManualHost:
    """§3-6 の手順を一回ずつ運ぶ試験用ホスト。finish だけが係を動かす。"""

    def __init__(self, make_window):
        from collections import deque
        from sui.runtime import Pledges
        self.make_window = make_window
        self.pledges = Pledges()
        self.window = None
        self.queue = deque()
        self.current = None
        self.unstarted = []
        self.work = []
        self.started = []
        self.number = 0
        self.mono_ns = 0
        self.start = self._start_work

    def post(self, event):
        from sui.runtime import Envelope
        self.number += 1
        self.queue.append(Envelope(number=self.number, event=event))

    def advance(self, ns):
        from sui.runtime import Tick
        self.mono_ns += ns
        self.post(Tick(mono_ns=self.mono_ns))

    def _collect(self):
        if self.window is not None:
            self.unstarted.extend((work, self.window.hand) for work in self.window.drain())

    def _start_work(self, work, hand):
        self.work.append((work, hand))
        self.started.append(work)

    def _start(self):
        while self.unstarted:
            self.start(*self.unstarted[0])
            self.unstarted.pop(0)

    def _failed(self, original):
        self._collect()
        self.window = None
        try:
            self._start()
        except Exception as start_error:
            start_error.__context__ = None
            original.__context__ = start_error

    def step(self):
        if self.window is None:
            try:
                self.window = self.make_window(self.pledges)
                self.window.settle()
            except Exception as exc:
                self._failed(exc)
                raise
        self._collect()
        self._start()
        if self.current is None:
            if not self.queue:
                return
            self.current = self.queue.popleft()
        try:
            self.window.accept(self.current)
            self.current = None
            self.window.settle()
        except Exception as exc:
            self._failed(exc)
            raise
        self._collect()
        self._start()

    def finish(self, work):
        from sui.runtime import _perform
        for index, (candidate, hand) in enumerate(self.work):
            if candidate is work:
                self.work.pop(index)
                event = _perform(work, hand)
                self.post(event)
                return event
        raise ValueError("work has not been started or has already finished")
