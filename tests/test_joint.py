"""S4b-1c (i)-1。期待値は総当たり・Fraction・解析式・固定値の台本から。

各試験の docstring は落とす誤実装。実行は Claude 側へ引き渡す。
"""

from collections import defaultdict
from dataclasses import replace
from fractions import Fraction as F
from itertools import product
import math

import numpy as np
import pytest

from sui.inference import ModelViolation, NumericalRange
from sui.joint import (Attempt, Completed, JointBelief, JointModel, NameSpec,
                       NotArrived, WorkPrior, condition, root_potential,
                       target_marginal, transition_bounds)
from sui.lookahead import OutsideEvaluationType
from sui.progress import (CompletionSpec, DensityPiece, INFINITE_WORK,
                          ProgressSegment, completion, completion_kernel)
from sui.quantity import IntegrationIncomplete
from sui.values import MeasureSpec


S = 1_000_000_000
# 包むのは計算の尾。解析値とのこの余裕は別の浮動小数点の丸め。
ROUND = 2e-14


def spec(*, actions=("a",), states=("0", "1"), rates=None, weights=(F(1),), bound=F(1),
         work_unit="ns", time_unit="ns"):
    if rates is None:
        rates = (tuple(tuple(F(1) for _ in states) for _ in actions),)
    return CompletionSpec(name="progress", version="1", actions=actions, states=states,
                          work_unit=work_unit, time_unit=time_unit, speed_unit=f"{work_unit}/{time_unit}",
                          candidates=rates, weights=weights, share="all_actions", max_speed=bound)


def bridge_model(*, static=False, measures="report"):
    q = 0. if static else math.log(2)
    return JointModel(completion=spec(actions=("a", "b")),
                      work={"a": WorkPrior(F(2), ((S, F(1, 2)), (2 * S, F(1, 2)))),
                            "b": WorkPrior(F(3), ((S, F(1)),))},
                      names={"a": NameSpec(((F(1), F(1)), (F(1), F(1))), True, measures),
                             "b": NameSpec(((F(1), F(0)), (F(0), F(1))), False, measures)},
                      outcomes=("0", "1"), initial=(F(1), F(0)),
                      Q=np.array([[-q, 0.], [q, 0.]]), measure=MeasureSpec("exact", "1", {}),
                      w_star_ns=S)


def belief(model, attempts=(), facts=(), observed_ns=0, transition_tolerance=1e-16):
    return JointBelief(model=model, attempts=tuple(attempts), facts=tuple(facts), origin_ns=0,
                       observed_ns=observed_ns, transition_tolerance=transition_tolerance)


def scalar_model(points=((1, F(1)),), *, alpha=F(1)):
    return JointModel(completion=spec(states=("s",)), work={"a": WorkPrior(alpha, points)},
                      names={"a": NameSpec(((F(1), F(1)),), True, "report")}, outcomes=("0", "1"),
                      initial=(F(1),), Q=np.zeros((1, 1)), measure=MeasureSpec("exact", "1", {}),
                      w_star_ns=1)


def enclosed(bounds, expected, *, rounding=ROUND):
    assert float(bounds.lower) - rounding <= float(expected) <= float(bounds.upper) + rounding


def brute_bridge(attempts, facts, times, *, static=False, measures="report"):
    """独立な総当たり。整数秒で P00=2^-Δ、P10=1-P00 を直接使う。

    状態の列×各試みの仕事量の列×観測済みの名前。Dirichlet は
    逐次の Polya の比で積分する。実装の混合やモーメントは呼ばない。
    """
    table = defaultdict(F)
    for path in product((0, 1), repeat=len(times)):
        probability = F(1) if path[0] == 0 else F(0)
        for before, after, s, t in zip(times, times[1:], path, path[1:]):
            delta = (after - before) // S
            assert (after - before) % S == 0
            if static:
                probability *= int(s == t)
            elif s == 1:
                probability *= int(t == 1)
            else:
                p00 = F(1, 2 ** delta)
                probability *= p00 if t == 0 else 1 - p00
        if not probability:
            continue
        for allocation in product(*((S, 2 * S) if a.action == "a" else (S,) for a in attempts)):
            p = probability
            work = [0, 0]
            bcount = 0
            names = [[0, 0], [0, 0]]
            seen = set()
            valid = True
            for a, w in zip(attempts, allocation):
                r = a.start_ns + w
                if a.action == "a":
                    j = int(w == 2 * S)
                    p *= F(1 + work[j], 2 + sum(work))
                    work[j] += 1
                else:
                    bcount += 1
                for f in facts:
                    if f.label != a.label:
                        continue
                    if isinstance(f, NotArrived):
                        valid &= r > f.until_ns
                    else:
                        valid &= r == f.report_ns
                        if f.outcome is not None and a.label not in seen:
                            seen.add(a.label)
                            t = a.start_ns if measures == "start" else r
                            state = path[times.index(t)]
                            y = int(f.outcome)
                            if a.action == "a":
                                p *= F(1 + names[state][y], 2 + sum(names[state]))
                                names[state][y] += 1
                            else:
                                p *= int(y == state)
            if valid and p:
                parameters = ((F(1 + work[0]), F(1 + work[1])), (F(3 + bcount),),
                              tuple(F(1 + n) for n in names[0]), tuple(F(1 + n) for n in names[1]))
                table[path, parameters] += p
    z = sum(table.values())
    return z, {key: p / z for key, p in table.items()} if z else {}


@pytest.mark.parametrize("static", [False, True])
@pytest.mark.parametrize("measures", ["start", "report"])
def test_joint_matches_state_work_name_exhaustion(static, measures):
    """落とす: Qを無視・nsを秒として使う・回数を平均・start/reportを混同。"""
    model = bridge_model(static=static, measures=measures)
    attempts = (Attempt("first", "a", 0), Attempt("other", "b", 0), Attempt("second", "a", S))
    facts = (Completed("first", S, "1"), NotArrived("other", 0), NotArrived("second", 2 * S))
    joint = belief(model, attempts, facts, 2 * S)
    posterior = joint.target_marginal((0, S, 2 * S, 3 * S))
    z, expected = brute_bridge(attempts, facts, (0, S, 2 * S, 3 * S), static=static, measures=measures)
    actual = defaultdict(F)
    for component in posterior.components:
        actual[component.states, component.parameters] += component.weight
    assert set(actual) == set(expected)
    for key, value in expected.items():
        if static:
            assert actual[key] == value
        else:
            assert float(actual[key]) == pytest.approx(float(value), abs=ROUND)
    enclosed(posterior.evidence_bounds, z, rounding=0 if static else ROUND)
    assert sum(actual.values()) == 1
    prediction = joint.predictive(attempts[2], until_ns=3 * S)
    for outcome in ("0", "1"):
        numerator, _ = brute_bridge(attempts, facts + (Completed("second", 3 * S, outcome),),
                                    (0, S, 2 * S, 3 * S), static=static, measures=measures)
        expected_probability = numerator / z
        if static:
            assert prediction.probabilities[3 * S, outcome] == expected_probability
        else:
            enclosed(prediction.bounds[3 * S, outcome], expected_probability)
    assert prediction.probabilities[None, None] == 0
    assert sum(prediction.probabilities.values()) == 1


def test_bridge_b_fixed_posterior_and_all_parameters():
    """落とす: 路を一本へ平均・測った状態を一律0にする・FかΘの学習を落とす。

    tools/s4b1c_fixed_values.py「段1の結合の事後」の独立な値。
    """
    model = bridge_model()
    root = belief(model)
    child = condition(root, (Completed("root-a", S, "1"),), observed_ns=S,
                      attempts=(Attempt("root-a", "a", 0),))
    posterior = target_marginal(child, (S, 2 * S))
    assert posterior.group_keys == (("work", "a"), ("work", "b"), ("names", "a", 0), ("names", "a", 1))
    expected = {(0, 0): F(1, 4), (0, 1): F(1, 4), (1, 1): F(1, 2)}
    assert set(posterior.state_probabilities()) == set(expected)
    for states, p in expected.items():
        enclosed(posterior.state_bounds()[states], p)
    for component in posterior.components:
        assert float(component.weight) == pytest.approx(float(expected[component.states]), abs=ROUND)
        state = component.states[0]
        theta0 = (F(1), F(2)) if state == 0 else (F(1), F(1))
        theta1 = (F(1), F(2)) if state == 1 else (F(1), F(1))
        assert component.parameters == ((F(2), F(1)), (F(3),), theta0, theta1)
    enclosed(posterior.evidence_bounds, F(1, 4))
    assert posterior.mean(("work", "a")) == (F(2, 3), F(1, 3))
    assert float(posterior.mean(("names", "a", 0))[1]) == pytest.approx(7 / 12, abs=ROUND)
    assert float(posterior.mean(("names", "a", 1))[1]) == pytest.approx(7 / 12, abs=ROUND)


def test_joint_future_work_and_name_cannot_be_multiplied():
    """落とす: 仕事量の予測と名前の予測を独立に掛ける。

    exactの過去ではFとΘの事後が分離できる場合もあるが、Qを通す
    未来の仕事量・測る状態・名前の共同予測は分離できない。
    """
    model = bridge_model()
    root = belief(model, (Attempt("known", "b", 0),), (Completed("known", S, "0"),), S)
    prediction = root.predictive(Attempt("new", "b", S), until_ns=2 * S)
    assert float(prediction.probabilities[2 * S, "1"]) == pytest.approx(.5, abs=ROUND)
    # 所要1か2で、状態を正確に読む同じ手。Θ固定も名前の契約の一部。
    names = dict(model.names)
    names["a"] = NameSpec(((F(1), F(0)), (F(0), F(1))), False, "report")
    world = replace(model, names=names)
    prediction = belief(world).predictive(Attempt("new", "a", 0), until_ns=2 * S)
    expected = {(S, "0"): F(1, 4), (S, "1"): F(1, 4),
                (2 * S, "0"): F(1, 8), (2 * S, "1"): F(3, 8), (None, None): F(0)}
    for key, p in expected.items():
        enclosed(prediction.bounds[key], p)
        assert float(prediction.probabilities[key]) == pytest.approx(float(p), abs=ROUND)
    # 独立に掛ける誤実装は P(所要1,名前1)=1/2*5/8=5/16。
    assert abs(float(prediction.probabilities[S, "1"]) - 5 / 16) > .06

    # 学んだΘとFを同時に使う場面。過去の名前0は、その時の状態の
    # Θへだけ加算。次の測定まで同じ状態でいる確率は3/4と5/8。
    learned = belief(model, (Attempt("past", "a", 0),), (Completed("past", S, "0"),), S)
    prediction = learned.predictive(Attempt("next", "a", S), until_ns=3 * S)
    expected = {(2 * S, "0"): F(5, 12), (2 * S, "1"): F(1, 4),
                (3 * S, "0"): F(29, 144), (3 * S, "1"): F(19, 144), (None, None): F(0)}
    for key, p in expected.items():
        enclosed(prediction.bounds[key], p)
    independent = F(2, 3) * F(89, 144)
    assert abs(float(prediction.probabilities[2 * S, "0"] - independent)) > .004


def test_mixture_label_is_marginalized_before_kl():
    """落とす: ½Beta(2,1)+½Beta(1,2) の内部ラベルへ偽のKLを付ける。"""
    model = scalar_model(((1, F(1, 2)), (2, F(1, 2))), alpha=F(2))
    root = belief(model)
    child = root.condition((), attempts=(Attempt("latent", "a", 0),), observed_ns=0)
    target = child.target_marginal(())
    assert [c.parameters[0] for c in target.components] == [(F(1), F(2)), (F(2), F(1))]
    assert [c.weight for c in target.components] == [F(1, 2), F(1, 2)]
    value = root_potential(root, child, times=(), tolerance=1e-12, series_budget=10)
    assert value.lower == value.upper == 0
    wrong = math.log(2) - .5  # 成分のKLの平均、固定値の台本と同じ誤り。
    assert wrong == pytest.approx(0.1931471805599453, abs=1e-16)
    assert value.upper < wrong


def test_pending_keeps_the_same_work_draw():
    """落とす: 未着の仕事の残りを更新後のFから新しく引き直す。"""
    model = scalar_model(((1, F(1, 2)), (2, F(1, 2))), alpha=F(2))
    old = Attempt("old", "a", 0)
    root = belief(model, (old,), (NotArrived("old", 1),), 1)
    assert dict(root.pending_work("old")) == {2: F(1)}
    old_prediction = root.predictive(old, until_ns=2)
    assert old_prediction.probabilities[None, None] == 0
    assert sum(p for (t, _), p in old_prediction.probabilities.items() if t == 2) == 1
    fresh = root.predictive(Attempt("fresh", "a", 1), until_ns=2)
    assert fresh.probabilities[None, None] == F(2, 3)
    assert sum(p for (t, _), p in fresh.probabilities.items() if t == 2) == F(1, 3)


def test_infinite_atom_is_separate_and_updates_its_work_prior():
    """落とす: ∞を大きな有限の時刻に替える・未着を無情報として捨てる。"""
    model = scalar_model(((1, F(1, 2)), (INFINITE_WORK, F(1, 2))), alpha=F(2))
    root = belief(model, (Attempt("old", "a", 0),), (NotArrived("old", 10),), 10)
    assert dict(root.pending_work("old")) == {INFINITE_WORK: F(1)}
    assert root.target_marginal().mean(("work", "a")) == (F(1, 3), F(2, 3))
    prediction = root.predictive(Attempt("new", "a", 10), until_ns=100)
    assert prediction.probabilities[None, None] == F(2, 3)


@pytest.mark.parametrize("outcome,expected", [("1", math.log(1.5) - 1 / 3),
                                               ("0", math.log(3) - 5 / 6)])
def test_root_potential_retains_the_root_reference(outcome, expected):
    """落とす: 節ごとの事前へ差し替える・回数を落とす・法則のKLを除く。"""
    model = scalar_model()
    prior = belief(model)
    root = prior.condition((Completed("first", 1, "1"),), observed_ns=1,
                           attempts=(Attempt("first", "a", 0),))
    child = root.condition((Completed("second", 2, outcome),), observed_ns=2,
                           attempts=(Attempt("second", "a", 1),))
    value = child.root_potential(root, times=(), tolerance=1e-12, series_budget=10)
    enclosed(value, expected)
    assert value.upper - value.lower <= 1e-12
    first = root.root_potential(prior, times=(), tolerance=1e-12, series_budget=10)
    enclosed(first, math.log(2) - .5)
    if outcome == "1":
        total = child.root_potential(prior, times=(), tolerance=1e-12, series_budget=10)
        enclosed(total, math.log(3) - 2 / 3)
        assert abs(total.midpoint - value.midpoint) > .3


def test_fact_order_batching_and_duplicate_receipt_are_invariant():
    """落とす: 同じ事実を二重に数える・取り込み順で状態や数えを変える。"""
    model = bridge_model(static=True)
    attempts = (Attempt("one", "a", 0), Attempt("two", "a", S))
    one, two = Completed("one", S, "1"), Completed("two", 2 * S, "0")
    all_at_once = belief(model, attempts, (two, one), 2 * S)
    batched = belief(model, attempts, (one,), S).condition((two, one), observed_ns=2 * S)
    assert all_at_once.target_marginal((S, 2 * S)).components == batched.target_marginal((S, 2 * S)).components
    assert all_at_once.target_marginal().evidence == F(1, 18)


def test_empty_and_impossible_facts_are_distinct():
    """落とす: 空入力と説明できない事実を同じ一様信念にする。"""
    model = scalar_model()
    root = belief(model)
    assert root.target_marginal().evidence == 1
    assert root.target_marginal().mean(("names", "a", 0)) == (F(1, 2), F(1, 2))
    impossible = root.condition((Completed("x", 2, "1"),), observed_ns=2, attempts=(Attempt("x", "a", 0),))
    with pytest.raises(ModelViolation, match="zero probability"):
        impossible.target_marginal()
    assert impossible.target_marginal(allow_impossible=True).evidence == 0
    contradictory = root.condition((Completed("x", 1, "1"), NotArrived("x", 1)), observed_ns=1,
                                   attempts=(Attempt("x", "a", 0),))
    with pytest.raises(ModelViolation):
        contradictory.target_marginal()


@pytest.mark.parametrize("change", ["speed", "lower", "tick", "unit", "zero"])
def test_inputs_outside_certified_stage_one_stop(change):
    """落とす: 範囲外を丸める・ρ≠1を所要に置き換えて黙って継続。"""
    model = scalar_model()
    with pytest.raises((IntegrationIncomplete, OutsideEvaluationType)):
        if change == "speed":
            replace(model, completion=spec(states=("s",), rates=(((F(2),),),), bound=2))
        elif change == "lower":
            replace(model, w_star_ns=None)
        elif change == "tick":
            replace(model, measure=MeasureSpec("tick", "1", {"width_ns": 2, "phase": {"point_ns": 0}, "check": "uniform_in_tick"}))
        elif change == "unit":
            replace(model, completion=spec(states=("s",), work_unit="second", time_unit="second"))
        else:
            scalar_model(((0, F(1)),))


@pytest.mark.parametrize("value", [0.5, F(1, 2), True])
def test_continuous_or_boolean_times_are_never_rounded(value):
    """落とす: int()やround()で連続の exact を実記録の整数とみなす。"""
    with pytest.raises(IntegrationIncomplete, match="integer ns"):
        Attempt("x", "a", value)
    with pytest.raises(IntegrationIncomplete, match="integer ns"):
        Completed("x", value, "1")


def test_transition_tail_and_ns_conversion_have_requested_bounds():
    """落とす: 相対1e-12を固定・尾を返さない・列と行やns/秒を取り違える。"""
    q = math.log(2)
    Q = np.array([[-q, 0.], [q, 0.]])
    for tolerance in (1e-5, 1e-16):
        lower, kappa = transition_bounds(Q, S, tolerance=tolerance)
        assert kappa <= math.log1p(tolerance)
        assert lower[0, 1] == -math.inf
        for i, j, expected in ((0, 0, .5), (1, 0, .5), (1, 1, 1.)):
            assert math.exp(lower[i, j]) - ROUND <= expected <= math.exp(lower[i, j] + kappa) + ROUND
    exact, error = transition_bounds(np.zeros((2, 2)), 7, tolerance=1e-16)
    assert error == 0
    assert np.array_equal(exact, np.array([[0., -math.inf], [-math.inf, 0.]]))


def test_information_unfinished_is_not_zero_or_an_impossible_model():
    """落とす: 要求精度未達を情報0・尤度0へ替える。"""
    model = bridge_model()
    root = belief(model, transition_tolerance=1e-4)
    child = root.condition((Completed("x", S, "1"),), observed_ns=S,
                           attempts=(Attempt("x", "a", 0),))
    assert child.target_marginal().evidence > 0
    with pytest.raises(IntegrationIncomplete, match="error exceeds"):
        child.root_potential(root, times=(S,), tolerance=1e-12, series_budget=10)


def test_nontrivial_mixture_series_budget_stops():
    """落とす: 状態を周辺化した混合を成分KLで置き換え・級数を黙って切る。"""
    model = bridge_model()
    root = belief(model)
    child = root.condition((Completed("x", S, "1"),), observed_ns=S,
                           attempts=(Attempt("x", "a", 0),))
    # 対象の状態なしでは θ0/2+θ1/2 の混合の対数が要る。
    with pytest.raises(IntegrationIncomplete, match="series budget"):
        child.root_potential(root, times=(), tolerance=1e-12, series_budget=1)


def test_path_mass_roundoff_preserves_joint_weights_and_polynomial_contract(monkeypatch):
    """落とす: 丸めで1を超えた道の質量をそのまま渡す・係数を個別に切る。

    同じ状態へ留まる遷移の対数に、小さい正の丸めを決定的に注入する。
    期待値は静的な世界の直接の和。実際のlibmの丸め方には依存しない。
    """
    delta = F(1, 2 ** 48)
    rounded_log = math.log1p(float(delta))

    def rounded_transition(Q, dt_ns, *, tolerance):
        assert np.array_equal(Q, np.zeros((2, 2)))
        assert dt_ns == S
        return np.array([[rounded_log, -math.inf], [-math.inf, rounded_log]]), 0.

    monkeypatch.setattr("sui.joint.transition_bounds", rounded_transition)
    model = replace(bridge_model(static=True), initial=(F(3, 4), F(1, 4)))
    root = belief(model)
    attempt = Attempt("latent", "a", 0)
    child = root.condition((), observed_ns=0, attempts=(attempt,))
    marginal = child.target_marginal((S, 2 * S))
    assert marginal.evidence == 1
    assert dict(marginal.state_probabilities()) == {(0, 0): F(3, 4), (1, 1): F(1, 4)}
    expected = {((0, 0), (F(2), F(1))): F(3, 8),
                ((0, 0), (F(1), F(2))): F(3, 8),
                ((1, 1), (F(2), F(1))): F(1, 8),
                ((1, 1), (F(1), F(2))): F(1, 8)}
    assert {(c.states, c.parameters[0]): c.weight for c in marginal.components} == expected
    # 個々の単項式だけを切る修正では、上の状態つきの証拠が1を超えた
    # ままになる。共同の周辺化でも ΣF=1 を厳密に保つことを確かめる。
    parameters = child.target_marginal(())
    assert parameters.evidence == 1
    assert parameters._polynomials[()].constant_value() == 1
    # 注入した対角成分を2区間で掛ける。補正の参照値も新コードから
    # 作らず、注入した行列の実際の数値から独立に計算する。
    rounded_factor = F(math.exp(rounded_log))
    correction = math.log1p(float(rounded_factor ** 2 - 1))
    assert parameters.log_error == correction and correction > 0
    prediction = child.predictive(attempt, until_ns=2 * S)
    assert dict(prediction.probabilities) == {(S, "0"): F(1, 4), (S, "1"): F(1, 4),
                                             (2 * S, "0"): F(1, 4), (2 * S, "1"): F(1, 4),
                                             (None, None): F(0)}
    info = child.root_potential(root, times=(), tolerance=1e-12, series_budget=1)
    assert info.lower == info.upper == 0


def test_tiny_positive_paths_are_preserved_or_report_numerical_range():
    """落とす: 稀な到達可能状態を構造の0として消す。"""
    q = 1e-250
    Q = np.array([[-q, 0.], [q, 0.]])
    lower, _ = transition_bounds(Q, S, tolerance=1e-12)
    assert math.isfinite(lower[1, 0]) and math.exp(lower[1, 0]) > 0
    assert lower[0, 1] == -math.inf
    with pytest.raises(NumericalRange):
        transition_bounds(np.array([[-1e308, 0.], [1e308, 0.]]), 10 * S, tolerance=1e-12)


def test_progress_first_arrival_plateau_and_two_permanent_reasons():
    """落とす: C=Wの任意の解・ρ=0で割る・有限の停止と∞を合算。"""
    world = spec(states=("moving", "stopped"), rates=(((F(2), F(0)),),), bound=2,
                 work_unit="unit", time_unit="second")
    path = (ProgressSegment(F(1), "moving"), ProgressSegment(None, "stopped"))
    assert completion(world, "a", 0, 2, path).elapsed == 1
    assert completion(world, "a", 0, 0, path).elapsed == 0
    assert completion(world, "a", 0, 3, path).reason == "unreachable_finite_work"
    assert completion(world, "a", 0, INFINITE_WORK, path).reason == "infinite_work"
    kernel = completion_kernel(world, "a", 0, path,
                               atoms=((2, F(1, 3)), (3, F(1, 3)), (INFINITE_WORK, F(1, 3))))
    assert kernel.atoms == ((F(1), F(1, 3)),)
    assert kernel.infinite_work_mass == kernel.unreachable_work_mass == F(1, 3)
    assert kernel.mass == 1


def test_progress_density_jacobian_and_finite_unreachable_mass():
    """落とす: 密度と原子を足す・Jacobianを忘れる・停止中に密度を出す。"""
    world = spec(states=("moving", "stopped"), rates=(((F(2), F(0)),),), bound=2,
                 work_unit="unit", time_unit="second")
    path = (ProgressSegment(F(1), "moving"), ProgressSegment(None, "stopped"))
    kernel = completion_kernel(world, "a", 0, path, atoms=(), densities=(DensityPiece(F(0), F(4), F(1, 4)),))
    assert kernel.atoms == ()
    assert kernel.densities == (DensityPiece(F(0), F(1), F(1, 2)),)
    assert kernel.infinite_work_mass == 0
    assert kernel.unreachable_work_mass == F(1, 2)
    assert kernel.mass == 1


def test_progress_scale_change_and_candidate_order():
    """落とす: 単位の変更時にWだけ動かす・全行動共有の候補順を失う。"""
    world = spec(states=("s",), rates=(((F(2),),), ((F(4),),)), weights=(F(1, 3), F(2, 3)), bound=4,
                 work_unit="unit", time_unit="second")
    scaled = replace(world, candidates=(((F(6),),), ((F(12),),)), max_speed=12)
    path = (ProgressSegment(None, "s"),)
    assert world.weights == scaled.weights == (F(1, 3), F(2, 3))
    assert [completion(world, "a", i, 8, path).elapsed for i in (0, 1)] == [F(4), F(2)]
    for i in (0, 1):
        assert completion(world, "a", i, 8, path) == completion(scaled, "a", i, 24, path)


@pytest.mark.parametrize("rate", [math.inf, math.nan, -1])
def test_speed_cannot_be_infinite_nan_or_negative(rate):
    """落とす: ∞を速さにも使う・非有限値を候補として通す。"""
    with pytest.raises(ValueError):
        spec(states=("s",), rates=(((rate,),),))


def test_speed_bound_versions_and_normalization_are_checked():
    """落とす: 版・上限M・候補の重み・密度の全質量を検査しない。"""
    world = spec(states=("s",))
    for changes in ({"version": "2"}, {"max_speed": 0}, {"weights": (F(1, 2),)},
                    {"share": "per_action"}, {"speed_unit": "wrong"}):
        with pytest.raises(ValueError):
            replace(world, **changes)
    with pytest.raises(ValueError, match="infinite final"):
        completion(world, "a", 0, 1, (ProgressSegment(1, "s"),))
    with pytest.raises(ValueError, match="normalized"):
        completion_kernel(world, "a", 0, (ProgressSegment(None, "s"),), atoms=((1, F(1, 2)),))
