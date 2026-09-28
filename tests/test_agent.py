from dataclasses import replace
from types import SimpleNamespace
import math

import numpy as np
import pytest

from sui.agent import ACTION, BELIEF, CODE_VERSION, DECISION, Agent
from sui.clock import FakeClock
from sui.contracts import ContractMismatch, ContractRef
from sui.ids import Ref, RefKind as K, SequentialIds, WrongKind
from sui.inference import ModelViolation, belief, ledger, log_likelihood
from sui.loop import ATTEMPT, OUTCOME
from sui.records import (
    BODY_KIND, AttemptStarted, Coverage, Decided, IdConflict, JobOpened,
    Observed, Payload, Prediction, Producer, Record, Role, StateRef,
)
from worlds import _close, _exact_posterior, _model, _naive_efe, _naive_novelty, _naive_softmax, _true_A


def _setup(model=None, *, record=True):
    model = _model() if model is None else model
    rig = SimpleNamespace(
        model=model, agent=Agent(model=model, lineage="line1"),
        clock=FakeClock(run=Ref(K.RUN, "r1")), ids=SequentialIds(),
        membrane=Producer(component="test.executor", code_version="1"),
    )
    rig.belief = rig.agent.belief_record(clock=rig.clock, ids=rig.ids) if record else None
    return rig


def _decide(rig, candidates=("look1", "look2", "wait"), u=.5):
    return rig.agent.decide(
        candidates, u=u, clock=rig.clock, ids=rig.ids,
        basis=Coverage(as_of=rig.clock.now(), ledger="test", through=1,
                       complete=frozenset(BODY_KIND)),
    )


def _start(rig, action="look1", *, register=True):
    _, job = _decide(rig, [action])
    attempt = Record(
        id=rig.ids.new(K.ATTEMPT), at=rig.clock.now(), writer=Role.MEMBRANE,
        producer=rig.membrane,
        body=AttemptStarted(job=job.id, contract=ATTEMPT, content=Payload.json({})),
    )
    if register:
        rig.agent.started(attempt)
    return attempt


def _observed(rig, attempt=None, outcome="o1"):
    return Record(
        id=rig.ids.new(K.OBSERVATION), at=rig.clock.now(), writer=Role.MEMBRANE,
        producer=rig.membrane,
        body=Observed(route="executor", caused_by=None if attempt is None else attempt.id,
                      contract=OUTCOME, content=Payload.json({"outcome": outcome})),
    )


def _observe(rig, record):
    return rig.agent.observe(record, clock=rig.clock, ids=rig.ids)


def _state(rig):
    return (rig.agent.q.tolist(), {action: rig.agent.counts(action).tolist()
                                 for action in rig.model.actions},
            rig.agent.revision, rig.agent.producer)


def _assert_unchanged(rig, state, latest):
    assert _state(rig) == state
    assert _decide(rig)[0].body.inputs == (latest.id,)


def _assert_record_reproducible(model, record):
    """A1・A13(6): 主体と純粋な関数の道がビット単位で同じかを確かめる。"""
    data = record.body.content.as_json()
    n = {action: np.array(data["n"][action], dtype=np.int64) for action in model.actions}
    q = belief(model.D, [log_likelihood(model.a[action], n[action],
                                      learnable=action in model.learnable)
                         for action in model.actions])
    np.testing.assert_array_equal(data["q"], q)
    for action in model.actions:
        a = ledger(model.a[action], n[action]) if action in model.learnable else model.a[action]
        np.testing.assert_array_equal(data["a"][action], a)


def test_a1_initial_state_and_belief_record():
    rig = _setup(record=False)
    with pytest.raises(ValueError):
        _decide(rig)
    _close(rig.agent.q, [.9, .1])
    assert rig.agent.revision == 0
    assert rig.agent.producer == Producer(component="sui.agent", code_version="s1c",
                                          state=StateRef(lineage="line1", revision=0))
    assert CODE_VERSION == "s1c"
    belief = rig.agent.belief_record(clock=rig.clock, ids=rig.ids)
    assert isinstance(belief.body, Prediction)
    assert belief.writer is Role.MODEL
    assert belief.body.target == "belief"
    assert belief.body.about == belief.body.basis == ()
    assert belief.body.contract == BELIEF == ContractRef("sui.s1.belief", "2")
    assert belief.producer == rig.agent.producer
    data = belief.body.content.as_json()
    assert set(data) == {"states", "outcomes", "q", "a", "n"}
    assert data["states"] == ["s0", "s1"]
    assert data["outcomes"] == ["o0", "o1", "none"]
    _close(data["q"], rig.model.D, atol=1e-15)
    _assert_record_reproducible(rig.model, belief)
    assert set(data["n"]) == set(rig.model.actions)
    for action in rig.model.actions:
        _close(data["a"][action], rig.model.a[action])
        assert data["n"][action] == [0] * len(rig.model.outcomes)
        assert all(type(count) is int for count in data["n"][action])
    basis = (Ref(K.OBSERVATION, "evidence"),)
    next_belief = rig.agent.belief_record(clock=rig.clock, ids=rig.ids, basis=basis)
    assert next_belief.body.basis == basis
    assert _decide(rig)[0].body.inputs == (next_belief.id,)


def test_a1_accessors_are_readonly_copies():
    rig = _setup()
    for value in (rig.agent.q, rig.agent.counts("look1")):
        assert value.dtype == np.float64
        with pytest.raises(ValueError):
            value.flat[0] = 42
        value.setflags(write=True)
        value.flat[0] = 42
    _close(rig.agent.q, [.9, .1])
    _close(rig.agent.counts("look1"), [[9, 5], [1, 5], [0, 0]])
    with pytest.raises(TypeError):
        rig.agent.counts(1)
    with pytest.raises(ValueError):
        rig.agent.counts("unknown")


@pytest.mark.parametrize("changes,error", [
    ({"model": object()}, TypeError), ({"lineage": "BAD"}, ValueError),
    ({"lineage": 1}, TypeError), ({"component": ""}, ValueError),
])
def test_a1_constructor_validation(changes, error):
    values = dict(model=_model(), lineage="line1")
    values.update(changes)
    with pytest.raises(error):
        Agent(**values)


def test_a2_decision_job_contents_and_unchanged_state():
    rig = _setup()
    before = _state(rig)
    decision, job = _decide(rig, ["wait", "look2", "look1"])
    assert isinstance(decision.body, Decided)
    assert decision.body.contract == DECISION == ContractRef("sui.s1.decision", "2")
    assert decision.body.inputs == (rig.belief.id,)
    assert decision.writer is job.writer is Role.MODEL
    assert decision.producer == job.producer == rig.agent.producer
    data = decision.body.content.as_json()
    assert set(data) == {"candidates", "risk", "ambiguity", "novelty", "G", "q_o",
                         "q_pi", "gamma", "u", "chosen"}
    assert data["candidates"] == ["look1", "look2", "wait"]
    _close(data["risk"], [.693648803604, .408668530210, 1.098612288668])
    _close(data["ambiguity"], [.361889394108, .656340759843, 0.])
    assert data["novelty"] == [0.0, 0.0, 0.0]
    _close(data["G"], [1.055538197712, 1.065009290053, 1.098612288668])
    _close(data["q_o"], [[.86, .14, 0.], [.46, .54, 0.], [0., 0., 1.]])
    _close(data["q_pi"], [.621525219, .339008974, .039465808], atol=1e-9)
    assert data["chosen"] == "look1"
    assert data["u"] == .5 and data["gamma"] == 64.0
    for name in ("risk", "ambiguity", "novelty", "G", "q_pi"):
        assert all(type(value) is float for value in data[name])
    assert all(type(value) is float for row in data["q_o"] for value in row)
    assert type(data["gamma"]) is type(data["u"]) is float
    assert isinstance(job.body, JobOpened)
    assert job.body.contract == ACTION == ContractRef("sui.s1.action", "1")
    assert job.body.decision == decision.id
    assert job.body.step == 0
    assert job.body.content.as_json() == {"action": "look1"}
    assert _state(rig) == before


def test_a2_model_precision_reaches_decision():
    rig = _setup(_model(gamma=1.0))
    data = _decide(rig)[0].body.content.as_json()
    expected_G = [sum(_naive_efe([.9, .1], A, rig.model.log_C)[:2]) for A in _true_A().values()]
    _close(data["q_pi"], _naive_softmax(expected_G, 1.0))
    assert data["gamma"] == 1.0
    assert not np.allclose(data["q_pi"], [.621525219, .339008974, .039465808])


def test_a2_model_nonuniform_preferences_reach_selection():
    rig = _setup(_model(log_C=np.log([.1, .2, .7])))
    data = _decide(rig)[0].body.content.as_json()
    _close(data["G"], [2.162470396760013, 1.894682616876371, .356674943938732], atol=1e-14)
    assert data["chosen"] == "wait"


def test_a3_same_belief_different_counts_change_selection():
    unknown_a = {action: 10 * A for action, A in _true_A().items()}
    unknown_a["look2"] = np.array([[1., 1.], [1., 1.], [0., 0.]])
    unknown = _setup(_model(D=np.array([.2, .8]), a=unknown_a))
    learned = _setup(_model(D=np.array([.2, .8])))
    old = _decide(unknown)[0].body.content.as_json()
    new = _decide(learned)[0].body.content.as_json()
    _close(unknown.agent.q, learned.agent.q)
    _close(old["G"], [1.037854627602, 1.098612288668, 1.098612288668])
    _close(new["G"], [1.037854627602, 1.025914616683, 1.098612288668])
    _close(old["q_pi"], [.960658654, .019670673, .019670673], atol=1e-9)
    _close(new["q_pi"], [.315689678, .677846186, .006464136], atol=1e-9)
    assert old["chosen"] == "look1" and new["chosen"] == "look2"


def test_a3_decision_uses_current_learned_counts():
    a = {action: 10 * A for action, A in _true_A().items()}
    a["look2"] = np.array([[1., 1.], [1., 1.], [0., 0.]])
    rig = _setup(_model(D=np.array([.2, .8]), a=a, learnable=frozenset({"look2"})))
    old = _decide(rig)[0].body.content.as_json()
    _observe(rig, _observed(rig, _start(rig, "look2")))
    expected_a = np.array([[1., 1.], [2., 2.], [0., 0.]])
    _close(rig.agent.q, [.2, .8])
    _close(rig.agent.counts("look2"), expected_a)
    data = _decide(rig)[0].body.content.as_json()
    expected_A = expected_a / expected_a.sum(axis=0)
    expected_novelty = _naive_novelty([.2, .8], expected_a)
    expected = sum(_naive_efe([.2, .8], expected_A, rig.model.log_C)[:2]) - expected_novelty
    _close(data["G"][1], expected)
    _close(data["G"][1], .962098120373)
    _close(data["q_o"][1], [1 / 3, 2 / 3, 0])
    _close(data["novelty"][1], expected_novelty, atol=1e-14)
    _close(data["novelty"][1], .136514168294814, atol=1e-14)
    _close(old["G"], [1.037854627602, .905465108108, 1.098612288668])
    _close(old["novelty"][1], math.log(2) - .5, atol=1e-14)
    assert abs(data["G"][1] - old["G"][1]) > .001


def test_a4_duplicate_and_reordered_candidates_do_not_bias_selection():
    rig = _setup()
    orders = [["look1", "look1", "look2", "wait"], ["look1", "look2", "wait"],
              ["wait", "look2", "look1"]]
    contents = [_decide(rig, iter(order), u=.97)[0].body.content.as_json() for order in orders]
    assert contents[0] == contents[1] == contents[2]
    assert contents[0]["chosen"] == "wait"
    _close(contents[0]["q_pi"], [.621525219, .339008974, .039465808], atol=1e-9)


def test_a5_redelivery_and_conflict_are_checked_before_used_attempt():
    rig = _setup(_model(learnable=frozenset({"look1"})))
    obs = _observed(rig, _start(rig))
    belief = _observe(rig, obs)
    before = _state(rig)
    assert _observe(rig, obs) is None
    assert _observe(rig, replace(obs, at=rig.clock.now())) is None
    for body in (replace(obs.body, content=Payload.json({"outcome": "o0"})),
                 replace(obs.body, caused_by=None)):
        with pytest.raises(IdConflict):
            _observe(rig, replace(obs, body=body))
        _assert_unchanged(rig, before, belief)


def test_a6_unexecuted_observations_and_extra_observations_do_not_learn():
    rig = _setup(_model(learnable=frozenset({"look1", "look2"})))
    before = _state(rig)
    assert _observe(rig, _observed(rig)) is None
    unknown = replace(_observed(rig), body=Observed(
        route="executor", caused_by=Ref(K.ATTEMPT, "unknown"), contract=OUTCOME,
        content=Payload.json({"outcome": "o1"}),
    ))
    assert _observe(rig, unknown) is None
    unopened_attempt = _start(rig, register=False)
    assert _observe(rig, _observed(rig, unopened_attempt)) is None
    _assert_unchanged(rig, before, rig.belief)
    rig.agent.started(unopened_attempt)
    belief = _observe(rig, _observed(rig, unopened_attempt))
    _close(rig.agent.counts("look2"), rig.model.a["look2"])
    _close(rig.agent.counts("wait"), rig.model.a["wait"])
    after = _state(rig)
    assert _observe(rig, _observed(rig, unopened_attempt, "o0")) is None
    _assert_unchanged(rig, after, belief)


def test_a6_unattributed_observation_does_not_consume_open_attempt():
    rig = _setup(_model(learnable=frozenset({"look1"})))
    attempt = _start(rig, "look1")
    before = _state(rig)

    external = _observed(rig, outcome="o1")
    assert _observe(rig, external) is None
    _assert_unchanged(rig, before, rig.belief)

    actual = _observed(rig, attempt, "o1")
    belief = _observe(rig, actual)
    assert belief is not None
    _close(rig.agent.q, [9 / 14, 5 / 14])
    _close(rig.agent.counts("look1"), [[9, 5], [2, 6], [0, 0]])
    for action in ("look2", "wait"):
        _close(rig.agent.counts(action), rig.model.a[action])
    assert rig.agent.revision == 1
    assert belief.body.basis == (actual.id,)
    assert _decide(rig)[0].body.inputs == (belief.id,)


def test_a7_posterior_before_learning_and_fixed_actions_do_not_learn():
    rig = _setup(_model(learnable=frozenset({"look1"})))
    obs = _observed(rig, _start(rig))
    belief = _observe(rig, obs)
    _close(rig.agent.q, [.642857142857, .357142857143])
    _close(rig.agent.counts("look1"), [[9, 5], [2, 6], [0, 0]])
    assert rig.agent.revision == 1
    assert belief.body.basis == (obs.id,)
    assert belief.producer.state == StateRef(lineage="line1", revision=1)
    _close(belief.body.content.as_json()["q"], rig.agent.q)
    for action in rig.model.actions:
        _close(belief.body.content.as_json()["a"][action], rig.agent.counts(action))
        _close(rig.model.a[action], 10 * _true_A()[action])
    assert _decide(rig)[0].body.content.as_json()["gamma"] == 64.0
    old_counts = rig.agent.counts("look2")
    _observe(rig, _observed(rig, _start(rig, "look2")))
    _close(rig.agent.q, [.5, .5])
    np.testing.assert_array_equal(rig.agent.counts("look2"), old_counts)
    assert rig.agent.revision == 2


def test_a7_observation_uses_its_attempt_with_multiple_open_attempts():
    rig = _setup(_model(learnable=frozenset({"look1", "look2"})))
    look1_attempt = _start(rig, "look1")
    look2_attempt = _start(rig, "look2")
    assert look1_attempt.id != look2_attempt.id
    _close(rig.agent.q, [.9, .1])

    obs = _observed(rig, look1_attempt, "o1")
    belief = _observe(rig, obs)
    assert belief is not None
    _close(rig.agent.q, [9 / 14, 5 / 14])
    _close(rig.agent.counts("look1"), [[9, 5], [2, 6], [0, 0]])
    for action in ("look2", "wait"):
        _close(rig.agent.counts(action), rig.model.a[action])
    assert rig.agent.revision == 1
    assert belief.body.basis == (obs.id,)
    assert _decide(rig)[0].body.inputs == (belief.id,)


def test_a7_impossible_observation_is_atomic_and_can_be_corrected():
    rig = _setup(_model(learnable=frozenset({"look1"})))
    attempt = _start(rig)
    obs = _observed(rig, attempt, "none")
    before = _state(rig)
    with pytest.raises(ModelViolation):
        _observe(rig, obs)
    _assert_unchanged(rig, before, rig.belief)
    corrected = replace(obs, body=replace(obs.body, content=Payload.json({"outcome": "o1"})))
    belief = _observe(rig, corrected)
    assert belief is not None
    _close(rig.agent.q, [.642857142857, .357142857143])
    _close(rig.agent.counts("look1"), [[9, 5], [2, 6], [0, 0]])
    assert rig.agent.revision == 1


@pytest.mark.parametrize("candidates,error", [
    ([], ValueError), (["unknown"], ValueError), ([""], ValueError),
    ([1], TypeError), (["look1", True], TypeError),
])
def test_a8_invalid_candidates_leave_state_unchanged(candidates, error):
    rig = _setup()
    before = _state(rig)
    with pytest.raises(error):
        _decide(rig, candidates)
    _assert_unchanged(rig, before, rig.belief)


@pytest.mark.parametrize("method", ["started", "observe"])
@pytest.mark.parametrize("not_record", [False, True])
def test_a8_wrong_record_type(method, not_record):
    rig = _setup()
    before = _state(rig)
    value = object() if not_record else rig.belief
    with pytest.raises(TypeError):
        if method == "started":
            rig.agent.started(value)
        else:
            _observe(rig, value)
    _assert_unchanged(rig, before, rig.belief)


@pytest.mark.parametrize("changes,error", [
    ({"contract": ContractRef("sui.s1.attempt", "999")}, ContractMismatch),
    ({"contract": OUTCOME}, ContractMismatch),
    ({"content": Payload.json({"x": 1})}, ValueError),
    ({"content": Payload.json([])}, ValueError),
    ({"content": Payload.json(None)}, ValueError),
    ({"content": Payload.text("{}")}, ValueError),
    ({"content": Payload("application/json", b"not-json")}, ValueError),
    ({"job": Ref(K.JOB, "unknown")}, ValueError),
])
def test_a8_invalid_attempt_is_not_remembered(changes, error):
    rig = _setup()
    attempt = _start(rig, register=False)
    before = _state(rig)
    with pytest.raises(error):
        rig.agent.started(replace(attempt, body=replace(attempt.body, **changes)))
    _assert_unchanged(rig, before, rig.belief)
    rig.agent.started(attempt)
    assert _observe(rig, _observed(rig, attempt)) is not None
    _close(rig.agent.q, [9 / 14, 5 / 14])


def test_a8_same_attempt_cannot_be_reassigned_to_another_job():
    rig = _setup(_model(learnable=frozenset({"look1", "look2"})))
    attempt = _start(rig)
    second = _start(rig, "look2", register=False)
    before = _state(rig)
    rig.agent.started(attempt)
    _assert_unchanged(rig, before, rig.belief)
    with pytest.raises(IdConflict):
        rig.agent.started(replace(attempt, body=replace(attempt.body, job=second.body.job)))
    # ID の衝突は契約や中身の検査よりも先。
    with pytest.raises(IdConflict):
        rig.agent.started(replace(attempt, body=replace(attempt.body, contract=OUTCOME)))
    _assert_unchanged(rig, before, rig.belief)
    _observe(rig, _observed(rig, attempt))
    _close(rig.agent.q, [9 / 14, 5 / 14])
    _close(rig.agent.counts("look1"), [[9, 5], [2, 6], [0, 0]])
    _close(rig.agent.counts("look2"), rig.model.a["look2"])


@pytest.mark.parametrize("changes,error", [
    ({"contract": ContractRef("sui.s1.outcome", "999")}, ContractMismatch),
    ({"contract": ATTEMPT}, ContractMismatch),
    ({"content": Payload.json({"outcome": 1})}, ValueError),
    ({"content": Payload.json({"outcome": "o1", "x": 1})}, ValueError),
    ({"content": Payload.json(["o1"])}, ValueError),
    ({"content": Payload.json({})}, ValueError),
    ({"content": Payload.json({"outcome": "o9"})}, ValueError),
    ({"content": Payload.text('{"outcome":"o1"}')}, ValueError),
    ({"content": Payload("application/json", b"not-json")}, ValueError),
])
def test_a8_invalid_observation_can_be_corrected(changes, error):
    rig = _setup(_model(learnable=frozenset({"look1"})))
    obs = _observed(rig, _start(rig))
    before = _state(rig)
    with pytest.raises(error):
        _observe(rig, replace(obs, body=replace(obs.body, **changes)))
    _assert_unchanged(rig, before, rig.belief)
    assert _observe(rig, obs) is not None
    _close(rig.agent.q, [9 / 14, 5 / 14])
    assert rig.agent.revision == 1


def test_a8_irrelevant_and_used_attempts_are_ignored_before_content_checks():
    rig = _setup()
    bad = replace(_observed(rig), body=Observed(
        route="executor", content=Payload.json([]), contract=ATTEMPT,
    ))
    assert _observe(rig, bad) is None
    unknown = replace(bad, body=replace(bad.body, caused_by=Ref(K.ATTEMPT, "unknown")))
    assert _observe(rig, unknown) is None
    attempt = _start(rig)
    belief = _observe(rig, _observed(rig, attempt))
    before = _state(rig)
    assert _observe(rig, replace(bad, body=replace(bad.body, caused_by=attempt.id))) is None
    _assert_unchanged(rig, before, belief)


def test_a9_learned_A_reaches_next_observation_update():
    rig = _setup(_model(learnable=frozenset({"look1"})))
    first_attempt = _start(rig)
    _observe(rig, _observed(rig, first_attempt))
    _close(rig.agent.q, [9 / 14, 5 / 14])
    second_attempt = _start(rig)
    assert second_attempt.id != first_attempt.id
    _observe(rig, _observed(rig, second_attempt))
    _close(rig.agent.q[0], .375, atol=1e-14)
    assert abs(rig.agent.q[0] - .264705882352941) > .08
    assert rig.agent.revision == 2


class _FailingIds:
    def __init__(self, delegate, fail_on):
        self._delegate = delegate
        self._fail_on = fail_on
        self._calls = 0

    def new(self, kind):
        self._calls += 1
        if self._calls == self._fail_on:
            raise RuntimeError("injected ID failure")
        return self._delegate.new(kind)


class _FailingClock:
    def now(self):
        raise RuntimeError("injected clock failure")


class _WrongKindIds:
    def new(self, kind):
        return Ref(K.JOB, "wrong_kind")


@pytest.mark.parametrize("failure", ["ids", "clock", "record"])
def test_a10_failed_record_creation_is_atomic_and_retryable(failure):
    rig = _setup(_model(learnable=frozenset({"look1"})))
    obs = _observed(rig, _start(rig))
    before = _state(rig)
    ids, clock, error = rig.ids, rig.clock, RuntimeError
    if failure == "ids":
        ids = _FailingIds(rig.ids, fail_on=1)
    elif failure == "clock":
        clock = _FailingClock()
    else:
        ids, error = _WrongKindIds(), WrongKind
    with pytest.raises(error):
        rig.agent.observe(obs, clock=clock, ids=ids)
    _assert_unchanged(rig, before, rig.belief)
    belief = _observe(rig, obs)
    assert belief is not None
    _close(rig.agent.q, [.642857142857, .357142857143])
    _close(rig.agent.counts("look1"), [[9, 5], [2, 6], [0, 0]])
    assert rig.agent.revision == 1
    assert belief.body.basis == (obs.id,)
    assert _decide(rig)[0].body.inputs == (belief.id,)


def test_a10_public_belief_record_failure_keeps_latest_record():
    rig = _setup()
    before = _state(rig)
    with pytest.raises(RuntimeError):
        rig.agent.belief_record(clock=rig.clock, ids=_FailingIds(rig.ids, fail_on=1))
    _assert_unchanged(rig, before, rig.belief)


def test_a11_only_learnable_novelty_reaches_decision_in_candidate_order():
    rig = _setup(_model(learnable=frozenset({"look1"})))
    before = _state(rig)
    decision, job = _decide(rig)
    data = decision.body.content.as_json()
    assert data["candidates"] == ["look1", "look2", "wait"]
    _close(data["novelty"][0], .042718759187663, atol=1e-14)
    assert data["novelty"][1:] == [0.0, 0.0]
    assert all(type(value) is float for value in data["novelty"])
    _close(data["risk"][0], .693648803604171, atol=1e-14)
    _close(data["ambiguity"][0], .361889394108298, atol=1e-14)
    _close(data["G"][0], 1.012819438524806, atol=1e-14)
    _close(data["G"], np.array(data["risk"]) + data["ambiguity"] - data["novelty"])
    _close(data["q_pi"], [.961948764, .034083408, .003967828], atol=1e-9)
    assert data["chosen"] == job.body.content.as_json()["action"] == "look1"
    assert decision.body.contract == ContractRef("sui.s1.decision", "2")
    assert decision.producer.code_version == job.producer.code_version == "s1c"
    reordered = _decide(rig, ["wait", "look2", "look1"])[0].body.content.as_json()
    assert reordered == data
    _assert_unchanged(rig, before, rig.belief)


def test_a11_multiple_learnable_candidates_each_receive_novelty():
    rig = _setup(_model(D=np.array([.9, .1]), learnable=frozenset({"look1", "look2"})))
    data = _decide(rig)[0].body.content.as_json()
    assert data["candidates"] == ["look1", "look2", "wait"]
    _close(data["novelty"], [.042718759187663, .046979648731984, 0.0])
    _close(data["G"], np.array(data["risk"]) + data["ambiguity"] - data["novelty"])


def test_a12_unknown_tool_does_not_reinforce_wrong_prior():
    a = {action: 10 * A for action, A in _true_A().items()}
    a["look2"] = np.array([[1, 1], [1, 1], [0, 0]])
    rig = _setup(_model(a=a, D=np.array([.9, .1]), learnable=frozenset({"look2"})))
    for count in range(1, 7):
        record = _observe(rig, _observed(rig, _start(rig, "look2"), "o1"))
        _close(rig.agent.q, [.9, .1])
        np.testing.assert_array_equal(rig.agent.counts("look2"), [[1, 1], [1 + count, 1 + count], [0, 0]])
        data = record.body.content.as_json()
        np.testing.assert_array_equal(data["q"], rig.agent.q)
        np.testing.assert_array_equal(data["a"]["look2"], rig.agent.counts("look2"))
        assert data["n"]["look2"] == [0, count, 0]


def test_a13_random_static_worlds_are_exact_order_independent_and_reproducible():
    rng = np.random.default_rng(20260928)
    outcomes, actions, learnable = 3, ("u0", "u1", "fixed"), {"u0", "u1"}
    coverage = dict(three_states=0, zeros=0, ruled_out=0, prior_zero=0, moved=0)
    for case in range(200):
        states = 2 if case % 2 == 0 else 3
        priors = {}
        for action in actions:
            while True:
                p = rng.uniform(.2, 5., size=(outcomes, states))
                if case % 4 in (1, 2):
                    p[rng.random((outcomes, states)) < .3] = 0.0
                if np.all(p.sum(axis=0) > 0):
                    break
            priors[action] = p
        D = rng.dirichlet(np.ones(states))
        if case % 8 == 3:
            D[rng.integers(states)] = 0.0
            D /= D.sum()
        state = int(rng.choice(states, p=D))
        columns = {}
        for action in actions:
            support = priors[action][:, state] > 0
            if action in learnable:
                column = np.zeros(outcomes)
                column[support] = rng.dirichlet(priors[action][support, state])
            else:
                column = priors[action][:, state] / priors[action][:, state].sum()
            columns[action] = column
        length = int(rng.integers(1, 13))
        observations = []
        for _ in range(length):
            action = actions[int(rng.integers(3))]
            observations.append((action, int(rng.choice(outcomes, p=columns[action]))))
        model = _model(states=tuple(f"s{k}" for k in range(states)),
                       outcomes=("o0", "o1", "o2"), actions=actions, a=priors,
                       learnable=frozenset(learnable), D=D,
                       log_C=np.full(outcomes, -math.log(outcomes)), gamma=64.0)
        expected_q, tally = _exact_posterior(D, priors, learnable, observations)
        rigs = [_setup(model), _setup(model)]
        final_data = []
        for rig, sequence in zip(rigs, [observations, list(reversed(observations))]):
            _assert_record_reproducible(model, rig.belief)
            for action, outcome in sequence:
                record = _observe(rig, _observed(rig, _start(rig, action), f"o{outcome}"))
            _close(rig.agent.q, expected_q)
            data = record.body.content.as_json()
            np.testing.assert_array_equal(data["q"], rig.agent.q)
            assert set(data["n"]) == set(actions)
            for action in actions:
                if action in learnable:
                    expected_a = np.where(priors[action] > 0, priors[action] + tally[action][:, None], 0.0)
                    _close(rig.agent.counts(action), expected_a)
                else:
                    np.testing.assert_array_equal(rig.agent.counts(action), priors[action])
                np.testing.assert_array_equal(data["a"][action], rig.agent.counts(action))
                np.testing.assert_array_equal(data["n"][action], tally[action])
                assert all(type(count) is int for count in data["n"][action])
            _assert_record_reproducible(model, record)
            final_data.append(data)
        np.testing.assert_array_equal(rigs[0].agent.q, rigs[1].agent.q)
        np.testing.assert_array_equal(final_data[0]["q"], final_data[1]["q"])
        for action in actions:
            np.testing.assert_array_equal(rigs[0].agent.counts(action), rigs[1].agent.counts(action))
            for name in ("a", "n"):
                np.testing.assert_array_equal(final_data[0][name][action], final_data[1][name][action])
        coverage["three_states"] += states == 3
        coverage["zeros"] += any(np.any(priors[action] == 0) for action in learnable)
        coverage["ruled_out"] += bool(np.any((D > 0) & (expected_q == 0)))
        coverage["prior_zero"] += bool(np.any(D == 0))
        coverage["moved"] += bool(np.max(np.abs(expected_q - D)) > .05)
    for name, minimum in dict(three_states=50, zeros=50, ruled_out=40, prior_zero=15, moved=100).items():
        assert coverage[name] >= minimum, coverage


def _binary_model(a=None, *, learnable=frozenset(), D=None):
    if a is None:
        a = {"look": np.array([[.9, .1], [.1, .9]])}
    if D is None:
        D = np.array([.5, .5])
    return _model(states=tuple(f"s{k}" for k in range(len(D))), outcomes=("o0", "o1"),
                  actions=tuple(a), a=a, learnable=learnable, D=D,
                  log_C=np.full(2, -math.log(2)), gamma=64.0)


def test_a14_underflowed_display_recovers_from_counts_regardless_of_order():
    model = _binary_model()
    rig = _setup(model)
    for _ in range(400):
        _observe(rig, _observed(rig, _start(rig, "look"), "o0"))
    assert rig.agent.q[1] < 1e-300
    for _ in range(400):
        record = _observe(rig, _observed(rig, _start(rig, "look"), "o1"))
    _close(rig.agent.q, [.5, .5])
    assert record.body.content.as_json()["n"]["look"] == [400, 400]
    interleaved = _setup(model)
    for _ in range(400):
        for outcome in ("o0", "o1"):
            _observe(interleaved, _observed(interleaved, _start(interleaved, "look"), outcome))
    np.testing.assert_array_equal(interleaved.agent.q, rig.agent.q)
    np.testing.assert_array_equal(rig.agent.counts("look"), model.a["look"])


def test_a14_extreme_fixed_likelihood_recovers():
    rig = _setup(_binary_model({"look": np.array([[1, 1e-200], [1e-200, 1]])}))
    for outcome in ("o0", "o0", "o1", "o1"):
        _observe(rig, _observed(rig, _start(rig, "look"), outcome))
    _close(rig.agent.q, [.5, .5])


def test_a14_extreme_counts_from_two_actions_remain_possible():
    a = {"u0": np.array([[1e-300, 1], [1e300, 1]]),
         "u1": np.array([[1, 1e-300], [1, 1e300]])}
    rig = _setup(_binary_model(a))
    for action in ("u0", "u1"):
        _observe(rig, _observed(rig, _start(rig, action), "o0"))
    _close(rig.agent.q, [.5, .5])


def test_a15_ledger_is_derived_from_prior_and_total_counts():
    rig = _setup(_binary_model({"look": np.array([[2**53], [1]])},
                               learnable=frozenset({"look"}), D=np.array([1.])))
    for _ in range(2):
        record = _observe(rig, _observed(rig, _start(rig, "look"), "o0"))
    assert rig.agent.counts("look")[0, 0] == 2**53 + 2
    assert record.body.content.as_json()["n"]["look"] == [2, 0]
