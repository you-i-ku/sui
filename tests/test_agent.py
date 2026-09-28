from dataclasses import replace
from types import SimpleNamespace
import math

import numpy as np
import pytest

from sui.agent import (ACTION, BELIEF, CODE_VERSION, DECISION, Agent, read,
                       ModelMismatch, RebuildMismatch, ModelFalsified)
from sui.ledger import Ledger, SequentialSalts, DerivedParent
from sui.clock import FakeClock
from sui.contracts import ContractMismatch, ContractRef
from sui.ids import Ref, RefKind as K, SequentialIds, WrongKind
from sui.inference import ModelViolation, belief, ledger, log_likelihood
from sui.loop import ATTEMPT, OUTCOME
from sui.records import (
    AttemptStarted, Decided, IdConflict, JobOpened,
    Observed, Payload, Prediction, Producer, Record, Role, StateRef,
)
from worlds import _close, _exact_posterior, _model, _naive_efe, _naive_novelty, _naive_softmax, _true_A


def _setup(model=None, *, record=True):
    model = _model() if model is None else model
    rig = SimpleNamespace(
        ledger=Ledger(salts=SequentialSalts()),
        model=model, agent=Agent(model=model, lineage="line1"),
        clock=FakeClock(run=Ref(K.RUN, "r1")), ids=SequentialIds(),
        membrane=Producer(component="test.executor", code_version="1"),
    )
    rig.belief = rig.agent.belief_record(clock=rig.clock, ids=rig.ids, ledger=rig.ledger) if record else None
    return rig


def _decide(rig, candidates=("look1", "look2", "wait"), u=.5):
    return rig.agent.decide(
        candidates, u=u, clock=rig.clock, ids=rig.ids,
        ledger=rig.ledger,
    )


def _start(rig, action="look1", *, register=True):
    _, job = _decide(rig, [action])
    attempt = Record(
        id=rig.ids.new(K.ATTEMPT), at=rig.clock.now(), writer=Role.MEMBRANE,
        producer=rig.membrane,
        body=AttemptStarted(job=job.id, contract=ATTEMPT, content=Payload.json({})),
    )
    if register:
        rig.ledger.accept(attempt)
    return attempt


def _observed(rig, attempt=None, outcome="o1"):
    return Record(
        id=rig.ids.new(K.OBSERVATION), at=rig.clock.now(), writer=Role.MEMBRANE,
        producer=rig.membrane,
        body=Observed(route="executor", caused_by=None if attempt is None else attempt.id,
                      contract=OUTCOME, content=Payload.json({"outcome": outcome})),
    )


def _observe(rig, record):
    rig.ledger.accept(record)
    return rig.agent.adopt(rig.ledger, clock=rig.clock, ids=rig.ids)


def _state(rig):
    return (rig.agent.q.tolist(), {action: rig.agent.counts(action).tolist()
                                 for action in rig.model.actions},
            rig.agent.revision, rig.agent.producer)


def _assert_unchanged(rig, state, latest):
    assert _state(rig) == state
    assert rig.agent._belief.id == latest.id


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
    assert rig.agent.producer == Producer(component="sui.agent", code_version="s2a",
                                          state=StateRef(lineage="line1", revision=0))
    assert CODE_VERSION == "s2a"
    belief = rig.agent.belief_record(clock=rig.clock, ids=rig.ids, ledger=rig.ledger)
    assert isinstance(belief.body, Prediction)
    assert belief.writer is Role.MODEL
    assert belief.body.target == "belief"
    assert belief.body.about == belief.body.basis == ()
    assert belief.body.contract == BELIEF == ContractRef("sui.s1.belief", "3")
    assert belief.producer == rig.agent.producer
    data = belief.body.content.as_json()
    assert set(data) == {"model", "states", "outcomes", "q", "a", "n", "unread"}
    assert data["states"] == ["s0", "s1"]
    assert data["outcomes"] == ["o0", "o1", "none"]
    _close(data["q"], rig.model.D, atol=1e-15)
    _assert_record_reproducible(rig.model, belief)
    assert set(data["n"]) == set(rig.model.actions)
    for action in rig.model.actions:
        _close(data["a"][action], rig.model.a[action])
        assert data["n"][action] == [0] * len(rig.model.outcomes)
        assert all(type(count) is int for count in data["n"][action])
    next_belief = rig.agent.belief_record(clock=rig.clock, ids=rig.ids, ledger=rig.ledger)
    assert next_belief.body.basis == ()
    assert rig.ledger.entries_of(next_belief.id)[0].parents == rig.agent.frontier
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
    external = _observed(rig)
    assert _observe(rig, external) is not None
    assert dict(rig.agent.unread)[external.id] == "no_attempt"
    attempt = _start(rig, register=False)
    obs = _observed(rig, attempt)
    assert _observe(rig, obs) is not None
    assert dict(rig.agent.unread)[obs.id] == "unknown_attempt"
    # A late attempt is a separate branch; its original timestamp precedes the observation.
    rig.ledger.append(attempt, ())
    rig.agent.adopt(rig.ledger, clock=rig.clock, ids=rig.ids)
    _close(rig.agent.q, [9 / 14, 5 / 14])
    extra = _observed(rig, attempt, "o0")
    belief = _observe(rig, extra)
    assert dict(rig.agent.unread)[obs.id] == dict(rig.agent.unread)[extra.id] == "ambiguous_attempt"
    assert belief.body.content.as_json()["n"]["look1"] == [0, 0, 0]
    _close(rig.agent.q, [.9, .1])
    for action in rig.model.actions:
        _close(rig.agent.counts(action), rig.model.a[action])


def test_a6_unattributed_observation_does_not_consume_open_attempt():
    rig = _setup(_model(learnable=frozenset({"look1"})))
    attempt = _start(rig)
    external = _observed(rig)
    assert _observe(rig, external) is not None
    assert dict(rig.agent.unread)[external.id] == "no_attempt"
    actual = _observed(rig, attempt)
    belief = _observe(rig, actual)
    _close(rig.agent.q, [9 / 14, 5 / 14])
    _close(rig.agent.counts("look1"), [[9, 5], [2, 6], [0, 0]])
    assert rig.agent.revision == 2
    assert belief.body.basis == ()
    assert rig.ledger.entries_of(belief.id)[0].parents == rig.agent.frontier


def test_a7_posterior_before_learning_and_fixed_actions_do_not_learn():
    rig = _setup(_model(learnable=frozenset({"look1"})))
    obs = _observed(rig, _start(rig))
    belief = _observe(rig, obs)
    _close(rig.agent.q, [.642857142857, .357142857143])
    _close(rig.agent.counts("look1"), [[9, 5], [2, 6], [0, 0]])
    assert rig.agent.revision == 1
    assert belief.body.basis == ()
    assert rig.ledger.entries_of(belief.id)[0].parents == rig.agent.frontier
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
    assert belief.body.basis == ()
    assert rig.ledger.entries_of(belief.id)[0].parents == rig.agent.frontier
    assert _decide(rig)[0].body.inputs == (belief.id,)


def test_a7_impossible_observation_is_preserved_and_correction_has_a_new_id():
    rig = _setup(_model(learnable=frozenset({"look1"})))
    obs = _observed(rig, _start(rig), "none")
    assert _observe(rig, obs) is not None
    assert dict(rig.agent.unread)[obs.id] == "impossible"
    corrected = replace(obs, body=replace(obs.body, content=Payload.json({"outcome": "o1"})))
    with pytest.raises(IdConflict):
        rig.ledger.accept(corrected)
    corrected = replace(corrected, id=rig.ids.new(K.OBSERVATION), at=rig.clock.now())
    assert _observe(rig, corrected) is not None
    _close(rig.agent.q, [.642857142857, .357142857143])
    _close(rig.agent.counts("look1"), [[9, 5], [2, 6], [0, 0]])
    assert dict(rig.agent.unread) == {obs.id: "impossible"}


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


@pytest.mark.parametrize("not_record", [False, True])
def test_a8_wrong_record_type(not_record):
    rig = _setup()
    value = object() if not_record else rig.belief
    with pytest.raises(TypeError if not_record else ValueError):
        rig.ledger.accept(value)


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
def test_a8_invalid_attempt_is_preserved_as_unreadable(changes, error):
    rig = _setup()
    attempt = _start(rig, register=False)
    bad = replace(attempt, body=replace(attempt.body, **changes))
    rig.ledger.accept(bad)
    obs = _observed(rig, bad)
    assert _observe(rig, obs) is not None
    assert dict(rig.agent.unread)[obs.id] == "unreadable_attempt"
    _close(rig.agent.q, [.9, .1])
    with pytest.raises(IdConflict):
        rig.ledger.accept(attempt)
    corrected = replace(attempt, id=rig.ids.new(K.ATTEMPT), at=rig.clock.now())
    rig.ledger.accept(corrected)
    _observe(rig, _observed(rig, corrected))
    _close(rig.agent.q, [9 / 14, 5 / 14])
    assert dict(rig.agent.unread)[obs.id] == "unreadable_attempt"


def test_a8_same_attempt_cannot_be_reassigned_to_another_job():
    rig = _setup(_model(learnable=frozenset({"look1", "look2"})))
    attempt = _start(rig)
    second = _start(rig, "look2", register=False)
    before = _state(rig)
    rig.ledger.accept(attempt)
    _assert_unchanged(rig, before, rig.belief)
    with pytest.raises(IdConflict):
        rig.ledger.accept(replace(attempt, body=replace(attempt.body, job=second.body.job)))
    # ID の衝突は契約や中身の検査よりも先。
    with pytest.raises(IdConflict):
        rig.ledger.accept(replace(attempt, body=replace(attempt.body, contract=OUTCOME)))
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
    bad = replace(obs, body=replace(obs.body, **changes))
    record = _observe(rig, bad)
    assert record is not None
    reason = "contract" if "contract" in changes else (
        "unknown_outcome" if changes["content"] == Payload.json({"outcome": "o9"}) else "content")
    assert dict(rig.agent.unread)[obs.id] == reason
    with pytest.raises(IdConflict):
        rig.ledger.accept(obs)
    corrected = replace(obs, id=rig.ids.new(K.OBSERVATION), at=rig.clock.now())
    assert _observe(rig, corrected) is not None
    _close(rig.agent.q, [9 / 14, 5 / 14])
    assert dict(rig.agent.unread)[obs.id] == reason


def test_a8_unread_reasons_precede_content_checks():
    rig = _setup()
    bad = replace(_observed(rig), body=Observed(route="executor", content=Payload.json([]), contract=ATTEMPT))
    _observe(rig, bad)
    assert dict(rig.agent.unread)[bad.id] == "no_attempt"
    unknown = replace(bad, id=rig.ids.new(K.OBSERVATION), at=rig.clock.now(),
                      body=replace(bad.body, caused_by=Ref(K.ATTEMPT, "unknown")))
    _observe(rig, unknown)
    assert dict(rig.agent.unread)[unknown.id] == "unknown_attempt"


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
        rig.ledger.accept(obs)
        rig.agent.adopt(rig.ledger, clock=clock, ids=ids)
    _assert_unchanged(rig, before, rig.belief)
    belief = _observe(rig, obs)
    assert belief is not None
    _close(rig.agent.q, [.642857142857, .357142857143])
    _close(rig.agent.counts("look1"), [[9, 5], [2, 6], [0, 0]])
    assert rig.agent.revision == 1
    assert belief.body.basis == ()
    assert rig.ledger.entries_of(belief.id)[0].parents == rig.agent.frontier
    assert _decide(rig)[0].body.inputs == (belief.id,)


def test_a10_public_belief_record_failure_keeps_latest_record():
    rig = _setup()
    before = _state(rig)
    with pytest.raises(RuntimeError):
        rig.agent.belief_record(clock=rig.clock, ids=_FailingIds(rig.ids, fail_on=1), ledger=rig.ledger)
    _assert_unchanged(rig, before, rig.belief)


@pytest.mark.parametrize("fail_on", [1, 2])
def test_a10_decision_builds_both_records_before_appending(fail_on):
    rig = _setup()
    before, entries = _full_state(rig.agent), rig.ledger.entries()
    with pytest.raises(RuntimeError):
        rig.agent.decide(["look1"], u=.5, clock=rig.clock,
                         ids=_FailingIds(rig.ids, fail_on), ledger=rig.ledger)
    assert _full_state(rig.agent) == before
    assert rig.ledger.entries() == entries


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
    assert decision.producer.code_version == job.producer.code_version == "s2a"
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


@pytest.mark.parametrize("error", [ValueError, FloatingPointError])
def test_a16_failed_derivation_is_atomic_and_retryable(monkeypatch, error):
    rig = _setup(_model(learnable=frozenset({"look1"})))
    obs = _observed(rig, _start(rig))
    before = _state(rig)

    def fail_likelihood(a, n, *, learnable):
        raise error("injected derivation failure")

    with monkeypatch.context() as patch:
        patch.setattr("sui.agent._log_likelihood", fail_likelihood)
        with pytest.raises(error, match="injected derivation failure"):
            _observe(rig, obs)
        _assert_unchanged(rig, before, rig.belief)

    record = _observe(rig, obs)
    assert record is not None
    assert record.body.content.as_json()["n"] == {
        "look1": [0, 1, 0], "look2": [0, 0, 0], "wait": [0, 0, 0],
    }
    _close(rig.agent.q, [9 / 14, 5 / 14])
    _close(rig.agent.counts("look1"), [[9, 5], [2, 6], [0, 0]])
    assert rig.agent.revision == 1
    assert record.body.basis == ()
    assert rig.ledger.entries_of(record.id)[0].parents == rig.agent.frontier
    assert _decide(rig)[0].body.inputs == (record.id,)



def _full_state(agent):
    return (agent.frontier, agent.revision, agent._belief, agent.unread,
            None if agent._q is None else agent.q.tolist(),
            {k: v.tolist() for k, v in agent._reading.n.items()},
            {k: agent.counts(k).tolist() for k in agent._reading.n})


def _restore(rig, record=None):
    record = rig.agent._belief if record is None else record
    return Agent.restore(model=rig.model, lineage="restored", ledger=rig.ledger,
                         belief=rig.ledger.entries_of(record.id)[0].cid)


def _mixed_facts():
    rig = _setup(_model(learnable=frozenset({"look1"})))
    expected = {}
    def add(record, reason=None):
        rig.ledger.accept(record)
        if reason is not None:
            expected[record.id] = reason
        return record
    add(_observed(rig), "no_attempt")
    add(replace(_observed(rig), body=replace(_observed(rig).body,
        caused_by=Ref(K.ATTEMPT, "missing"))), "unknown_attempt")
    bad_attempt = _start(rig, register=False)
    rig.ledger.accept(replace(bad_attempt, body=replace(bad_attempt.body, content=Payload.json({"x": 1}))))
    add(_observed(rig, bad_attempt), "unreadable_attempt")
    ambiguous = _start(rig)
    add(_observed(rig, ambiguous, "o0"), "ambiguous_attempt")
    add(_observed(rig, ambiguous, "o1"), "ambiguous_attempt")
    for reason in ("contract", "content", "unknown_outcome", "impossible"):
        obs = _observed(rig, _start(rig))
        change = {"contract": dict(contract=ContractRef("sui.other", "1")),
                  "content": dict(content=Payload.json({"outcome": 1})),
                  "unknown_outcome": dict(content=Payload.json({"outcome": "o9"})),
                  "impossible": dict(content=Payload.json({"outcome": "none"}))}[reason]
        add(replace(obs, body=replace(obs.body, **change)), reason)
    add(_observed(rig, _start(rig, "look1"), "o1"))
    add(_observed(rig, _start(rig, "look2"), "o0"))
    return rig, expected


def test_a17_unread_facts_remain_and_only_two_observations_are_learned():
    rig, expected = _mixed_facts()
    record = rig.agent.adopt(rig.ledger, clock=rig.clock, ids=rig.ids)
    data = record.body.content.as_json()
    assert len(expected) == 9
    assert data["unread"] == [{"id": str(ref), "reason": expected[ref]} for ref in sorted(expected, key=str)]
    assert dict(rig.agent.unread) == expected
    assert all(rig.ledger.entries_of(ref) for ref in expected)
    assert data["n"] == {"look1": [0, 1, 0], "look2": [1, 0, 0], "wait": [0, 0, 0]}
    _close(data["q"], [.9, .1])
    assert data["a"]["look1"] == [[9, 5], [2, 6], [0, 0]]


def test_a17b_unread_is_sorted_by_ref_not_causal_order():
    rig = _setup()
    for name in ("z", "a"):
        rig.ledger.accept(replace(_observed(rig), id=Ref(K.OBSERVATION, name)))
    record = rig.agent.adopt(rig.ledger, clock=rig.clock, ids=rig.ids)
    assert record.body.content.as_json()["unread"] == [
        {"id": "observation:a", "reason": "no_attempt"}, {"id": "observation:z", "reason": "no_attempt"}]
    assert rig.agent.unread == ((Ref(K.OBSERVATION, "a"), "no_attempt"), (Ref(K.OBSERVATION, "z"), "no_attempt"))


def test_a17c_late_attempt_turns_unknown_observation_into_evidence():
    rig = _setup(_model(learnable=frozenset({"look1"})))
    attempt = _start(rig)
    facts = rig.ledger
    rig.ledger = Ledger(salts=SequentialSalts())
    obs = _observed(rig, attempt)
    _observe(rig, obs)
    assert dict(rig.agent.unread) == {obs.id: "unknown_attempt"}
    _close(rig.agent.q, [.9, .1])
    rig.ledger.merge(facts)
    record = rig.agent.adopt(rig.ledger, clock=rig.clock, ids=rig.ids)
    assert rig.agent.unread == ()
    _close(rig.agent.q, [9 / 14, 5 / 14])
    assert record.body.content.as_json()["n"]["look1"] == [0, 1, 0]


@pytest.mark.parametrize("learnable", [frozenset(), frozenset({"look"})])
@pytest.mark.parametrize("ambiguous_outcome", [0, 1])
def test_a17d_r2_falsified_models_keep_counts_and_allow_further_adoption(learnable, ambiguous_outcome):
    model = _binary_model({"look": np.eye(2)}, learnable=learnable)
    rig = _setup(model)
    attempt0 = _start(rig, "look")
    observation0 = _observed(rig, attempt0, "o0")
    _observe(rig, observation0)
    _close(rig.agent.q, [1, 0])
    attempt1 = _start(rig, "look")
    observation1 = _observed(rig, attempt1, "o1")
    record = _observe(rig, observation1)
    data = record.body.content.as_json()
    assert data["q"] is None
    assert data["n"]["look"] == [1, 1]
    assert data["a"]["look"] == ([[2, 0], [0, 2]] if learnable else [[1, 0], [0, 1]])
    assert data["unread"] == []
    with pytest.raises(ModelFalsified):
        _ = rig.agent.q
    with pytest.raises(ModelFalsified):
        _decide(rig, ["look"])
    before = rig.agent.frontier
    external = _observed(rig)
    next_record = _observe(rig, external)
    assert rig.agent.frontier != before
    assert next_record.body.content.as_json()["q"] is None
    restored = _restore(rig)
    assert _full_state(restored) == _full_state(rig.agent)

    attempt = (attempt0, attempt1)[ambiguous_outcome]
    original = (observation0, observation1)[ambiguous_outcome]
    extra = _observed(rig, attempt, f"o{ambiguous_outcome}")
    recovered = _observe(rig, extra)
    data = recovered.body.content.as_json()
    # 一方の試みを保留すると、残る一件が支持する状態だけになる。
    expected_n = [0, 1] if ambiguous_outcome == 0 else [1, 0]
    expected_a = [[1, 0], [0, 1]]
    if learnable:
        expected_a = [[1 + expected_n[0], 0], [0, 1 + expected_n[1]]]
    assert data["q"] == expected_n
    np.testing.assert_array_equal(rig.agent.q, expected_n)
    assert data["n"]["look"] == expected_n
    assert data["a"]["look"] == expected_a
    assert dict(rig.agent.unread) == {
        external.id: "no_attempt", original.id: "ambiguous_attempt", extra.id: "ambiguous_attempt",
    }
    assert _full_state(_restore(rig)) == _full_state(rig.agent)
    assert _decide(rig, ["look"])[0].body.content.as_json()["chosen"] == "look"


def test_r1_read_is_independent_of_twenty_permutations_and_reverse_order():
    import random
    rig, _ = _mixed_facts()
    records = list(rig.ledger.snapshot(rig.ledger.heads()).records)
    baseline = read(rig.model, records)
    rng = random.Random(20260929)
    orders = [list(reversed(records))]
    for _ in range(20):
        order = records.copy()
        rng.shuffle(order)
        orders.append(order)
    for order in orders:
        reading = read(rig.model, iter(order))
        assert reading.unread == baseline.unread
        for action in rig.model.actions:
            np.testing.assert_array_equal(reading.n[action], baseline.n[action])
            assert reading.n[action].dtype == np.int64
            assert not reading.n[action].flags.writeable
    with pytest.raises(TypeError):
        baseline.unread[Ref(K.OBSERVATION, "x")] = "no_attempt"
    with pytest.raises(TypeError):
        baseline.n["look1"] = np.zeros(3, dtype=np.int64)


def test_r2_impossible_uses_prior_support():
    rig = _setup(_binary_model({"look": np.eye(2)}, D=np.array([1., 0.])))
    obs = _observed(rig, _start(rig, "look"), "o1")
    record = _observe(rig, obs)
    assert dict(rig.agent.unread) == {obs.id: "impossible"}
    assert record.body.content.as_json()["n"]["look"] == [0, 0]
    _close(rig.agent.q, [1, 0])


def test_r2_identical_outcomes_with_different_ids_are_also_ambiguous():
    rig = _setup()
    attempt = _start(rig)
    first, second = _observed(rig, attempt), _observed(rig, attempt)
    rig.ledger.accept(first)
    record = _observe(rig, second)
    assert dict(rig.agent.unread) == {first.id: "ambiguous_attempt", second.id: "ambiguous_attempt"}
    assert record.body.content.as_json()["n"]["look1"] == [0, 0, 0]


@pytest.mark.parametrize("reason", ["no_attempt", "unknown_attempt", "unreadable_attempt", "contract", "content", "unknown_outcome", "impossible"])
def test_r2_reason_priority_with_later_checks_also_invalid(reason):
    rig = _setup()
    attempt = _start(rig, register=False)
    if reason == "unreadable_attempt":
        attempt = replace(attempt, body=replace(attempt.body, content=Payload.json({"x": 1})))
    if reason not in ("no_attempt", "unknown_attempt"):
        rig.ledger.accept(attempt)
    obs = _observed(rig, attempt)
    if reason == "no_attempt":
        obs = replace(obs, body=replace(obs.body, caused_by=None))
    if reason in ("no_attempt", "unknown_attempt", "unreadable_attempt", "contract"):
        obs = replace(obs, body=replace(obs.body, contract=ContractRef("sui.other", "1"), content=Payload.json({"outcome": 1})))
    elif reason == "content":
        obs = replace(obs, body=replace(obs.body, content=Payload.json({"outcome": 1})))
    else:
        obs = replace(obs, body=replace(obs.body, content=Payload.json({"outcome": "o9" if reason == "unknown_outcome" else "none"})))
    record = _observe(rig, obs)
    assert dict(rig.agent.unread) == {obs.id: reason}
    assert record.body.content.as_json()["n"]["look1"] == [0, 0, 0]


def test_a18_other_lineages_jobs_are_read():
    rig = _setup(_model(learnable=frozenset({"look1"})))
    other = Agent(model=rig.model, lineage="someone_else")
    other.belief_record(clock=rig.clock, ids=rig.ids, ledger=rig.ledger)
    _, job = other.decide(["look1"], u=.5, clock=rig.clock, ids=rig.ids, ledger=rig.ledger)
    attempt = Record(id=rig.ids.new(K.ATTEMPT), at=rig.clock.now(), writer=Role.MEMBRANE,
                     producer=rig.membrane, body=AttemptStarted(job=job.id, content=Payload.json({}), contract=ATTEMPT))
    rig.ledger.accept(attempt)
    record = _observe(rig, _observed(rig, attempt))
    assert job.producer.state.lineage != rig.agent.producer.state.lineage
    assert record.body.content.as_json()["n"]["look1"] == [0, 1, 0]
    _close(rig.agent.q, [9 / 14, 5 / 14])


def test_a19_restore_every_step_and_continue_the_same_sampled_world():
    import copy
    import random
    from sui.loop import run_step
    from worlds import SampledWorld
    rig = _setup()
    world = SampledWorld(true_state=1, A=_true_A(), seed=7)
    rng = random.Random(11)
    draws = [rng.random() for _ in range(20)]
    history, states = [], []
    for index, u in enumerate(draws):
        step = run_step(rig.agent, world, rig.model.actions, u=u, clock=rig.clock,
                        ids=rig.ids, ledger=rig.ledger, membrane=rig.membrane)
        history.append(step)
        states.append(_full_state(rig.agent))
        if index == 9:
            branch_ledger = Ledger(salts=SequentialSalts())
            branch_ledger.merge(rig.ledger)
            branch_world = copy.deepcopy(world)
    for step, expected in zip(history, states):
        restored = _restore(rig, step.belief)
        assert _full_state(restored) == expected
    branch = Agent.restore(model=rig.model, lineage="branch", ledger=branch_ledger,
                           belief=branch_ledger.entries_of(history[9].belief.id)[0].cid)
    clock, ids = FakeClock(run=Ref(K.RUN, "branch")), SequentialIds("branch")
    for u, expected in zip(draws[10:], history[10:]):
        step = run_step(branch, branch_world, rig.model.actions, u=u, clock=clock,
                        ids=ids, ledger=branch_ledger, membrane=rig.membrane)
        data, old = step.decided.body.content.as_json(), expected.decided.body.content.as_json()
        assert data["chosen"] == old["chosen"]
        assert data["q_pi"] == old["q_pi"]
        assert step.belief.body.content == expected.belief.body.content


@pytest.mark.parametrize("learnable", [frozenset(), frozenset({"look1"})])
def test_a26_restore_without_cached_records_matches_cached_rebuild(learnable):
    import random
    from sui.loop import run_step
    from worlds import SampledWorld
    rig = _setup(_model(learnable=learnable))
    world = SampledWorld(true_state=1, A=_true_A(), seed=7)
    draws = random.Random(11)
    for _ in range(20):
        step = run_step(rig.agent, world, rig.model.actions, u=draws.random(),
                        clock=rig.clock, ids=rig.ids, ledger=rig.ledger, membrane=rig.membrane)
    belief = step.belief
    if learnable:
        assert belief.body.content.as_json()["n"]["look1"] != [0, 0, 0]
    assert rig.ledger._records
    cached = _restore(rig, belief)
    cached_record = cached.belief_record(clock=rig.clock, ids=rig.ids, ledger=rig.ledger)
    rig.ledger._records.clear()
    assert not rig.ledger._records
    uncached = _restore(rig, belief)
    uncached_record = uncached.belief_record(clock=rig.clock, ids=rig.ids, ledger=rig.ledger)
    assert uncached_record.body.content == cached_record.body.content == belief.body.content


def test_a20_restore_does_not_repeat_effects():
    import inspect
    from sui.loop import run_step
    from worlds import ScriptedWorld
    rig = _setup()
    world = ScriptedWorld({"look1": ["o1"] * 5})
    for _ in range(5):
        run_step(rig.agent, world, ["look1"], u=.5, clock=rig.clock, ids=rig.ids,
                 ledger=rig.ledger, membrane=rig.membrane)
    before = list(world.calls)
    _restore(rig)
    assert world.calls == before == ["look1"] * 5
    assert "executor" not in inspect.signature(Agent.restore).parameters


def test_a21_restore_rejects_different_model_reference():
    rig = _setup()
    with pytest.raises(ModelMismatch):
        Agent.restore(model=replace(rig.model, gamma=63.0), lineage="restored", ledger=rig.ledger,
                      belief=rig.ledger.entries_of(rig.belief.id)[0].cid)


@pytest.mark.parametrize("key", ["n", "q", "a", "unread", "states", "outcomes"])
def test_a22_restore_compares_each_key_independently(key):
    rig = _setup(_model(learnable=frozenset({"look1"})))
    correct = _observe(rig, _observed(rig, _start(rig)))
    data = correct.body.content.as_json()
    if key == "n":
        data[key]["look1"][0] += 1
    elif key == "q":
        data[key][0] += 1e-12
    elif key == "a":
        data[key]["look1"][0][0] += 1
    elif key == "unread":
        data[key].append({"id": "observation:extra", "reason": "no_attempt"})
    else:
        data[key][0], data[key][1] = data[key][1], data[key][0]
    fake = replace(correct, id=rig.ids.new(K.PREDICTION), at=rig.clock.now(),
                   body=replace(correct.body, content=Payload.json(data)))
    entry = rig.ledger.append(fake, rig.agent.frontier)
    with pytest.raises(RebuildMismatch) as error:
        Agent.restore(model=rig.model, lineage="restored", ledger=rig.ledger, belief=entry.cid)
    assert error.value.fields == (key,)


@pytest.mark.parametrize("failure", ["missing_key", "state", "target", "contract", "not_prediction", "model_type", "states_type", "outcomes_type", "q_type", "n_type", "a_type", "unread_type"])
def test_a22_restore_rejects_malformed_beliefs(failure):
    rig = _setup()
    record = rig.belief
    data = record.body.content.as_json()
    if failure == "missing_key":
        del data["unread"]
    elif failure.endswith("_type"):
        data[failure[:-5]] = False
    elif failure == "state":
        record = replace(record, producer=replace(record.producer, state=None))
    elif failure == "target":
        record = replace(record, body=replace(record.body, target="other"))
    elif failure == "contract":
        record = replace(record, body=replace(record.body, contract=OUTCOME))
    elif failure == "not_prediction":
        entry = rig.ledger.accept(_observed(rig))
        with pytest.raises(ValueError, match="Prediction"):
            Agent.restore(model=rig.model, lineage="r", ledger=rig.ledger, belief=entry.cid)
        return
    record = replace(record, id=rig.ids.new(K.PREDICTION), at=rig.clock.now(),
                     body=replace(record.body, content=Payload.json(data)))
    entry = rig.ledger.append(record, rig.agent.frontier)
    with pytest.raises(ValueError):
        Agent.restore(model=rig.model, lineage="r", ledger=rig.ledger, belief=entry.cid)


def test_a23_removing_all_derived_leaves_preserves_facts_and_rebuilds():
    rig = _setup(_model(learnable=frozenset({"look1"})))
    for _ in range(10):
        _observe(rig, _observed(rig, _start(rig)))
    target = Ledger(salts=SequentialSalts())
    target.merge(rig.ledger, events_only=True)
    assert all(entry.is_event for entry in target.entries())
    assert {entry.cid for entry in target.entries()} == {entry.cid for entry in rig.ledger.entries() if entry.is_event}
    assert target.heads() == rig.ledger.heads()
    assert target.verify() is rig.ledger.verify() is None
    subject = Agent(model=rig.model, lineage="fresh")
    record = subject.adopt(target, clock=rig.clock, ids=rig.ids)
    assert record.body.content == rig.agent._belief.body.content


def test_a24_adoption_is_idempotent_and_cannot_go_back_or_use_leaves():
    rig = _setup()
    first = _observe(rig, _observed(rig, _start(rig)))
    previous = rig.agent.frontier
    _observe(rig, _observed(rig, _start(rig)))
    state, entries = _full_state(rig.agent), rig.ledger.entries()
    assert rig.agent.adopt(rig.ledger, clock=rig.clock, ids=rig.ids) is None
    assert _full_state(rig.agent) == state and rig.ledger.entries() == entries
    with pytest.raises(ValueError):
        rig.agent.adopt(rig.ledger, clock=rig.clock, ids=rig.ids, through=previous)
    with pytest.raises(DerivedParent):
        rig.agent.adopt(rig.ledger, clock=rig.clock, ids=rig.ids, through={rig.ledger.entries_of(first.id)[0].cid})
    assert _full_state(rig.agent) == state and rig.ledger.entries() == entries


@pytest.mark.parametrize("unread_only", [False, True])
@pytest.mark.parametrize("failure", ["ids", "storage"])
def test_a25_failed_adoption_is_atomic_and_retryable(unread_only, failure):
    rig = _setup(_model(learnable=frozenset({"look1"})))
    obs = _observed(rig) if unread_only else _observed(rig, _start(rig))
    rig.ledger.accept(obs)
    before, entries = _full_state(rig.agent), rig.ledger.entries()
    contents = rig.ledger.contents
    class FailingContents:
        def get(self, seal):
            return contents.get(seal)
        def put(self, *args):
            raise RuntimeError("injected put failure")
    if failure == "storage":
        rig.ledger.contents = FailingContents()
    try:
        with pytest.raises(RuntimeError):
            rig.agent.adopt(rig.ledger, clock=rig.clock,
                            ids=_FailingIds(rig.ids, 1) if failure == "ids" else rig.ids)
    finally:
        rig.ledger.contents = contents
    assert _full_state(rig.agent) == before
    assert rig.ledger.entries() == entries
    assert rig.ledger.entries_of(obs.id)
    clean = Agent(model=rig.model, lineage="clean")
    expected = clean.adopt(rig.ledger, clock=rig.clock, ids=rig.ids)
    retried = rig.agent.adopt(rig.ledger, clock=rig.clock, ids=rig.ids)
    assert retried.body.content == expected.body.content
    assert rig.agent.frontier == clean.frontier
    assert rig.agent.revision == clean.revision
