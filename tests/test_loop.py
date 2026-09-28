from dataclasses import FrozenInstanceError, fields
import random

import numpy as np
import pytest

from sui.agent import ACTION, BELIEF, DECISION, Agent
from sui.clock import FakeClock
from sui.contracts import ContractRef
from sui.ids import Ref, RefKind as K, SequentialIds
from sui.ledger import Ledger, SequentialSalts
from sui.loop import ATTEMPT, OUTCOME, StepRecords, run_step
from sui.records import (
    AttemptStarted, Decided, JobOpened, Observed, Prediction, Producer, Role,
)
from worlds import SampledWorld, ScriptedWorld, _close, _model, _true_A
from worlds import _storage, _stored_rig, _stored_step


@pytest.mark.parametrize("backend", ["memory", "sqlite"])
def test_s2b_loop_store_substitution(tmp_path, backend):
    with _storage(tmp_path, backend) as store:
        rig = _stored_rig(store)
        previous = rig.belief
        for index in range(3):
            step = _stored_step(rig)
            assert step.decided.body.inputs == (previous.id,)
            assert step.attempt.body.job == step.job.id
            assert step.observed.body.caused_by == step.attempt.id
            assert rig.agent.revision == index + 1
            assert len(rig.world.calls) == index + 1
            rig.ledger.verify()
            previous = step.belief


def _setup(*, learnable=frozenset(), **model_changes):
    agent = Agent(model=_model(learnable=learnable, **model_changes), lineage="line1")
    clock = FakeClock(run=Ref(K.RUN, "r1"))
    ids = SequentialIds()
    ledger = Ledger(salts=SequentialSalts())
    agent.belief_record(clock=clock, ids=ids, ledger=ledger)
    kwargs = dict(clock=clock, ids=ids, ledger=ledger,
                  membrane=Producer(component="test.executor", code_version="1"))
    return agent, kwargs


def _assert_step_links(step, previous_belief, revision, through, kwargs):
    assert step.decided.body.inputs == (previous_belief.id,)
    assert step.belief.body.basis == ()
    assert step.observed.body.caused_by == step.attempt.id
    assert step.attempt.body.job == step.job.id
    assert step.job.body.decision == step.decided.id
    assert step.job.body.step == 0
    assert step.belief.body.about == () and step.belief.body.target == "belief"
    assert step.observed.body.route == "executor"
    assert step.attempt.body.content.as_json() == {}
    assert step.decided.producer.state.revision == revision
    assert step.job.producer.state.revision == revision
    assert step.belief.producer.state.revision == revision + 1
    assert step.decided.producer.state.lineage == step.belief.producer.state.lineage == "line1"
    ledger = kwargs["ledger"]
    entry = lambda record: ledger.entries_of(record.id)[0]
    assert entry(step.decided).parents == through
    assert entry(step.job).parents == {entry(step.decided).cid}
    assert entry(step.attempt).parents == {entry(step.job).cid}
    assert entry(step.observed).parents == {entry(step.attempt).cid}
    assert entry(step.belief).parents == {entry(step.observed).cid}
    assert previous_belief.at.seq < step.decided.at.seq
    records = [step.decided, step.job, step.attempt, step.observed, step.belief]
    assert [type(record.body) for record in records] == [Decided, JobOpened, AttemptStarted, Observed, Prediction]
    assert [record.body.contract for record in records] == [DECISION, ACTION, ATTEMPT, OUTCOME, BELIEF]
    assert [record.id.kind for record in records] == [K.DECISION, K.JOB, K.ATTEMPT, K.OBSERVATION, K.PREDICTION]
    assert [record.writer for record in records] == [Role.MODEL, Role.MODEL, Role.MEMBRANE, Role.MEMBRANE, Role.MODEL]
    assert step.attempt.producer == step.observed.producer == kwargs["membrane"]
    assert all(ledger.record(entry(record).cid) == record for record in records)
    assert all(a.at.seq < b.at.seq for a, b in zip(records, records[1:]))
    assert step.job.body.content.as_json()["action"] == step.decided.body.content.as_json()["chosen"]


def test_l1_closed_loop_changes_executed_action_and_preserves_evidence_chain():
    agent, kwargs = _setup()
    world = ScriptedWorld({"look1": ["o1", "o1"], "look2": ["o1", "o1"]})
    expected_G = [
        [1.055538197712, 1.065009290053, 1.098612288668],
        [1.000795783531, 1.008551405495, 1.098612288668],
        [1.023776337850, 1.012674275385, 1.098612288668],
    ]
    expected_pi = [
        [.621525219, .339008974, .039465808],
        [.620866069, .377947608, .001186324],
        [.328580932, .668686389, .002732679],
    ]
    expected_q = [.9, .642857142857, .264705882353, .166666666667]
    actions = ["look1", "look1", "look2"]
    for index in range(3):
        _close(agent.q[0], expected_q[index])
        assert np.all(agent.q > 0)
        through = agent.frontier
        previous = agent._belief
        step = run_step(agent, world, ["look1", "look2", "wait"], u=.5, **kwargs)
        data = step.decided.body.content.as_json()
        _close(data["G"], expected_G[index])
        _close(data["q_pi"], expected_pi[index], atol=1e-9)
        assert data["chosen"] == actions[index]
        _close(agent.q[0], expected_q[index + 1])
        _close(step.belief.body.content.as_json()["q"], agent.q)
        _assert_step_links(step, previous, index, through, kwargs)
    assert world.calls == actions
    assert len(kwargs["ledger"].entries()) == 16
    assert len({record.id for record in kwargs["ledger"].entries()}) == 16
    assert agent.revision == 3
    for action, A in _true_A().items():
        _close(agent.counts(action), 10 * A)


def test_l2_learning_and_novelty_reach_fixed_decision_values():
    agent, kwargs = _setup(learnable=frozenset({"look1"}))
    world = ScriptedWorld({"look1": ["o1", "o1", "o1"], "look2": ["o1", "o1"]})
    expected_G = [
        [1.012819438525, 1.065009290053, 1.098612288668],
        [.986812554474, 1.008551405495, 1.098612288668],
        [1.004699161538, .999384195129, 1.098612288668],
    ]
    expected_pi = [
        [.961948764, .034083408, .003967828],
        [.800297140, .199077982, .000624877],
        [.415347525, .583633624, .001018851],
    ]
    expected_q = [.9, .642857142857, .375, .25]
    expected_o1_counts = [
        [2, 6], [3, 7], [3, 7],
    ]
    actions = ["look1", "look1", "look2"]
    for index in range(3):
        _close(agent.q[0], expected_q[index])
        previous, through = agent._belief, agent.frontier
        step = run_step(agent, world, ["look1", "look2", "wait"], u=.5, **kwargs)
        data = step.decided.body.content.as_json()
        _close(data["G"], expected_G[index])
        _close(data["q_pi"], expected_pi[index], atol=1e-9)
        _close(data["G"], np.array(data["risk"]) + data["ambiguity"] - data["novelty"])
        assert data["chosen"] == actions[index]
        _close(agent.q[0], expected_q[index + 1])
        _assert_step_links(step, previous, index, through, kwargs)
        _close(agent.counts("look1"), [[9, 5], expected_o1_counts[index], [0, 0]])
        for action in ("look2", "wait"):
            _close(agent.counts(action), 10 * _true_A()[action])
    assert world.calls == actions
    assert agent.revision == 3


def test_l3_sampled_world_runs_twenty_steps():
    agent, kwargs = _setup()
    world = SampledWorld(true_state=1, A=_true_A(), seed=7)
    draws = random.Random(11)
    for index in range(20):
        previous, through = agent._belief, agent.frontier
        step = run_step(agent, world, ["look1", "look2", "wait"], u=draws.random(), **kwargs)
        _assert_step_links(step, previous, index, through, kwargs)
    assert len(kwargs["ledger"].entries()) == 1 + 5 * 20
    assert len({record.id for record in kwargs["ledger"].entries()}) == 101
    assert agent.q[1] > .5
    assert agent.revision == 20


@pytest.mark.parametrize("u,action,outcome", [(0.0, "look1", "o0"), (.7, "look2", "o1"), (.99, "wait", "none")])
def test_l4_executor_receives_the_selected_job_action(u, action, outcome):
    agent, kwargs = _setup()
    world = ScriptedWorld({action: [outcome]})
    step = run_step(agent, world, ["wait", "look2", "look1"], u=u, **kwargs)
    assert world.calls == [step.job.body.content.as_json()["action"]] == [action]
    assert step.observed.body.content.as_json() == {"outcome": outcome}
    assert step.observed.body.contract == ContractRef("sui.s1.outcome", "2")
    assert step.attempt.body.contract == ContractRef("sui.s1.attempt", "1")
    assert isinstance(step, StepRecords)
    assert not hasattr(step, "__dict__")
    assert [field.name for field in fields(step)] == ["decided", "job", "attempt", "observed", "belief"]
    with pytest.raises(FrozenInstanceError):
        step.belief = None


class _FailingExecutor:
    def execute(self, action):
        raise RuntimeError("injected executor failure")


class _FailingIds:
    def __init__(self, delegate, fail_on):
        self._delegate = delegate
        self._remaining = fail_on

    def new(self, kind):
        self._remaining -= 1
        if self._remaining == 0:
            raise RuntimeError("injected ID failure")
        return self._delegate.new(kind)


@pytest.mark.parametrize("failure,retained", [("executor", 3), ("observation_id", 3), ("belief_id", 4)])
def test_l4_failed_step_keeps_accepted_facts(failure, retained):
    agent, kwargs = _setup(learnable=frozenset({"look1"}))
    world = ScriptedWorld({"look1": ["o1"]})
    original_ids = kwargs["ids"]
    before = (agent.frontier, agent.revision, agent._belief, agent.unread,
              agent.q.tolist(), {k: agent.counts(k).tolist() for k in ("look1", "look2", "wait")})
    if failure == "executor":
        world = _FailingExecutor()
    else:
        kwargs["ids"] = _FailingIds(original_ids, fail_on=4 if failure == "observation_id" else 5)
    with pytest.raises(RuntimeError):
        run_step(agent, world, ["look1", "look2", "wait"], u=.5, **kwargs)
    events = [e for e in kwargs["ledger"].entries() if e.is_event]
    assert [e.body_type for e in events] == [Decided, JobOpened, AttemptStarted, Observed][:retained]
    assert (agent.frontier, agent.revision, agent._belief, agent.unread,
            agent.q.tolist(), {k: agent.counts(k).tolist() for k in ("look1", "look2", "wait")}) == before
    if failure == "belief_id":
        record = agent.adopt(kwargs["ledger"], clock=kwargs["clock"], ids=original_ids)
        clean, clean_kwargs = _setup(learnable=frozenset({"look1"}))
        expected = run_step(clean, ScriptedWorld({"look1": ["o1"]}), ["look1", "look2", "wait"],
                            u=.5, **clean_kwargs)
        assert record.body.content == expected.belief.body.content


def test_l4_impossible_outcome_is_preserved_as_unread():
    agent, kwargs = _setup(learnable=frozenset({"look1"}))
    step = run_step(agent, ScriptedWorld({"look1": ["none"]}), ["look1"], u=.5, **kwargs)
    assert dict(agent.unread) == {step.observed.id: "impossible"}
    assert kwargs["ledger"].entries_of(step.observed.id)
    assert step.belief.body.content.as_json()["n"]["look1"] == [0, 0, 0]


def test_l5_learning_reduces_novelty_and_switches_executed_action():
    a = {action: 10 * A for action, A in _true_A().items()}
    a["look2"] = np.array([[1., 1.], [1., 1.], [0., 0.]])
    agent, kwargs = _setup(learnable=frozenset({"look2"}), a=a,
                           D=np.array([.5, .5]), gamma=64.0)
    world = ScriptedWorld({"look1": ["o1"] * 12, "look2": ["o1"] * 12})
    expected_novelty = [.193147180560, .136514168295, .104001811285,
                        .083735756872, .083735756872, .070005653311]
    expected_G = {
        0: [.996863063589, .905465108108, 1.098612288668],
        3: [.996863063589, 1.014876531797, 1.098612288668],
        4: [1.046183669570, 1.014876531797, 1.098612288668],
    }
    expected_pi = {
        0: [.002873137, .997122594, .000004268],
        2: [.463701266, .535609869, .000688865],
        3: [.759176100, .239696083, .001127816],
        4: [.118328908, .877542087, .004129005],
    }
    actions = ["look2"] * 3 + ["look1"] + ["look2"] * 2
    novelties = []
    for index in range(6):
        _close(agent.q, [.5, .5] if index < 4 else [1 / 6, 5 / 6])
        previous, through = agent._belief, agent.frontier
        step = run_step(agent, world, ["look1", "look2", "wait"], u=.5, **kwargs)
        data = step.decided.body.content.as_json()
        assert data["candidates"] == ["look1", "look2", "wait"]
        assert data["chosen"] == actions[index]
        assert data["novelty"][0] == data["novelty"][2] == 0.0
        novelties.append(data["novelty"][1])
        _close(novelties[-1], expected_novelty[index])
        _close(data["G"], np.array(data["risk"]) + data["ambiguity"] - data["novelty"])
        if index in expected_G:
            _close(data["G"], expected_G[index])
        if index in expected_pi:
            _close(data["q_pi"], expected_pi[index], atol=1e-9)
        k = actions[:index + 1].count("look2")
        _close(agent.counts("look2"), [[1, 1], [1 + k, 1 + k], [0, 0]])
        for action in ("look1", "wait"):
            np.testing.assert_array_equal(agent.counts(action), a[action])
        expected_q = [.5, .5] if index < 3 else [1 / 6, 5 / 6]
        _close(agent.q, expected_q)
        _close(step.belief.body.content.as_json()["q"], expected_q)
        _close(step.belief.body.content.as_json()["a"]["look2"], agent.counts("look2"))
        _assert_step_links(step, previous, index, through, kwargs)
    for action, before, after in zip(actions, novelties, novelties[1:]):
        if action == "look2":
            assert before > after
        else:
            _close(after, before, atol=1e-14)
    assert world.calls == actions
    assert agent.revision == 6
    assert len(kwargs["ledger"].entries()) == len({record.id for record in kwargs["ledger"].entries()}) == 31
