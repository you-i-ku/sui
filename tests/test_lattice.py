"""S4b-1aの格子。独立な道の総当たりと仕様書の固定値で識別する。"""

from dataclasses import FrozenInstanceError, replace
from fractions import Fraction as F
from itertools import product
import json
import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from sui import lattice
from sui.agent import Agent, ModelFalsified, RebuildMismatch, plan, plan_s4c, read, replay_decision
from sui.contracts import ContractRef
from sui.ids import Ref, RefKind as K, SequentialIds
from sui.ledger import Ledger, SequentialSalts
from sui.records import Payload
from sui.inference import (
    ModelViolation, _log_A, _s4d_filter_log, belief, expected_A, ledger, log_likelihood,
)
from sui.lattice import learn
from sui.model import model_from_json, model_json, model_ref
from worlds import HandHistory, _lattice_model


NS = 10**9


def _sequence(rows):
    return tuple((seconds * NS, 0, index, f"observation:{index}", action, outcome)
                 for index, (seconds, action, outcome) in enumerate(rows))


def _transition(size, dt):
    """Qの閉じた式。対角へ1、残りへ一様、減衰は2**(-dt)。"""
    decay = F(1, 2**dt)
    return tuple(tuple((1 - decay) / size + (decay if i == j else 0)
                       for j in range(size)) for i in range(size))


def _brute(model, rows, until):
    """道を全部列挙し、Dirichletのモーメントを積分。実装の格子は使わない。"""
    size, outcomes = len(model.states), len(model.outcomes)
    actions = sorted(model.learnable)
    times = [0] + [seconds for seconds, _, _ in rows]
    if until != times[-1]:
        times.append(until)
    result = {}
    for path in product(range(size), repeat=len(times)):
        weight = F(float(model.D[path[0]])).limit_denominator()
        for index in range(1, len(times)):
            weight *= _transition(size, times[index] - times[index - 1])[path[index]][path[index - 1]]
        counts = [0] * (len(actions) * outcomes * size)
        for (_, action, outcome), state in zip(rows, path[1:]):
            observed = model.outcomes.index(outcome)
            if action in actions:
                counts[(actions.index(action) * outcomes + observed) * size + state] += 1
            else:
                column = [F(float(value)).limit_denominator() for value in model.a[action][:, state]]
                weight *= column[observed] / sum(column)
        for action_index, action in enumerate(actions):
            for state in range(size):
                column = [F(float(value)).limit_denominator() for value in model.a[action][:, state]]
                used = [counts[(action_index * outcomes + outcome) * size + state]
                        for outcome in range(outcomes)]
                for prior, count in zip(column, used):
                    for increment in range(count):
                        weight *= prior + increment
                for increment in range(sum(used)):
                    weight /= sum(column) + increment
        if weight:
            key = path[-1], tuple(counts)
            result[key] = result.get(key, F(0)) + weight
    evidence = sum(result.values())
    return evidence, {key: value / evidence for key, value in result.items()}


def _prediction(model, posterior, action):
    """結合からの予測を照合する。説明用の無条件theta_meanは使わない。"""
    result = np.zeros(len(model.outcomes))
    for (state, counts), log_weight in posterior.log_w.items():
        column = model.a[action][:, state].copy()
        if action in model.learnable:
            offset = sorted(model.learnable).index(action)
            column += np.array(counts).reshape(
                len(model.learnable), len(model.outcomes), len(model.states))[offset, :, state]
        result += math.exp(log_weight) * (column / column.sum())
    return result


def _compare(model, rows, until):
    evidence, expected = _brute(model, rows, until)
    posterior = learn(model, _sequence(rows), until_ns=until * NS)
    assert set(posterior.log_w) == set(expected)
    assert list(posterior.log_w) == sorted(expected)
    for key, value in expected.items():
        assert math.exp(posterior.log_w[key]) == pytest.approx(float(value), abs=1e-12, rel=0)
    marginal = [sum(value for (state, _), value in expected.items() if state == target)
                for target in range(len(model.states))]
    np.testing.assert_allclose(np.exp(posterior.marginal_state()),
                               list(map(float, marginal)), atol=1e-12, rtol=0)
    for action in model.actions:
        predicted = [F(0)] * len(model.outcomes)
        for (state, counts), value in expected.items():
            column = [F(float(v)).limit_denominator() for v in model.a[action][:, state]]
            if action in model.learnable:
                offset = sorted(model.learnable).index(action)
                column = [prior + counts[(offset * len(column) + o) * len(model.states) + state]
                          for o, prior in enumerate(column)]
            predicted = [p + value * v / sum(column) for p, v in zip(predicted, column)]
        np.testing.assert_allclose(_prediction(model, posterior, action),
                                   list(map(float, predicted)), atol=1e-12, rtol=0)
    return evidence, posterior


def test_l1_64_paths_fixed_evidence_and_all_joint_weights():
    model = _lattice_model(learnable=frozenset({"a"}))
    model = replace(model, a={**model.a, "f": np.array([[1., .25], [0., .75]])})
    rows = ((1, "a", "x"), (1, "a", "y"), (2, "f", "y"),
            (4, "a", "x"), (4, "a", "y"))
    evidence, posterior = _compare(model, rows, 4)
    assert evidence == F(387, 35840)
    np.testing.assert_allclose(np.exp(posterior.marginal_state()),
                               [63 / 172, 109 / 172], atol=1e-12, rtol=0)


def test_l1_three_states_three_outcomes_two_independent_learning_actions():
    rate = math.log(2) / 3
    Q = np.full((3, 3), rate)
    np.fill_diagonal(Q, -2 * rate)
    model = _lattice_model(states=("s2", "s0", "s1"), outcomes=("z", "x", "y"),
        actions=("z", "f", "a"), learnable=frozenset({"z", "a"}),
        a={"z": np.array([[2., 1., 1.], [1., 0., 2.], [1., 3., 1.]]),
           "a": np.array([[1., 2., 0.], [2., 1., 1.], [1., 1., 3.]]),
           "f": np.array([[2., 0., 1.], [1., 1., 2.], [0., 2., 1.]])},
        D=np.array([.5, 1 / 3, 1 / 6]), log_C=np.full(3, -math.log(3)), Q=Q)
    _compare(model, ((1, "z", "x"), (1, "a", "y"), (2, "f", "z"),
                     (3, "z", "z"), (3, "a", "x")), 4)


def test_l2_identity_transition_matches_s1c_belief_conditional_ledgers_and_prediction():
    model = _lattice_model()
    rows = ((1, "a", "x"), (1, "b", "y"), (2, "f", "y"), (3, "a", "y"))
    identity = np.array([[0., -np.inf], [-np.inf, 0.]])
    seconds = []

    def transition(dt):
        seconds.append(dt)
        return identity

    posterior = learn(model, _sequence(rows), until_ns=4 * NS, _log_transition=transition)
    assert seconds == [1., 1., 1., 1.]
    n = {action: np.array([sum(a == action and o == outcome for _, a, o in rows)
                          for outcome in model.outcomes], dtype=int) for action in model.actions}
    q = belief(model.D, [log_likelihood(model.a[a], n[a], learnable=a in model.learnable)
                        for a in model.actions])
    np.testing.assert_allclose(np.exp(posterior.marginal_state()), q, atol=1e-12, rtol=0)
    assert posterior.components() == 2
    for (state, counts), _ in posterior.log_w.items():
        for index, action in enumerate(sorted(model.learnable)):
            allocated = np.array(counts).reshape(2, 2, 2)[index]
            conditional = model.a[action] + allocated
            np.testing.assert_array_equal(conditional[:, state], ledger(model.a[action], n[action])[:, state])
            np.testing.assert_array_equal(conditional[:, 1 - state], model.a[action][:, 1 - state])
    for action in model.actions:
        conditional = ledger(model.a[action], n[action]) if action in model.learnable else model.a[action]
        np.testing.assert_allclose(_prediction(model, posterior, action),
                                   expected_A(conditional) @ q, atol=1e-12, rtol=0)


def test_l3_no_learning_has_one_count_pattern_and_matches_log_filter():
    model = _lattice_model(learnable=frozenset())
    rows = ((1, "a", "x"), (1, "b", "y"), (3, "f", "y"))
    posterior = learn(model, _sequence(rows))
    logs = _s4d_filter_log(model.D, model.Q,
        [(t * NS, _log_A(model.a[a])[model.outcomes.index(o)]) for t, a, o in rows])
    assert {counts for _, counts in posterior.log_w} == {()}
    assert posterior.theta_mean() == {}
    np.testing.assert_allclose(posterior.marginal_state(), logs, atol=1e-12, rtol=0)
    for action in model.actions:
        np.testing.assert_allclose(_prediction(model, posterior, action),
                                   expected_A(model.a[action]) @ np.exp(logs), atol=1e-12, rtol=0)


def test_l4_concentration_preserves_support_and_converges_in_prediction():
    model = _lattice_model(learnable=frozenset({"a"}),
        a={"a": np.array([[1., .25], [0., .75]]),
           "b": np.array([[.25, .75], [.75, .25]]),
           "f": np.array([[.75, .25], [.25, .75]])})
    rows = ((1, "a", "x"), (2, "a", "y"), (3, "f", "y"))
    fixed = replace(model, learnable=frozenset())
    target = _prediction(fixed, learn(fixed, _sequence(rows), until_ns=4 * NS), "a")
    errors = []
    for concentration in (1e2, 1e4, 1e6):
        concentrated = replace(model, a={**model.a, "a": model.a["a"] * concentration})
        posterior = learn(concentrated, _sequence(rows), until_ns=4 * NS)
        assert posterior.theta_mean()["a"][1, 0] == 0
        errors.append(np.max(np.abs(_prediction(concentrated, posterior, "a") - target)))
    assert errors[0] > 1e-5
    assert errors[1] < errors[0] / 50
    assert errors[2] < errors[1] / 50


def test_l8_empty_support_raises_model_violation_without_substituting_prior():
    model = _lattice_model(a={a: np.array([[1., 2.], [0., 0.]]) for a in ("a", "b", "f")})
    with pytest.raises(ModelViolation):
        learn(model, _sequence(((1, "a", "y"),)))


def test_l9_structural_zero_never_receives_a_count_or_retains_a_branch():
    model = _lattice_model(learnable=frozenset({"a"}))
    model = replace(model, a={**model.a, "a": np.array([[2., 0.], [0., 3.]])})
    posterior = learn(model, _sequence(((1, "a", "x"), (2, "a", "y"))))
    assert dict(posterior.log_w) == {(1, (1, 0, 0, 1)): 0.}
    np.testing.assert_array_equal(posterior.theta_mean()["a"], np.eye(2))


def test_l10_keeps_both_integer_allocations_not_map_or_expected_counts():
    model = _lattice_model(learnable=frozenset({"a"}), D=np.array([.5, .5]))
    model = replace(model, a={**model.a, "a": np.ones((2, 2))})
    posterior = learn(model, _sequence(((0, "a", "x"),)))
    assert set(posterior.log_w) == {(0, (1, 0, 0, 0)), (1, (0, 1, 0, 0))}
    np.testing.assert_allclose(list(posterior.log_w.values()), [-math.log(2)] * 2, atol=1e-12, rtol=0)
    np.testing.assert_allclose(_prediction(model, posterior, "a"), [2 / 3, 1 / 3], atol=1e-12, rtol=0)
    np.testing.assert_allclose(posterior.theta_mean()["a"],
                               [[7 / 12, 7 / 12], [5 / 12, 5 / 12]], atol=1e-12, rtol=0)
    assert abs(float(posterior.theta_mean()["a"][0] @ np.array([.5, .5])) - 2 / 3) > .08


@pytest.mark.parametrize("shift", [-1e16, -1e300])
def test_l14_common_negative_offset_is_removed_before_normalization(monkeypatch, shift):
    model = _lattice_model(D=np.array([.5, .5]))
    model = replace(model, a={**model.a, "a": np.ones((2, 2))})
    observe = lattice._observe

    def shifted(*args):
        table = observe(*args)
        assert len(set(table.values())) == 1
        return {key: shift for key in table}

    monkeypatch.setattr(lattice, "_observe", shifted)
    posterior = learn(model, _sequence(((0, "a", "x"),)))
    np.testing.assert_allclose(list(posterior.log_w.values()), [-math.log(2)] * 2, atol=1e-12, rtol=0)
    assert sum(map(math.exp, posterior.log_w.values())) == pytest.approx(1., abs=1e-12, rel=0)


def test_l15_positive_underflow_is_not_a_structural_zero():
    model = _lattice_model(D=np.array([.5, .5]))
    model = replace(model, a={**model.a, "a": np.ones((2, 2)),
                              "f": np.array([[1., 1e-200], [0., 1.]])})
    rows = _sequence(((0, "a", "x"), (0, "f", "x"), (0, "f", "x")))
    positive = learn(model, rows)
    zero_model = replace(model, a={**model.a, "f": np.eye(2)})
    zero = learn(zero_model, rows)
    assert positive.components() == 2 and zero.components() == 1
    assert positive.marginal_state()[1] == pytest.approx(-400 * math.log(10), abs=1e-12, rel=0)
    assert zero.marginal_state()[1] == -math.inf
    assert math.exp(positive.marginal_state()[1]) == 0.


def test_l16_first_transition_is_from_origin_not_first_observation():
    model = _lattice_model(D=np.array([1., 0.]), learnable=frozenset({"a"}))
    posterior = learn(model, _sequence(((1, "a", "x"),)))
    np.testing.assert_allclose(np.exp(posterior.marginal_state()), [8 / 9, 1 / 9], atol=1e-12, rtol=0)
    np.testing.assert_allclose(_prediction(model, posterior, "a"), [32 / 45, 13 / 45], atol=1e-12, rtol=0)
    wrong = learn(model, _sequence(((0, "a", "x"),)))
    np.testing.assert_allclose(np.exp(wrong.marginal_state()), [1., 0.], atol=1e-12, rtol=0)
    assert _prediction(model, wrong, "a")[0] == pytest.approx(3 / 4)


@pytest.mark.parametrize("rows,until", [(((1, "a", "x"), (0, "b", "y")), None),
    (((-1, "a", "x"),), None), (((.5, "a", "x"),), None),
    ((), -1), ((), True), ((), .5), (((1, "a", "x"),), 0)])
def test_learn_rejects_invalid_time_and_backwards_until(rows, until):
    with pytest.raises(ValueError):
        learn(_lattice_model(), _sequence(rows), until_ns=until)


def test_empty_history_at_origin_and_future_and_frozen_result():
    model = _lattice_model(D=np.array([1., 0.]))
    origin = learn(model, ())
    future = learn(model, (), until_ns=NS)
    assert origin.components() == 1 and future.components() == 2
    np.testing.assert_allclose(np.exp(origin.marginal_state()), [1., 0.], atol=1e-12, rtol=0)
    np.testing.assert_allclose(np.exp(future.marginal_state()), [.75, .25], atol=1e-12, rtol=0)
    for action in model.learnable:
        np.testing.assert_allclose(future.theta_mean()[action], expected_A(model.a[action]), atol=1e-12, rtol=0)
    with pytest.raises(TypeError):
        origin.log_w[next(iter(origin.log_w))] = 1.
    with pytest.raises(FrozenInstanceError):
        origin.stats.final_keys = 42
    before = dict(origin.log_w)
    origin.theta_mean()["a"][:] = 0
    assert origin.log_w == before


@pytest.mark.parametrize("length,anchor_keys,future_keys,prediction", [
    (0, 2, 2, .5), (3, 6, 12, 299 / 570), (8, 40, 48, 50141 / 81286)])
def test_g6_lattice_counts_and_prediction_fixed_values(length, anchor_keys, future_keys, prediction):
    model = _lattice_model(actions=("look", "peek"), learnable=frozenset({"look"}),
        a={"look": np.ones((2, 2)), "peek": np.array([[.75, .25], [.25, .75]])}, D=np.array([.5, .5]))
    sequence = _sequence(tuple((t, "look", o) for t, o in enumerate("xxyxyyxx"[:length], start=1)))
    anchor = learn(model, sequence)
    posterior = learn(model, sequence, until_ns=(length + 1) * NS)
    assert anchor.components() == anchor_keys
    assert posterior.components() == future_keys
    assert _prediction(model, posterior, "look")[0] == pytest.approx(prediction, abs=1e-12, rel=0)


def test_e9_no_pruning_and_count_bound_uses_each_observation_total():
    model = _lattice_model(learnable=frozenset({"a"}))
    sequence = _sequence(tuple((i + 1, "a", "xy"[i % 2]) for i in range(80)))
    anchor = learn(model, sequence)
    predicted = learn(model, sequence, until_ns=81 * NS)
    bound = 2 * math.comb(40 + 1, 1)**2
    assert anchor.components() == 3280
    assert predicted.components() == bound == 3362
    for posterior in (anchor, predicted):
        assert posterior.stats.final_keys == posterior.components()
        assert posterior.stats.max_keys >= posterior.components()
        assert posterior.stats.evaluated_branches == 0


@pytest.mark.parametrize("points", [(), ((1., 1.),), ((1., .5), (None, .5))])
def test_e4_model5_roundtrip_independent_of_duration_and_none(points):
    durations = {a: points for a in ("a", "b", "f")} if points else {}
    model = _lattice_model(durations=durations, measures={a: "report" for a in durations})
    encoded = model_json(model)
    value = json.loads(encoded)
    assert value["scheme"] == "sui.model.5"
    assert set(value) == {"scheme", "states", "outcomes", "actions", "a", "learnable",
                          "D", "log_C", "gamma", "Q", "arrivals", "durations", "measures"}
    assert model_json(model_from_json(encoded)) == encoded
    assert model_ref(model_from_json(encoded)) == model_ref(model)
    for invalid in ({**value, "learnable": []}, {**value, "Q": None},
                    {**value, "scheme": "sui.model.4"}, {**value, "extra": 1},
                    {key: item for key, item in value.items() if key != "durations"}):
        data = json.dumps(invalid, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        with pytest.raises(ValueError):
            model_from_json(data)
    with pytest.raises(ValueError, match="canonical"):
        model_from_json(json.dumps(value).encode())


def test_e4_old_model_bytes_and_refs_match_saved_golden_without_regenerating():
    golden = json.loads((Path(__file__).with_name("golden_s4b1a.json")).read_bytes())
    assert len(golden) == 18
    schemes = set()
    for case in golden.values():
        encoded = case["model_json"]["body"].encode("utf-8")
        model = model_from_json(encoded)
        assert model_json(model) == encoded
        assert model_ref(model) == "sha256:" + case["model_json"]["sha256"]
        schemes.add(json.loads(encoded)["scheme"])
    assert schemes == {"sui.model.1", "sui.model.2", "sui.model.3", "sui.model.4"}


def _hand_history(rows):
    return tuple((seconds * NS, action, outcome) for seconds, action, outcome in rows)


def _brute_hand(model, rows, pending, capture):
    """全状態の道と仮の報告を列挙し、各列のモーメントを分数で積分する。"""
    states, outcomes = len(model.states), len(model.outcomes)
    learning = sorted(model.learnable)
    pending = sorted(pending, key=lambda item: str(item[0]))
    events = [(t, 0, i, a, model.outcomes.index(o)) for i, (t, a, o) in enumerate(rows)]
    events += [(t, 1, i, a, None) for i, (_, a, t) in enumerate(pending) if t is not None]
    events += [(capture, 2, 0, None, None)]
    events.sort()
    times = [0] + [t for t, *_ in events]
    result = {}
    possible_reports = [(None,) if t is None else range(outcomes) for _, _, t in pending]
    for path in product(range(states), repeat=len(times)):
        prior = F(float(model.D[path[0]])).limit_denominator()
        for i in range(1, len(times)):
            prior *= _transition(states, times[i] - times[i - 1])[path[i]][path[i - 1]]
        if not prior:
            continue
        for z in product(*possible_reports):
            weight = prior
            counts = [0] * (len(learning) * outcomes * states)
            for (_, kind, index, action, observed), state in zip(events, path[1:]):
                if kind == 2:
                    captured = state
                    continue
                observed = z[index] if kind == 1 else observed
                if action in learning:
                    counts[(learning.index(action) * outcomes + observed) * states + state] += 1
                else:
                    column = [F(float(v)).limit_denominator() for v in model.a[action][:, state]]
                    weight *= column[observed] / sum(column)
            for i, action in enumerate(learning):
                for state in range(states):
                    column = [F(float(v)).limit_denominator() for v in model.a[action][:, state]]
                    used = [counts[(i * outcomes + o) * states + state] for o in range(outcomes)]
                    for a, n in zip(column, used):
                        for offset in range(n):
                            weight *= a + offset
                    for offset in range(sum(used)):
                        weight /= sum(column) + offset
            if weight:
                key = z, captured, tuple(counts)
                result[key] = result.get(key, F(0)) + weight
    total = sum(result.values())
    return {key: value / total for key, value in result.items()}


def _compare_hand(model, rows, pending, candidate, capture):
    expected = _brute_hand(model, rows, pending, capture)
    table = lattice.hand_table(model, _hand_history(rows),
        tuple((job, action, None if t is None else t * NS) for job, action, t in pending),
        candidate, capture_ns=capture * NS)
    assert set(table.log_w) == set(expected)
    for key, value in expected.items():
        assert math.exp(table.log_w[key]) == pytest.approx(float(value), abs=1e-12, rel=0)
    assert table.stats.final_keys == len(expected)
    assert table.stats.evaluated_branches == len({z for z, _, _ in expected})
    assert table.stats.max_keys >= len(expected)
    return table


def _as_hand(posterior):
    return lattice.HandTable(log_w={((), state, counts): weight
        for (state, counts), weight in posterior.log_w.items()}, stats=posterior.stats)


def test_g1_fixed_fair_coin_has_no_parameter_information():
    model = _lattice_model()
    model = replace(model, a={**model.a, "f": np.ones((2, 2))})
    table = lattice.hand_table(model, (), (), "f", capture_ns=NS)
    cost, information = lattice.one_step_components(model, table, "f", [.4, 1.2])
    assert cost == pytest.approx(.8, abs=1e-12, rel=0)
    assert information == pytest.approx(0., abs=1e-12, rel=0)
    assert abs(information - .1931471805599453) > .19


@pytest.mark.parametrize("action,expected", [("a", .13651416829481278), ("b", .1931471805599453)])
def test_g2_same_action_and_identical_but_independent_action(action, expected):
    model = _lattice_model(D=np.array([1., 0.]))
    model = replace(model, a={**model.a, "a": np.ones((2, 2)), "b": np.ones((2, 2))})
    table = _compare_hand(model, (), (("job1", action, 0),), "a", 0)
    cost, information = lattice.one_step_components(model, table, "a", [1., 0.])
    assert cost == pytest.approx(.5, abs=1e-12, rel=0)
    assert information == pytest.approx(expected, abs=1e-12, rel=0)
    assert table.stats.evaluated_branches == 2


@pytest.mark.parametrize("action,expected", [("a", .1931471805599453), ("b", .13651416829481278)])
def test_g2_candidate_b_keeps_identical_action_columns_independent(action, expected):
    """G2の鏡像。読む列だけを最初の同値な行動aに寄せる誤りも落とす。"""
    model = _lattice_model(D=np.array([1., 0.]))
    model = replace(model, a={**model.a, "a": np.ones((2, 2)), "b": np.ones((2, 2))})
    table = _compare_hand(model, (), (("job1", action, 0),), "b", 0)
    cost, information = lattice.one_step_components(model, table, "b", [1., 0.])
    assert cost == pytest.approx(.5, abs=1e-12, rel=0)
    assert information == pytest.approx(expected, abs=1e-12, rel=0)
    assert table.stats.evaluated_branches == 2


def test_g3_past_report_does_not_measure_current_state():
    rate = math.log(5 / 3) / 2
    model = _lattice_model(D=np.array([.5, .5]), learnable=frozenset({"a"}),
        Q=np.array([[-rate, rate], [rate, -rate]]))
    model = replace(model, a={**model.a, "b": np.eye(2), "f": np.eye(2)})
    table = lattice.hand_table(model, (), (("past", "b", 0),), "f", capture_ns=NS)
    wrong = lattice.hand_table(model, (), (("past", "b", NS),), "f", capture_ns=NS)
    assert lattice.one_step_components(model, table, "f", [0., 0.])[1] == pytest.approx(
        .5004024235381879, abs=1e-12, rel=0)
    assert lattice.one_step_components(model, wrong, "f", [0., 0.])[1] == pytest.approx(0., abs=1e-12, rel=0)


def test_g4_later_report_keeps_captured_state_and_uses_all_evidence_counts():
    model = _lattice_model()
    rows = ((1, "a", "x"), (2, "f", "y"))
    components = []
    for capture, predicted, information in ((3, 312 / 635, .181087815627327),
                                           (7, 1303 / 2540, .186981328996852)):
        table = _compare_hand(model, rows, (("job1", "a", 5),), "a", capture)
        value = lattice.one_step_components(model, table, "a", [1., 0.])
        np.testing.assert_allclose(value, [predicted, information], atol=1e-12, rtol=0)
        components.append(value)
    np.testing.assert_allclose(np.mean(components, axis=0),
                               [2551 / 5080, .184034572312090], atol=1e-12, rtol=0)
    assert abs(components[0][0] - 323 / 635) > .01
    assert abs(components[0][1] - .138100404451086) > .04


@pytest.mark.parametrize("measure,capture,probability,information", [
    ("start", 1, F(3, 4), .5623351446188083),
    ("report", 3, F(9, 16), .6853142072764582)])
def test_g4_public_plan_distinguishes_candidate_start_from_report(measure, capture, probability, information):
    """同じ事実・now=1・所要2秒でも、候補の測る時刻は1秒と3秒で異なる。"""
    model = _lattice_model(D=np.array([1., 0.]), learnable=frozenset({"a"}),
        a={"a": np.ones((2, 2)), "b": np.ones((2, 2)), "f": np.eye(2)},
        durations={"a": ((0., 1.),), "b": ((2., 1.),), "f": ((2., 1.),)},
        measures={"a": "report", "b": "report", "f": measure})
    # Dは非定常。x@0は既知のs0でaを学ぶだけなので、P(s0,t)=(1+2**(-t))/2。
    # fは状態の完全観測で、I=H(S_capture)。分数の総当たりでも独立に照合する。
    oracle = _brute_hand(model, ((0, "a", "x"),), (), capture)
    marginal = tuple(sum(w for (_, s, _), w in oracle.items() if s == state) for state in (0, 1))
    assert marginal == (probability, 1 - probability)
    entropy = -sum(float(p) * math.log(float(p)) for p in marginal)
    assert entropy == pytest.approx(information, abs=1e-12, rel=0)
    h = HandHistory()
    h.boot()
    h.observe(h.start("a"), "x", 0)
    r = _agent_rig(model, h)
    data = plan(_view(r, 1), ("f",), u=.5).content.as_json()
    assert data["expected_cost"] == [0.]
    assert data["information"] == pytest.approx([information], abs=1e-12, rel=0)
    assert data["J"] == pytest.approx([-information], abs=1e-12, rel=0)


def test_g5_previous_run_and_never_arriving_branches_fixed_tables():
    # 未着の境界の選択自体はAgent側で試す。ここでは仕様の残った4枝を渡す。
    model = _lattice_model()
    rows = ((1, "a", "x"), (4, "f", "y"))
    components = []
    for pending, capture, information in ((3, 5, .199249550698705),
        (3, 9, .205918307589716), (None, 5, .199695120121166), (None, 9, .205918737884458)):
        table = _compare_hand(model, rows, (("job1", "b", pending),), "a", capture)
        value = lattice.one_step_components(model, table, "a", [1., 0.])
        assert value[1] == pytest.approx(information, abs=1e-12, rel=0)
        components.append(value)
    np.testing.assert_allclose(np.mean(components, axis=0),
                               [10651 / 21880, .202695429073511], atol=1e-12, rtol=0)


@pytest.mark.parametrize("length,information,probability,chosen", [
    (0, .193147180559945, .515578741993495, "look"),
    (3, .152466485561553, .505413400871267, "look"),
    (8, .120707491926042, .497473885489595, "peek")])
def test_g6_learned_information_changes_choice_in_changing_world(length, information, probability, chosen):
    from sui.inference import select
    from sui.lookahead import _policy
    model = _lattice_model(actions=("look", "peek"), learnable=frozenset({"look"}),
        a={"look": np.ones((2, 2)), "peek": np.array([[.75, .25], [.25, .75]])}, D=np.array([.5, .5]))
    rows = tuple((t, "look", o) for t, o in enumerate("xxyxyyxx"[:length], start=1))
    table = lattice.hand_table(model, _hand_history(rows), (), "look", capture_ns=(length + 1) * NS)
    values = [lattice.one_step_components(model, table, action, [0., 0.])[1] for action in model.actions]
    np.testing.assert_allclose(values, [information, .130812035941137], atol=1e-12, rtol=0)
    policy = _policy(-np.array(values), 1.)
    np.testing.assert_allclose(policy, [probability, 1 - probability], atol=1e-12, rtol=0)
    assert model.actions[select(policy, .5)] == chosen
    fixed = replace(model, learnable=frozenset())
    table = lattice.hand_table(fixed, _hand_history(rows), (), "look", capture_ns=(length + 1) * NS)
    values = [lattice.one_step_components(fixed, table, action, [0., 0.])[1] for action in fixed.actions]
    assert values[0] == pytest.approx(0., abs=1e-12, rel=0)
    np.testing.assert_allclose(_policy(-np.array(values), 1.),
                               [.467343545268778, .532656454731222], atol=1e-12, rtol=0)


@pytest.mark.parametrize("pending,z", [((), ()), ((("job1", "a", None),), (None,))])
def test_g7a_g7b_candidate_and_bottom_do_not_increment_counts(pending, z):
    model = _lattice_model(D=np.array([1., 0.]), learnable=frozenset({"a"}))
    model = replace(model, a={**model.a, "a": np.ones((2, 2))})
    table = lattice.hand_table(model, (), pending, "a", capture_ns=0)
    assert dict(table.log_w) == {(z, 0, (0, 0, 0, 0)): 0.}
    np.testing.assert_allclose(lattice.one_step_components(model, table, "a", [1., 0.]),
                               [.5, .1931471805599453], atol=1e-12, rtol=0)
    assert table.stats.evaluated_branches == 1


def test_g7c_nonuniform_reports_keep_their_probability_mass():
    model = _lattice_model(D=np.array([1., 0.]), learnable=frozenset({"a"}))
    model = replace(model, a={**model.a, "a": np.array([[2., 2.], [1., 1.]])})
    table = _compare_hand(model, (), (("job1", "a", 0),), "a", 0)
    masses = [sum(math.exp(w) for (z, _, _), w in table.log_w.items() if z == (o,)) for o in range(2)]
    np.testing.assert_allclose(masses, [2 / 3, 1 / 3], atol=1e-12, rtol=0)
    cost, info = lattice.one_step_components(model, table, "a", [1., 0.])
    assert cost == pytest.approx(2 / 3, abs=1e-12, rel=0)
    assert info == pytest.approx(.10593915659918729, abs=1e-12, rel=0)
    assert abs(info - .10690782925604345) > .0009


def test_g7d_each_duration_branch_is_evaluated_before_averaging_information():
    model = _lattice_model(D=np.array([1., 0.]), learnable=frozenset({"a"}))
    model = replace(model, a={**model.a, "a": np.ones((2, 2)), "f": np.eye(2)})
    branches, mixed = [], {}
    for capture, predicted in ((1, 3 / 4), (3, 9 / 16)):
        table = _compare_hand(model, ((0, "a", "x"),), (), "f", capture)
        components = lattice.one_step_components(model, table, "f", [1., 0.])
        assert components[0] == pytest.approx(predicted, abs=1e-12, rel=0)
        branches.append(components)
        for key, weight in table.log_w.items():
            mixed[key] = np.logaddexp(mixed.get(key, -math.inf), weight - math.log(2))
    wrong = lattice.one_step_components(model, lattice.HandTable(log_w=mixed, stats=table.stats), "f", [1., 0.])
    assert np.mean(branches, axis=0)[1] == pytest.approx(.6238246759476332, abs=1e-12, rel=0)
    assert wrong[1] == pytest.approx(.6434915530192904, abs=1e-12, rel=0)
    assert wrong[1] - np.mean(branches, axis=0)[1] > .019


def test_hand_joint_all_weights_with_later_history_and_reordered_job_labels():
    model = _lattice_model()
    rows = ((1, "a", "x"), (3, "f", "y"), (3, "b", "x"))
    pending = (("job_z", "b", 1), ("job_a", "a", 2), ("job_none", "a", None))
    table = _compare_hand(model, rows, pending, "b", 2)
    reordered = lattice.hand_table(model, _hand_history(rows),
        tuple((job, action, None if t is None else t * NS) for job, action, t in reversed(pending)),
        "b", capture_ns=2 * NS)
    assert table.log_w == reordered.log_w
    assert table.stats == reordered.stats
    assert {z for z, _, _ in table.log_w} == {(a, None, b) for a in (0, 1) for b in (0, 1)}
    assert list(table.log_w) == sorted(table.log_w, key=lattice._hand_key)
    with pytest.raises(TypeError):
        table.log_w[next(iter(table.log_w))] = 0.
    with pytest.raises(FrozenInstanceError):
        table.stats.final_keys = 0


def test_hand_three_states_three_outcomes_structural_zeros_and_coincident_events():
    rate = math.log(2) / 3
    Q = np.full((3, 3), rate)
    np.fill_diagonal(Q, -2 * rate)
    model = _lattice_model(states=("s2", "s0", "s1"), outcomes=("z", "x", "y"),
        a={"a": np.array([[1., 2., 0.], [2., 1., 1.], [1., 1., 3.]]),
           "b": np.array([[2., 1., 1.], [1., 0., 2.], [1., 3., 1.]]),
           "f": np.array([[2., 0., 1.], [1., 1., 2.], [0., 2., 1.]])},
        D=np.array([.5, 1 / 3, 1 / 6]), log_C=np.full(3, -math.log(3)), Q=Q)
    table = _compare_hand(model, ((1, "a", "x"), (2, "f", "y")),
                          (("job_z", "a", 3), ("job_a", "b", 1)), "a", 1)
    assert table.stats.evaluated_branches == 9
    for action in model.actions:
        cost, information = lattice.one_step_components(model, table, action, [0., 0., 0.])
        assert cost == 0
        assert -1e-12 <= information <= math.log(3) + 1e-12


def test_l2_identity_reduction_information_g_and_policy_match_s1c():
    from sui.inference import efe, novelty, policy_posterior
    from sui.lookahead import _policy
    model = _lattice_model(log_C=np.log(np.array([.8, .2])), gamma=3.)
    rows = ((1, "a", "x"), (1, "b", "y"), (2, "f", "y"), (3, "a", "y"))
    posterior = learn(model, _sequence(rows), until_ns=4 * NS,
                      _log_transition=lambda dt: np.array([[0., -np.inf], [-np.inf, 0.]]))
    table = _as_hand(posterior)
    n = {a: np.array([sum(action == a and o == outcome for _, action, o in rows)
                      for outcome in model.outcomes], dtype=int) for a in model.actions}
    q = belief(model.D, [log_likelihood(model.a[a], n[a], learnable=a in model.learnable)
                        for a in model.actions])
    expected_g, actual_g = [], []
    for action in model.actions:
        a = ledger(model.a[action], n[action]) if action in model.learnable else model.a[action]
        risk, ambiguity, _ = efe(q, expected_A(a), model.log_C)
        g = risk + ambiguity - (novelty(q, a) if action in model.learnable else 0.)
        cost, info = lattice.one_step_components(model, table, action, -model.log_C)
        expected_cost = float(-(expected_A(a) @ q) @ model.log_C)
        np.testing.assert_allclose([cost, info, cost - info], [expected_cost, expected_cost - g, g], atol=1e-12, rtol=0)
        expected_g.append(g)
        actual_g.append(cost - info)
    np.testing.assert_allclose(_policy(actual_g, model.gamma),
        policy_posterior(np.array(expected_g), model.gamma), atol=1e-12, rtol=0)


def test_l3_fixed_hand_matches_s4d_joint_components_g_and_policy():
    from sui.agent import _one_step_components
    from sui.inference import _s4d_hand_joint_log, _s4d_normalize
    from sui.lookahead import _policy
    model = _lattice_model(learnable=frozenset())
    rows = ((1, "a", "x"), (4, "f", "y"))
    pending = (("job1", "a", 2), ("job2", "b", 5))
    costs = np.array([.2, 1.3])
    actual, expected = [], []
    table = _compare_hand(model, rows, pending, "a", 3)
    legacy = _s4d_hand_joint_log(model.D, model.Q,
        tuple((t * NS, _log_A(model.a[a])[model.outcomes.index(o)]) for t, a, o in rows),
        tuple((t * NS, model.a[a]) for _, a, t in pending), 3 * NS)
    for row, z in zip(legacy, product(range(2), repeat=2)):
        for state, weight in enumerate(row):
            assert table.log_w[z, state, ()] == pytest.approx(float(weight), abs=1e-12, rel=0)
    for action in model.actions:
        parts = lattice.one_step_components(model, table, action, costs)
        target = np.zeros(2)
        for row in legacy:
            conditional, mass = _s4d_normalize(row)
            target += math.exp(mass) * np.array(_one_step_components(conditional, model.a[action], False, costs))
        np.testing.assert_allclose(parts, target, atol=1e-12, rtol=0)
        actual.append(parts[0] - parts[1])
        expected.append(target[0] - target[1])
    np.testing.assert_allclose(actual, expected, atol=1e-12, rtol=0)
    np.testing.assert_allclose(_policy(actual, 2.), _policy(expected, 2.), atol=1e-12, rtol=0)


def test_l4_concentration_converges_in_information_g_and_policy():
    from sui.lookahead import _policy
    model = _lattice_model(learnable=frozenset({"a"}))
    model = replace(model, a={**model.a, "a": np.array([[1., .25], [0., .75]])})
    history = _hand_history(((1, "a", "x"), (2, "a", "y"), (3, "f", "y")))
    def quantities(current):
        table = lattice.hand_table(current, history, (("job1", "f", 5 * NS),), "a", capture_ns=4 * NS)
        components = np.array([lattice.one_step_components(current, table, action, [.2, 1.4])
                               for action in ("a", "f")])
        g = components[:, 0] - components[:, 1]
        return np.r_[components.flatten(), g, _policy(g, 2.)]
    target = quantities(replace(model, learnable=frozenset()))
    errors = [np.max(np.abs(quantities(replace(model, a={**model.a, "a": model.a["a"] * k})) - target))
              for k in (1e2, 1e4, 1e6)]
    assert errors[0] > 1e-5
    assert errors[1] < errors[0] / 50
    assert errors[2] < errors[1] / 50


@pytest.mark.parametrize("learning", [False, True])
def test_l11_hand_candidate_positive_underflow_retains_prohibition(learning):
    model = _lattice_model(learnable=frozenset({"a", "b"} if learning else {"a"}))
    model = replace(model, a={**model.a, "a": np.ones((2, 2)),
        "b": np.array([[1e200, 1e200], [1e-200, 1e-200]]), "f": np.eye(2)})
    table = lattice.hand_table(model, ((0, "a", "x"),), (), "b", capture_ns=NS)
    assert lattice.one_step_components(model, table, "b", [0., math.inf])[0] == math.inf
    zero = replace(model, a={**model.a, "b": np.array([[1., 1.], [0., 0.]])})
    assert lattice.one_step_components(zero, table, "b", [0., math.inf])[0] == 0.


def test_l11_hand_pending_positive_underflow_branch_retains_prohibition():
    model = _lattice_model(learnable=frozenset({"a"}), D=np.array([.5, .5]))
    model = replace(model, a={"a": np.ones((2, 2)),
        "b": np.array([[1., 1e-200], [0., 1.]]), "f": np.eye(2)})
    table = lattice.hand_table(model, ((0, "a", "x"), (0, "b", "x"), (0, "b", "x")),
                               (("job1", "f", 0),), "f", capture_ns=0)
    rare = [weight for (z, _, _), weight in table.log_w.items() if z == (1,)]
    assert len(rare) == 1
    assert rare[0] == pytest.approx(-400 * math.log(10), abs=1e-12, rel=0)
    assert math.exp(rare[0]) == 0.
    assert table.stats.evaluated_branches == 2
    assert lattice.one_step_components(model, table, "f", [0., math.inf])[0] == math.inf


@pytest.mark.parametrize("shift", [-1e16, -1e300])
def test_l14_hand_update_and_components_remove_common_negative_offset(monkeypatch, shift):
    model = _lattice_model(D=np.array([.5, .5]))
    model = replace(model, a={**model.a, "a": np.ones((2, 2)), "f": np.eye(2)})
    emission = lattice._emission
    def shifted(*args):
        _, counts = emission(*args)
        return shift, counts
    monkeypatch.setattr(lattice, "_emission", shifted)
    table = lattice.hand_table(model, ((0, "a", "x"),), (), "f", capture_ns=0)
    np.testing.assert_allclose(list(table.log_w.values()), [-math.log(2)] * 2, atol=1e-12, rtol=0)
    assert lattice.one_step_components(model, table, "f", [math.log(2)] * 2)[1] == pytest.approx(
        math.log(2), abs=1e-12, rel=0)


@pytest.mark.parametrize("where,ns", [("history", -1), ("pending", .5), ("capture", True)])
def test_hand_rejects_invalid_measurement_time(where, ns):
    with pytest.raises(ValueError, match="measurement times"):
        lattice.hand_table(_lattice_model(), ((ns, "a", "x"),) if where == "history" else (),
            (("job", "a", ns),) if where == "pending" else (), "a", capture_ns=ns if where == "capture" else 0)


def test_hand_empty_support_and_unreachable_reports():
    model = _lattice_model(learnable=frozenset({"a"}),
        a={a: np.array([[1., 2.], [0., 0.]]) for a in ("a", "b", "f")})
    with pytest.raises(ModelViolation):
        lattice.hand_table(model, ((NS, "a", "y"),), (), "a", capture_ns=NS)
    table = lattice.hand_table(model, (), (("job", "a", NS),), "a", capture_ns=0)
    assert {z for z, _, _ in table.log_w} == {(0,)}
    assert table.stats.evaluated_branches == 1
    np.testing.assert_allclose(lattice.one_step_components(model, table, "a", [2., math.inf]),
                               [2., 0.], atol=1e-12, rtol=0)


def _agent_rig(model=None, history=None):
    """紙も付箋も足さない。事実は同じ台帳に順に受け入れる。"""
    model = _lattice_model() if model is None else model
    h = HandHistory() if history is None else history
    if history is None:
        h.boot()
    book, ids = Ledger(salts=SequentialSalts()), SequentialIds(prefix="lattice")
    for record in h.records:
        book.append(record, book.heads())
    subject = Agent(model=model, lineage="lattice")
    if h.records:
        subject.adopt(book, clock=h.clock, ids=ids)
    else:
        subject.belief_record(clock=h.clock, ids=ids, ledger=book)
    return SimpleNamespace(agent=subject, model=model, h=h, ledger=book, clock=h.clock, ids=ids)


def _adopt_new(r, records):
    for record in records:
        r.ledger.append(record, r.ledger.heads())
    return r.agent.adopt(r.ledger, clock=r.clock, ids=r.ids)


def _view(r, now=0, observed=None):
    return r.agent.view(now_ns=now * NS, observed_ns=(now if observed is None else observed) * NS)


def _belief_copy(r, *, content=None, contract=None):
    original = r.agent._belief
    body = replace(original.body, content=original.body.content if content is None else Payload.json(content),
                   contract=original.body.contract if contract is None else contract)
    record = replace(original, id=r.ids.new(K.PREDICTION), body=body)
    return r.ledger.append(record, r.agent.frontier).cid


@pytest.mark.parametrize("points", [(), ((1., 1.),), ((1., .5), (None, .5))])
def test_e1_e5_e8_new_contract_precedes_none_and_old_entries_refuse(points):
    durations = {a: points for a in ("a", "b", "f")} if points else {}
    model = _lattice_model(durations=durations, measures={a: "report" for a in durations})
    r = _agent_rig(model)
    before = tuple(r.ledger.entries()), r.agent._belief, r.agent.frontier
    assert r.agent._belief.body.contract == ContractRef("sui.s4b.belief", "1")
    with pytest.raises(ValueError, match="^plan_s4c: learning under a changing state is not supported$"):
        plan_s4c(_view(r), ("a",), u=.5)
    with pytest.raises(ValueError, match="^plan_s4c: learning under a changing state is not supported$"):
        r.agent.decide_s4c(("a",), u=.5, clock=r.clock, ids=r.ids, ledger=r.ledger, now_mono_ns=0)
    with pytest.raises(ValueError, match="^counts: no single ledger under a changing state$"):
        r.agent.counts("a")
    assert (tuple(r.ledger.entries()), r.agent._belief, r.agent.frontier) == before
    old = _agent_rig(replace(model, Q=None))
    np.testing.assert_array_equal(old.agent.counts("a"), model.a["a"])
    assert old.agent._belief.body.contract != ContractRef("sui.s4b.belief", "1")


@pytest.mark.parametrize("H", [0, NS])
@pytest.mark.parametrize("with_item", [False, True])
def test_e2_e11_learning_changing_refuses_lookahead_including_zero_horizon(H, with_item):
    from test_lookahead import _rig, _table
    from sui.lookahead import OutsideEvaluationType, evaluate
    from sui.preference import current, resolve
    r = _rig(model=_lattice_model(), H=H,
             items=(_table("candidate_outcome", [["x", .5], ["y", .5]]),) if with_item else ())
    before = tuple(r.ledger.entries()), r.agent._belief
    message = "^lookahead with learning under a changing state is 1d$"
    with pytest.raises(OutsideEvaluationType, match=message):
        r.agent.decide(("a",), u=.5, clock=r.clock, ids=r.ids, ledger=r.ledger, now_mono_ns=0)
    view = _view(r)
    with pytest.raises(OutsideEvaluationType, match=message):
        evaluate(view, ("a",), resolve(current(view.preferences), view), u=.5)
    assert (tuple(r.ledger.entries()), r.agent._belief) == before


def test_e3_pending_none_is_allowed_but_candidate_none_refuses_whole_decision():
    from sui.lookahead import OutsideEvaluationType
    model = _lattice_model(D=np.array([1., 0.]),
        a={"a": np.ones((2, 2)), "b": np.ones((2, 2)), "f": np.eye(2)},
        durations={"a": ((0., 1.),), "b": ((None, 1.),), "f": ((0., 1.),)},
        measures={a: "report" for a in ("a", "b", "f")})
    h = HandHistory()
    h.boot()
    h.start("b")
    r = _agent_rig(model, h)
    before = tuple(r.ledger.entries()), r.agent._belief
    data = plan(_view(r), ("a",), u=.5).content.as_json()
    assert data["information"] == pytest.approx([.1931471805599453], abs=1e-12, rel=0)
    assert data["J"] == pytest.approx([-.1931471805599453], abs=1e-12, rel=0)
    with pytest.raises(OutsideEvaluationType, match="one_step requires every candidate"):
        r.agent.decide(("a", "b"), u=.5, clock=r.clock, ids=r.ids, ledger=r.ledger, now_mono_ns=0)
    assert (tuple(r.ledger.entries()), r.agent._belief) == before


@pytest.mark.parametrize("length,components,information,probability,chosen", [
    (0, 2, .193147180559945, .515578741993495, "look"),
    (3, 6, .152466485561553, .505413400871267, "look"),
    (8, 40, .120707491926042, .497473885489595, "peek")])
def test_g6_e6_e9_agent_saves_anchor_summary_and_replays_choice(length, components, information, probability, chosen):
    model = _lattice_model(actions=("look", "peek"), learnable=frozenset({"look"}),
        a={"look": np.ones((2, 2)), "peek": np.array([[.75, .25], [.25, .75]])}, D=np.array([.5, .5]))
    h = HandHistory()
    h.boot()
    for t, outcome in enumerate("xxyxyyxx"[:length], 1):
        h.observe(h.start("look", t), outcome, t)
    r = _agent_rig(model, h)
    saved = r.agent._belief.body.content.as_json()
    assert set(saved) == {"model", "states", "outcomes", "q", "theta_mean", "fixed", "n",
                          "lattice", "unread", "time", "arrivals"}
    assert saved["lattice"] == {"components": components}
    assert saved["time"]["anchor_ns"] == length * NS
    assert set(saved["theta_mean"]) == {"look"} and saved["fixed"] == {"peek": model.a["peek"].tolist()}
    draft = plan(_view(r, length + 1), ("look", "peek"), u=.5)
    data = draft.content.as_json()
    assert data["style"] is None and data["items"] == [] and data["evaluation"] == "one_step"
    np.testing.assert_allclose(data["information"], [information, .130812035941137], atol=1e-12, rtol=0)
    np.testing.assert_allclose(data["q_pi"], [probability, 1 - probability], atol=1e-12, rtol=0)
    np.testing.assert_allclose(data["J"], -np.array(data["information"]), atol=1e-12, rtol=0)
    assert data["chosen"] == chosen and data["expected_cost"] == [0., 0.]
    belief_entry, = r.ledger.entries_of(r.agent._belief.id)
    restored = Agent.restore(model=model, lineage="restore", ledger=r.ledger, belief=belief_entry.cid)
    assert restored.belief_record(clock=r.clock, ids=r.ids, ledger=r.ledger).body.content.as_json() == saved
    assert plan(restored.view(now_ns=(length + 1) * NS), model.actions, u=.5).content == draft.content
    prepared = r.agent.prepare(draft, clock=r.clock, ids=r.ids)
    r.agent.commit(prepared, ledger=r.ledger)
    entry, = r.ledger.entries_of(prepared.decided.id)
    assert replay_decision(model=model, ledger=r.ledger, decision=entry.cid) == draft
    assert r.agent._belief.body.content.as_json() == saved


def test_e5_before_boot_and_after_boot_keep_prior_and_explicit_null_anchor():
    model = _lattice_model(D=np.array([1., 0.]))
    h = HandHistory()
    r = _agent_rig(model, h)
    before = r.agent._belief.body.content.as_json()
    assert before["q"] == [1., 0.] and before["lattice"] == {"components": 1}
    assert before["time"] == {"anchor": None, "anchor_ns": None, "clock_issues": []}
    for action in model.learnable:
        np.testing.assert_allclose(before["theta_mean"][action], expected_A(model.a[action]), atol=1e-12, rtol=0)
    boot = h.boot(7)
    _adopt_new(r, (boot,))
    after = r.agent._belief.body.content.as_json()
    assert after["q"] == before["q"] and after["theta_mean"] == before["theta_mean"]
    assert after["time"]["anchor"] == str(boot.id) and after["time"]["anchor_ns"] == 0


def test_e6_all_summary_fields_are_rebuilt_and_schema_rejects_wrong_action_sets():
    h = HandHistory()
    h.boot()
    h.observe(h.start("a", 1), "x", 1)
    r = _agent_rig(history=h)
    original = r.agent._belief.body.content.as_json()
    for field, value in {"q": [.5, .5], "theta_mean": {a: [[.5, .5], [.5, .5]] for a in ("a", "b")},
                         "fixed": {"f": [[1., 0.], [0., 1.]]}, "n": {a: [0, 0] for a in ("a", "b", "f")},
                         "lattice": {"components": 99}, "unread": [{"id": "observation:extra", "reason": "content"}],
                         "time": {**original["time"], "anchor_ns": 0}, "arrivals": {"extra":
                             {"N": 0, "T_ns": 0, "alpha": 1., "beta_s": 1., "outside": []}}}.items():
        cid = _belief_copy(r, content={**original, field: value})
        with pytest.raises(RebuildMismatch) as error:
            Agent.restore(model=r.model, lineage="tampered", ledger=r.ledger, belief=cid)
        assert field in error.value.fields
    for change in ({"theta_mean": {"f": original["fixed"]["f"]}}, {"fixed": original["theta_mean"]},
                   {"theta_mean": None}, {"lattice": {"components": True}}, {"extra": 0}):
        cid = _belief_copy(r, content={**original, **change})
        with pytest.raises(ValueError, match="belief content"):
            Agent.restore(model=r.model, lineage="schema", ledger=r.ledger, belief=cid)
    # Pythonでは0 == 0.0でも、新しい要約は全欄を完全照合する。
    prior = _agent_rig(_lattice_model(D=np.array([1., 0.])))
    value = prior.agent._belief.body.content.as_json()
    assert value["q"] == [1., 0.]
    cid = _belief_copy(prior, content={**value, "q": [1, 0]})
    with pytest.raises(RebuildMismatch) as error:
        Agent.restore(model=prior.model, lineage="types", ledger=prior.ledger, belief=cid)
    assert error.value.fields == ("q",)


@pytest.mark.parametrize("old", [ContractRef("sui.s1.belief", "3"), ContractRef("sui.s4.belief", "1"),
    ContractRef("sui.s4.belief", "2"), ContractRef("sui.s4d.belief", "1")])
def test_e6_restore_rejects_new_model_with_each_old_belief_contract(old):
    r = _agent_rig()
    with pytest.raises(ValueError, match="belief: incompatible contract"):
        Agent.restore(model=r.model, lineage="swap", ledger=r.ledger, belief=_belief_copy(r, contract=old))
    entry, = r.ledger.entries_of(r.agent._belief.id)
    with pytest.raises(ValueError, match="belief: incompatible contract"):
        Agent.restore(model=replace(r.model, learnable=frozenset()), lineage="old", ledger=r.ledger, belief=entry.cid)


@pytest.mark.parametrize("swap", ["legacy_decision", "old_belief", "evaluation", "H_ns", "information"])
def test_e6_replay_rejects_swapped_method_contract_and_content(swap):
    from sui.s4_contracts import DECISION as OLD_DECISION, BELIEF as OLD_BELIEF
    r = _agent_rig()
    draft = plan(_view(r), ("a",), u=.5)
    prepared = r.agent.prepare(draft, clock=r.clock, ids=r.ids)
    body = prepared.decided.body
    if swap == "legacy_decision":
        body = replace(body, contract=OLD_DECISION)
    elif swap == "old_belief":
        cid = _belief_copy(r, contract=OLD_BELIEF)
        body = replace(body, inputs=(r.ledger.record(cid).id,))
    else:
        value = {"evaluation": "lookahead", "H_ns": 0, "information": [42.]}[swap]
        body = replace(body, content=Payload.json({**body.content.as_json(), swap: value}))
    entry = r.ledger.append(replace(prepared.decided, body=body), prepared.parents)
    with pytest.raises(ValueError):
        replay_decision(model=r.model, ledger=r.ledger, decision=entry.cid)


def test_e6_failed_adopt_does_not_replace_current_summary_and_retry_uses_new_one(monkeypatch):
    r = _agent_rig()
    saved = (r.agent.frontier, r.agent._reading, r.agent._q, r.agent._a,
             r.agent._lattice, r.agent.revision, r.agent._belief)
    r.h.observe(r.h.start("a", 1), "x", 1)
    for record in r.h.records[1:]:
        r.ledger.append(record, r.ledger.heads())
    append = r.ledger.append
    with monkeypatch.context() as patch:
        def fail(*args, **kwargs):
            raise OSError("storage unavailable")
        patch.setattr(r.ledger, "append", fail)
        with pytest.raises(OSError, match="storage unavailable"):
            r.agent.adopt(r.ledger, clock=r.clock, ids=r.ids)
    current = (r.agent.frontier, r.agent._reading, r.agent._q, r.agent._a,
               r.agent._lattice, r.agent.revision, r.agent._belief)
    assert all(x is y for x, y in zip(saved, current))
    assert r.ledger.append == append
    result = r.agent.adopt(r.ledger, clock=r.clock, ids=r.ids)
    assert result.body.content.as_json()["theta_mean"] != saved[-1].body.content.as_json()["theta_mean"]
    entry, = r.ledger.entries_of(result.id)
    restored = Agent.restore(model=r.model, lineage="retry", ledger=r.ledger, belief=entry.cid)
    assert restored._belief.body.content == result.body.content


def _marker(h, seconds):
    from sui.records import Observed
    return h.add(Observed(route="membrane", contract=ContractRef("test.marker", "1"),
        content=Payload.json({}), received_ns=seconds * NS), seconds)


def test_g4_agent_uses_observed_boundary_and_averages_duration_branches(monkeypatch):
    from sui import agent as module
    model = _lattice_model(durations={"a": ((1., .5), (5., .5)), "b": ((0., 1.),), "f": ((0., 1.),)},
                           measures={a: "report" for a in ("a", "b", "f")})
    h = HandHistory()
    h.boot()
    pending = h.start("a")
    h.observe(h.start("a", 1), "x", 1)
    h.observe(h.start("f", 2), "y", 2)
    r = _agent_rig(model, h)
    seen = []
    original = module._lattice_hand_table
    def inspect(model, history, pending, action, *, capture_ns):
        seen.append((pending, capture_ns))
        return original(model, history, pending, action, capture_ns=capture_ns)
    monkeypatch.setattr(module, "_lattice_hand_table", inspect)
    data = plan(_view(r, 2), ("a",), u=.5).content.as_json()
    assert data["information"] == pytest.approx([.184034572312090], abs=1e-12, rel=0)
    assert seen == [(((pending.body.job, "a", 5 * NS),), capture * NS) for capture in (3, 7)]
    assert data["time"]["earlier_run_pending"] == []
    # observed=1の等号で短い点を残す。now=2を未到着の境界にしてはならない。
    seen.clear()
    plan(_view(r, 2, observed=1), ("a",), u=.5)
    assert seen == [(((pending.body.job, "a", arrival * NS),), capture * NS)
                    for arrival in (1, 5) for capture in (3, 7)]


@pytest.mark.parametrize("previous_end", [2, 3])
def test_g5_agent_previous_run_boundary_and_equality_keep_report_and_none(previous_end, monkeypatch):
    from sui import agent as module
    model = _lattice_model(durations={"a": ((1., .5), (5., .5)),
        "b": ((1., 1 / 3), (3., 1 / 3), (None, 1 / 3)), "f": ((0., 1.),)},
        measures={a: "report" for a in ("a", "b", "f")})
    first = HandHistory()
    first.boot()
    pending = first.start("b")
    first.observe(first.start("a", 1), "x", 1)
    _marker(first, previous_end)
    second = HandHistory("r2", 1, wall=103)
    second.boot()
    second.observe(second.start("f", 1), "y", 1)
    second.records[:0] = first.records
    r = _agent_rig(model, second)
    seen = []
    original = module._lattice_hand_table
    def inspect(model, history, pending, action, *, capture_ns):
        seen.append((pending, capture_ns))
        return original(model, history, pending, action, capture_ns=capture_ns)
    monkeypatch.setattr(module, "_lattice_hand_table", inspect)
    data = plan(_view(r, 4), ("a",), u=.5).content.as_json()
    assert data["information"] == pytest.approx([.202695429073511], abs=1e-12, rel=0)
    assert data["time"]["earlier_run_pending"] == [str(pending.body.job)]
    assert seen == [(((pending.body.job, "b", arrival),), capture * NS)
                    for arrival in (3 * NS, None) for capture in (5, 9)]


def test_g7d_agent_averages_information_after_evaluating_each_duration():
    model = _lattice_model(D=np.array([1., 0.]), learnable=frozenset({"a"}),
        a={"a": np.ones((2, 2)), "b": np.ones((2, 2)), "f": np.eye(2)},
        durations={"a": ((0., 1.),), "b": ((0., 1.),), "f": ((1., .5), (3., .5))},
        measures={a: "report" for a in ("a", "b", "f")})
    h = HandHistory()
    h.boot()
    h.observe(h.start("a"), "x", 0)
    r = _agent_rig(model, h)
    data = plan(_view(r), ("f",), u=.5).content.as_json()
    assert data["information"] == pytest.approx([.6238246759476332], abs=1e-12, rel=0)
    assert abs(data["information"][0] - .6434915530192904) > .019


def _assert_agent_brute(r, rows, until):
    """読みの時刻も検査し、全キーと要約を独立な分数の総当たりへ照合する。"""
    sequence = r.agent._reading.sequence
    assert tuple((t // NS, a, o) for t, _, _, _, a, o in sequence) == rows
    _, expected = _brute(r.model, rows, until)
    actual = learn(r.model, sequence)
    assert set(actual.log_w) == set(expected)
    for key, value in expected.items():
        assert math.exp(actual.log_w[key]) == pytest.approx(float(value), abs=1e-12, rel=0)
    q = [float(sum(w for (s, _), w in expected.items() if s == i)) for i in range(len(r.model.states))]
    np.testing.assert_allclose(r.agent.q, q, atol=1e-12, rtol=0)
    saved = r.agent._belief.body.content.as_json()
    assert saved["lattice"]["components"] == len(expected)
    for action_index, action in enumerate(sorted(r.model.learnable)):
        mean = np.zeros_like(r.model.a[action])
        for (_, counts), weight in expected.items():
            for state in range(len(r.model.states)):
                column = [F(float(v)).limit_denominator() +
                    counts[(action_index * len(r.model.outcomes) + o) * len(r.model.states) + state]
                    for o, v in enumerate(r.model.a[action][:, state])]
                mean[:, state] += [float(weight * v / sum(column)) for v in column]
        np.testing.assert_allclose(saved["theta_mean"][action], mean, atol=1e-12, rtol=0)


def test_l5_adoption_order_redelivery_and_merge_rebuild_identical_lattice_content():
    h = HandHistory()
    h.boot()
    for t, action, outcome in ((1, "a", "x"), (1, "b", "y"), (2, "f", "y"), (3, "a", "y")):
        h.observe(h.start(action, t), outcome, t)
    target = _agent_rig(history=h)
    expected = target.agent._belief.body.content
    for order in (h.records[1:], list(reversed(h.records[1:]))):
        initial = HandHistory()
        initial.records = h.records[:1]
        initial.clock = h.clock
        r = _agent_rig(history=initial)
        boot_entry, = r.ledger.entries_of(h.records[0].id)
        for record in order:
            r.ledger.append(record, {boot_entry.cid})
            r.agent.adopt(r.ledger, clock=r.clock, ids=r.ids)
        assert r.agent._belief.body.content == expected
        _adopt_new(r, h.records)
        assert r.agent._belief.body.content == expected
    left, right = Ledger(salts=SequentialSalts()), Ledger(salts=SequentialSalts())
    for book, records in ((left, h.records[:7]), (right, [h.records[0], *h.records[7:]])):
        for record in records:
            book.append(record, book.heads())
    r.ledger = left
    r.agent = Agent(model=r.model, lineage="merge")
    r.agent.adopt(left, clock=r.clock, ids=r.ids)
    left.merge(right)
    r.agent.adopt(left, clock=r.clock, ids=r.ids)
    assert r.agent._belief.body.content == expected
    _assert_agent_brute(r, ((1, "a", "x"), (1, "b", "y"), (2, "f", "y"), (3, "a", "y")), 3)


def test_l7_late_start_measurement_is_reinserted_before_newer_history():
    model = _lattice_model(durations={a: ((10., 1.),) for a in ("a", "b", "f")},
        measures={"a": "start", "b": "report", "f": "report"})
    h = HandHistory()
    h.boot()
    late = h.start("a", 1)
    h.observe(h.start("f", 3), "y", 3)
    r = _agent_rig(model, h)
    saved = r.agent._belief.body.content
    report = h.observe(late, "x", 4)
    _adopt_new(r, (report,))
    _assert_agent_brute(r, ((1, "a", "x"), (3, "f", "y")), 3)
    assert r.agent._belief.body.content != saved
    _, wrong = _brute(model, ((3, "f", "y"), (4, "a", "x")), 4)
    assert abs(r.agent.q[0] - float(sum(w for (s, _), w in wrong.items() if s == 0))) > .01


def test_l8_empty_lattice_is_saved_and_replayed_as_null_not_prior():
    model = _lattice_model(learnable=frozenset({"a"}), a={a: np.eye(2) for a in ("a", "b", "f")})
    h = HandHistory()
    h.boot()
    h.observe(h.start("a"), "x", 0)
    h.observe(h.start("a"), "y", 0)
    r = _agent_rig(model, h)
    data = r.agent._belief.body.content.as_json()
    assert data["q"] is None and data["theta_mean"] is None and data["lattice"] == {"components": 0}
    assert data["n"]["a"] == [1, 1] and data["unread"] == []
    entry, = r.ledger.entries_of(r.agent._belief.id)
    restored = Agent.restore(model=model, lineage="empty", ledger=r.ledger, belief=entry.cid)
    assert restored._belief.body.content == r.agent._belief.body.content
    before = tuple(r.ledger.entries())
    with pytest.raises(ModelFalsified):
        r.agent.decide(("a",), u=.5, clock=r.clock, ids=r.ids, ledger=r.ledger, now_mono_ns=NS)
    with pytest.raises(ModelFalsified):
        _ = restored.q
    assert tuple(r.ledger.entries()) == before


def test_l8_missing_timeline_has_null_component_count_distinct_from_empty_lattice():
    first, second = HandHistory(), HandHistory("other", 0)
    first.boot()
    second.boot()
    first.records.extend(second.records)
    r = _agent_rig(history=first)
    data = r.agent._belief.body.content.as_json()
    assert data["q"] is None and data["theta_mean"] is None and data["lattice"] == {"components": None}
    assert data["time"]["clock_issues"][0]["kind"] == "concurrent_runs"
    entry, = r.ledger.entries_of(r.agent._belief.id)
    assert Agent.restore(model=r.model, lineage="clock", ledger=r.ledger, belief=entry.cid)._belief.body.content == r.agent._belief.body.content


def test_l16_initial_prediction_cross_run_history_and_ambiguous_attempt_rebuild():
    model = _lattice_model(D=np.array([1., 0.]), learnable=frozenset({"a"}))
    first = HandHistory()
    first.boot()
    first.observe(first.start("a", 1), "x", 1)
    r = _agent_rig(model, first)
    np.testing.assert_allclose(r.agent.q, [8 / 9, 1 / 9], atol=1e-12, rtol=0)
    # 別の非定常の事前でも、run2の起動で状態と帳面を戻さない。
    model = replace(model, D=np.array([.4, .6]))
    _marker(first, 2)
    second = HandHistory("r2", 1, wall=103)
    second.boot()
    second.observe(second.start("f", 1), "y", 1)
    r = _agent_rig(model, first)
    r.clock = second.clock
    _adopt_new(r, second.records)
    _assert_agent_brute(r, ((1, "a", "x"), (4, "f", "y")), 4)
    h = HandHistory()
    h.boot()
    attempt = h.start("a", 1)
    first_report = h.observe(attempt, "x", 1)
    h.observe(h.start("f", 2), "y", 2)
    r = _agent_rig(model, h)
    before = r.agent._belief.body.content
    second_report = h.observe(attempt, "x", 3)
    _adopt_new(r, (second_report,))
    assert dict(r.agent.unread) == {first_report.id: "ambiguous_attempt", second_report.id: "ambiguous_attempt"}
    assert r.agent._reading.n["a"].tolist() == [0, 0]
    _assert_agent_brute(r, ((2, "f", "y"),), 2)
    assert r.agent._belief.body.content != before


def test_e7_runtime_think_keeps_fixed_view_while_new_learning_is_adopted():
    from sui.runtime import Window, Tick, Reconsider, Think, Thought
    from sui.records import Producer, Decided
    from worlds import ManualHost, ScriptDrive, GatedHand
    r = _agent_rig()
    drive = ScriptDrive(lambda status, event: [Reconsider(candidates=("a",), u=.5)]
                        if isinstance(event, Tick) else [])
    host = ManualHost(lambda pledges: Window(agent=r.agent, ledger=r.ledger, clock=r.clock, ids=r.ids,
        hand=GatedHand({a: set() for a in r.model.actions}, {}), route="test", drive=drive,
        membrane=Producer(component="test.hand", code_version="1"), capacity={"think": 1}, pledges=pledges),
        clock=r.clock)
    host.advance(0)
    host.step()
    work = next(work for work, _ in host.work if isinstance(work, Think))
    old = plan(work.view, work.candidates, u=work.u)
    r.h.observe(r.h.start("a"), "x", 0)
    _adopt_new(r, r.h.records[1:])
    assert plan(_view(r), ("a",), u=.5).content != old.content
    result = host.finish(work)
    assert isinstance(result, Thought) and result.draft == old
    host.step()
    entry, = [e for e in r.ledger.entries() if e.body_type is Decided]
    assert entry.parents == work.view.frontier
    assert replay_decision(model=r.model, ledger=r.ledger, decision=entry.cid) == old


def test_l6_ticks_and_reconsiderations_do_not_accumulate_hypothetical_learning():
    from sui.runtime import Think, Tick, Envelope, Window, Pledges, _perform
    from sui.records import Producer
    from worlds import GatedHand, ScriptDrive
    h = HandHistory()
    h.boot()
    h.observe(h.start("a", 1), "x", 1)
    r = _agent_rig(history=h)
    saved = r.agent._belief.body.content
    expected = plan(_view(r, 5), ("a", "b"), u=.5).content
    window = Window(agent=r.agent, ledger=r.ledger, clock=r.clock, ids=r.ids,
        hand=GatedHand({a: set() for a in r.model.actions}, {}), route="test",
        drive=ScriptDrive(lambda status, event: []),
        membrane=Producer(component="test.ticks", code_version="1"),
        capacity={"think": 1}, pledges=Pledges())
    for number, now in enumerate((1, 2, 3, 5, 5), 1):
        r.clock.advance(now * NS - r.clock.mono_ns())
        window.accept(Envelope(number=number, event=Tick(mono_ns=now * NS), received_ns=now * NS))
        window.settle()
        work = Think(work=f"think:{now}", view=_view(r, now), candidates=("a", "b"), u=.5)
        result = _perform(work, None)
        assert result.error is None and result.draft is not None
        if now == 5:
            assert result.draft.content == expected
        assert r.agent.adopt(r.ledger, clock=r.clock, ids=r.ids) is None
        assert r.agent.belief_record(clock=r.clock, ids=r.ids, ledger=r.ledger).body.content == saved
    _assert_agent_brute(r, ((1, "a", "x"),), 1)


@pytest.mark.parametrize("gamma", [0., 1.])
@pytest.mark.parametrize("learning_probe", [False, True])
def test_l11_l12_agent_keeps_tiny_candidate_prohibition_at_zero_gamma(gamma, learning_probe):
    from test_lookahead import _rig, _table
    from sui.lookahead import NoAdmissibleCandidate
    model = _lattice_model(D=np.array([.5, .5]), learnable=frozenset({"a", "b"} if learning_probe else {"a"}),
        a={"a": np.ones((2, 2)), "b": np.array([[1e200, 1e200], [1e-200, 1e-200]]),
           "f": np.array([[1., 1.], [0., 0.]])})
    h = HandHistory()
    h.boot()
    h.observe(h.start("a"), "x", 0)
    r = _rig(model=model, history=h, H=None, gamma=gamma, items=(_table("candidate_outcome", [["x", 1.]]),))
    data = plan(_view(r, 1), ("b", "f"), u=.5).content.as_json()
    assert data["expected_cost"] == ["+inf", 0.] and data["q_pi"] == [0., 1.]
    assert data["chosen"] == "f"
    before = tuple(r.ledger.entries()), r.agent._belief
    with pytest.raises(NoAdmissibleCandidate):
        r.agent.decide(("b",), u=.5, clock=r.clock, ids=r.ids, ledger=r.ledger, now_mono_ns=NS)
    assert (tuple(r.ledger.entries()), r.agent._belief) == before
    zero = replace(model, a={**model.a, "b": model.a["f"]})
    control = _rig(model=zero, history=h, H=None, gamma=gamma, items=(_table("candidate_outcome", [["x", 1.]]),))
    assert plan(_view(control, 1), ("b",), u=.5).content.as_json()["J"] == pytest.approx([0.], abs=1e-12, rel=0)


def test_l11_agent_tiny_pending_report_still_forbids_candidate():
    from test_lookahead import _rig, _table
    from sui.lookahead import NoAdmissibleCandidate
    model = _lattice_model(D=np.array([.5, .5]), learnable=frozenset({"a"}),
        a={"a": np.ones((2, 2)), "b": np.array([[1., 1e-200], [0., 1.]]), "f": np.eye(2)})
    h = HandHistory()
    h.boot()
    for action in ("a", "b", "b"):
        h.observe(h.start(action), "x", 0)
    h.start("f")
    r = _rig(model=model, history=h, H=None, items=(_table("candidate_outcome", [["x", 1.]]),))
    assert r.agent.q[1] == 0. and r.agent._belief.body.content.as_json()["lattice"]["components"] == 2
    with pytest.raises(NoAdmissibleCandidate):
        plan(_view(r), ("f",), u=.5)


def test_l11_agent_inspects_tiny_duration_branch_log_weight_before_averaging(monkeypatch):
    from sui import agent as module
    from test_lookahead import _rig, _table
    from sui.lookahead import NoAdmissibleCandidate
    model = _lattice_model(D=np.array([.5, .5]), learnable=frozenset({"a"}),
        a={"a": np.ones((2, 2)), "b": np.ones((2, 2)), "f": np.eye(2)},
        durations={a: ((0., 1.), (1., 1e-200)) for a in ("a", "b", "f")},
        measures={a: "report" for a in ("a", "b", "f")})
    h = HandHistory()
    h.boot()
    pending = h.start("a")
    r = _rig(model=model, history=h, H=None, items=(_table("candidate_outcome", [["x", 1.]]),))
    tables, weights = [], []
    original_table, original_average = module._lattice_hand_table, module._average_components
    def inspect_table(model, history, measured, candidate, *, capture_ns):
        tables.append((measured, capture_ns))
        return original_table(model, history, measured, candidate, capture_ns=capture_ns)
    def inspect_average(branches):
        values = list(branches)
        weights.extend(values)
        return original_average(values)
    monkeypatch.setattr(module, "_lattice_hand_table", inspect_table)
    monkeypatch.setattr(module, "_average_components", inspect_average)
    with pytest.raises(NoAdmissibleCandidate):
        plan(_view(r), ("f",), u=.5)
    assert tables == [(((pending.body.job, "a", arrival * NS),), capture * NS)
                      for arrival in (0, 1) for capture in (0, 1)]
    assert len(weights) == 4
    np.testing.assert_allclose([w for w, _ in weights],
        [0., -200 * math.log(10), -200 * math.log(10), -400 * math.log(10)], atol=1e-12, rtol=0)
    assert math.exp(weights[-1][0]) == 0. and weights[-1][1][0] == math.inf


@pytest.mark.parametrize("mode", ["one_step", "hand"])
@pytest.mark.parametrize("pending", [False, True])
@pytest.mark.parametrize("control", ["positive", "disconnected", "zero_time"])
def test_l11_agent_rare_transition_is_positive_but_disconnected_and_zero_time_are_not(mode, pending, control):
    from test_lookahead import _rig, _table, _n6_model
    elapsed = 0. if control == "zero_time" else 1.
    model = replace(_n6_model(mode, elapsed=elapsed, second=0. if control == "disconnected" else 1e-200),
                    learnable=frozenset({"safe"}))
    h = HandHistory()
    h.boot()
    if pending:
        h.start("sense")
    r = _rig(model=model, history=h, H=None, items=(_table("candidate_outcome", [["o0", 1.]]),))
    view = r.agent.view(now_ns=round(elapsed * NS) if mode == "one_step" else 0, observed_ns=0)
    data = plan(view, ("probe", "safe"), u=.5).content.as_json()
    if control == "positive":
        assert data["expected_cost"] == ["+inf", 0.] and data["q_pi"] == [0., 1.]
    else:
        assert all(math.isfinite(v) for v in data["J"])
        assert plan(view, ("probe",), u=.5).content.as_json()["q_pi"] == [1.]


@pytest.mark.parametrize("magnitude", [1e308, 1e307])
def test_l13_agent_cost_sum_overflow_has_no_records_but_large_finite_cost_is_allowed(magnitude):
    from sui.inference import NumericalRange
    from test_lookahead import _rig
    model = _lattice_model(learnable=frozenset({"a"}),
        a={"a": np.ones((2, 2)), "b": np.array([[.9, .9], [.1, .1]]), "f": np.array([[1., 1.], [0., 0.]])})
    h = HandHistory()
    h.boot()
    h.observe(h.start("a"), "x", 0)
    item = {"kind": "item", "rule": {"name": "table", "version": "1"},
        "args": {"feature": {"name": "candidate_outcome", "version": "1"},
                 "log_probs": [["x", 0.], ["y", -magnitude]]}}
    r = _rig(model=model, history=h, H=None, gamma=0., items=(item, item))
    before = tuple(r.ledger.entries()), r.agent._belief, r.agent.frontier
    if magnitude == 1e308:
        with pytest.raises(NumericalRange):
            r.agent.decide(("b", "f"), u=.5, clock=r.clock, ids=r.ids, ledger=r.ledger, now_mono_ns=NS)
        assert (tuple(r.ledger.entries()), r.agent._belief, r.agent.frontier) == before
    else:
        decision, _ = r.agent.decide(("b", "f"), u=.5, clock=r.clock, ids=r.ids, ledger=r.ledger, now_mono_ns=NS)
        data = decision.body.content.as_json()
        assert data["expected_cost"] == pytest.approx([2e306, 0.], rel=1e-12)
        assert data["q_pi"] == [.5, .5]


def test_e9_agent_record_counts_anchor_components_for_eighty_reports():
    h = HandHistory()
    h.boot()
    for t in range(1, 81):
        h.observe(h.start("a", t), "xy"[(t - 1) % 2], t)
    r = _agent_rig(_lattice_model(learnable=frozenset({"a"})), h)
    data = r.agent._belief.body.content.as_json()
    assert data["lattice"] == {"components": 3280}
    assert data["lattice"]["components"] < 2 * math.comb(41, 1)**2 == 3362
    assert data["time"]["anchor_ns"] == 80 * NS and data["n"]["a"] == [40, 40]
