"""S4dの先読み。固定値は仕様§6、独立解は試験の中の総当たり。"""

from dataclasses import replace, FrozenInstanceError
from itertools import product
import math
from types import SimpleNamespace

import numpy as np
import pytest
from scipy.special import logsumexp

from sui.agent import Agent, plan, replay_decision, RebuildMismatch
from sui.contracts import ContractRef
from sui.ids import RefKind as K, SequentialIds
from sui.ledger import Ledger, SequentialSalts
from sui.records import Record, Preference, Payload, Role, Producer
from sui.preference import current, resolve, Feature, EvaluationInput
from sui import preference as preference_module
from sui.s4d_contracts import PREFERENCE, DECISION
from sui import lookahead as la
from worlds import HandHistory, _lookahead_model


NS = 1_000_000_000


def _rig(*, model=None, history=None, H=4 * NS, gamma=1., items=()):
    model = _lookahead_model() if model is None else model
    h = HandHistory() if history is None else history
    if history is None:
        h.boot()
    ledger, ids = Ledger(salts=SequentialSalts()), SequentialIds(prefix="lookahead")
    for record in h.records:
        ledger.append(record, ledger.heads())
    for data in (*items, {"kind": "style", "H_ns": H, "gamma": gamma}):
        record = Record(id=ids.new(K.PREFERENCE), at=h.clock.now(), writer=Role.MODEL,
            producer=Producer(component="test.lookahead", code_version="1"),
            body=Preference(basis=(), contract=PREFERENCE, content=Payload.json(data)))
        ledger.append(record, ledger.heads())
    agent = Agent(model=model, lineage="lookahead")
    agent.adopt(ledger, clock=h.clock, ids=ids)
    return SimpleNamespace(agent=agent, model=model, h=h, clock=h.clock, ledger=ledger, ids=ids)


def _table(name, probabilities):
    return {"kind": "item", "rule": {"name": "table", "version": "1"},
            "args": {"feature": {"name": name, "version": "1"}, "probs": probabilities}}


def _view(r, now=0, observed=0):
    return r.agent.view(now_ns=now, observed_ns=observed)


def _n6_model(mode, *, second=1e-200, elapsed=1., ratio=False):
    rate = 1e-200
    Q = (np.array([[-rate, 0., 0., 0.], [rate, -3 * rate, 0., 0.],
                   [0., rate, 0., 0.], [0., 2 * rate, 0., 0.]]) if ratio else
         np.array([[-rate, 0., 0.], [rate, -second, 0.], [0., second, 0.]]))
    size = len(Q)
    probe = (np.array([[1., 1., 1., 0.], [0., 0., 0., 1.]]) if ratio else
             np.array([[1., 1., 0.], [0., 0., 1.]]))
    a = {"probe": probe, "safe": np.array([[1.] * size, [0.] * size]),
         "sense": np.array([[1., 1.] + [0.] * (size - 2), [0., 0.] + [1.] * (size - 2)])}
    durations = {} if mode == "one_step" else {name: ((elapsed, 1.),) for name in a}
    return _lookahead_model(states=tuple(f"s{i}" for i in range(size)), outcomes=("o0", "o1"),
        actions=tuple(a), a=a, D=np.array([1.] + [0.] * (size - 1)), Q=Q,
        log_C=np.log([.5, .5]), durations=durations,
        measures={} if not durations else {name: "report" for name in a})


@pytest.mark.parametrize("mode", ["one_step", "hand", "lookahead"])
@pytest.mark.parametrize("control", ["positive", "disconnected", "zero_time"])
@pytest.mark.parametrize("pending", [False, True])
def test_n6_tiny_transition_preserves_forbidden_outcome(mode, control, pending):
    """約5e-401の結果も禁止。道がない時・経過0とは3つの入口すべてで区別する。"""
    from sui.lookahead import NoAdmissibleCandidate
    elapsed = 0. if control == "zero_time" else 1.
    model = _n6_model(mode, second=0. if control == "disconnected" else 1e-200,
                      elapsed=1. if mode == "lookahead" else elapsed)
    H = round(elapsed * NS) if mode == "lookahead" else None
    allowed = [[], [["probe", "o0"]], [["safe", "o0"]]]
    if pending:
        allowed += [[[action, "o0"], ["sense", outcome]]
                    for action in ("probe", "safe") for outcome in ("o0", "o1")]
    item = (_table("outcome_multiset", [[value, 1 / len(allowed)] for value in allowed])
            if mode == "lookahead" else
            _table("candidate_outcome", [["o0", 1.]]))
    h = HandHistory()
    h.boot()
    if pending:
        h.start("sense")
    r = _rig(model=model, history=h, H=H, items=(item,))
    view = _view(r, now=round(elapsed * NS) if mode == "one_step" else 0)
    data = plan(view, ("probe", "safe"), u=.5).content.as_json()
    if control == "positive":
        assert data["expected_cost"][0] == data["J"][0] == "+inf"
        assert data["q_pi"] == [0., 1.]
        with pytest.raises(NoAdmissibleCandidate):
            plan(view, ("probe",), u=.5)
    else:
        assert all(isinstance(v, float) and math.isfinite(v) for v in data["J"])
        assert plan(view, ("probe",), u=.5).content.as_json()["q_pi"] == [1.]


@pytest.mark.parametrize("mode", ["one_step", "hand", "lookahead", "lookahead_model4"])
@pytest.mark.parametrize("ratio", [False, True])
def test_n6_rare_fact_rebuilds_log_belief_and_replays_without_changing_saved_belief(mode, ratio):
    """旧q=nullの事実を新入口で読める。極小の2状態は1:2のまま、保存と互換は変えない。"""
    from sui.agent import ModelFalsified, plan_s4c
    model = _n6_model(mode, ratio=ratio)
    ahead = mode.startswith("lookahead")
    if mode == "lookahead_model4":
        model = replace(model, actions=(*model.actions, "wait"), a={**model.a, "wait": model.a["safe"]},
            durations={**model.durations, "wait": ((None, 1.),)}, measures={**model.measures, "wait": "report"})
    h = HandHistory()
    h.boot()
    attempt = h.start("sense")
    h.observe(attempt, "o1", 1)
    item = (_table("outcome_multiset", [[[["probe", "o0"]], .8], [[["probe", "o1"]], .2]])
            if ahead else _table("candidate_outcome", [["o0", .8], ["o1", .2]]))
    r = _rig(model=model, history=h, H=NS if ahead else None, items=(item,))
    saved = r.agent._belief.body.content
    assert saved.as_json()["q"] is None
    view = _view(r, now=NS, observed=NS)
    if mode == "lookahead_model4":
        assert r.agent._belief.body.contract == ContractRef("sui.s4d.belief", "1")
        with pytest.raises(ValueError, match="sui.model.4 is not supported"):
            plan_s4c(view, ("probe",), u=.5)
    else:
        with pytest.raises(ModelFalsified):
            plan_s4c(view, ("probe",), u=.5)
    draft = plan(view, ("probe",), u=.5)
    data = draft.content.as_json()
    # 独立の極限: 2回の跳躍の行き先の率が1:2。残る誤差はO(1e-200)。
    expected_cost = -(math.log(.8) + 2 * math.log(.2)) / 3 if ratio else -math.log(.2)
    expected_information = -(math.log(1 / 3) + 2 * math.log(2 / 3)) / 3 if ratio else 0.
    assert data["expected_cost"] == pytest.approx([expected_cost], abs=1e-12)
    assert data["information"] == pytest.approx([expected_information], abs=1e-12)
    assert data["J"] == pytest.approx([expected_cost - expected_information], abs=1e-12)
    commit = r.agent.prepare(draft, clock=r.clock, ids=r.ids)
    r.agent.commit(commit, ledger=r.ledger)
    entry, = r.ledger.entries_of(commit.decided.id)
    assert replay_decision(model=model, ledger=r.ledger, decision=entry.cid) == draft
    assert r.agent._belief.body.content == saved


@pytest.mark.parametrize("mode", ["one_step", "hand", "lookahead"])
def test_n6_truly_impossible_fact_still_falsifies_new_entry(mode):
    """経過0で到達できない結果は旧信念も新入口も説明不能で、一様には戻さない。"""
    from sui.agent import ModelFalsified
    h = HandHistory()
    h.boot()
    h.observe(h.start("sense"), "o1", 0)
    r = _rig(model=_n6_model(mode), history=h, H=NS if mode == "lookahead" else None)
    assert r.agent._belief.body.content.as_json()["q"] is None
    with pytest.raises(ModelFalsified):
        plan(_view(r, now=NS, observed=NS), ("probe",), u=.5)


@pytest.mark.parametrize("rate,dt", [(1e-200, 1.), (.5, 2.), (13., 2.), (50., 2.)])
def test_n6_uniformization_meets_component_relative_accuracy(rate, dt):
    """吸収する2状態の独立な閉じた式と相対1e-12で一致。小さな固定Kでは足りない。"""
    from sui.inference import _s4d_log_transition
    actual = _s4d_log_transition(np.array([[-rate, 0.], [rate, 0.]]), dt)
    mean = rate * dt
    expected = np.array([[-mean, -math.inf], [math.log(-math.expm1(-mean)), 0.]])
    support = np.isfinite(expected)
    assert np.array_equal(np.isfinite(actual), support)
    np.testing.assert_allclose(np.exp(actual[support] - expected[support]), 1., rtol=1e-12, atol=0)


def test_n6_uniformization_keeps_tiny_log_magnitude_and_exact_zeros():
    """仕様の固定値・グラフの到達・Q=0・dt=0を区別し、比も対数のまま保つ。"""
    from sui.inference import _s4d_log_transition
    model = _n6_model("one_step")
    actual = _s4d_log_transition(model.Q, 1.)
    assert actual[2, 0] == pytest.approx(-921.7271843781782, abs=1e-12)
    assert np.array_equal(np.isfinite(actual), np.tri(3, dtype=bool))
    identity = np.full((3, 3), -math.inf)
    np.fill_diagonal(identity, 0.)
    assert np.array_equal(_s4d_log_transition(model.Q, 0.), identity)
    assert np.array_equal(_s4d_log_transition(np.zeros((3, 3)), 1.), identity)
    ratio = _s4d_log_transition(_n6_model("one_step", ratio=True).Q, 1.)
    assert math.exp(ratio[3, 0] - ratio[2, 0]) == pytest.approx(2., abs=1e-12)


@pytest.mark.parametrize("shift", [0., -1000., -1e16, -1e300])
def test_n8_normalization_removes_large_common_offset_before_logsumexp(shift):
    """大きな共通項を戻してから引くと和2になる。構造的0を保ち和1にする。"""
    from sui.inference import _s4d_normalize
    logs = np.array([[shift, -math.inf], [-math.inf, shift]])
    before = logs.copy()
    actual, total = _s4d_normalize(logs)
    np.testing.assert_allclose(actual[np.isfinite(actual)], [-math.log(2)] * 2, rtol=0, atol=1e-15)
    assert np.array_equal(np.isfinite(actual), np.isfinite(logs))
    assert math.fsum(np.exp(actual).flat) == pytest.approx(1., abs=1e-15)
    assert math.isfinite(total)
    assert np.array_equal(logs, before)


def test_n8_normalization_preserves_representable_unequal_log_ratios():
    """1e16を引いても表せる差0,-2,-4の比を保ち、一様化でも通らない。"""
    from sui.inference import _s4d_normalize
    logs = np.array([0., -2., -4., -math.inf])
    expected = logs - math.log(math.fsum([1., math.exp(-2), math.exp(-4)]))
    for shift in (0., -1e16):
        actual, _ = _s4d_normalize(logs + shift)
        np.testing.assert_allclose(actual, expected, rtol=0, atol=1e-15)


@pytest.mark.parametrize("shift", [0., -1e16, -1e300])
def test_n8_one_step_components_keep_cost_information_and_zero_J(shift):
    """単位の観測・一様な好みなら費用も情報もlog 2、共通項によらずJ=0。"""
    from sui.agent import _one_step_components
    cost, information = _one_step_components(np.array([shift, shift]), np.eye(2), False,
                                             np.full(2, math.log(2)))
    assert cost == pytest.approx(math.log(2), abs=1e-15)
    assert information == pytest.approx(math.log(2), abs=1e-15)
    assert cost - information == pytest.approx(0., abs=1e-15)


def test_n8_duration_posterior_normalizes_before_restoring_common_branch_mass(monkeypatch):
    """同じ未着の枝に属する所要2/3秒は、大きな共通log重みがあっても半々。"""
    h = HandHistory()
    h.boot()
    h.start("look")
    model = _lookahead_model(durations={"look": ((2., .5), (3., .5)),
        "peek": ((2., 1.),), "wait": ((None, 1.),)})
    r = _rig(model=model, history=h, H=NS)
    eta, b, T, _, _ = _root(r, candidates=("wait",))
    baseline, = la.branches(eta, b, "wait", T)
    # 新しい仕事の全点に共通の対数重み。内部所要の条件つきの比は変えない。
    monkeypatch.setattr(la, "_log_points", lambda points: tuple((d, -1e16) for d, _ in points))
    actual, = la.branches(eta, b, "wait", T)
    assert _points(actual.belief.jobs[0]) == _points(baseline.belief.jobs[0]) == {2 * NS: .5, 3 * NS: .5}
    assert actual.E == baseline.E == ()
    assert actual.log_probability == -1e16


@pytest.mark.parametrize("k,mean", [(0, 10000.), (15, 15.), (16, 16.), (16, 1.),
    (16, 100.), (9999, 10000.), (10000, 10000.), (10001, 10000.), (10000, 9999.75), (16, 1e-200)])
def test_n8_poisson_log_weight_matches_independent_decimal_factorial(k, mean):
    """式の切り替わりと山の前後を80桁の階乗式で検算し、大きな項の相殺を見つける。"""
    from decimal import Decimal, localcontext
    from sui.inference import _s4d_poisson_log
    with localcontext() as ctx:
        ctx.prec = 80
        m = Decimal.from_float(mean)
        expected = float(-m + k * m.ln() - Decimal(math.factorial(k)).ln())
    assert _s4d_poisson_log(k, mean, math.log(mean)) == pytest.approx(expected, rel=0, abs=5e-12)


@pytest.mark.parametrize("mean", [16., 100., 1000., 9999.75, 10000.])
def test_n8_large_uniformization_total_error_against_absorbing_closed_form(mean):
    """総相対誤差の試験の許しは1e-12。仕様の打ち切りの尾の保証とは別に測る。"""
    from sui.inference import _s4d_log_transition
    actual = _s4d_log_transition(np.array([[-mean, 0.], [mean, 0.]]), 1.)
    expected = np.array([[-mean, -math.inf], [math.log(-math.expm1(-mean)), 0.]])
    support = np.isfinite(expected)
    assert np.array_equal(np.isfinite(actual), support)
    # exp(log B)を先に作ると、残留確率exp(-10000)を0にして比較できない。
    relative_error = np.abs(np.expm1(actual[support] - expected[support]))
    assert float(relative_error.max()) <= 1e-12


def _n9_chain_log_mass(rate, dt, steps):
    """独立解。100桁で吸収点へのPoisson尾を正の項だけで足す。"""
    from decimal import Decimal, localcontext
    with localcontext() as ctx:
        ctx.prec = 100
        mean = Decimal.from_float(rate) * Decimal.from_float(dt)
        term = mean ** steps / Decimal(math.factorial(steps))
        total, k = term, steps
        while True:
            k += 1
            term *= mean / k
            updated = total + term
            if updated == total:
                return float(-mean + total.ln())
            total = updated


def _n9_chain(steps, rate):
    Q = np.zeros((steps + 1, steps + 1))
    for s in range(steps):
        Q[s, s], Q[s + 1, s] = -rate, rate
    return Q


@pytest.mark.parametrize("rate", [1e-315, 6e-315, 1e-310])
@pytest.mark.parametrize("k", [15, 16])
def test_n9_poisson_keeps_log_mean_when_rate_time_product_rounds(rate, k):
    """率と時間を別々に渡す。0または非正規化数に丸まる積でも15/16段の境界を保つ。"""
    from decimal import Decimal, localcontext
    from sui.inference import _s4d_poisson_log
    dt = 1e-9
    mean, log_mean = rate * dt, math.log(rate) + math.log(dt)
    assert mean == 0. or abs(math.log(mean) - log_mean) > 1e-7
    with localcontext() as ctx:
        ctx.prec = 100
        exact_mean = Decimal.from_float(rate) * Decimal.from_float(dt)
        expected = float(-exact_mean + k * exact_mean.ln() - Decimal(math.factorial(k)).ln())
    actual = _s4d_poisson_log(k, mean, log_mean)
    assert actual == pytest.approx(expected, rel=0, abs=5e-12)


@pytest.mark.parametrize("rate", [1e-315, 6e-315])
@pytest.mark.parametrize("steps", [15, 16])
def test_n9_chain_transition_matches_independent_decimal_tail(rate, steps):
    """鎖の終点を100桁の尾と照合。通常の確率は0でも対数の大きさを保つ。"""
    from sui.inference import _s4d_log_transition
    actual = _s4d_log_transition(_n9_chain(steps, rate), 1e-9)[steps, 0]
    expected = _n9_chain_log_mass(rate, 1e-9, steps)
    assert actual == pytest.approx(expected, rel=0, abs=5e-12)
    if rate == 6e-315 and steps == 16:
        assert actual == pytest.approx(-11938.604830677508, rel=0, abs=5e-12)


def test_n9_33_state_ledger_observation_keeps_probe_choice_and_replay():
    """16段/15段の終点の事実から調べる価値を計算。丸めたmeanへ戻すとblindを選ぶ。"""
    from decimal import Decimal, localcontext
    rate, dt = 6e-315, 1e-9
    Q = np.zeros((33, 33))
    Q[:17, :17], Q[17:, 17:] = _n9_chain(16, rate), _n9_chain(15, rate)
    D = np.zeros(33)
    D[0], D[17] = 1., math.ulp(0.)
    blind = np.zeros((3, 33))
    blind[0] = 1.
    probe, sense = blind.copy(), blind.copy()
    probe[:, 16] = [0., 1., 0.]
    sense[:, [16, 32]] = [[0.], [0.], [1.]]
    model = _lookahead_model(states=tuple(f"s{i}" for i in range(33)),
        outcomes=("o0", "o1", "seen"), actions=("blind", "probe", "sense"),
        a={"blind": blind, "probe": probe, "sense": sense}, D=D, Q=Q,
        durations={}, measures={})
    h = HandHistory()
    h.boot()
    h.observe(h.start("sense"), "seen", dt)
    r = _rig(model=model, history=h, H=None)
    assert r.agent._belief.body.content.as_json()["q"] is None
    view = _view(r, now=1, observed=1)
    assert view.reading.n["sense"].tolist() == [0, 0, 1]
    # この極小meanでは、尾の次項の相対寄与はmean/(steps+1)未満。
    # 2つの終点への質量比はmean/(16*D[17])、誤差はO(1e-324)。
    with localcontext() as ctx:
        ctx.prec = 100
        mean = Decimal.from_float(rate) * Decimal.from_float(dt)
        ratio = mean / (16 * Decimal.from_float(D[17]))
        left = float(ratio / (1 + ratio))
    information = -left * math.log(left) - (1 - left) * math.log1p(-left)
    blind_probability = 1 / (1 + math.exp(information))
    draft = plan(view, ("blind", "probe"), u=.47)
    data = draft.content.as_json()
    assert data["expected_cost"] == [0., 0.]
    assert data["information"] == pytest.approx([0., information], rel=0, abs=1e-12)
    assert data["J"] == pytest.approx([0., -information], rel=0, abs=1e-12)
    assert data["q_pi"] == pytest.approx([blind_probability, 1 - blind_probability], rel=0, abs=1e-12)
    assert data["chosen"] == "probe"
    commit = r.agent.prepare(draft, clock=r.clock, ids=r.ids)
    r.agent.commit(commit, ledger=r.ledger)
    entry, = r.ledger.entries_of(commit.decided.id)
    assert replay_decision(model=model, ledger=r.ledger, decision=entry.cid) == draft


def _n10_rig(evaluation, kind):
    ahead = evaluation == "lookahead"
    if kind == "expectation":
        outcomes = (*(f"o{i}" for i in range(8)), "unused")
        a = {"probe": np.array([[1.]] * 8 + [[0.]]),
             "safe": np.array([[0.]] * 8 + [[1.]])}
        pairs = [("probe", name, -float(np.finfo(float).max)) for name in outcomes[:8]]
        pairs.append(("safe", "unused", 0.))
        copies = 1
    else:
        outcomes = ("o0", "o1")
        a = {"probe": np.array([[.9], [.1]]), "safe": np.array([[1.], [0.]])}
        pairs = [("probe", "o0", -math.log(2)), ("safe", "o0", -math.log(2))] if ahead else [("probe", "o0", 0.)]
        if kind != "forbidden":
            pairs.append(("probe", "o1", -1e307 if kind == "finite" else -1e308))
        copies = 2
    rows = [[[[action, outcome]] if ahead else outcome, lp] for action, outcome, lp in pairs]
    item = {"kind": "item", "rule": {"name": "table", "version": "1"},
        "args": {"feature": {"name": "outcome_multiset" if ahead else "candidate_outcome", "version": "1"},
                 "log_probs": rows}}
    model = _lookahead_model(states=("s",), outcomes=outcomes, actions=("probe", "safe"),
        a=a, D=np.ones(1), log_C=np.full(len(outcomes), -math.log(len(outcomes))),
        durations={name: ((1., 1.),) for name in a} if ahead else {},
        measures={name: "report" for name in a} if ahead else {})
    return _rig(model=model, H=NS if ahead else None, gamma=0., items=(item,) * copies)


@pytest.mark.parametrize("evaluation", ["one_step", "lookahead"])
@pytest.mark.parametrize("candidates", [("probe",), ("probe", "safe")])
@pytest.mark.parametrize("kind", ["items", "expectation"])
def test_n10_finite_cost_overflow_refuses_public_decision_without_writing(evaluation, candidates, kind):
    """有限の付箋の和と重みつき期待値のあふれを、禁止と誤らず無記録で止める。"""
    from sui.inference import NumericalRange
    r = _n10_rig(evaluation, kind)
    before = tuple(r.ledger.entries())
    with pytest.raises(NumericalRange):
        r.agent.decide(candidates, u=.25, clock=r.clock, ids=r.ids, ledger=r.ledger,
                       now_mono_ns=0, observed_mono_ns=0)
    assert tuple(r.ledger.entries()) == before


@pytest.mark.parametrize("evaluation", ["one_step", "lookahead"])
def test_n10_true_prohibition_still_excludes_candidate_or_refuses_all(evaluation):
    """本当に表に無い結果は+inf。有限のあふれと区別し、gamma=0でも禁止を外す。"""
    from sui.lookahead import NoAdmissibleCandidate
    from sui.records import Decided, JobOpened
    r = _n10_rig(evaluation, "forbidden")
    before = tuple(r.ledger.entries())
    with pytest.raises(NoAdmissibleCandidate):
        r.agent.decide(("probe",), u=.25, clock=r.clock, ids=r.ids, ledger=r.ledger,
                       now_mono_ns=0, observed_mono_ns=0)
    assert tuple(r.ledger.entries()) == before
    decision, job = r.agent.decide(("probe", "safe"), u=.25, clock=r.clock, ids=r.ids, ledger=r.ledger,
                                  now_mono_ns=0, observed_mono_ns=0)
    data = decision.body.content.as_json()
    assert data["J"][0] == data["expected_cost"][0] == "+inf"
    assert data["q_pi"] == [0., 1.] and data["chosen"] == "safe"
    assert isinstance(decision.body, Decided) and isinstance(job.body, JobOpened)
    assert len(tuple(r.ledger.entries())) == len(before) + 2


@pytest.mark.parametrize("evaluation", ["one_step", "lookahead"])
def test_n10_large_representable_cost_is_not_a_prohibition(evaluation):
    """大きくても有限に表せる費用ならgamma=0で両候補を残し、正常に記録する。"""
    r = _n10_rig(evaluation, "finite")
    decision, _ = r.agent.decide(("probe", "safe"), u=.25, clock=r.clock, ids=r.ids, ledger=r.ledger,
                                now_mono_ns=0, observed_mono_ns=0)
    data = decision.body.content.as_json()
    assert data["expected_cost"][0] == pytest.approx(2e306, rel=1e-12)
    assert data["q_pi"] == [.5, .5] and data["chosen"] == "probe"


def test_n10_pending_expectation_overflow_is_not_a_prohibition():
    """8つの等確率の枝の丸めで有限の期待費用があふれても、禁止には変換しない。"""
    from sui.agent import _average_components
    from sui.inference import NumericalRange
    with pytest.raises(NumericalRange):
        _average_components((-math.log(8), (float(np.finfo(float).max), 0.)) for _ in range(8))


@pytest.mark.parametrize("case", ["product", "nan_product", "sum", "nan_sum"])
def test_n10_cost_arithmetic_distinguishes_overflow_nan_and_true_infinity(case):
    """有限の積/和のあふれと非数を拒み、意味の+infは重みが0へ丸まっても保つ。"""
    from sui.inference import NumericalRange, _s4d_weighted_cost, _s4d_cost_sum
    maximum = float(np.finfo(float).max)
    with pytest.raises(NumericalRange):
        if case == "product":
            _s4d_weighted_cost(math.nextafter(1., math.inf), maximum)
        elif case == "nan_product":
            _s4d_weighted_cost(0., math.nan)
        elif case == "sum":
            _s4d_cost_sum([1e308, 1e308])
        else:
            _s4d_cost_sum([math.nan])
    assert _s4d_weighted_cost(0., math.inf) == math.inf
    assert _s4d_cost_sum([1., math.inf]) == math.inf


@pytest.mark.parametrize("evaluation", ["one_step", "lookahead"])
def test_n10_window_reports_cost_overflow_without_a_decision(evaluation):
    """付箋のあふれを窓口がNumericalRangeで駆動へ渡し、決定を書かない。"""
    from sui.runtime import Window, Tick, Reconsider, Think, Thought
    from sui.records import Decided
    from worlds import ManualHost, ScriptDrive, GatedHand
    r = _n10_rig(evaluation, "items")
    drive = ScriptDrive(lambda status, event: [Reconsider(candidates=("probe", "safe"), u=.25)]
                        if isinstance(event, Tick) else [])
    host = ManualHost(lambda pledges: Window(agent=r.agent, ledger=r.ledger, clock=r.clock, ids=r.ids,
        hand=GatedHand({name: set() for name in r.model.actions}, {}), route="test", drive=drive,
        membrane=Producer(component="test.hand", code_version="1"), capacity={"think": 1}, pledges=pledges),
        clock=r.clock)
    host.advance(0)
    host.step()
    work = next(work for work, _ in host.work if isinstance(work, Think))
    event = host.finish(work)
    assert isinstance(event, Thought) and event.error == "NumericalRange" and event.draft is None
    host.step()
    assert host.window.status().thinking == 0
    assert not any(e.body_type is Decided for e in r.ledger.entries())
    assert any(isinstance(e, Thought) and e.error == "NumericalRange" for _, e in drive.calls)


def _n7_rig(mode):
    Q = np.array([[-1e308, 1e308], [1e308, -1e308]])
    model = _lookahead_model(states=("s0", "s1"), outcomes=("o0",), actions=("probe",),
        a={"probe": np.ones((1, 2))}, D=np.array([1., 0.]), log_C=np.zeros(1), Q=Q,
        durations={} if mode == "one_step" else {"probe": ((2., 1.),)},
        measures={} if mode == "one_step" else {"probe": "report"})
    return _rig(model=model, H=2 * NS if mode == "lookahead" else None)


@pytest.mark.parametrize("mode", ["one_step", "hand", "lookahead"])
def test_n7_unrepresentable_mean_refuses_decision_without_writing(mode):
    """λΔtのあふれは理由つきNumericalRange。同期の道にも決定・仕事を残さない。"""
    from sui.inference import NumericalRange
    r = _n7_rig(mode)
    before = tuple(r.ledger.entries())
    with pytest.raises(NumericalRange, match="uniformization mean"):
        r.agent.decide(("probe",), u=.5, clock=r.clock, ids=r.ids, ledger=r.ledger,
                       now_mono_ns=2 * NS if mode == "one_step" else 0, observed_mono_ns=0)
    assert tuple(r.ledger.entries()) == before


def test_n7_unrepresentable_bound_and_log_arithmetic_do_not_become_structural_zero():
    """尾・積・正規化のあふれを検出し、支えの消失や一様な近似にしない。"""
    from sui.inference import NumericalRange, _s4d_uniform_terms, _s4d_log_product, _s4d_normalize
    with pytest.raises(NumericalRange, match="tail bound"):
        _s4d_uniform_terms(1e308, math.log(1e308), -1e308)
    with pytest.raises(NumericalRange, match="log product"):
        _s4d_log_product(-1e308, -1e308)
    with pytest.raises(NumericalRange, match="normalized log probability"):
        _s4d_normalize(np.array([1e308, -1e308]))


def test_n7_window_reports_numerical_range_to_drive_without_a_decision():
    """数として表せない先読みは窓口で名前を届け、台帳に決定を残さない。"""
    from sui.runtime import Window, Tick, Reconsider, Think, Thought
    from sui.records import Decided
    from worlds import ManualHost, ScriptDrive, GatedHand
    r = _n7_rig("lookahead")
    drive = ScriptDrive(lambda status, event: [Reconsider(candidates=("probe",), u=.5)]
                        if isinstance(event, Tick) else [])
    host = ManualHost(lambda pledges: Window(agent=r.agent, ledger=r.ledger, clock=r.clock, ids=r.ids,
        hand=GatedHand({"probe": set()}, {}), route="test", drive=drive,
        membrane=Producer(component="test.hand", code_version="1"), capacity={"think": 1}, pledges=pledges),
        clock=r.clock)
    host.advance(0)
    host.step()
    work = next(work for work, _ in host.work if isinstance(work, Think))
    event = host.finish(work)
    assert isinstance(event, Thought) and event.error == "NumericalRange" and event.draft is None
    host.step()
    assert host.window.status().thinking == 0
    assert not any(e.body_type is Decided for e in r.ledger.entries())
    assert any(isinstance(e, Thought) and e.error == "NumericalRange" for _, e in drive.calls)


@pytest.mark.parametrize("H", [None, 2 * NS])
def test_n7_new_entry_deduplicates_and_orders_candidates_before_evaluation(H):
    """1歩も先読みも候補は集合。同じ手を多く列挙しても本文はバイト一致する。"""
    r = _rig(H=H)
    for u in (0., .4, .999):
        baseline = plan(_view(r), ("look", "peek"), u=u)
        for candidates in (("peek", "look"), ("peek", "peek", "look"), ("look", "peek", "look", "look")):
            draft = plan(_view(r), iter(candidates), u=u)
            assert draft.content.data == baseline.content.data
            assert draft == baseline


def test_c9_unobserved_duration_cannot_choose_the_next_action(monkeypatch):
    """1秒の子では2秒/3秒は半々。到着時刻を先に知って当てる選択と区別する。"""
    actions = ("first", "guess2", "guess3", "pending")
    model = _lookahead_model(states=("s",), outcomes=("o0",), actions=actions,
        a={name: np.ones((1, 1)) for name in actions}, D=np.ones(1), log_C=np.zeros(1),
        durations={"first": ((1., 1.),), "guess2": ((None, 1.),), "guess3": ((None, 1.),),
                   "pending": ((2., .5), (3., .5))}, measures={name: "report" for name in actions})
    h = HandHistory()
    h.boot()
    h.start("pending")
    ref = ContractRef("test.guess_arrival", "1")
    def project(value):
        if len(value.A) == 1:
            return "single"
        if len(value.A) != 2 or value.A[1][2] == "first":
            return "forbidden"
        arrival = next(t for t, label, _, _ in value.O if label[0] == "pending")
        return "hit" if (value.A[1][2] == "guess2") == (arrival == 2 * NS) else "miss"
    feature = Feature(ref=ref, evaluations=frozenset({"lookahead"}), _project=project)
    table = {"single": math.log(.2), "hit": math.log(.64), "miss": math.log(.16)}
    _register_rule(monkeypatch, ref, lambda h, args, definitions: (feature, lambda v: table.get(v, -math.inf)))
    r = _rig(model=model, history=h, H=3 * NS, items=(
        {"kind": "item", "rule": {"name": ref.name, "version": "1"}, "args": {}},))
    candidates = ("first", "guess2", "guess3")
    eta, b, T, _, resolved = _root(r, candidates=candidates)
    child, = la.branches(eta, b, "first", T)
    assert child.E == ((NS, ("new", 0), "first", "o0"),)
    assert _points(child.belief.jobs[0]) == {2 * NS: .5, 3 * NS: .5}
    next_eta = la._advance(eta, "first", child)
    values = [la._action_value(next_eta, child.belief, a, T, candidates, resolved) for a in candidates]
    # どちらを当てに行っても、まだ半々。内部の所要を先に選ぶとここが変わる。
    expected = -.5 * math.log(.64) - .5 * math.log(.16)
    assert [v.J for v in values] == pytest.approx([math.inf, expected, expected], abs=1e-12)
    assert la._policy([v.J for v in values], 1.).tolist() == [0., .5, .5]
    data = plan(_view(r), candidates, u=.5).content.as_json()
    assert data["J"] == pytest.approx([expected, -math.log(.2), -math.log(.2)], abs=1e-12)
    assert data["information"] == [0., 0., 0.]
    assert data["q_pi"] == pytest.approx([4 / 9, 5 / 18, 5 / 18], abs=1e-12)
    # 誤りの独立計算：所要ごとの子でsoftmaxを取り、当たり.8/外れ.2で平均。
    clairvoyant = -.8 * math.log(.64) - .2 * math.log(.16)
    assert expected - clairvoyant == pytest.approx(.3 * math.log(4), abs=1e-12)
    assert data["J"][0] != pytest.approx(clairvoyant, abs=1e-12)


def _root(r, *, now=0, observed=0, candidates=None):
    view = _view(r, now, observed)
    resolved = resolve(current(view.preferences), view)
    actions = tuple(sorted(r.model.actions if candidates is None else candidates))
    eta, b, time = la._initial(view, actions, resolved)
    return eta, b, time["deadline_ns"], actions, resolved


def _register_rule(monkeypatch, ref, rule):
    monkeypatch.setattr(preference_module, "BUILTINS", {**preference_module.BUILTINS,
        ("rule", ref.name, ref.version): rule})


def _count_rule(monkeypatch):
    ref = ContractRef("test.o1_count", "1")
    feature = Feature(evaluations=frozenset({"lookahead"}), ref=ContractRef("test.o1_count", "1"),
                      _project=lambda value: min(sum(o == "o1" for *_, o in value.O), 2))
    _register_rule(monkeypatch, ref, lambda h, args, definitions: (feature, lambda count: math.log((.2, .3, .5)[count])))
    return {"kind": "item", "rule": {"name": ref.name, "version": ref.version}, "args": {}}


@pytest.mark.parametrize("H,preferred,J,q", [
    (4 * NS, False, [-.4083188371797285, -.6931471805599453, 0.],
     [.33396779668307724, .4440214688779485, .22201073443897426]),
    (4 * NS, True, [.8896351075783104, .5668701865644227, 1.6094379124341003],
     [.3487006970483583, .48153497860862265, .16976432434301916]),
    (NS, False, [-.1376980576243852, 0., 0.],
     [.3646010973266676, .31769945133666616, .31769945133666616]),
])
def test_r1_l1_l2_l3_specification_fixed_values(monkeypatch, H, preferred, J, q):
    r = _rig(H=H, items=(_count_rule(monkeypatch),) if preferred else ())
    draft = plan(_view(r), reversed(r.model.actions), u=.5)
    data = draft.content.as_json()
    assert data["evaluation"] == "lookahead" and data["H_ns"] == H
    assert data["time"]["deadline_ns"] == H and data["candidates"] == ["look", "peek", "wait"]
    assert data["J"] == pytest.approx(J, abs=1e-12)
    assert data["q_pi"] == pytest.approx(q, abs=1e-12)
    assert np.array_equal(data["J"], np.array(data["expected_cost"]) - data["information"])
    assert "undefined_reason" not in data


def test_r1_unknown_theta_two_observations_update_the_same_coin():
    """Beta(1,1)の2観測。最初の情報を2倍する誤りを落とす。"""
    model = _lookahead_model(states=("s",), outcomes=("o0", "o1"), actions=("coin",),
        a={"coin": np.ones((2, 1))}, D=np.ones(1), log_C=np.log([.5, .5]),
        learnable=frozenset({"coin"}), durations={"coin": ((1., 1.),)}, measures={"coin": "report"})
    r = _rig(model=model, H=2 * NS)
    result = plan(_view(r), ("coin",), u=.5).content.as_json()
    assert result["information"] == pytest.approx([.3296613488547581], abs=1e-12)
    assert result["J"] == pytest.approx([-.3296613488547581], abs=1e-12)
    assert result["information"][0] != pytest.approx(2 * .1931471805599453, abs=1e-12)
    assert r.agent.view().reading.n["coin"].tolist() == [0, 0]


def _points(job):
    return {d: math.exp(p) for d, p in job.points}


def test_n4_c9_tail_and_none_merge_before_information_and_keep_both_reasons():
    model = _lookahead_model(durations={"look": ((2., .5), (None, .5)),
        "peek": ((2., 1.),), "wait": ((None, 1.),)})
    r = _rig(model=model, H=NS)
    eta, b, T, _, _ = _root(r)
    branches = la.branches(eta, b, "look", T)
    assert len(branches) == 1
    branch, = branches
    assert branch.E == () and branch.terminal and branch.t_end == NS
    assert branch.log_probability == pytest.approx(0., abs=1e-15)
    assert _points(branch.belief.jobs[-1]) == {2 * NS: .5, None: .5}
    assert branch.belief.kl(b) == pytest.approx(0., abs=1e-15)
    # Hを伸ばした問いには時刻2の報告か、時刻3まで未着の答え。
    r = _rig(model=model, H=3 * NS)
    eta, b, T, _, _ = _root(r)
    branches = la.branches(eta, b, "look", T)
    assert math.fsum(math.exp(x.log_probability) for x in branches if not x.terminal) == pytest.approx(.5)
    absent, = [x for x in branches if x.terminal]
    assert math.exp(absent.log_probability) == pytest.approx(.5)
    assert _points(absent.belief.jobs[-1]) == {None: 1.}
    assert logsumexp([x.log_probability for x in branches]) == pytest.approx(0., abs=1e-12)
    mixed = sum(math.exp(x.log_probability) * np.exp(x.belief.log_x) for x in branches)
    np.testing.assert_allclose(mixed, np.exp(b.log_x), atol=1e-12, rtol=0)


def test_n4_tree_boundary_is_strict_while_root_boundary_is_closed():
    model = _lookahead_model(durations={"look": ((2., .5), (None, .5)),
        "peek": ((2., 1.),), "wait": ((None, 1.),)})
    h = HandHistory()
    h.boot()
    h.start("look")
    r = _rig(model=model, history=h, H=3 * NS)
    eta, b, T, _, _ = _root(r, now=2 * NS, observed=2 * NS)
    assert _points(b.jobs[0]) == {2 * NS: .5, None: .5}
    eta, b, T, _, _ = _root(r)
    absent = [x for x in la.branches(eta, b, "peek", T)
              if not any(e[1][0] == "pending" for e in x.E)]
    assert absent and all(x.t_end == 2 * NS and not x.terminal for x in absent)
    for branch in absent:
        assert _points(branch.belief.jobs[0]) == {None: 1.}
        next_eta = la._advance(eta, "peek", branch)
        assert all(not any(e[1][0] == "pending" for e in x.E)
                   for x in la.branches(next_eta, branch.belief, "wait", T))


def test_c9_duration_information_is_not_information_about_x():
    model = _lookahead_model(states=("s",), D=np.ones(1),
        a={a: np.array([[1.], [0.], [0.]]) for a in ("look", "peek", "wait")},
        durations={"look": ((1., .5), (None, .5)), "peek": ((2., 1.),), "wait": ((None, 1.),)})
    r = _rig(model=model, H=NS)
    eta, b, T, _, _ = _root(r)
    branches = la.branches(eta, b, "look", T)
    assert len(branches) == 2
    assert [math.exp(x.log_probability) for x in branches] == pytest.approx([.5, .5])
    assert math.fsum(math.exp(x.log_probability) * x.belief.kl(b) for x in branches) == 0.
    assert all(len(x.belief.jobs[-1].points) == 1 for x in branches)
    # 所要の事後までKLへ入れた値はln2になる。
    assert -sum(math.exp(x.log_probability) * x.log_probability for x in branches) == pytest.approx(.6931471805599453)


@pytest.mark.parametrize("names", [("look",), ("look", "wait")])
def test_r1_positive_joint_probability_underflow_does_not_erase_forbidden_path(names):
    model = _lookahead_model(states=("s",), D=np.ones(1),
        a={a: np.array([[1.], [1e-200], [0.]]) for a in ("look", "peek", "wait")},
        durations={"look": ((1., 1.),), "peek": ((2., 1.),), "wait": ((None, 1.),)})
    h = HandHistory()
    h.boot()
    h.start("look")
    h.start("look")
    item = _table("outcome_multiset", [[[["look", "o0"], ["look", "o0"]], .5],
                                       [[["look", "o0"], ["look", "o1"]], .5]])
    r = _rig(model=model, history=h, H=NS, items=(item,))
    eta, b, T, actions, resolved = _root(r, candidates=names)
    rare, = [x for x in la.branches(eta, b, "wait", T) if all(e[-1] == "o1" for e in x.E)]
    assert rare.log_probability == pytest.approx(-921.0340371976183, abs=1e-12)
    assert math.exp(rare.log_probability) == 0. and len(rare.E) == 2
    value = la._action_value(eta, b, "wait", T, actions, resolved)
    assert value.J == math.inf and value.information == 0.
    with pytest.raises(la.NoAdmissibleCandidate):
        plan(_view(r), ("wait",), u=.5)


@pytest.mark.parametrize("preferred,J,q", [
    (False, [-.6931471805599453] * 2, [.5, .5]),
    (True, [-.4700036292457356, .916290731874155], [.8, .2]),
])
def test_r6_o0_is_evaluated_after_root_choice_even_at_zero_horizon(preferred, J, q):
    h = HandHistory()
    h.boot()
    h.start("peek")
    item = _table("started_actions", [[["look"], .8], [["wait"], .2]])
    r = _rig(history=h, H=0, items=(item,) if preferred else ())
    data = plan(_view(r, 2 * NS, 0), ("look", "wait"), u=.5).content.as_json()
    assert data["J"] == pytest.approx(J, abs=1e-12)
    assert data["q_pi"] == pytest.approx(q, abs=1e-12)
    assert data["time"]["deadline_ns"] == 2 * NS
    # O₀を受け取った値ごとに初手を選び直す道は無い。
    eta, b, T, _, _ = _root(r, now=2 * NS)
    branches = la.branches(eta, b, "look", T)
    assert len(branches) == 2 and all(x.terminal for x in branches)
    assert {x.E[0][-1] for x in branches} == {"o0", "o1"}
    assert all(x.E[0][0] == 0 for x in branches)


def test_r2_r5_result_at_deadline_creates_a_choice_and_one_more_start(monkeypatch):
    model = _lookahead_model(states=("s",), D=np.ones(1), actions=("look",),
        a={"look": np.array([[1.], [0.], [0.]])}, durations={"look": ((1., 1.),)},
        measures={"look": "report"})
    r = _rig(model=model, H=NS, items=(_table("counts", [[[1, 1], .8], [[1, 2], .2]]),))
    seen = []
    original = la.branches
    def tracked(eta, belief, action, deadline_ns):
        seen.append((eta.time_ns, eta.A))
        return original(eta, belief, action, deadline_ns)
    monkeypatch.setattr(la, "branches", tracked)
    data = plan(_view(r), ("look",), u=.5).content.as_json()
    assert data["J"] == pytest.approx([1.6094379124341003], abs=1e-15)
    assert [t for t, _ in seen] == [0, NS]
    assert len(seen[-1][1]) + 1 == 2  # floor(H/δ)+1。


@pytest.mark.parametrize("bad", [0., .0000000004])
def test_r5_positive_duration_is_checked_after_ns_rounding_for_all_actions(bad):
    model = _lookahead_model(durations={"look": ((1., 1.),), "peek": ((bad, 1.),), "wait": ((None, 1.),)})
    r = _rig(model=model)
    with pytest.raises(ValueError, match="positive in ns"):
        plan(_view(r), ("wait",), u=.5)  # 候補外のpeekも検査。


def test_r5_all_none_is_a_valid_one_node_tree_and_actions_still_have_cost():
    model = _lookahead_model(durations={a: ((None, 1.),) for a in ("look", "peek", "wait")})
    r = _rig(model=model, items=(_table("started_actions", [[["look"], .8], [["wait"], .2]]),))
    data = plan(_view(r), ("look", "wait"), u=.5).content.as_json()
    assert data["information"] == [0., 0.]
    assert data["expected_cost"] == pytest.approx([.2231435513142097, 1.6094379124341003], abs=1e-15)
    assert data["q_pi"] == pytest.approx([.8, .2], abs=1e-15)


def test_r2_terminal_wait_still_reads_pending_and_keeps_negative_o0_time():
    h = HandHistory()
    h.boot()
    h.start("peek")
    r = _rig(history=h, H=NS)
    data = plan(_view(r, 3 * NS, 0), ("wait",), u=.5).content.as_json()
    assert data["information"] == pytest.approx([.6931471805599453], abs=1e-15)
    eta, b, T, _, _ = _root(r, now=3 * NS)
    for branch in la.branches(eta, b, "wait", T):
        assert branch.E[0][0] == -NS and branch.t_end == 4 * NS
        assert branch.E[0][1] == ("pending", "peek", -3 * NS, 0)


def test_c9_pending_ranks_are_root_fixed_and_simultaneous_reports_form_one_e():
    model = _lookahead_model(durations={"look": ((NS / 1e9, .5), (None, .5)),
        "peek": ((1., 1.),), "wait": ((None, 1.),)})
    h = HandHistory()
    h.boot()
    h.start("look")
    h.start("look")
    r = _rig(model=model, history=h, H=2 * NS)
    eta, b, T, _, _ = _root(r)
    assert [j.label for j in b.jobs] == [("pending", "look", 0, 0), ("pending", "look", 0, 1)]
    branches = la.branches(eta, b, "peek", T)
    second_only = [x for x in branches if {e[1] for e in x.E if e[1][0] == "pending"} == {b.jobs[1].label}]
    assert second_only
    for branch in second_only:
        assert {e[0] for e in branch.E} == {NS}
        assert {e[1] for e in branch.E} == {("pending", "look", 0, 1), ("new", 0)}
        assert not branch.terminal and branch.t_end == NS
        next_eta = la._advance(eta, "peek", branch)
        assert len(next_eta.O) == 2
        next_branches = la.branches(next_eta, branch.belief, "peek", T)
        assert all(x.E[0][1] == ("new", 1) and x.t_end == 2 * NS for x in next_branches)
        assert all(x.belief.world is b.world for x in next_branches)
    with pytest.raises(FrozenInstanceError):
        b.jobs[0].label = ("changed",)


@pytest.mark.parametrize("gamma", [0., 1.])
def test_r4_c8_undefined_continuation_and_direct_ban_are_distinct_and_replayable(gamma):
    """lookは次節の全候補禁止、peekは終端の禁止、waitだけ選べる。"""
    model = _lookahead_model(durations={"look": ((1., 1.),), "peek": ((2., 1.),), "wait": ((None, 1.),)})
    r = _rig(model=model, H=NS, gamma=gamma,
             items=(_table("started_actions", [[["look"], .5], [["wait"], .5]]),))
    draft = plan(_view(r), model.actions, u=.5)
    data = draft.content.as_json()
    assert data["J"] == ["+inf", "+inf", .6931471805599453]
    assert data["expected_cost"] == data["J"]
    assert data["information"] == [None, 0., 0.]
    assert data["undefined_reason"] == ["no_admissible_continuation", None, None]
    assert data["q_pi"] == [0., 0., 1.] and data["chosen"] == "wait"
    prepared = r.agent.prepare(draft, clock=r.clock, ids=r.ids)
    r.agent.commit(prepared, ledger=r.ledger)
    entry = r.ledger.entries_of(prepared.decided.id)[0]
    assert prepared.decided.body.contract == DECISION
    assert replay_decision(model=model, ledger=r.ledger, decision=entry.cid) == draft
    for key, value in (("information", [0., 0., 0.]),
                       ("undefined_reason", [None, None, None]),
                       ("undefined_reason", {"look": "no_admissible_continuation"})):
        wrong = {**data, key: value}
        record = replace(prepared.decided, id=r.ids.new(K.DECISION),
                         body=replace(prepared.decided.body, content=Payload.json(wrong)))
        cid = r.ledger.append(record, entry.parents).cid
        with pytest.raises(RebuildMismatch):
            replay_decision(model=model, ledger=r.ledger, decision=cid)
    with pytest.raises(la.NoAdmissibleCandidate):
        plan(_view(r), ("look", "peek"), u=.5)


def test_c6_extending_only_horizon_does_not_extend_the_preference_table():
    item = _table("counts", [[[0, 1], 1.]])
    early = _rig(H=0, items=(item,))
    assert plan(_view(early), ("peek",), u=.5).content.as_json()["J"] == [0.]
    late = _rig(H=2 * NS, items=(item,))
    with pytest.raises(la.NoAdmissibleCandidate):
        plan(_view(late), ("peek",), u=.5)


def _path_information(joint, *, include_actions):
    px, py, projected = {}, {}, {}
    for (state, O, A), mass in joint.items():
        key = (O, A) if include_actions else O
        px[state] = px.get(state, 0.) + mass
        py[key] = py.get(key, 0.) + mass
        projected[(state, key)] = projected.get((state, key), 0.) + mass
    return math.fsum(mass * math.log(mass / (px[state] * py[key]))
                     for (state, key), mass in projected.items() if mass > 0)


def _enumerate_reference(model, history, pending, now, T, actions, ell):
    """本体を使わない状態道×所要×観測×選択の総当たり。小さい既知Aの世界用。"""
    from scipy.linalg import expm
    import json
    duration = {a: tuple((None if d is None else round(d * NS), p) for d, p in model.durations[a])
                for a in model.actions}
    A = {a: model.a[a] / model.a[a].sum(axis=0) for a in model.actions}
    starts, todo = {now}, [now]
    times = {0, *(ns for ns, _, _ in history)}
    while todo:
        start = todo.pop()
        for action in actions:
            for d, _ in duration[action]:
                if d is not None and start + d <= T:
                    end = start + d
                    times.add(start if model.measures[action] == "start" else end)
                    if end not in starts:
                        starts.add(end)
                        todo.append(end)
    for label, action, start, points in pending:
        for d, _ in points:
            if d is not None and start + d <= T:
                times.add(start if model.measures[action] == "start" else start + d)
    times = sorted(times)
    matrices = [np.eye(len(model.D)) if model.Q is None else expm(model.Q * ((b - a) / NS))
                for a, b in zip(times, times[1:])]
    prior = {}
    for states in product(range(len(model.D)), repeat=len(times)):
        weight = model.D[states[0]] * math.prod(M[states[i + 1], states[i]] for i, M in enumerate(matrices))
        weight *= math.prod(A[a][model.outcomes.index(o), states[times.index(t)]] for t, a, o in history)
        for combination in product(*(points for _, _, _, points in pending)):
            mass = weight * math.prod(p for _, p in combination)
            if mass > 0:
                prior[(states, tuple(d for d, _ in combination))] = mass
    normalizer = math.fsum(prior.values())
    prior = {key: mass / normalizer for key, mass in prior.items()}

    def marginal(post):
        result = {}
        for (states, _), mass in post.items():
            result[states] = result.get(states, 0.) + mass
        return result

    def action_value(post, t, action, O, acts):
        label = ("new", len(acts))
        acts = acts + ((t - now, label, action),)
        grouped = {}
        seen = {row[1] for row in O}
        for latent, weight in post.items():
            states, waiting = latent
            for d, pd in duration[action]:
                terminal = d is None or t + d > T
                end = T if terminal else t + d
                deliveries = [(start + point, lab, a, start) for (lab, a, start, _), point in zip(pending, waiting)
                              if lab not in seen and point is not None and start + point <= end]
                if not terminal:
                    deliveries.append((end, label, action, t))
                deliveries.sort(key=lambda row: (row[0], json.dumps(row[1], separators=(",", ":"))))
                for outcomes in product(model.outcomes, repeat=len(deliveries)):
                    E = tuple((at - now, lab, a, o) for (at, lab, a, _), o in zip(deliveries, outcomes))
                    prob = weight * pd
                    for (at, lab, a, start), outcome in zip(deliveries, outcomes):
                        measured = start if model.measures[a] == "start" else at
                        prob *= A[a][model.outcomes.index(outcome), states[times.index(measured)]]
                    if prob > 0:
                        row = grouped.setdefault((E, end, terminal), {})
                        row[latent] = row.get(latent, 0.) + prob
        original = marginal(post)
        J, joint = 0., {}
        for (E, end, terminal), row in grouped.items():
            probability = math.fsum(row.values())
            child = {key: mass / probability for key, mass in row.items()}
            state_post = marginal(child)
            information = math.fsum(p * math.log(p / original[s]) for s, p in state_post.items())
            path_O = O + E
            if terminal:
                continuation = ell(path_O, acts)
                paths = {(s, path_O, acts): p for s, p in state_post.items()}
            else:
                next_values = [action_value(child, end, a, path_O, acts) for a in actions]
                scores = [item[0] for item in next_values]
                weights = [math.exp(-(v - min(scores))) for v in scores]
                rho = [w / math.fsum(weights) for w in weights]
                continuation = math.fsum(p * value for p, (value, _) in zip(rho, next_values))
                paths = {}
                for choice, (_, entries) in zip(rho, next_values):
                    for key, mass in entries.items():
                        paths[key] = paths.get(key, 0.) + choice * mass
            J += probability * (continuation - information)
            for key, mass in paths.items():
                joint[key] = joint.get(key, 0.) + probability * mass
        return J, joint
    return [action_value(prior, now, action, (), ()) for action in actions]


@pytest.mark.parametrize("measure", ["start", "report"])
def test_r1_w2_wp2_matches_independent_state_duration_observation_action_enumeration(monkeypatch, measure):
    """過去の証拠・O₀・進行中・同時刻の結果を含むQありの本体branchesを通す。"""
    from worlds import _hand_model
    base = _hand_model(world="WP2", measure=measure)
    model = replace(base, actions=("look", "peek", "wait"),
        a={a: base.a[a] for a in ("look", "peek", "wait")},
        durations={"look": ((1., .5), (2., .5)), "peek": ((1., 1.),), "wait": ((None, 1.),)},
        measures={"look": measure, "peek": "start", "wait": "report"})
    h = HandHistory()
    h.boot()
    known = h.start("look")
    h.start("look")
    h.observe(known, "o0", .5)
    feature = lambda O, A, candidate: (A[-1][2], any(t == 2 * NS for t, _, _ in A), any(o == "o1" for *_, o in O))
    keys = list(product(model.actions, (False, True), (False, True)))
    table = {key: math.log((i + 1) / 78.) for i, key in enumerate(keys)}
    ref = ContractRef("test.path", "1")
    _register_rule(monkeypatch, ref, lambda h, args, definitions: (Feature(evaluations=frozenset({"lookahead"}), ref=ref, _project=lambda value: feature(value.O, value.A, value.candidate_outcome)), table.__getitem__))
    item = {"kind": "item", "rule": {"name": ref.name, "version": ref.version}, "args": {}}
    r = _rig(model=model, history=h, H=2 * NS, items=(item,))
    actual = plan(_view(r, NS, NS // 2), model.actions, u=.5).content.as_json()
    pending = [(("pending", "look", -NS, 0), "look", 0, ((NS, .5), (2 * NS, .5)))]
    ell = lambda O, A: -table[feature(O, A, None)]
    reference = _enumerate_reference(model, [(0 if measure == "start" else NS // 2, "look", "o0")],
                                     pending, NS, 3 * NS, model.actions, ell)
    scores = []
    for index, (J, joint) in enumerate(reference):
        expected_cost = math.fsum(p * ell(O, A) for (_, O, A), p in joint.items())
        info = _path_information(joint, include_actions=True)
        assert math.fsum(joint.values()) == pytest.approx(1., abs=1e-12)
        assert J == pytest.approx(expected_cost - info, abs=1e-12)
        assert _path_information(joint, include_actions=False) == pytest.approx(info, abs=1e-12)
        assert actual["J"][index] == pytest.approx(J, abs=1e-12)
        assert actual["expected_cost"][index] == pytest.approx(expected_cost, abs=1e-12)
        assert actual["information"][index] == pytest.approx(info, abs=1e-12)
        scores.append(J)
    weights = np.exp(-(np.array(scores) - min(scores)))
    np.testing.assert_allclose(actual["q_pi"], weights / weights.sum(), atol=1e-12, rtol=0)
    eta, b, T, _, _ = _root(r, now=NS, observed=NS // 2)
    roots = la.branches(eta, b, "peek", T)
    assert any(len(x.E) == 2 and x.E[0][0] == 0 for x in roots)  # O₀。
    assert any(len(x.E) == 2 and x.E[0][0] == x.E[1][0] == NS for x in roots)
    assert all(x.t_end == 2 * NS and not x.terminal for x in roots)
    assert logsumexp([x.log_probability for x in roots]) == pytest.approx(0., abs=1e-12)
    np.testing.assert_allclose(sum(math.exp(x.log_probability) * np.exp(x.belief.log_x) for x in roots),
                               np.exp(b.log_x), atol=1e-12, rtol=0)
    prepared = r.agent.prepare(plan(_view(r, NS, NS // 2), model.actions, u=.5), clock=r.clock, ids=r.ids)
    r.agent.commit(prepared, ledger=r.ledger)
    cid = r.ledger.entries_of(prepared.decided.id)[0].cid
    assert replay_decision(model=model, ledger=r.ledger, decision=cid).content == prepared.decided.body.content


@pytest.mark.parametrize("preferred", [False, True])
def test_r2_choices_use_local_softmax_mean_not_soft_minimum_or_whole_tree(monkeypatch, preferred):
    """Aは終端1本、Bは次節2本。費用0なら初手は1/2ずつ、1/3と2/3ではない。"""
    b = SimpleNamespace(kl=lambda parent: 0.)
    def next_branches(eta, belief, action, deadline_ns):
        continuation = not eta.A and action == "peek"
        E = ((NS, ("new", 0), "peek", "o0"),) if continuation else ()
        return (la.Branch(E, 0., b, NS if continuation else deadline_ns, not continuation),)
    monkeypatch.setattr(la, "branches", next_branches)
    item = _table("started_actions", [[["look"], .5], [["peek", "look"], .4], [["peek", "peek"], .1]])
    r = _rig(H=2 * NS, items=(item,) if preferred else ())
    eta, _, T, _, resolved = _root(r)
    values = [la._action_value(eta, b, a, T, ("look", "peek"), resolved) for a in ("look", "peek")]
    if preferred:
        child_mean = .8 * -math.log(.4) + .2 * -math.log(.1)
        assert [v.J for v in values] == pytest.approx([math.log(2), child_mean], abs=1e-15)
        assert values[1].J != pytest.approx(-math.log(.4 + .1), abs=1e-12)
        expected = [1 / (1 + math.exp(math.log(2) - child_mean)),
                    1 / (1 + math.exp(child_mean - math.log(2)))]
    else:
        assert [v.J for v in values] == [0., 0.]
        expected = [.5, .5]
    assert la._policy([v.J for v in values], 1.) == pytest.approx(expected, abs=1e-15)


class _FiniteBelief:
    def __init__(self, probabilities):
        self.p = tuple(probabilities)

    def kl(self, parent):
        return math.fsum(p * math.log(p / q) for p, q in zip(self.p, parent.p) if p > 0)


@pytest.mark.parametrize("seed", [4, 9, 27])
def test_r1_r2_abstract_tree_arbitrary_policy_matches_oa_but_o_can_differ(monkeypatch, seed):
    """S4dの範囲外の状態依存未着。最後の行動を落とす誤りも独立の全路で識別。"""
    import random
    first = random.Random(seed).uniform(.1, .9)
    rho = (first, 1 - first)
    monkeypatch.setattr(la, "_policy", lambda values, gamma: np.array(rho))
    def next_branches(eta, b, action, deadline_ns):
        if not eta.A:
            return (la.Branch(((NS, ("new", 0), action, "root"),), 0., b, NS, False),)
        probability = (.9, .1) if action == "look" else (.1, .9)
        result = []
        for arrives in (False, True):
            joint = [p * (v if arrives else 1 - v) for p, v in zip(b.p, probability)]
            q = math.fsum(joint)
            E = ((2 * NS, ("signal",), action, "ok"),) if arrives else ()
            result.append(la.Branch(E, math.log(q), _FiniteBelief([x / q for x in joint]), 2 * NS, True))
        return tuple(result)
    monkeypatch.setattr(la, "branches", next_branches)
    ref = ContractRef("test.last", "1")
    _register_rule(monkeypatch, ref, lambda h, args, definitions: (Feature(evaluations=frozenset({"lookahead"}), ref=ref, _project=lambda value: value.A[-1][2]),
                                                  lambda a: math.log(.8 if a == "look" else .2)))
    r = _rig(H=2 * NS, items=({"kind": "item", "rule": {"name": ref.name, "version": "1"}, "args": {}},))
    eta, _, T, _, resolved = _root(r)
    value = la._action_value(eta, _FiniteBelief((.5, .5)), "look", T, ("look", "peek"), resolved)
    joint = {}
    for state, (choice, action), arrives in product(range(2), zip(rho, ("look", "peek")), (False, True)):
        p = ((.9, .1) if action == "look" else (.1, .9))[state]
        weight = .5 * choice * (p if arrives else 1 - p)
        O = ((NS, ("new", 0), "look", "root"),)
        if arrives:
            O += ((2 * NS, ("signal",), action, "ok"),)
        A = ((0, ("new", 0), "look"), (NS, ("new", 1), action))
        joint[(state, O, A)] = weight
    cost = first * -math.log(.8) + (1 - first) * -math.log(.2)
    info = _path_information(joint, include_actions=True)
    assert value.J == pytest.approx(cost - info, abs=1e-12)
    assert value.expected_cost == pytest.approx(cost, abs=1e-12)
    assert value.information == pytest.approx(info, abs=1e-12)
    assert _path_information(joint, include_actions=False) < info - .01


def test_r1_l1_l2_independent_full_paths_match_fixed_values(monkeypatch):
    for items in ((), (_count_rule(monkeypatch),)):
        r = _rig(items=items)
        preferred = bool(items)
        ell = (lambda O, A: -math.log((.2, .3, .5)[min(sum(o == "o1" for *_, o in O), 2)])) if preferred else (lambda O, A: 0.)
        rows = _enumerate_reference(r.model, [], [], 0, 4 * NS, r.model.actions, ell)
        fixed = [.8896351075783104, .5668701865644227, 1.6094379124341003] if preferred else [-.4083188371797285, -.6931471805599453, 0.]
        actual = plan(_view(r), r.model.actions, u=.5).content.as_json()
        for index, (J, joint) in enumerate(rows):
            cost = math.fsum(p * ell(O, A) for (_, O, A), p in joint.items())
            for include_actions in (False, True):
                direct = cost - _path_information(joint, include_actions=include_actions)
                assert direct == pytest.approx(fixed[index], abs=1e-12)
                assert direct == pytest.approx(J, abs=1e-12)
                assert actual["J"][index] == pytest.approx(direct, abs=1e-12)


def test_c6_root_rule_experience_candidates_and_world_are_fixed(monkeypatch):
    """未来の想像で好みを解き直さず、候補外のpeekやモデルのC・γを使わない。"""
    ref, calls = ContractRef("test.frozen", "1"), []
    def rule(h, args, definitions):
        calls.append(tuple(h.reading.n["look"]))
        return definitions[("rule", "by_experience", "1")](h, args, definitions)
    _register_rule(monkeypatch, ref, rule)
    item = {"kind": "item", "rule": {"name": ref.name, "version": "1"}, "args": {
        "feature": {"name": "constant", "version": "1"},
        "experience": {"name": "observed_count", "version": "1", "action": "look", "outcome": "o0"},
        "cap": 1, "tables": {"0": {"probs": [[None, .8], ["unused", .2]]},
                              "1": {"probs": [[None, .2], ["unused", .8]]}}}}
    r = _rig(H=3 * NS, items=(item,))
    class Guard:
        def __getattr__(self, name):
            if name in ("log_C", "gamma"):
                raise AssertionError("model preference was read")
            return getattr(r.model, name)
    observed, original = [], la.branches
    def tracked(eta, b, action, T):
        observed.append((action, T, b.world))
        return original(eta, b, action, T)
    monkeypatch.setattr(la, "branches", tracked)
    data = plan(replace(_view(r), model=Guard()), ("look", "wait"), u=.5).content.as_json()
    assert calls == [(0, 0, 0)]
    assert data["expected_cost"] == pytest.approx([.2231435513142097] * 2, abs=1e-12)
    assert {a for a, _, _ in observed} == {"look", "wait"}
    assert {T for _, T, _ in observed} == {3 * NS}
    assert all(world is observed[0][2] for _, _, world in observed)


def test_r3_one_level_window_includes_the_other_hands_possible_report():
    model = _lookahead_model(outcomes=("o0", "o1"), actions=("look", "wait"), log_C=np.log([.5, .5]),
        a={"look": np.eye(2), "wait": np.ones((2, 2))},
        durations={"look": ((2., .5), (None, .5)), "wait": ((4., 1.),)},
        measures={"look": "report", "wait": "report"})
    h = HandHistory()
    h.boot()
    h.start("look")
    item = _table("outcome_multiset", [[[], 1 / 3], [[["look", "o0"]], 1 / 3], [[["look", "o1"]], 1 / 3]])
    r = _rig(model=model, history=h, H=3 * NS, items=(item,))
    result = plan(_view(r), ("wait",), u=.5).content.as_json()
    assert result["J"] == pytest.approx([.7520386983881371], abs=1e-12)
    assert result["expected_cost"] == pytest.approx([1.0986122886681098], abs=1e-12)
    assert result["information"] == pytest.approx([.34657359027997264], abs=1e-12)


def test_r3_s4c_difference_is_the_pending_information_not_a_dropped_constant(monkeypatch):
    from sui.agent import plan_s4c
    model = _lookahead_model(outcomes=("o0", "o1"), actions=("peek",),
        log_C=np.log([.5, .5]), a={"peek": np.eye(2)},
        durations={"peek": ((2., 1.),)}, measures={"peek": "report"})
    h = HandHistory()
    h.boot()
    h.start("peek")
    ref = ContractRef("test.first_outcome", "1")
    project = lambda O, A, candidate: next(o for _, label, _, o in O if label == ("new", 0))
    _register_rule(monkeypatch, ref, lambda h, args, definitions: (Feature(evaluations=frozenset({"lookahead"}), ref=ref, _project=lambda value: project(value.O, value.A, value.candidate_outcome)),
                                                  lambda o: -.6931471805599453))
    item = {"kind": "item", "rule": {"name": ref.name, "version": "1"}, "args": {}}
    r = _rig(model=model, history=h, H=2 * NS, items=(item,))
    old = plan_s4c(_view(r), ("peek",), u=.5).content.as_json()
    new = plan(_view(r), ("peek",), u=.5).content.as_json()
    assert old["G"] == pytest.approx([.6931471805599453], abs=1e-12)
    assert new["J"] == pytest.approx([0.], abs=1e-12)
    assert np.array(old["G"]) - new["J"] == pytest.approx([.6931471805599453], abs=1e-12)


def test_r2_o0_is_not_exposed_to_the_first_action_choice(monkeypatch):
    """初手で当てる好み。O₀を先渡しすれば常に当たりにできるが、実際は1/2。"""
    h = HandHistory()
    h.boot()
    h.start("peek")
    ref = ContractRef("test.guess", "1")
    def project(O, A, candidate):
        bit = next(o for _, label, _, o in O if label[0] == "pending")
        return (A[0][2] == "look") == (bit == "o0")
    _register_rule(monkeypatch, ref, lambda h, args, definitions: (Feature(evaluations=frozenset({"lookahead"}), ref=ref, _project=lambda value: project(value.O, value.A, value.candidate_outcome)),
                                                  lambda correct: math.log(.8 if correct else .2)))
    r = _rig(history=h, H=0, items=({"kind": "item", "rule": {"name": ref.name, "version": "1"}, "args": {}},))
    data = plan(_view(r, 2 * NS, 0), ("look", "wait"), u=.5).content.as_json()
    assert data["expected_cost"] == pytest.approx([.916290731874155] * 2, abs=1e-12)
    assert data["J"] == pytest.approx([.2231435513142097] * 2, abs=1e-12)
    assert data["q_pi"] == [.5, .5]


def test_r5_bound_holds_for_every_path_and_pending_does_not_create_extra_choices(monkeypatch):
    h = HandHistory()
    h.boot()
    h.start("look")
    h.start("peek")
    r = _rig(history=h, H=4 * NS)
    choices, original = [], la.branches
    def tracked(eta, belief, action, T):
        choices.append(eta)
        return original(eta, belief, action, T)
    monkeypatch.setattr(la, "branches", tracked)
    plan(_view(r), r.model.actions, u=.5)
    assert max(len(eta.A) + 1 for eta in choices) == 5
    for eta in choices:
        if not eta.root:
            label = ("new", len(eta.A) - 1)
            assert any(t == eta.time_ns and lab == label for t, lab, _, _ in eta.O)
        assert all(0 <= t <= 4 * NS for t, _, _ in eta.A)


def test_c9_previous_run_boundary_and_queued_start_use_the_root_conventions():
    old = HandHistory(run="old", wall=100)
    old.boot()
    pending = old.start("peek")
    recent = HandHistory(run="new", index=1, wall=103)
    recent.boot()
    recent.records = old.records + recent.records
    r = _rig(history=recent, H=0)
    now = r.agent.view().reading.timeline.to_axis(recent.clock.run, 0)
    assert now == 3 * NS
    data = plan(_view(r, now, now), ("wait",), u=.5).content.as_json()
    assert data["time"]["earlier_run_pending"] == [str(pending.body.job)]
    assert data["information"] == pytest.approx([.6931471805599453], abs=1e-12)
    # 順番待ちは根のnowを開始とする。過去のJobOpenedの時刻から数えない。
    queued = HandHistory()
    queued.boot()
    attempt = queued.start("peek")
    queued.records.remove(attempt)
    r = _rig(history=queued, H=2 * NS)
    eta, b, T, _, _ = _root(r, now=NS, observed=NS)
    assert b.jobs[0].label == ("pending", "peek", 0, 0) and b.jobs[0].start_ns == NS
    branches = la.branches(eta, b, "wait", T)
    assert all(x.E[0][0] == 2 * NS for x in branches)


def test_k1_k5_synchronous_loop_uses_adopted_lookahead_and_replays():
    from sui.loop import run_step
    from worlds import ScriptedWorld
    r = _rig()
    world = ScriptedWorld({"peek": ["o0"]})
    step = run_step(r.agent, world, r.model.actions, u=.5, clock=r.clock, ids=r.ids, ledger=r.ledger,
                    membrane=Producer(component="test.hand", code_version="1"))
    assert world.calls == ["peek"]
    assert step.decided.body.content.as_json()["evaluation"] == "lookahead"
    cid = r.ledger.entries_of(step.decided.id)[0].cid
    assert replay_decision(model=r.model, ledger=r.ledger, decision=cid).content == step.decided.body.content


def test_k2_window_keeps_the_old_lookahead_style_after_new_preferences_arrive():
    from sui.runtime import Window, Tick, Reconsider, Think, Thought
    from worlds import ManualHost, ScriptDrive, GatedHand
    r = _rig()
    drive = ScriptDrive(lambda status, event: [Reconsider(candidates=r.model.actions, u=.5)]
                        if isinstance(event, Tick) else [])
    host = ManualHost(lambda pledges: Window(agent=r.agent, ledger=r.ledger, clock=r.clock, ids=r.ids,
        hand=GatedHand({a: set() for a in r.model.actions}, {}), route="test", drive=drive,
        membrane=Producer(component="test.hand", code_version="1"), capacity={"think": 1}, pledges=pledges),
        clock=r.clock)
    host.advance(0)
    host.step()
    work = next(work for work, _ in host.work if isinstance(work, Think))
    old = plan(work.view, work.candidates, u=work.u)
    paper = Record(id=r.ids.new(K.PREFERENCE), at=r.clock.now(), writer=Role.MODEL,
        producer=r.agent.producer, body=Preference(basis=(), contract=PREFERENCE,
            content=Payload.json({"kind": "style", "H_ns": 0, "gamma": 0.})))
    r.ledger.append(paper, r.ledger.heads())
    r.agent.adopt(r.ledger, clock=r.clock, ids=r.ids)
    event = host.finish(work)
    assert isinstance(event, Thought) and event.draft == old
    host.step()
    from sui.records import Decided
    entries = [e for e in r.ledger.entries() if e.body_type is Decided]
    entry, = entries
    decided = r.ledger.record(entry.cid)
    assert decided.body.content.as_json()["H_ns"] == 4 * NS
    assert paper.id not in decided.body.inputs and entry.parents == work.view.frontier
    assert replay_decision(model=r.model, ledger=r.ledger, decision=entry.cid).content == old.content


def test_c6_two_items_sum_over_full_paths_without_replacing_root_preference(monkeypatch):
    first = _count_rule(monkeypatch)
    constant = _table("constant", [[None, .25], ["unused", .75]])
    r = _rig(items=(first, constant))
    data = plan(_view(r), r.model.actions, u=.5).content.as_json()
    ell = lambda O, A: -math.log((.2, .3, .5)[min(sum(o == "o1" for *_, o in O), 2)]) - math.log(.25)
    reference = _enumerate_reference(r.model, [], [], 0, 4 * NS, r.model.actions, ell)
    for i, (J, joint) in enumerate(reference):
        cost = math.fsum(p * ell(O, A) for (_, O, A), p in joint.items())
        assert data["J"][i] == pytest.approx(J, abs=1e-12)
        assert data["expected_cost"][i] == pytest.approx(cost, abs=1e-12)
    assert data["q_pi"] == pytest.approx([.3487006970483583, .48153497860862265, .16976432434301916], abs=1e-12)


def test_c9_feature_projection_does_not_merge_report_identity_or_duration_posterior():
    h = HandHistory()
    h.boot()
    h.start("look")
    h.start("look")
    model = _lookahead_model(durations={"look": ((1., .5), (None, .5)),
        "peek": ((2., 1.),), "wait": ((None, 1.),)})
    r = _rig(model=model, history=h, H=NS)
    eta, b, T, _, _ = _root(r)
    rows = [branch for branch in la.branches(eta, b, "wait", T)
            if len(branch.E) == 1 and branch.E[0][-1] == "o0"]
    left, right = sorted(rows, key=lambda branch: branch.E[0][1])
    feature = preference_module.BUILTINS[("feature", "outcome_multiset", "1")]
    assert feature(EvaluationInput(evaluation="lookahead", O=left.E)) == feature(EvaluationInput(evaluation="lookahead", O=right.E)) == [["look", "o0"]]
    assert left.E != right.E
    assert _points(left.belief.jobs[0]) == {NS: 1.} and _points(left.belief.jobs[1]) == {None: 1.}
    assert _points(right.belief.jobs[0]) == {None: 1.} and _points(right.belief.jobs[1]) == {NS: 1.}
    timed = preference_module.BUILTINS[("feature", "timed_path", "1")]
    assert timed(EvaluationInput(evaluation="lookahead", O=left.E)) != timed(EvaluationInput(evaluation="lookahead", O=right.E))


def test_k3_no_admissible_lookahead_returns_error_through_the_window_without_a_decision():
    from sui.runtime import Window, Tick, Reconsider, Think, Thought
    from sui.records import Decided
    from worlds import ManualHost, ScriptDrive, GatedHand
    r = _rig(items=(_table("started_actions", [[["never"], 1.]]),))
    drive = ScriptDrive(lambda status, event: [Reconsider(candidates=r.model.actions, u=.5)]
                        if isinstance(event, Tick) else [])
    host = ManualHost(lambda pledges: Window(agent=r.agent, ledger=r.ledger, clock=r.clock, ids=r.ids,
        hand=GatedHand({a: set() for a in r.model.actions}, {}), route="test", drive=drive,
        membrane=Producer(component="test.hand", code_version="1"), capacity={"think": 1}, pledges=pledges),
        clock=r.clock)
    host.advance(0)
    host.step()
    work = next(work for work, _ in host.work if isinstance(work, Think))
    event = host.finish(work)
    assert isinstance(event, Thought) and event.error == "NoAdmissibleCandidate" and event.draft is None
    host.step()
    assert host.window.status().thinking == 0
    assert not any(e.body_type is Decided for e in r.ledger.entries())
    assert any(isinstance(e, Thought) and e.error == "NoAdmissibleCandidate" for _, e in drive.calls)
