from dataclasses import FrozenInstanceError, fields
import random

import numpy as np
import pytest

from sui.agent import ACTION, BELIEF, DECISION, Agent
from sui.clock import FakeClock
from sui.contracts import ContractRef
from sui.ids import Ref, RefKind as K, SequentialIds
from sui.inference import ModelViolation
from sui.loop import ATTEMPT, OUTCOME, StepRecords, run_step
from sui.records import (
    BODY_KIND, AttemptStarted, Decided, JobOpened, Observed, Prediction, Producer, Role,
)
from worlds import SampledWorld, ScriptedWorld, _close, _model, _true_A


def _setup(*, learnable=frozenset()):
    agent = Agent(model=_model(learnable=learnable), lineage="line1")
    clock = FakeClock(run=Ref(K.RUN, "r1"))
    ids = SequentialIds()
    ledger = [agent.belief_record(clock=clock, ids=ids)]
    kwargs = dict(clock=clock, ids=ids, ledger=ledger, ledger_name="memory.r1",
                  membrane=Producer(component="test.executor", code_version="1"))
    return agent, kwargs


def _assert_step_links(step, previous_belief, revision, through, kwargs):
    assert step.decided.body.inputs == (previous_belief.id,)
    assert step.belief.body.basis == (step.observed.id,)
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
    basis = step.decided.body.basis
    assert basis.through == through
    assert basis.ledger == kwargs["ledger_name"]
    assert basis.complete == frozenset(BODY_KIND)
    assert previous_belief.at.order_key() < basis.as_of.order_key() < step.decided.at.order_key()
    records = [step.decided, step.job, step.attempt, step.observed, step.belief]
    assert [type(record.body) for record in records] == [Decided, JobOpened, AttemptStarted, Observed, Prediction]
    assert [record.body.contract for record in records] == [DECISION, ACTION, ATTEMPT, OUTCOME, BELIEF]
    assert [record.id.kind for record in records] == [K.DECISION, K.JOB, K.ATTEMPT, K.OBSERVATION, K.PREDICTION]
    assert [record.writer for record in records] == [Role.MODEL, Role.MODEL, Role.MEMBRANE, Role.MEMBRANE, Role.MODEL]
    assert step.attempt.producer == step.observed.producer == kwargs["membrane"]
    assert kwargs["ledger"][through:] == records
    assert all(a.at.order_key() < b.at.order_key() for a, b in zip(records, records[1:]))
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
        through = len(kwargs["ledger"])
        previous = kwargs["ledger"][-1]
        step = run_step(agent, world, ["look1", "look2", "wait"], u=.5, **kwargs)
        data = step.decided.body.content.as_json()
        _close(data["G"], expected_G[index])
        _close(data["q_pi"], expected_pi[index], atol=1e-9)
        assert data["chosen"] == actions[index]
        _close(agent.q[0], expected_q[index + 1])
        _close(step.belief.body.content.as_json()["q"], agent.q)
        _assert_step_links(step, previous, index, through, kwargs)
    assert world.calls == actions
    assert len(kwargs["ledger"]) == 16
    assert len({record.id for record in kwargs["ledger"]}) == 16
    assert agent.revision == 3
    for action, A in _true_A().items():
        _close(agent.counts(action), 10 * A)


def test_l2_learning_changes_the_second_action_with_the_same_belief():
    agent, kwargs = _setup(learnable=frozenset({"look1"}))
    world = ScriptedWorld({"look1": ["o1", "o1"], "look2": ["o1", "o1"]})
    expected_G = [
        [1.055538197712, 1.065009290053, 1.098612288668],
        [1.025854473448, 1.008551405495, 1.098612288668],
        [1.021778050493, .996863063589, 1.098612288668],
    ]
    expected_pi = [
        [.621525219, .339008974, .039465808],
        [.247772039, .749874213, .002353748],
        [.168535297, .830231328, .001233375],
    ]
    expected_q = [.9, .642857142857, .5, .357142857143]
    for index in range(3):
        _close(agent.q[0], expected_q[index])
        previous, through = kwargs["ledger"][-1], len(kwargs["ledger"])
        step = run_step(agent, world, ["look1", "look2", "wait"], u=.5, **kwargs)
        data = step.decided.body.content.as_json()
        _close(data["G"], expected_G[index])
        _close(data["q_pi"], expected_pi[index], atol=1e-9)
        _close(agent.q[0], expected_q[index + 1])
        _assert_step_links(step, previous, index, through, kwargs)
        _close(agent.counts("look1"), [[9, 5], [1.642857142857, 5.357142857143], [0, 0]])
    assert world.calls == ["look1", "look2", "look2"]
    assert agent.revision == 3


def test_l3_sampled_world_runs_twenty_steps():
    agent, kwargs = _setup()
    world = SampledWorld(true_state=1, A=_true_A(), seed=7)
    draws = random.Random(11)
    for index in range(20):
        previous, through = kwargs["ledger"][-1], len(kwargs["ledger"])
        step = run_step(agent, world, ["look1", "look2", "wait"], u=draws.random(), **kwargs)
        _assert_step_links(step, previous, index, through, kwargs)
    assert len(kwargs["ledger"]) == 1 + 5 * 20
    assert len({record.id for record in kwargs["ledger"]}) == 101
    assert agent.q[1] > .5
    assert agent.revision == 20


@pytest.mark.parametrize("u,action,outcome", [(0.0, "look1", "o0"), (.7, "look2", "o1"), (.99, "wait", "none")])
def test_l4_executor_receives_the_selected_job_action(u, action, outcome):
    agent, kwargs = _setup()
    world = ScriptedWorld({action: [outcome]})
    step = run_step(agent, world, ["wait", "look2", "look1"], u=u, **kwargs)
    assert world.calls == [step.job.body.content.as_json()["action"]] == [action]
    assert step.observed.body.content.as_json() == {"outcome": outcome}
    assert step.observed.body.contract == ContractRef("sui.s1.outcome", "1")
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


@pytest.mark.parametrize("failure", ["executor", "outcome", "observation_id", "belief_id"])
def test_l4_failed_step_leaves_ledger_untouched(failure):
    agent, kwargs = _setup(learnable=frozenset({"look1"}))
    world = ScriptedWorld({"look1": ["o1"]})
    before = list(kwargs["ledger"])
    error = RuntimeError
    if failure == "executor":
        world = _FailingExecutor()
    elif failure == "outcome":
        world = ScriptedWorld({"look1": ["none"]})
        error = ModelViolation
    else:
        kwargs["ids"] = _FailingIds(kwargs["ids"], fail_on=4 if failure == "observation_id" else 5)
    with pytest.raises(error):
        run_step(agent, world, ["look1", "look2", "wait"], u=.5, **kwargs)
    assert kwargs["ledger"] == before
    # 失敗した Agent と ledger はここで破棄し、続行しない。
