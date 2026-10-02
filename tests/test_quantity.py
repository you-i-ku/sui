"""S4b-1b。独立のDirichletモーメントと仕様書の定規。固定値台本は読まない。"""

from fractions import Fraction as F
from itertools import permutations, product
import json
import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from sui.model import GenerativeModel, model_from_json, model_json, model_ref
from sui.quantity import BaseSpec, DurationPrior, ExactEvidence, exact_posterior, read_timing
from sui.quantity import (Timing, TimingEvent, AttemptTiming, HistoryKernel, ClockMeasure, QuantityMeasure,
    MeasureCandidate, MeasurePrior, atoms_posterior, isolated_record_likelihood,
    restricted_growth_strings, AtomLikelihood, PolynomialPiece, PolynomialLikelihood, MultiplicityMoments,
    _kernel_moment, _polytope_integral)
from sui.quantity import (PowerFactor, PowerTerm, IntegrationPiece, IntegralEstimate, LinearIntegral, TailDensity,
    integrate_pieces, integrate_linear, partition_evidence, sum_integrals, condition_probability,
    IntegrationIncomplete, _linear_pieces, _eliminate_separable_interval, _eliminate_density_halfline,
    _axis_log_m, _MappedTerm, _bisect_box)
from sui.values import ValueBelief, ValueSpace, MeasureSpec, InformationBounds
from sui.quantity import (SimplexPolynomial, AtomicPolynomialMeasure, AtomicRecordLaw,
                          PhiSeries, EntropyTailBounds, _log_phi_fraction)
from sui.quantity import RecordTailBound, KernelEvent, ReplicaProduct, ReplicaMoments
from sui.quantity import GeneralRecordLaw, ConjunctionEvent
from sui.quantity import (posterior, QuantityQuery, FutureRecordsQuery, timing_context,
                          RecordEvent, UnionEvent, one_step_values)
from sui.quantity import _bounded_phi_quadrature


def _prior(beta=(1, 1, 1), points=(1, 2, None)):
    return DurationPrior(float(sum(beta)), BaseSpec("atoms", "1", {
        "points": [[point, float(F(mass, sum(beta)))] for point, mass in zip(points, beta)]}))


def _quantity_model(**changes):
    values = dict(states=("s",), outcomes=("x", "y"), actions=("a", "b"),
        a={"a": np.array([[1.], [1.]]), "b": np.array([[1.], [1.]])},
        learnable=frozenset({"a"}), D=np.array([1.]), log_C=np.log(np.array([.5, .5])), gamma=1.,
        duration_priors={a: _prior(points=(1, 3, None)) for a in ("a", "b")},
        measure={"share": "all_actions", "candidates": [
            {"name": "tick", "version": "1", "params": {
                "width_ns": 4, "phase": "uniform", "check": "uniform_in_tick"}, "weight": 1.}]})
    values.update(changes)
    return GenerativeModel(**values)


def _rising(x, n):
    result = F(1)
    for k in range(n):
        result *= x + k
    return result


def _brute(beta, points, evidence):
    """Polya逐次更新を使わず、Dirichletの単項式の積分を全割り振りで足す。"""
    raw = {}
    for allocation in product(range(len(beta)), repeat=len(evidence)):
        valid = True
        for item, index in zip(evidence, allocation):
            value = points[index]
            valid &= not item.complete or value == item.value
            valid &= value is None or all(value > lower if strict else value >= lower
                                         for lower, strict in item.checks)
        if not valid:
            continue
        counts = tuple(allocation.count(i) for i in range(len(beta)))
        numerator = math.prod(_rising(F(b), n) for b, n in zip(beta, counts))
        raw[counts, allocation] = numerator / _rising(F(sum(beta)), len(evidence))
    normalizer = sum(raw.values(), F(0))
    return normalizer, {key: value / normalizer for key, value in raw.items()}


_HISTORIES = tuple(product(range(5), repeat=3))


@pytest.mark.parametrize("beta", [(1, 1, 1), (2, 3, 1), (1, 2, 3)])
def test_d1_direct_dirichlet_moments_all_allocations(beta):
    options = [(((2, False),), False, None), (((2, True),), False, None),
               ((), True, 1), ((), True, 2), ((), False, None)]
    for choices in _HISTORIES:
        evidence = tuple(ExactEvidence(str(i), *options[k]) for i, k in enumerate(choices))
        normalizer, expected = _brute(beta, (1, 2, None), evidence)
        actual = exact_posterior(_prior(beta), evidence)
        assert math.exp(actual.log_evidence) == pytest.approx(float(normalizer), abs=1e-12)
        assert set(actual.log_w) == set(expected)
        for key, probability in expected.items():
            assert math.exp(actual.log_w[key]) == pytest.approx(float(probability), abs=1e-12)


def _specified_history():
    # v0.12の指定例の入力は元のCodexレビュー1通目でも確認 (台本は非参照)。
    return (ExactEvidence("d1", (), True, 1),
            ExactEvidence("d2", ((1, True),), False, None),
            ExactEvidence("d3", ((0, True),), False, None))


def test_d1_fixed_evidence_five_count_groups_and_prediction():
    actual = exact_posterior(_prior(), _specified_history())
    groups = {}
    for (counts, _), weight in actual.log_w.items():
        groups.setdefault(counts, []).append(math.exp(weight))
    assert math.exp(actual.log_evidence) == pytest.approx(1/6, abs=1e-12)
    assert len(groups) == 5
    assert [math.fsum(v) for v in groups.values()] == pytest.approx([1/5] * 5, abs=1e-12)
    assert [math.exp(v) for v in actual.predictive().values()] == pytest.approx([2/5, 3/10, 3/10])


def test_d2_right_censor_product_formula():
    actual = exact_posterior(_prior(), (ExactEvidence("p", ((1, True),), False, None),))
    assert math.fsum(math.exp(actual.joint_new((v,))) for v in (2, None)) == pytest.approx(3/4)
    assert math.fsum(math.exp(actual.joint_new(values))
                     for values in product((2, None), repeat=3)) == pytest.approx(F(3*4*5, 4*5*6))


def test_d3_completion_reweights_existing_censor_components():
    actual = exact_posterior(_prior(), (ExactEvidence("p", ((1, True),), False, None),
                                      ExactEvidence("new", (), True, 2)))
    assert [math.exp(v) for v in actual.predictive().values()] == pytest.approx([1/5, 8/15, 4/15])
    assert math.exp(actual.allocated({"p": 2})) == pytest.approx(2/3)


def test_d4_rechecks_are_one_latent_sample_and_duplicate_rows_refuse():
    once = exact_posterior(_prior(), (ExactEvidence("p", ((2, False),), False, None),))
    twice = exact_posterior(_prior(), (ExactEvidence("p", ((2, False), (2, False)), False, None),))
    assert once.log_w == twice.log_w
    assert [math.exp(v) for v in twice.predictive().values()] == pytest.approx([1/4, 3/8, 3/8])
    with pytest.raises(ValueError, match="duplicate attempt"):
        exact_posterior(_prior(), (twice.evidence[0], twice.evidence[0]))


def test_d5_unknown_ten_observations_leave_prior_moments_unchanged():
    prior = _prior((1, 1), (1, 2))
    result = exact_posterior(prior, tuple(ExactEvidence(str(i), (), False, None) for i in range(10)))
    assert math.exp(result.joint_new((1, 1))) == pytest.approx(1/3)
    assert math.exp(result.log_evidence) == pytest.approx(1.)
    limited = exact_posterior(_prior(), (ExactEvidence("lost", ((2, False),), False, None),))
    assert [math.exp(v) for v in limited.predictive().values()] == pytest.approx([1/4, 3/8, 3/8])


def test_d6_existing_pending_pair_is_not_two_new_samples():
    result = exact_posterior(_prior(), _specified_history())
    assert math.exp(result.allocated({"d2": None, "d3": None})) == pytest.approx(1/5)
    assert math.exp(result.joint_new((None, None))) == pytest.approx(2/15)
    assert math.exp(result.allocated({"d2": None})) == pytest.approx(1/2)
    assert math.exp(result.allocated({"d3": None})) == pytest.approx(3/10)


def test_d7_root_boundary_allows_completion_at_check():
    result = exact_posterior(_prior(), (ExactEvidence("p", ((2, False),), True, 2),))
    assert math.exp(result.log_evidence) == pytest.approx(1/3)
    assert [math.exp(v) for v in result.predictive().values()] == pytest.approx([1/4, 1/2, 1/4])


def test_o3_separate_polya_blocks_can_draw_same_infinite_atom():
    result = exact_posterior(_prior((1, 1), (1, None)), ())
    assert math.exp(result.joint_new((None, None))) == pytest.approx(1/3)


def test_u9_tiny_positive_mass_stays_in_log_space():
    prior = DurationPrior(1e-100, BaseSpec("atoms", "1", {"points": [[1, 1.], [None, 1e-300]]}))
    result = exact_posterior(prior, ())
    assert result.predictive()[None] == pytest.approx(math.log(1e-300))
    condition = exact_posterior(prior, (ExactEvidence("p", ((2, False),), False, None),))
    assert math.isfinite(condition.log_evidence)
    assert math.exp(condition.allocated({"p": None})) == 1.


def test_u1_exact_entropy_formula_and_protocol():
    result = exact_posterior(_prior((1, 1), (1, 2)), ())
    assert isinstance(result, ValueBelief)
    bounds = result.information("distribution", "new_value", None)
    assert bounds.lower == pytest.approx(math.log(2) - 1/2, abs=1e-12)
    assert bounds.lower == bounds.upper


def test_y1_model6_roundtrip_and_immutable_model_owned_params():
    candidate = {"share": "all_actions", "candidates": [{"name": "tick", "version": "1", "weight": 1.,
        "params": {"width_ns": 4, "phase": {"point_ns": 2}, "check": "uniform_in_tick"}}]}
    model = _quantity_model(measure=candidate)
    before = model_json(model)
    assert json.loads(before)["scheme"] == "sui.model.6"
    candidate["candidates"][0]["params"]["phase"]["point_ns"] = 0
    assert model_json(model) == before
    assert model_json(model_from_json(before)) == before
    assert model_ref(model_from_json(before)) == model_ref(model)
    with pytest.raises(TypeError):
        model.measure.candidates[0].spec.params["phase"]["point_ns"] = 0
    with pytest.raises(TypeError):
        model.duration_priors["a"] = model.duration_priors["b"]


@pytest.mark.parametrize("golden", ["golden_s4b1b.json", "golden_s4b1a.json"])
def test_y1_saved_old_model_bytes_and_references(golden):
    scenes = json.loads((Path(__file__).with_name(golden)).read_text(encoding="utf-8"))
    for scene in scenes.values():
        data = scene["model_json"]
        model = model_from_json(data["body"].encode("utf-8"))
        assert model_json(model) == data["body"].encode("utf-8")
        assert model_ref(model) == "sha256:" + data["sha256"]


@pytest.mark.parametrize("change", [
    {"durations": {"a": ((1., 1.),), "b": ((1., 1.),)}, "measures": {"a": "report", "b": "report"}},
    {"states": ("s", "t"), "D": np.array([.5, .5]), "Q": np.array([[-1., 1.], [1., -1.]]),
     "a": {"a": np.ones((2, 2)), "b": np.ones((2, 2))}},
    {"duration_priors": {}}, {"measure": None},
    {"duration_priors": {"a": _prior()}},
])
def test_y2_model6_incompatible_fields_refuse(change):
    with pytest.raises(ValueError):
        _quantity_model(**change)


@pytest.mark.parametrize("params", [
    {"width_ns": 0, "phase": "uniform", "check": "uniform_in_tick"},
    {"width_ns": True, "phase": "uniform", "check": "uniform_in_tick"},
    {"width_ns": 4, "phase": {"point_ns": 4}, "check": "uniform_in_tick"},
    {"width_ns": 4, "phase": {"point_ns": .5}, "check": "uniform_in_tick"},
    {"width_ns": 4, "phase": "uniform"},
    {"width_ns": 4, "phase": "uniform", "check": "invented"},
])
def test_y2_y10_measure_requires_explicit_supported_params(params):
    with pytest.raises(ValueError):
        _quantity_model(measure={"share": "all_actions", "candidates": [
            {"name": "tick", "version": "1", "params": params, "weight": 1.}]})


@pytest.mark.parametrize("base", [
    {"name": "other", "version": "1", "params": {}},
    {"name": "atoms", "version": "2", "params": {"points": [[1, 1.]]}},
    {"name": "atoms", "version": "1", "params": {"points": [[-1, 1.]]}},
    {"name": "atoms", "version": "1", "params": {"points": [[1, .5], [1, .5]]}},
    {"name": "atoms", "version": "1", "params": {"points": [[1, -1.], [None, 2.]]}},
    {"name": "atoms", "version": "1", "params": {"points": [[1, .9]]}},
])
def test_y2_base_rejects_unsupported_and_invalid_inputs(base):
    with pytest.raises(ValueError):
        _quantity_model(duration_priors={a: {"alpha": 2., "base": base} for a in ("a", "b")})


def _piecewise():
    return {"name": "piecewise", "version": "1", "params": {
        "edges_ns": [0, 4], "masses": [.5],
        "tail": {"kind": "pareto", "kappa": 2/3, "mass": .4}, "p_inf": .1}}


def test_u8_model_rejects_exact_times_continuous_base():
    priors = {a: {"alpha": 1., "base": _piecewise()} for a in ("a", "b")}
    tick = _quantity_model(duration_priors=priors)
    assert model_json(model_from_json(model_json(tick))) == model_json(tick)
    with pytest.raises(ValueError, match="infinite information"):
        _quantity_model(duration_priors=priors, measure={"share": "all_actions", "candidates": [
            {"name": "exact", "version": "1", "params": {}, "weight": 1.}]})


@pytest.mark.parametrize("mutate", [
    lambda d: d.update(scheme="sui.model.5"),
    lambda d: d["duration_priors"]["a"]["base"]["params"]["points"].reverse(),
    lambda d: d["measure"]["candidates"][0].update(weight=1),
    lambda d: d.pop("measure"),
    lambda d: d.update(extra=True),
])
def test_y1_model6_noncanonical_inputs_refuse(mutate):
    data = json.loads(model_json(_quantity_model()))
    mutate(data)
    with pytest.raises(ValueError):
        model_from_json(json.dumps(data, sort_keys=True, separators=(",", ":")).encode())


def test_y7_common_types_own_params_and_adapters_have_protocol():
    from sui.names import NameBelief
    candidate = MeasureSpec("custom", "2", {"nested": [1, {"x": 2}]})
    assert candidate.as_json()["params"] == {"nested": [1, {"x": 2}]}
    with pytest.raises(TypeError):
        candidate.params["nested"][1]["x"] = 0
    assert isinstance(NameBelief(_quantity_model(), SimpleNamespace()), ValueBelief)
    assert isinstance(exact_posterior(_prior(), ()), ValueBelief)
    assert ValueSpace("quantity", "1") != ValueSpace("name", "1")
    assert InformationBounds(.1, .3).midpoint == pytest.approx(.2)


def test_y7_name_adapter_values_match_existing_static_computations():
    from sui.agent import read, _derive, _one_step_components
    from sui.inference import _s4d_log_belief, _s4d_likelihood, _log_A
    from sui.names import NameBelief, NameQuery
    from scipy.special import logsumexp
    model = _quantity_model(duration_priors={}, measure=None)
    reading = read(model, ())
    adapter = NameBelief(model, reading)
    q, a = _derive(model, reading.n)
    logs = _s4d_log_belief(model.D, [_s4d_likelihood(model.a[action], reading.n[action],
        learnable=action in model.learnable) for action in model.actions])
    for action in model.actions:
        np.testing.assert_allclose(adapter.predictive(NameQuery(action, 0)),
            logsumexp(_log_A(a[action]) + logs[None, :], axis=1), atol=1e-12, rtol=0)
        _, expected = _one_step_components(logs, a[action], action in model.learnable,
                                       np.array([0., 0.]))
        assert adapter.information("state_and_parameters", NameQuery(action, 0), ()).lower == pytest.approx(expected)


def _tick(width, phase):
    return MeasureSpec("tick", "1", {"width_ns": width, "phase": phase, "check": "uniform_in_tick"})


def _measure(*weighted_specs):
    return MeasurePrior("all_actions", tuple(MeasureCandidate(spec, weight) for spec, weight in weighted_specs))


def _history(events, attempts):
    """入力の名札と順を保つ膜の読み。数値はこの試験のfixtureにだけ置く。"""
    return Timing({ref: TimingEvent(ref, "run", 0, seq, reading, kind, attempt)
                   for seq, (ref, reading, kind, attempt) in enumerate(events)}, tuple(attempts))


def _checked_history(count, *, complete=False):
    events = [("s", 0, "start", "a")]
    events += [(f"c{i}", 0, "external", None) for i in range(count)]
    if complete:
        events.append(("r", 0, "report", "a"))
    return _history(events, (AttemptTiming("a", "j", "x", "s", tuple(f"c{i}" for i in range(count)),
                                           "r" if complete else None, "complete" if complete else "pending"),))


@pytest.mark.parametrize("complete", [False, True])
def test_d10_d20_o2_all_checks_survive_completion(complete):
    prior = _prior((1, 1), (1, 3))
    measure = _measure((_tick(4, {"point_ns": 0}), 1.))
    one = atoms_posterior({"x": prior}, measure, _checked_history(1, complete=complete))
    two = atoms_posterior({"x": prior}, measure, _checked_history(2, complete=complete))
    assert one.fraction_evidence == F(1, 2)
    assert two.fraction_evidence == F(5, 16)
    assert math.exp(one.allocated({"a": 3})) == pytest.approx(.75)
    assert math.exp(two.allocated({"a": 3})) == pytest.approx(.9)
    assert HistoryKernel(_checked_history(1, complete=complete), measure.candidates[0].spec)({"a": 1}) == F(1, 4)


def test_d10_d12_one_start_phase_for_entire_history():
    spec = _tick(4, "uniform")
    assert HistoryKernel(_checked_history(1), spec)({"a": 2}) == F(3, 4)
    assert HistoryKernel(_checked_history(2), spec)({"a": 2}) == F(1, 2)
    assert HistoryKernel(_checked_history(2, complete=True), spec)({"a": 2}) == F(3, 8)


def test_d23_point_start_is_conditioned_without_uniformizing():
    kernel = HistoryKernel(_checked_history(1), _tick(4, {"point_ns": 2}))
    assert kernel({"a": 1}) == F(1, 2)
    assert kernel({"a": 1}) != F(7, 16)
    assert kernel.dimension == 1
    assert kernel.external_ids == ("s", "c0")
    assert isinstance(ClockMeasure(), QuantityMeasure)


def test_d11_d17_shared_check_across_actions_and_candidates():
    timing = _history([("sA", 0, "start", "A"), ("sB", 0, "start", "B"),
                       ("c", 0, "external", None)],
        (AttemptTiming("A", "jA", "a", "sA", ("c",), None, "pending"),
         AttemptTiming("B", "jB", "b", "sB", ("c",), None, "pending")))
    kernel = HistoryKernel(timing, _tick(4, {"point_ns": 0}))
    assert kernel({"A": 2, "B": 2}) == F(1, 2)
    assert kernel.dimension == 1
    priors = {a: _prior((1,), (1,)) for a in ("a", "b")}
    result = atoms_posterior(priors, _measure((_tick(2, {"point_ns": 0}), .5),
                                             (_tick(4, {"point_ns": 0}), .5)), timing)
    assert result.fraction_measure_weights == (F(2, 3), F(1, 3))
    assert result.stats.partitions == 2


def test_d19_report_order_is_a_joint_duration_constraint():
    timing = _history([("sA", 0, "start", "A"), ("sB", 0, "start", "B"),
                       ("rA", 0, "report", "A"), ("rB", 0, "report", "B")],
        (AttemptTiming("A", "jA", "a", "sA", (), "rA", "complete"),
         AttemptTiming("B", "jB", "b", "sB", ("rA",), "rB", "complete")))
    spec = _tick(8, {"point_ns": 0})
    kernel = HistoryKernel(timing, spec)
    assert tuple(kernel({"A": a, "B": b}) for a, b in product((1, 3), (2, 4))) == (1, 1, 0, 1)
    result = atoms_posterior({"a": _prior((1, 1), (1, 3)), "b": _prior((1, 1), (2, 4))},
                             _measure((spec, 1.)), timing)
    assert result.fraction_evidence == F(3, 4)
    assert math.exp(result.allocated({"A": 3})) == pytest.approx(1 / 3)
    assert math.exp(result.allocated({"B": 4})) == pytest.approx(2 / 3)
    assert result.fraction_new_value("a")[3] == F(4, 9)
    assert result.fraction_new_value("b")[4] == F(5, 9)


def _d22_history(report=None):
    events = [("sB", 0, "start", "B"), ("rB", 0, "report", "B"), ("sA", 0, "start", "A")]
    if report is not None:
        events.append(("rA", report, "report", "A"))
    return _history(events, (AttemptTiming("B", "jB", "b", "sB", (), "rB", "complete"),
        AttemptTiming("A", "jA", "a", "sA", (), None if report is None else "rA",
                      "pending" if report is None else "complete")))


def test_d22_known_action_updates_another_actions_distribution():
    priors = {"b": _prior((1, 1), (1, 3)), "a": _prior((1,), (2,))}
    measure = _measure((_tick(4, "uniform"), 1.))
    history = atoms_posterior(priors, measure, _d22_history())
    zero = atoms_posterior(priors, measure, _d22_history(0))
    four = atoms_posterior(priors, measure, _d22_history(4))
    assert history.fraction_evidence == F(5, 16)
    assert zero.fraction_evidence / history.fraction_evidence == F(1, 10)
    assert zero.fraction_evidence + four.fraction_evidence == history.fraction_evidence
    assert history.fraction_new_value("b")[1] == F(19, 30)
    assert zero.fraction_new_value("b")[1] == F(2, 3)
    assert four.fraction_new_value("b")[1] == F(17, 27)


@pytest.mark.parametrize("duration", [0, 1, 2, 3, 4, 6, 8])
@pytest.mark.parametrize("phase", ["uniform", {"point_ns": 0}, {"point_ns": 2}])
def test_d16_completion_kernels_normalize_over_all_readings(duration, phase):
    spec = _tick(4, phase)
    values = []
    for reading in (0, 4, 8, 12):
        timing = _history([("s", 0, "start", "a"), ("r", reading, "report", "a")],
            (AttemptTiming("a", "j", "x", "s", (), "r", "complete"),))
        value = HistoryKernel(timing, spec)({"a": duration})
        assert value == isolated_record_likelihood(spec, duration, reading)
        values.append(value)
    assert sum(values) == 1


def test_d16_arrived_and_unarrived_partition_the_same_external_boundary():
    spec = _tick(4, "uniform")
    pending = _checked_history(1)
    complete = _history([("s", 0, "start", "a"), ("r", 0, "report", "a"),
                         ("c0", 0, "external", None)],
        (AttemptTiming("a", "j", "x", "s", (), "r", "complete"),))
    assert HistoryKernel(pending, spec)({"a": 2}) == F(3, 4)
    assert HistoryKernel(complete, spec)({"a": 2}) == F(1, 4)


def test_d16_clock_labels_preserve_axis_translation_and_reject_inconsistent_lattice():
    spec = _tick(4, "uniform")
    def kernel(start, report):
        timing = _history([("s", start, "start", "a"), ("r", report, "report", "a")],
            (AttemptTiming("a", "j", "x", "s", (), "r", "complete"),))
        return HistoryKernel(timing, spec)({"a": 3})
    assert kernel(3, 7) == kernel(0, 4) == F(3, 4)
    assert kernel(3, 6) == 0


def _isolated_history(readings, *, actions=None):
    actions = ("x",) * len(readings) if actions is None else actions
    events, attempts = [], []
    for i, (reading, action) in enumerate(zip(readings, actions)):
        start = i * 12
        events += [(f"s{i}", start, "start", f"a{i}"), (f"r{i}", start + reading, "report", f"a{i}")]
        attempts.append(AttemptTiming(f"a{i}", f"j{i}", action, f"s{i}", (), f"r{i}", "complete"))
    return _history(events, attempts)


@pytest.mark.parametrize("readings,evidence,weights,prediction", [
    ((), F(1), (F(1, 2), F(1, 2)), F(3, 4)),
    ((0,), F(3, 4), (F(2, 3), F(1, 3)), F(61, 72)),
    ((4,), F(1, 4), (F(0), F(1)), F(11, 24)),
    ((0, 0), F(61, 96), (F(48, 61), F(13, 61)), F(111, 122)),
])
def test_o4_joint_measure_and_distribution_posterior(readings, evidence, weights, prediction):
    measure = _measure((_tick(4, {"point_ns": 0}), .5), (_tick(4, "uniform"), .5))
    result = atoms_posterior({"x": _prior((1, 1), (1, 3))}, measure, _isolated_history(readings))
    assert result.fraction_evidence == evidence
    assert result.fraction_measure_weights == weights
    assert result.fraction_isolated_record("x", 0) == prediction
    assert sum(result.fraction_new_value("x").values()) == 1


def test_o4_independent_actions_keep_their_own_dp():
    measure = _measure((_tick(4, {"point_ns": 0}), .5), (_tick(4, "uniform"), .5))
    result = atoms_posterior({a: _prior((1, 1), (1, 3)) for a in ("x", "y")}, measure,
                             _isolated_history((0, 0), actions=("x", "y")))
    assert result.fraction_measure_weights == (F(4, 5), F(1, 5))


def test_o5_cloned_measure_candidates_preserve_predictions():
    point, uniform = _tick(4, {"point_ns": 0}), _tick(4, "uniform")
    priors, timing = {"x": _prior((1, 1), (1, 3))}, _isolated_history((0, 0))
    first = atoms_posterior(priors, _measure((point, .5), (uniform, .5)), timing)
    second = atoms_posterior(priors, _measure((point, .25), (point, .25), (uniform, .5)), timing)
    assert first.fraction_evidence == second.fraction_evidence
    assert first.fraction_new_value("x") == second.fraction_new_value("x")
    assert first.fraction_isolated_record("x", 0) == second.fraction_isolated_record("x", 0)
    assert first.fraction_measure_weights[0] == sum(second.fraction_measure_weights[:2])


def test_o6_tick_exact_reduction_on_grid_and_point_phase_counterexample():
    prior = _prior((1, 1, 2), (0, 4, 8))
    timing = _isolated_history((0, 4))
    tick = atoms_posterior({"x": prior}, _measure((_tick(4, "uniform"), 1.)), timing)
    exact = exact_posterior(prior, (ExactEvidence("a0", (), True, 0), ExactEvidence("a1", (), True, 4)))
    assert tick.log_evidence == pytest.approx(exact.log_evidence, abs=1e-14)
    assert tick.new_value("x") == pytest.approx(exact.predictive(), abs=1e-14)
    point = _tick(4, {"point_ns": 0})
    assert isolated_record_likelihood(point, 1, 0) == isolated_record_likelihood(point, 3, 0) == 1


def _uniform_prior(alpha):
    return DurationPrior(alpha, BaseSpec("piecewise", "1", {"edges_ns": [0, 4], "masses": [1.],
        "tail": {"kind": "pareto", "kappa": 1., "mass": 0.}, "p_inf": 0.}))


def _zero_record_polynomial():
    return PolynomialLikelihood((PolynomialPiece(0, 4, (1, F(-1, 4))), PolynomialPiece(4, None, (0,))), F(0))


def _direct_product_partition_moment(prior, kernels):
    """名札つきの分割を直接列挙。多重度の二項係数の漸化式を使わない。"""
    numerator, rows = F(0), []
    alpha = F(prior.alpha)
    for rgs in restricted_growth_strings(len(kernels)):
        term = alpha ** (max(rgs, default=-1) + 1)
        for label in range(max(rgs, default=-1) + 1):
            indexes = [i for i, b in enumerate(rgs) if b == label]
            _, moment = _kernel_moment(prior.base, kernels, tuple(int(i in indexes) for i in range(len(kernels))))
            assert moment is not None
            term *= math.factorial(len(indexes) - 1) * moment
        rows.append(term / _rising(alpha, len(kernels)))
        numerator += term
    return numerator / _rising(alpha, len(kernels)), rows


def test_o1_o9_tick_moments_and_continuous_partition_weights():
    recurrence = MultiplicityMoments(_prior((1, 1), (1, 3)), (AtomLikelihood((F(3, 4), F(1, 4))),))
    assert tuple(recurrence.fraction_z((n,)) for n in (1, 2, 3)) == (F(1, 2), F(13, 48), F(5, 32))
    prior, kernel = _uniform_prior(1), _zero_record_polynomial()
    uniform = MultiplicityMoments(prior, (kernel,))
    evidence, rows = _direct_product_partition_moment(prior, (kernel, kernel))
    assert evidence == uniform.fraction_z((2,)) == F(7, 24)
    assert tuple(w / evidence for w in rows) == (F(4, 7), F(3, 7))
    assert uniform.fraction_z((3,)) / evidence == F(9, 14)


def test_o9_multiplicity_recurrence_keeps_rising_factorial_ratio():
    prior = _prior((1, 1), (1, 3))
    kernels = (AtomLikelihood((1, 0)), AtomLikelihood((F(3, 4), F(1, 4))),
               AtomLikelihood((F(1, 4), F(3, 4))))
    moments = MultiplicityMoments(prior, kernels)
    history = (2, 0, 0)
    for added, expected in [((0, 1, 0), F(5, 8)), ((0, 1, 1), F(9, 40)), ((0, 1, 2), F(11, 128))]:
        counts = tuple(a + b for a, b in zip(history, added))
        assert moments.fraction_z(counts) / moments.fraction_z(history) == expected
        assert math.exp(moments.log_ratio(history, added)) == pytest.approx(float(expected), abs=1e-14)
        expanded = tuple(k for k, n in zip(kernels, counts) for _ in range(n))
        direct, _ = _direct_product_partition_moment(prior, expanded)
        assert moments.fraction_z(counts) == direct


def test_o9_replicas_are_aggregated_without_bell_enumeration():
    moments = MultiplicityMoments(_prior((1, 1), (1, 3)), (AtomLikelihood((F(3, 4), F(1, 4))),))
    # A 65-sample labelled sum has Bell(65) terms. This uses exactly 66 count states.
    result = moments.log_z((65,))
    expected = (F(3, 4) ** 66 - F(1, 4) ** 66) / (F(1, 2) * 66)
    assert result == pytest.approx(math.log(expected), abs=1e-12)
    assert moments.cached_states == 66


def test_o9_equal_kernel_types_merge_exactly():
    prior, kernel = _uniform_prior(1), _zero_record_polynomial()
    same_function = PolynomialLikelihood((PolynomialPiece(0, 2, (1, F(-1, 4), 0)),
        PolynomialPiece(2, 4, (1, F(-1, 4))), PolynomialPiece(4, None, (0, 0))), F(0))
    repeated = MultiplicityMoments(prior, (kernel, same_function))
    unique = MultiplicityMoments(prior, (kernel,))
    assert repeated.log_z((10, 10)) == unique.log_z((20,))
    assert repeated.fraction_z((1, 1)) == F(7, 24)
    assert len(repeated.kernels) == 1
    assert repeated.cached_states == 21


def test_o7_pareto_closed_moments_log_branch_and_triangle():
    base = BaseSpec("piecewise", "1", {"edges_ns": [0, 1], "masses": [0.],
        "tail": {"kind": "pareto", "kappa": 1., "mass": 1.}, "p_inf": 0.})
    assert base.interval_moment(1, 2, 3) == pytest.approx(math.log(1.5), abs=1e-15)
    assert base.interval_moment(0, 2, None) == pytest.approx(.5)
    assert base.log_finite_tail(4) == pytest.approx(math.log(.25))
    with pytest.raises(ValueError, match="diverges"):
        base.interval_moment(1, 1, None)
    triangle = PolynomialLikelihood((PolynomialPiece(0, 1, (0,)), PolynomialPiece(1, 2, (-1, 1)),
        PolynomialPiece(2, 3, (3, -1)), PolynomialPiece(3, None, (0,))), F(0))
    moments = MultiplicityMoments(DurationPrior(1, base), (triangle,))
    assert math.exp(moments.log_z((1,))) == pytest.approx(math.log(4 / 3), abs=1e-15)


def test_u9_joint_atoms_and_multiplicity_keep_underflowed_positive_mass():
    prior = DurationPrior(1e-200, BaseSpec("atoms", "1", {"points": [[1, 1e-200], [3, 1.]]}))
    result = atoms_posterior({"x": prior}, _measure((_tick(4, {"point_ns": 0}), 1.)), _isolated_history(()))
    assert math.isfinite(result.new_value("x")[1])
    assert result.new_value("x")[1] == pytest.approx(math.log(1e-200), abs=1e-12)
    moments = MultiplicityMoments(prior, (AtomLikelihood((1, 0)),))
    assert moments.log_z((1,)) == pytest.approx(math.log(1e-200), abs=1e-12)
    # Updating this rare complete observation uses rational weights, not float αG₀=0.
    completed = _history([("s", 0, "start", "a"), ("r", 1, "report", "a")],
        (AttemptTiming("a", "j", "x", "s", (), "r", "complete"),))
    posterior = atoms_posterior({"x": prior}, _measure((MeasureSpec("exact", "1", {}), 1.)), completed)
    assert math.isfinite(posterior.new_value("x")[3])
    assert posterior.new_value("x")[3] == pytest.approx(math.log(1e-200), abs=1e-12)


def test_o3_partition_blocks_can_land_on_the_same_infinity_atom():
    timing = _history([("sA", 0, "start", "A"), ("sB", 0, "start", "B")],
        (AttemptTiming("A", "jA", "x", "sA", (), None, "pending"),
         AttemptTiming("B", "jB", "x", "sB", (), None, "pending")))
    result = atoms_posterior({"x": _prior((1, 1), (1, None))},
                             _measure((_tick(4, {"point_ns": 0}), 1.)), timing)
    assert math.exp(result.allocated({"A": None, "B": None})) == pytest.approx(1 / 3)
    infinity_rows = [(c, w) for c, w in zip(result.components, result.fraction_weights)
                     if c.allocation == (None, None)]
    assert [c.partitions for c, _ in infinity_rows] == [((0, 0),), ((0, 1),)]
    assert [w for _, w in infinity_rows] == [F(1, 6), F(1, 6)]
    assert result.stats.partitions == 2
    assert result.stats.allocated_branches == 6


def test_d21_joint_exact_point_faces_and_equal_time_prefix():
    before = _history([("sA", 0, "start", "A"), ("sB", 0, "start", "B"),
                       ("rA", 1, "report", "A")],
        (AttemptTiming("A", "jA", "a", "sA", (), "rA", "complete"),
         AttemptTiming("B", "jB", "b", "sB", ("rA",), None, "pending")))
    exact = MeasureSpec("exact", "1", {})
    assert HistoryKernel(before, exact)({"A": 1, "B": 1}) == F(1, 2)
    assert HistoryKernel(before, exact)({"A": 1, "B": 0}) == 0
    after = _history([("sA", 0, "start", "A"), ("sB", 0, "start", "B"),
                      ("rA", 1, "report", "A"), ("rB", 1, "report", "B")],
        (AttemptTiming("A", "jA", "a", "sA", (), "rA", "complete"),
         AttemptTiming("B", "jB", "b", "sB", ("rA",), "rB", "complete")))
    assert HistoryKernel(after, exact)({"A": 1, "B": 1}) == F(1, 2)


def test_polytope_partition_covers_envelope_switches_and_polynomial_moments():
    # 0 <= x <= 1, 0 <= y <= min(x,1-x). The active upper face switches at x=1/2.
    constraints = tuple((tuple(map(F, a)), False) for a in
                        ((0, 1, 0), (1, -1, 0), (0, 0, 1), (0, 1, -1), (1, -1, -1)))
    area, pieces = _polytope_integral(2, constraints, {(0, 0): F(1)})
    x_moment, _ = _polytope_integral(2, constraints, {(1, 0): F(1)})
    y_moment, _ = _polytope_integral(2, constraints, {(0, 1): F(1)})
    assert (area, x_moment, y_moment, pieces) == (F(1, 4), F(1, 8), F(1, 24), 2)
    simplex = tuple((tuple(map(F, a)), False) for a in
                    ((0, 1, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1), (1, -1, -1, -1)))
    assert _polytope_integral(3, simplex, {(0, 0, 0): F(1)})[0] == F(1, 6)
    assert _polytope_integral(3, simplex, {(1, 1, 0): F(1)})[0] == F(1, 120)
    assert _polytope_integral(0, (((F(0),), False),), {(): F(1)}) == (1, 1)
    assert _polytope_integral(0, (((F(0),), True),), {(): F(1)}) == (0, 0)


def _coupled_pair_history(check_count, states, *, same_action):
    actions = ("x", "x") if same_action else ("x", "y")
    events = [("sA", 0, "start", "A"), ("sB", 0, "start", "B")]
    checks = tuple(f"c{i}" for i in range(check_count))
    events += [(ref, 0, "external", None) for ref in checks]
    reports = []
    for name, reading in zip(("A", "B"), states):
        if reading is not None:
            events.append((f"r{name}", reading, "report", name))
            reports.append((name, f"r{name}"))
    attempts = []
    for name, action, reading in zip(("A", "B"), actions, states):
        earlier_reports = tuple(ref for other, ref in reports if other != name and
                                (reading is None or reports.index((other, ref)) < reports.index((name, f"r{name}"))))
        attempts.append(AttemptTiming(name, f"j{name}", action, f"s{name}", checks + earlier_reports,
                                      None if reading is None else f"r{name}",
                                      "pending" if reading is None else "complete"))
    return _history(events, attempts)


def _direct_dirichlet_joint(priors, timing, kernel):
    """有限のDirichletの単項式を全割り振りで直接積分。DPの分割を使わない。"""
    attempts, raw = kernel.attempts, {}
    choices = tuple(tuple(p for p, _ in priors[a.action].base.params["points"]) for a in attempts)
    for allocation in product(*choices):
        moment = F(1)
        for action, prior in priors.items():
            indexes = [i for i, a in enumerate(attempts) if a.action == action]
            for point, mass in prior.base.params["points"]:
                moment *= _rising(F(prior.alpha) * F(mass), sum(allocation[i] == point for i in indexes))
            moment /= _rising(F(prior.alpha), len(indexes))
        likelihood = kernel({a.attempt: d for a, d in zip(attempts, allocation)})
        if likelihood:
            raw[allocation] = moment * likelihood
    return sum(raw.values(), F(0)), raw


def test_u14_joint_partition_sum_matches_93_direct_dirichlet_integrals():
    matched = 0
    for alpha in (1, 2, 4):
        matched_this_alpha = 0
        for phase, count, states, same_action in product(("uniform", {"point_ns": 0}, {"point_ns": 2}),
                range(3), ((None, None), (0, None), (None, 0), (0, 0), (0, 4), (4, 4)), (True, False)):
            base = BaseSpec("atoms", "1", {"points": [[1, .25], [3, .5], [None, .25]]})
            priors = {a: DurationPrior(alpha, base) for a in (("x",) if same_action else ("x", "y"))}
            timing = _coupled_pair_history(count, states, same_action=same_action)
            spec = _tick(4, phase)
            evidence, raw = _direct_dirichlet_joint(priors, timing, HistoryKernel(timing, spec))
            if not evidence:
                continue
            result = atoms_posterior(priors, _measure((spec, 1.)), timing)
            assert result.fraction_evidence == evidence
            for action, prior in priors.items():
                indexes = [i for i, a in enumerate(timing.attempts) if a.action == action]
                denominator = F(alpha) + len(indexes)
                direct = {point: sum((weight * (F(alpha) * F(mass)
                           + sum(allocation[i] == point for i in indexes)) / denominator
                           for allocation, weight in raw.items()), F(0)) / evidence
                          for point, mass in base.params["points"]}
                assert result.fraction_new_value(action) == direct
            for allocation, weight in raw.items():
                probability = sum((w for c, w in zip(result.components, result.fraction_weights)
                                   if c.allocation == allocation), F(0))
                assert probability == weight / evidence
            matched += 1
            matched_this_alpha += 1
            if matched_this_alpha == 31:
                break
        assert matched_this_alpha == 31
    assert matched == 93


def _o10_one_piece():
    return IntegrationPiece((((2,), (3,)),), (PowerTerm(1, (
        PowerFactor((0, 1), -2 / 3), PowerFactor((-1, 1), -2 / 3))),))


def test_o10_one_variable_integral_enclosure_degree_and_space():
    result = integrate_pieces((_o10_one_piece(),), tolerance=1e-12, initial_degree=4)
    reference = .430963660567163360273514772492
    lo, hi = result.bounds()
    assert lo <= reference <= hi
    assert result.log_width <= math.log(1e-12)
    assert result.boxes > 1 and result.max_degree > 4
    # Enclosure is tested where the discretization bound dominates float rounding.
    assert math.exp(result.log_error) > 100 * math.ulp(reference)


def test_o10_map_and_one_axis_ellipse_bounds_are_multiaffine():
    piece = IntegrationPiece((((1,), (2,)), ((0, 1), (0, 3))),
                             (PowerTerm(1, (PowerFactor((0, 0, 1), -2 / 3),)),))
    mapped = piece.mapped_terms()[0]
    assert mapped.factors[0][0] == {0: 1, 1: 1, 2: 2, 3: 2}
    assert mapped.factors[1:] == (({0: 1}, 1.), ({0: 2, 1: 2}, 1.))
    term = _MappedTerm(F(1), 0., (({0: F(1), 3: F(1)}, -2 / 3),))
    # s0 alone is complex, s1 is at real vertices: min Re(1+s0*s1)=7/8 for rho=2.
    assert _axis_log_m((term,), 2, 0, 2.) == pytest.approx(-(2 / 3) * math.log(7 / 8), abs=1e-15)
    invalid = _MappedTerm(F(1), 0., (({1: F(1)}, -.5),))
    assert _axis_log_m((invalid,), 1, 0, 2.) is None
    integer = _MappedTerm(F(1), 0., (({1: F(1)}, 2.),))
    assert _axis_log_m((integer,), 1, 0, 2.) is not None


def test_o10_constant_finishes_by_degree_growth_on_one_piece():
    piece = IntegrationPiece((((0,), (1,)),), (PowerTerm(1, ()),))
    # 4点→5点なら計9点。4点のまま二分すると最初の子2つで計12点。
    result = integrate_pieces((piece,), tolerance=1e-12, initial_degree=4, node_budget=9)
    assert result.pieces == result.boxes == 1
    assert result.max_degree > 4
    assert result.nodes <= 9
    assert result.log_width <= math.log(1e-12)
    assert math.exp(result.log_value) == pytest.approx(1.)


def _o10_four_history():
    # All units are multiplied by 2 so L=5 is an integer ns in the public BaseSpec.
    prior = DurationPrior(1, BaseSpec("piecewise", "1", {"edges_ns": [0, 5], "masses": [.5],
        "tail": {"kind": "pareto", "kappa": 2 / 3, "mass": .5}, "p_inf": 0.}))
    events = [(f"s{i}", 2 * i, "start", str(i)) for i in range(4)]
    events += [(f"r{i}", 10, "report", str(i)) for i in range(4)]
    attempts = tuple(AttemptTiming(str(i), f"j{i}", f"a{i}", f"s{i}", tuple(f"r{j}" for j in range(i)),
                                    f"r{i}", "complete") for i in range(4))
    return {f"a{i}": prior for i in range(4)}, _measure((_tick(2, {"point_ns": 0}), 1.)), _history(events, attempts)


def test_o10_four_action_history_raw_four_and_ad_eliminated_two():
    priors, measure, timing = _o10_four_history()
    posterior = partition_evidence(priors, measure, timing, tolerance=1e-12)
    reference = 7.4028953660967428951458956525992e-7
    assert posterior.evidence.bounds()[0] <= reference <= posterior.evidence.bounds()[1]
    assert posterior.stats.partitions == 1
    assert posterior.stats.integration_pieces == 3
    assert posterior.stats.final_groups == 2
    assert _log_sum_width(posterior.component_probabilities) <= math.log(1e-12)
    raw, reduced = [], []
    for entry in posterior.entries:
        if entry.region is None:
            continue
        assert entry.region.dimension == 4
        assert tuple(name[0] for name in entry.variables) == ("a2", "a1", "a0", "a3")
        raw.extend(IntegrationPiece(b, entry.region.terms) for b in _linear_pieces(4, entry.region.constraints))
        # c,b,a,d -> eliminate d (index3), then a (index2). Keep exactly c,b.
        after_d = _eliminate_separable_interval(entry.region, 3)
        assert after_d is not None
        for r in after_d:
            after_a = _eliminate_separable_interval(r, 2)
            assert after_a is not None
            for rr in after_a:
                reduced.extend(IntegrationPiece(b, rr.terms) for b in _linear_pieces(2, rr.constraints))
    assert len(raw) == len(reduced) == 3
    assert {len(p.bounds) for p in raw} == {4}
    assert {len(p.bounds) for p in reduced} == {2}
    for pieces in (raw, reduced):
        estimate = integrate_pieces(pieces, tolerance=1e-13)
        lo, hi = estimate.bounds()
        assert lo <= reference <= hi
        assert math.exp(estimate.log_error) > 100 * math.ulp(reference)
        assert estimate.log_width <= math.log(1e-13)
    optimized = partition_evidence(priors, measure, timing, tolerance=1e-12, eliminate_finite=True)
    # At tighter degrees float rounding can exceed the discretization bound.
    # The enclosure above is checked at a coarser degree where that bound dominates.
    assert math.exp(optimized.evidence.log_value) == pytest.approx(reference, abs=1e-17, rel=0)
    assert optimized.stats.integration_pieces == 3
    assert _log_sum_width(optimized.component_probabilities) <= math.log(1e-12)


def _log_sum_width(probabilities):
    from sui.quantity import _logadd
    return _logadd(p.log_width for p in probabilities)


def test_o10_density_only_halfline_and_eventually_constant_boundary():
    # T~U[0,2], x~Pareto(1,1), x>=T: split the max(1,T) at T=1 before eliminating x.
    constraints = tuple((tuple(map(F, a)), False) for a in
                        ((0, 1, 0), (2, -1, 0), (-1, 0, 1), (0, -1, 1)))
    tail = TailDensity("x", 1, 1, 1., 1., F(1))
    region = LinearIntegral(2, constraints, (PowerTerm(F(1, 2), (PowerFactor((0, 0, 1), -2),)),), (tail,))
    assert _eliminate_density_halfline(region, tail) is not None
    result = integrate_linear(region, tolerance=1e-12)
    reference = (1 + math.log(2)) / 2
    assert result.bounds()[0] <= reference <= result.bounds()[1]
    assert result.pieces == 2
    assert result.log_tail == -math.inf


def test_o10_coupled_halfline_requires_finite_tail_mass_in_enclosure():
    # ∫∫ x^-2 y^-2 /(x+y), x,y>=1 = 2/3*(1-log2). K=1/(x+y)<=1.
    region = LinearIntegral(2, (((F(-1), F(1), F(0)), False), ((F(-1), F(0), F(1)), False)),
        (PowerTerm(1, (PowerFactor((0, 1, 0), -2), PowerFactor((0, 0, 1), -2), PowerFactor((0, 1, 1), -1))),),
        (TailDensity("x", 0, 1, 1., 1., F(1)), TailDensity("y", 1, 1, 1., 1., F(1))))
    assert all(_eliminate_density_halfline(region, t) is None for t in region.tails)
    result = integrate_linear(region, tolerance=.26, finite_tolerance=1e-9, cutoffs={"x": 8, "y": 8})
    reference = 2 / 3 * (1 - math.log(2))
    assert result.bounds()[0] <= reference <= result.bounds()[1]
    assert result.log_tail == pytest.approx(math.log(F(1, 4)), abs=1e-15)
    assert math.exp(result.log_value) + math.exp(result.log_error) < reference
    assert result.log_width <= math.log(.26)
    with pytest.raises(IntegrationIncomplete, match="cutoffs"):
        integrate_linear(region, tolerance=1e-12, cutoffs={"x": 8, "y": 8})


def test_o10_global_error_sum_and_conditioning_small_evidence():
    single = integrate_pieces((_o10_one_piece(),), tolerance=1e-12)
    naive = sum_integrals((single,) * 8, (F(1),) * 8)
    assert naive.log_width > math.log(1e-12)
    combined = integrate_pieces((_o10_one_piece(),) * 8, tolerance=1e-12)
    assert combined.log_width <= math.log(1e-12)
    numerator = IntegralEstimate(math.log(5e-11), math.log(1e-13))
    denominator = IntegralEstimate(math.log(1e-10), math.log(1e-13))
    conditional = condition_probability(numerator, denominator)
    assert math.exp(conditional.log_lower) < .5 < math.exp(conditional.log_upper)
    assert conditional.log_width > math.log(1e-3)
    scaled = condition_probability(IntegralEstimate(numerator.log_value - 1000, numerator.log_error - 1000),
        IntegralEstimate(denominator.log_value - 1000, denominator.log_error - 1000))
    assert scaled.log_width == pytest.approx(conditional.log_width, abs=1e-12)
    tight = condition_probability(IntegralEstimate(-1000 - math.log(2), -1100),
                                  IntegralEstimate(-1000, -1100))
    # Endpoints round to the same log value; the propagated error remains positive.
    assert tight.log_lower == tight.log_upper
    assert math.isfinite(tight.log_width)
    assert tight.log_width == pytest.approx(-100 + math.log(3), abs=1e-12)


@pytest.mark.parametrize("alpha", [1, 2, 4])
@pytest.mark.parametrize("checks", [1, 2])
@pytest.mark.parametrize("same_action", [True, False])
def test_u14_piecewise_joint_history_matches_conditional_dirichlet_polynomial(alpha, checks, same_action):
    timing = _coupled_pair_history(checks, (None, None), same_action=same_action)
    priors = {a: _uniform_prior(alpha) for a in (("x",) if same_action else ("x", "y"))}
    result = partition_evidence(priors, _measure((_tick(4, {"point_ns": 0}), 1.)), timing, tolerance=1e-12)
    # Conditional on max check T, Dirichlet tail P has E[P²]=(alpha*p²+p)/(alpha+1).
    mean_p, mean_p2 = (F(1, 2), F(1, 3)) if checks == 1 else (F(1, 3), F(1, 6))
    expected = (alpha * mean_p2 + mean_p) / (alpha + 1) if same_action else mean_p2
    assert result.evidence.log_error == result.evidence.log_tail == -math.inf
    assert result.evidence.log_value == pytest.approx(math.log(expected), abs=1e-14)
    assert result.stats.partitions == (2 if same_action else 1)


def test_d16_piecewise_report_histories_partition_the_normalized_kernel():
    prior, measure = _uniform_prior(1), _measure((_tick(4, "uniform"), 1.))
    pieces = []
    for reading in (0, 4):
        timing = _isolated_history((reading,))
        result = partition_evidence({"x": prior}, measure, timing, tolerance=1e-12)
        assert result.evidence.log_error == -math.inf
        assert result.evidence.log_value == pytest.approx(math.log(.5), abs=1e-14)
        pieces.append(result.evidence)
    total = sum_integrals(pieces, (F(1), F(1)))
    assert total.log_value == pytest.approx(0., abs=1e-14)


def test_u14_pareto_joint_partition_sum_keeps_shared_check():
    prior = DurationPrior(1, BaseSpec("piecewise", "1", {"edges_ns": [0, 1], "masses": [0.],
        "tail": {"kind": "pareto", "kappa": 1., "mass": 1.}, "p_inf": 0.}))
    timing = _history([("sA", 0, "start", "A"), ("sB", 0, "start", "B"), ("c", 2, "external", None)],
        (AttemptTiming("A", "jA", "x", "sA", ("c",), None, "pending"),
         AttemptTiming("B", "jB", "x", "sB", ("c",), None, "pending")))
    result = partition_evidence({"x": prior}, _measure((_tick(1, {"point_ns": 0}), 1.)), timing, tolerance=1e-12)
    reference = math.log(1.5) / 2 + 1 / 12
    assert result.evidence.bounds()[0] <= reference <= result.evidence.bounds()[1]
    assert _log_sum_width(result.component_probabilities) <= math.log(1e-12)
    assert result.stats.partitions == 2
    assert result.evidence.log_tail == -math.inf


def test_o10_u14_one_variable_reference_from_raw_three_variable_history():
    prior = DurationPrior(1, BaseSpec("piecewise", "1", {"edges_ns": [0, 1], "masses": [0.],
        "tail": {"kind": "pareto", "kappa": 2 / 3, "mass": 1.}, "p_inf": 0.}))
    timing = _history([("sA", 0, "start", "A"), ("sB", 1, "start", "B"), ("c", 2, "external", None)],
        (AttemptTiming("A", "jA", "x", "sA", ("c",), None, "pending"),
         AttemptTiming("B", "jB", "y", "sB", ("c",), None, "pending")))
    # Use a coarser enclosure here so its discretization bound dominates rounding.
    tolerance = 1e-10
    result = partition_evidence({"x": prior, "y": prior}, _measure((_tick(1, {"point_ns": 0}), 1.)),
                                timing, tolerance=tolerance)
    reference = .430963660567163360273514772492
    assert result.entries[0].region.dimension == 3
    assert result.stats.integration_pieces == 1
    assert result.evidence.bounds()[0] <= reference <= result.evidence.bounds()[1]
    assert math.exp(result.evidence.log_error) > 100 * math.ulp(reference)
    assert result.evidence.log_tail == -math.inf
    assert _log_sum_width(result.component_probabilities) <= math.log(tolerance)


def test_d17_piecewise_actions_share_the_external_check_before_lambda_mixing():
    timing = _coupled_pair_history(1, (None, None), same_action=False)
    measure = _measure((_tick(4, {"point_ns": 0}), .5), (_tick(8, {"point_ns": 0}), .5))
    result = partition_evidence({a: _uniform_prior(1) for a in ("x", "y")}, measure, timing, tolerance=1e-12)
    # Each action has D~U[0,4]. For T~U[0,h], integrate (1-T/4)^2 on [0,4].
    # Evidence per lambda is 1/3 or 1/6, so their equal-prior mixture is 1/4.
    assert result.evidence.log_value == pytest.approx(math.log(F(1, 4)), abs=1e-14)
    assert result.evidence.log_error == result.evidence.log_tail == -math.inf
    assert tuple(math.exp(p.log_lower) for p in result.measure_probabilities) == pytest.approx((2 / 3, 1 / 3))
    assert result.stats.partitions == 2


def test_o5_piecewise_joint_lambda_normalization_and_replica_budget():
    prior = DurationPrior(1, BaseSpec("piecewise", "1", {"edges_ns": [0, 1], "masses": [0.],
        "tail": {"kind": "pareto", "kappa": 1., "mass": 1.}, "p_inf": 0.}))
    timing = _history([("sA", 0, "start", "A"), ("sB", 0, "start", "B"), ("c", 2, "external", None)],
        (AttemptTiming("A", "jA", "x", "sA", ("c",), None, "pending"),
         AttemptTiming("B", "jB", "x", "sB", ("c",), None, "pending")))
    specs = (_tick(1, {"point_ns": 0}), _tick(2, {"point_ns": 0}))
    original = partition_evidence({"x": prior}, _measure((specs[0], .5), (specs[1], .5)),
                                  timing, tolerance=1e-12)
    cloned = partition_evidence({"x": prior}, _measure((specs[0], .25), (specs[0], .25), (specs[1], .5)),
                                timing, tolerance=1e-12)
    # Given the shared T, E[F([T,inf))²]=(1/T²+1/T)/2 for alpha=1.
    z1, z2 = math.log(1.5) / 2 + 1 / 12, (math.log(2) + 1 / 4) / 4
    expected_evidence, expected_weight = (z1 + z2) / 2, z1 / (z1 + z2)
    for posterior in (original, cloned):
        assert math.exp(posterior.evidence.log_value) == pytest.approx(expected_evidence, abs=1e-14, rel=0)
        assert posterior.evidence.log_width <= math.log(1e-12)
        assert _log_sum_width(posterior.component_probabilities) <= math.log(1e-12)
        assert _log_sum_width(posterior.measure_probabilities) <= math.log(1e-12)
        assert posterior.evidence.log_tail == -math.inf
    assert original.stats.partitions == 4 and cloned.stats.partitions == 6
    assert math.exp(original.measure_probabilities[0].log_lower) == pytest.approx(expected_weight, abs=1e-12, rel=0)
    assert sum(math.exp(p.log_lower) for p in cloned.measure_probabilities[:2]) == pytest.approx(
        expected_weight, abs=1e-12, rel=0)
    assert original.evidence.log_value == pytest.approx(cloned.evidence.log_value, abs=1e-14)


def test_o10_y9_node_budget_is_an_incomplete_computation():
    with pytest.raises(IntegrationIncomplete, match="budget") as caught:
        integrate_pieces((_o10_one_piece(),), tolerance=1e-12, node_budget=1)
    assert type(caught.value) is IntegrationIncomplete


def test_u9_quadrature_positive_value_and_bound_stay_in_log_space():
    tiny = F(1, 10 ** 400)
    piece = IntegrationPiece((((0,), (1,)),), (PowerTerm(tiny, ()),))
    result = integrate_pieces((piece,), tolerance=1e-200)
    assert math.isfinite(result.log_value) and math.isfinite(result.log_error)
    assert result.log_value == pytest.approx(-400 * math.log(10), abs=1e-12)


@pytest.mark.parametrize("failure", ["midpoint", "nonfinite", "bound", "display"])
def test_o10_y9_numerical_range_failures_are_not_success(failure):
    from sui.inference import NumericalRange
    with pytest.raises(NumericalRange):
        if failure == "midpoint":
            _bisect_box(((1., math.nextafter(1., 2.)),), 0)
        elif failure == "nonfinite":
            PowerTerm(1, (), math.inf)
        elif failure == "bound":
            piece = IntegrationPiece((((0,), (1,)),), (PowerTerm(1, (PowerFactor((10, 1), 1e308),)),))
            integrate_pieces((piece,), tolerance=1e-12)
        else:
            IntegralEstimate(-1000., -1100.).bounds()


def _timing_fixture():
    from sui.clock import FakeClock
    from sui.ids import Ref, RefKind, SequentialIds
    from sui.records import Record, Role, Producer, Observed, AttemptStarted, JobOpened, Payload, BODY_KIND
    from sui.s1_contracts import ACTION, ATTEMPT, OUTCOME
    from sui.s4_contracts import BOOT
    clock = FakeClock(run=Ref(RefKind.RUN, "timing"))
    ids, records, jobs, attempts = SequentialIds(prefix="timing"), [], {}, {}
    def add(body, ns):
        clock.advance(ns - clock.mono_ns())
        record = Record(id=ids.new(BODY_KIND[type(body)]), at=clock.now(),
            writer=Role.MEMBRANE if isinstance(body, (Observed, AttemptStarted)) else Role.MODEL,
            producer=Producer(component="test.quantity", code_version="1"), body=body)
        records.append(record)
        return record
    add(Observed(route="membrane", received_ns=0, content=Payload.json({}), contract=BOOT), 0)
    def start(action="a", ns=0):
        job = add(JobOpened(decision=Ref(RefKind.DECISION, "d"), step=0,
            content=Payload.json({"action": action}), contract=ACTION), ns)
        attempt = add(AttemptStarted(job=job.id, content=Payload.json({}), contract=ATTEMPT), ns)
        jobs[job.id], attempts[attempt.id] = action, action
        return attempt
    def observe(attempt, ns, received_ns):
        return add(Observed(route="executor", received_ns=received_ns, caused_by=attempt.id,
            content=Payload.text("unreadable name"), contract=OUTCOME), ns)
    def external(ns):
        return add(Observed(route="sensor", received_ns=ns, content=Payload.json({}), contract=OUTCOME), ns)
    return SimpleNamespace(records=records, jobs=jobs, attempts=attempts,
                           start=start, observe=observe, external=external)


def test_d8_d9_d15_timing_unreadable_name_first_receipt_order_and_reordering():
    from sui.timeline import timeline
    r = _timing_fixture()
    one, two = r.start(), r.start()
    receipt = r.observe(one, 2, 2)
    first_missing = r.observe(two, 3, None)
    later = r.observe(two, 4, 4)
    axis = timeline(r.records)
    timing = read_timing(r.records, axis, r.jobs, r.attempts, {})
    assert timing == read_timing(tuple(reversed(r.records)), axis, r.jobs, r.attempts, {})
    first, second = timing.attempts
    assert first.state == "complete" and first.report_event == receipt.id
    assert second.state == "unknown" and second.report_event == first_missing.id
    assert later.id not in second.check_events
    assert second.check_events == (receipt.id,)
    assert timing.exact_evidence("a")[0].value == 2
    assert timing.exact_evidence("a")[1].checks == ((2, False),)


def test_d11_d20_reading_keeps_shared_event_identity_and_past_checks_after_completion():
    from sui.timeline import timeline
    r = _timing_fixture()
    a, b, c = r.start(), r.start(), r.start()
    first, second = r.observe(a, 1, 1), r.observe(b, 2, 2)
    last = r.observe(c, 3, 3)
    timing = read_timing(r.records, timeline(r.records), r.jobs, r.attempts, {})
    assert timing.attempts[1].check_events == (first.id,)
    assert timing.attempts[2].check_events == (first.id, second.id)
    assert timing.attempts[2].report_event == last.id
    assert len(timing.events) == 7  # boot・始まり3・報告3
    assert timing.exact_evidence("a")[2].checks == ((1, False), (2, False))


def test_d9_public_read_separates_unreadable_names_from_timing():
    from sui.agent import read
    r = _timing_fixture()
    attempt = r.start()
    receipt = r.observe(attempt, 2, 2)
    result = read(_quantity_model(), r.records)
    assert result.unread[receipt.id] == "content"  # text payload は名前の本文として読めない
    assert result.n["a"].tolist() == [0, 0]
    assert result.timing.attempts[0].state == "complete"
    assert result.timing.exact_evidence("a")[0].value == 2


def test_d21_exact_equal_time_reports_have_one_ordered_prefix():
    from sui.timeline import timeline
    r = _timing_fixture()
    a, b = r.start(), r.start()
    first = r.observe(a, 2, 2)
    boundary = read_timing(r.records, timeline(r.records), r.jobs, r.attempts, {b.body.job: "a"})
    assert [p.state for p in boundary.attempts] == ["complete", "pending"]
    assert boundary.attempts[1].check_events == (first.id,)
    complete = r.observe(b, 2, 2)
    final = read_timing(r.records, timeline(r.records), r.jobs, r.attempts, {})
    assert [p.state for p in final.attempts] == ["complete", "complete"]
    assert final.attempts[1].report_event == complete.id
    posterior = exact_posterior(_prior(), final.exact_evidence("a"))
    assert math.exp(posterior.log_evidence) == pytest.approx(1/6)


def _binary_record_law(*, mixed=False, pending=False):
    measure = AtomicPolynomialMeasure({"x": _prior((1, 1), (1, 3))})
    p = SimplexPolynomial((2,), (1,), {(1, 0): F(3, 4), (0, 1): F(1, 4)})
    one, zero = (SimplexPolynomial.constant((2,), v) for v in (1, 0))
    kernels = ((one, p), (zero, p.complement())) if mixed else ((p,), (p.complement(),))
    weights = (F(1, 2), F(1, 2)) if mixed else (F(1),)
    cells = {z: {e: tuple(left.multiply(right) for left, right in zip(kernels[z], kernels[e]))
                 for e in range(2)} for z in range(2)} if pending else {"z": {e: v for e, v in enumerate(kernels)}}
    return AtomicRecordLaw(measure, weights, cells)


def _finite_eta_record_law(weights, cells, *, tails=None):
    measure = AtomicPolynomialMeasure({"fixed": _prior((1,), (1,))})
    return AtomicRecordLaw(measure, weights,
        {z: {e: tuple(SimplexPolynomial.constant(measure.sizes, v) for v in values)
             for e, values in records.items()} for z, records in cells.items()}, tails=tails)


def test_u2_phi_series_reproduces_64_and_70_term_bounds():
    law, reference = _binary_record_law(), .0427916441916780934
    for terms, width in ((64, 5.29231984256609e-12), (70, 7.90460386504392e-13)):
        result = law.information(tolerance=1e-12, terms=terms)
        assert result.bounds.lower <= reference <= result.bounds.upper
        assert math.exp(result.log_series_width) == pytest.approx(width, rel=1e-13)
        assert result.stats.series_terms == terms
    result = law.information(tolerance=1e-12)
    assert result.log_width <= math.log(1e-12)
    assert result.stats.series_terms == 70


@pytest.mark.parametrize("mixed,reference", [(False, .0393153919887595056), (True, .1678629519655597415)])
def test_u2_u3_information_conditions_on_all_pending_record_values(mixed, reference):
    result = _binary_record_law(mixed=mixed, pending=True).information(tolerance=1e-12)
    assert result.bounds.lower <= reference <= result.bounds.upper
    assert result.log_width <= math.log(1e-12)


def test_u3_joint_target_and_chain_decomposition_include_lambda():
    law = _binary_record_law(mixed=True)
    joint = law.information(tolerance=1e-12)
    latent = law.project_parameters().information(tolerance=1e-12)
    given = law.given_latent(tolerance=1e-12)
    assert joint.bounds.lower <= .2371573764346747423 <= joint.bounds.upper
    assert latent.bounds.midpoint == pytest.approx(.2157615543388356956, abs=1e-15)
    assert given.bounds.lower <= .0213958220958390467 <= given.bounds.upper
    assert joint.bounds.midpoint == pytest.approx(latent.bounds.midpoint + given.bounds.midpoint, abs=1e-12)


def test_u6_deterministic_latent_candidate_has_exact_zero_entropy_and_remainder():
    result = _binary_record_law(mixed=True).information(tolerance=1e-12, terms=64)
    assert math.exp(result.log_series_width) == pytest.approx(2.646159921283045e-12, rel=1e-13)
    measure = AtomicPolynomialMeasure({"x": _prior((1, 1), (1, 3))})
    for value in (0, 1):
        series = PhiSeries(measure, SimplexPolynomial.constant(measure.sizes, value))
        for _ in range(64):
            series.advance()
        assert series.log_value == series.log_remainder == -math.inf


def test_u4_pending_record_reveals_lambda_and_leaves_zero_conditional_information():
    cells = {z: {e: tuple(F(int(z == i and e == i)) for i in range(2)) for e in range(2)} for z in range(2)}
    result = _finite_eta_record_law((F(1, 2),) * 2, cells).information(tolerance=1e-12)
    assert result.bounds.lower == result.bounds.upper == 0
    assert result.log_width == -math.inf


def test_u4_o8_projecting_lambda_preserves_its_posterior_correlation_with_f():
    class IntervalSpecificMeasure:
        def history_kernel(self, timing, *, lam):
            whole = HistoryKernel(timing, lam.spec)
            kernels = []
            for attempt in whole.attempts:
                start, report = (timing.events[ref] for ref in (attempt.start_event, attempt.report_event))
                phase = lam.spec.params["phase"]
                if start.reading >= 12:
                    phase = {"point_ns": 3 if phase == "uniform" else 0}
                single = Timing({e.id: e for e in (start, report)}, (attempt,))
                kernels.append(HistoryKernel(single, _tick(4, phase)))
            def probability(durations):
                return math.prod((k({a.attempt: durations[a.attempt] for a in k.attempts})
                                  for k in kernels), start=F(1))
            # A kernel interface with all old/new trials, T already marginalized.
            return _Kernel(whole.attempts, probability)

    class _Kernel:
        def __init__(self, attempts, probability):
            self.attempts, self.probability = attempts, probability
        def __call__(self, durations):
            return self.probability(durations)

    measurement = IntervalSpecificMeasure()
    assert isinstance(measurement, QuantityMeasure)
    measure = _measure((_tick(4, {"point_ns": 0}), .5), (_tick(4, "uniform"), .5))
    law = AtomicRecordLaw.from_timings({"x": _prior((1, 1), (1, 3))}, measure,
        {"z": {r: _isolated_history((0, r)) for r in (0, 4)}},
        history=_isolated_history((0,)), measurement=measurement)
    marginal = law.project_latent().information(tolerance=1e-12)
    assert marginal.bounds.lower <= .0096212884228709242 <= marginal.bounds.upper
    given = law.given_latent(tolerance=1e-12)
    assert given.bounds.lower == given.bounds.upper == 0
    assert law.evidence == F(3, 4)


def test_u3_known_f_still_has_information_about_the_clock_from_actual_kernels():
    measure = _measure((_tick(4, {"point_ns": 0}), .5), (_tick(4, "uniform"), .5))
    law = AtomicRecordLaw.from_timings({"x": _prior((1,), (1,))}, measure,
        {"z": {r: _isolated_history((r,)) for r in (0, 4)}}, history=_isolated_history(()))
    assert law.information(tolerance=1e-12).bounds.midpoint == pytest.approx(.0956025889470326111, abs=1e-15)


def test_u10_external_start_phase_is_marginalized_before_entropy():
    law = AtomicRecordLaw.from_timings({"x": _prior((1,), (2,))}, _measure((_tick(4, "uniform"), 1.)),
        {"z": {r: _isolated_history((r,)) for r in (0, 4)}}, history=_isolated_history(()))
    assert tuple(law.expectation(v) for _, v in law.rows[0][1]) == (F(1, 2), F(1, 2))
    result = law.information(tolerance=1e-12)
    assert result.bounds.lower == result.bounds.upper == 0
    assert result.stats.series_terms == 0  # T would give log2, but W is known.


def _shared_check_record_law():
    priors, measure = {"x": _prior((1, 1), (1, 3))}, _measure((_tick(4, {"point_ns": 0}), 1.))
    arrived = _history([("sA", 0, "start", "A"), ("sB", 0, "start", "B"),
                        ("rB", 0, "report", "B"), ("c0", 0, "external", None)],
        (AttemptTiming("A", "jA", "x", "sA", ("rB", "c0"), None, "pending"),
         AttemptTiming("B", "jB", "x", "sB", (), "rB", "complete")))
    return AtomicRecordLaw.from_timings(priors, measure, {"z": {
        "pending": _coupled_pair_history(1, (None, None), same_action=True), "arrived": arrived}},
        history=_checked_history(1))


def test_u11_u12_shared_t_is_marginalized_before_prediction_and_conditional_moments():
    law = _shared_check_record_law()
    assert law.evidence == F(1, 2)
    assert law.expectation(dict(law.rows[0][1])["pending"]) / law.evidence == F(5, 6)
    result = law.conditional_variance("z", "pending", tolerance=1e-12)
    assert result.bounds()[0] <= .13203058762418829859 <= result.bounds()[1]
    assert result.log_width <= math.log(1e-12)
    assert result.bounds()[0] > 1 / 12


def test_d22_general_information_keeps_other_actions_f_when_candidate_duration_is_known():
    priors = {"b": _prior((1, 1), (1, 3)), "a": _prior((1,), (2,))}
    law = AtomicRecordLaw.from_timings(priors, _measure((_tick(4, "uniform"), 1.)),
        {"z": {r: _d22_history(r) for r in (0, 4)}}, history=_d22_history())
    assert law.evidence == F(5, 16)
    result = law.information(tolerance=1e-12)
    assert result.bounds.lower <= .0015967840886618202613 <= result.bounds.upper
    assert result.bounds.lower > 0
    assert result.log_width <= math.log(1e-12)


def test_u13_entropy_identity_1000_terms_keeps_positive_remainder_beyond_float_endpoint_resolution():
    law = _finite_eta_record_law((F(1, 2),) * 2, {"z": {
        "pending": (F(17, 32), F(9, 32)), "arrived": (F(3, 32), F(3, 32))}})
    reference = .007508706066214646434704861
    coarse = law.information(tolerance=1e-12, terms=64)
    assert coarse.bounds.lower <= reference <= coarse.bounds.upper
    fine = law.information(tolerance=1e-12, terms=1000)
    assert fine.bounds.midpoint == pytest.approx(reference, abs=1e-15)
    assert math.exp(fine.log_width) == pytest.approx(3.2052618673138847e-46, rel=1e-13)
    assert fine.bounds.lower == fine.bounds.upper and math.isfinite(fine.log_width)


def test_u13_nonuniform_z_weights_are_in_the_entropy_identity():
    law = _finite_eta_record_law((F(1, 2),) * 2,
        {0: {0: (F(1, 8), F(1, 8)), 1: (F(1, 8), F(3, 8))},
         1: {0: (F(1, 8), F(1, 16)), 1: (F(1, 8), F(1, 16))}})
    assert law.evidence == F(9, 16)
    assert tuple(law.expectation(a) / law.evidence for _, _, a in law.rows) == (F(2, 3), F(1, 3))
    result = law.information(tolerance=1e-12, terms=128)
    assert result.bounds.lower <= .0203833411304169878573 <= result.bounds.upper


def test_u5_low_level_eight_branch_information_and_its_two_parts():
    cells = {z: {v: tuple(F(int((i // 2 if z == 0 else i % 2) == v), 2) for i in range(4))
                 for v in range(2)} for z in range(2)}
    joint = _finite_eta_record_law((F(1, 4),) * 4, cells).information(tolerance=1e-12)
    parts = []
    for part in range(2):
        table = {z: (cells[z] if part == z else {0: (F(1, 2),) * 4}) for z in range(2)}
        parts.append(_finite_eta_record_law((F(1, 4),) * 4, table).information(tolerance=1e-12))
    assert joint.bounds.midpoint == pytest.approx(math.log(2), abs=1e-15)
    assert tuple(p.bounds.midpoint for p in parts) == pytest.approx((math.log(2) / 2,) * 2, abs=1e-15)


@pytest.mark.parametrize("axis", ["E", "Z"])
def test_u7_entropy_tail_bounds_cover_aggregation_and_z_omission_misses_true_information(axis):
    if axis == "Z":
        # E=eta XOR Z, eta and Z are independent fair bits: I(eta;E|Z)=log2.
        # Dropping Z gives I(eta;E)=0.
        tails = EntropyTailBounds(-math.inf, math.log(math.log(2)))
        cells = {"other": {e: (F(1, 2), F(1, 2)) for e in range(2)}}
    else:
        tails = EntropyTailBounds(math.log(math.log(2)), -math.inf)
        cells = {"z": {"other": (F(1), F(1))}}
    result = _finite_eta_record_law((F(1, 2),) * 2, cells, tails=tails).information(tolerance=2.)
    assert result.bounds.lower <= math.log(2) <= result.bounds.upper + 1e-15
    assert result.log_width == pytest.approx(tails.log_width)
    omitted = _finite_eta_record_law((F(1, 2),) * 2, cells).information(tolerance=1e-12)
    assert omitted.bounds.upper == 0 < math.log(2)


@pytest.mark.parametrize("repeats", [0, 1, 10, 1000])
def test_o11_identical_history_likelihoods_do_not_change_latent_odds(repeats):
    likelihood = F(1, 3) ** repeats
    law = _finite_eta_record_law((F(1, 4), F(3, 4)), {"z": {
        0: (likelihood, F(0)), 1: (F(0), likelihood)}})
    assert tuple(w * law.measure.expectation(p) / law.evidence for w, p in zip(law.weights, law.history)) == (F(1, 4), F(3, 4))
    result = law.information(tolerance=1e-12)
    assert result.bounds.midpoint == pytest.approx(-.25 * math.log(.25) - .75 * math.log(.75), abs=1e-12)


def test_o5_latent_clones_preserve_information_and_series_width_exactly():
    law = _binary_record_law(mixed=True)
    cells = {z: {e: (values[0], values[0], values[1]) for e, values in records} for z, records, _ in law.rows}
    cloned = AtomicRecordLaw(law.measure, (F(1, 4), F(1, 4), F(1, 2)), cells)
    assert cloned.information(tolerance=1e-12, terms=64) == law.information(tolerance=1e-12, terms=64)


def test_u1_phi_of_a_monomial_uses_closed_dirichlet_log_moment():
    measure = AtomicPolynomialMeasure({"x": _prior((1, 1), (1, 3))})
    p = SimplexPolynomial((2,), (2,), {(2, 0): F(1, 2)})
    series = PhiSeries(measure, p, closed_forms=True)
    assert math.exp(series.log_value) == pytest.approx(math.log(2) / 6 + 1 / 9, abs=1e-15)
    assert series.log_remainder == -math.inf


@pytest.mark.parametrize("beta", [(F(1, 2), F(1, 2)), (F(2, 3), F(7, 3))])
def test_u1_scipy_closed_phi_real_parameters_match_independent_beta_integral(beta):
    from scipy.integrate import quad
    from scipy.special import betaln
    measure = AtomicPolynomialMeasure({"x": _prior(beta, (1, 3))})
    p = SimplexPolynomial((2,), (2,), {(2, 0): F(1, 2)})
    series = PhiSeries(measure, p, closed_forms=True)
    b0, b1 = map(float, measure.beta[0])
    def integrand(x):
        probability = x * x / 2
        return (-probability * math.log(probability)
                * math.exp((b0 - 1) * math.log(x) + (b1 - 1) * math.log1p(-x) - betaln(b0, b1)))
    reference, error = quad(integrand, 0., 1., epsabs=1e-13, epsrel=1e-13)
    assert error < 1e-12
    assert math.exp(series.log_value) == pytest.approx(reference, abs=1e-12, rel=0)
    assert series.log_remainder == -math.inf


def test_u9_entropy_keeps_both_tiny_p_and_tiny_one_minus_p_in_logs():
    tiny = F(1, 10 ** 400)
    assert math.isfinite(_log_phi_fraction(tiny))
    assert _log_phi_fraction(tiny) == pytest.approx(-400 * math.log(10) + math.log(400 * math.log(10)), abs=1e-12)
    assert _log_phi_fraction(1 - tiny) == pytest.approx(-400 * math.log(10), abs=1e-12)


def test_y9_information_series_resource_budget_is_incomplete_computation():
    with pytest.raises(IntegrationIncomplete, match="series-work"):
        _binary_record_law().information(tolerance=1e-12, series_budget=1)
    with pytest.raises(IntegrationIncomplete, match="series-work"):
        _shared_check_record_law().conditional_variance("z", "pending", tolerance=1e-12, series_budget=1)
    fixed = _finite_eta_record_law((F(1, 2),) * 2, {"z": {"other": (F(1), F(1))}},
                                 tails=EntropyTailBounds(math.log(.1), -math.inf))
    with pytest.raises(IntegrationIncomplete, match="aggregation"):
        fixed.information(tolerance=1e-12)


def _isolated_timing(reading):
    return _history([("s", 0, "start", "a"), ("r", reading, "report", "a")],
                    (AttemptTiming("a", "j", "x", "s", (), "r", "complete"),))


def _unit_uniform_prior(alpha):
    return DurationPrior(alpha, BaseSpec("piecewise", "1", {"edges_ns": [0, 1], "masses": [1.],
        "tail": {"kind": "pareto", "kappa": 1., "mass": 0.}, "p_inf": 0.}))


def test_u7_concrete_pareto_record_entropy_tail_after_history_and_lambda_mixture():
    base = BaseSpec("piecewise", "1", {"edges_ns": [0, 1], "masses": [0.],
        "tail": {"kind": "pareto", "kappa": 1., "mass": 1.}, "p_inf": 0.})
    measure = _measure((_tick(1, "uniform"), 1.))
    bound = RecordTailBound(base, measure, 0.)
    # 独立の閉じたq_r=log(r²/(r²−1))、q_tail=log(R/(R−1))。
    cutoff, stop = 8, 10000
    q_tail = math.log1p(1 / (cutoff - 1))
    partial = math.fsum(-q * math.log(q) for r in range(cutoff, stop)
                        for q in [math.log1p(1 / (r * r - 1))])
    reference_lower = partial + q_tail * math.log(q_tail)
    reference_upper = reference_lower + math.exp(bound.log_bound(stop))
    assert 0 < reference_lower <= reference_upper < math.exp(bound.log_bound(cutoff))
    assert bound.log_bound(16) < bound.log_bound(8)
    # 極小の履歴で条件づける増幅と、複数λも同じ正規化前の支配で扱う。
    mixed = RecordTailBound(base, _measure((_tick(1, "uniform"), .25),
                                         (_tick(2, {"point_ns": 0}), .75)), math.log(.1))
    assert mixed.log_bound(32) > bound.log_bound(32)
    with pytest.raises(ValueError, match="below 1/e"):
        bound.log_bound(2)


def test_u7_record_tail_separates_permanent_nonarrival_from_finite_tail():
    base = BaseSpec("piecewise", "1", {"edges_ns": [0, 1], "masses": [.5],
        "tail": {"kind": "pareto", "kappa": 1., "mass": 0.}, "p_inf": .5})
    assert RecordTailBound(base, _measure((_tick(1, "uniform"), 1.)), 0.).log_bound(3) == -math.inf
    assert RecordTailBound(_prior((1, 1), (1, None)).base,
                          _measure((_tick(1, "uniform"), 1.)), 0.).log_bound(3) == -math.inf


def test_u14_general_piecewise_replicas_share_f_and_keep_complements_positive():
    event = KernelEvent((HistoryKernel(_isolated_timing(0), _tick(1, "uniform")),))
    backend = ReplicaMoments({"x": _unit_uniform_prior(1)})
    first = backend.expectation(event, tolerance=1e-12)
    square = backend.expectation(ReplicaProduct((event, event)), tolerance=1e-12)
    variance = backend.expectation(ReplicaProduct((event, event.complement())), tolerance=1e-12)
    assert first.log_error == square.log_error == variance.log_error == -math.inf
    assert math.exp(first.log_value) == pytest.approx(1/2)
    assert math.exp(square.log_value) == pytest.approx(7/24)
    assert math.exp(variance.log_value) == pytest.approx(5/24)
    assert backend.partitions == 5


def test_u10_u14_replicas_share_the_whole_f_but_not_external_t_between_copies():
    timing = _history([("sA", 0, "start", "A"), ("sB", 0, "start", "B"),
                       ("c", 0, "external", None)],
        (AttemptTiming("A", "jA", "a", "sA", ("c",), None, "pending"),
         AttemptTiming("B", "jB", "b", "sB", ("c",), None, "pending")))
    event = KernelEvent((HistoryKernel(timing, _tick(4, {"point_ns": 0})),))
    backend = ReplicaMoments({a: _prior((1,), (2,)) for a in ("a", "b")})
    once = backend.expectation(event, tolerance=1e-12)
    twice = backend.expectation(ReplicaProduct((event, event)), tolerance=1e-12)
    complement = backend.expectation(ReplicaProduct((event, event.complement())), tolerance=1e-12)
    assert math.exp(once.log_value) == pytest.approx(.5)
    assert math.exp(twice.log_value) == pytest.approx(.25)
    assert math.exp(complement.log_value) == pytest.approx(.25)


def test_d16_replica_union_disjointizes_duplicate_records_and_keeps_same_external_law():
    zero = HistoryKernel(_isolated_timing(0), _tick(1, "uniform"))
    one = HistoryKernel(_isolated_timing(1), _tick(1, "uniform"))
    backend = ReplicaMoments({"x": _unit_uniform_prior(1)})
    duplicate = backend.expectation(KernelEvent((zero, zero)), tolerance=1e-12)
    whole = backend.expectation(KernelEvent((zero, one)), tolerance=1e-12)
    outside = backend.expectation(KernelEvent((zero, one), True), tolerance=1e-12)
    assert math.exp(duplicate.log_value) == pytest.approx(.5)
    assert math.exp(whole.log_value) == pytest.approx(1.)
    assert outside.log_upper == -math.inf
    incompatible = HistoryKernel(_checked_history(1, complete=True), _tick(1, "uniform"))
    with pytest.raises(ValueError, match="same external conditions"):
        KernelEvent((zero, incompatible))


def test_y9_replica_partition_resource_budget_is_not_numerical_range():
    event = KernelEvent((HistoryKernel(_isolated_timing(0), _tick(1, "uniform")),))
    backend = ReplicaMoments({"x": _uniform_prior(1)})
    with pytest.raises(IntegrationIncomplete, match="partition resource"):
        backend.expectation(ReplicaProduct((event, event)), tolerance=1e-12, partition_budget=1)


def _general_isolated_record_law(prior, measure):
    width = measure.candidates[-1].spec.params["width_ns"]
    cells = {"z": {r: tuple(KernelEvent((HistoryKernel(_isolated_timing(r), c.spec),))
                           for c in measure.candidates) for r in (0, width)}}
    return GeneralRecordLaw({"x": prior}, tuple(c.weight for c in measure.candidates), cells)


def test_u14_piecewise_phi_replicas_reduce_to_exact_multiplicity_moments():
    law = _general_isolated_record_law(_unit_uniform_prior(1), _measure((_tick(1, "uniform"), 1.)))
    result = law.information(tolerance=1e-12, terms=2)
    assert result.bounds.lower == pytest.approx(math.log(2) - F(31, 48))
    assert result.bounds.upper == pytest.approx(math.log(2) - F(25, 48))
    assert math.exp(result.log_series_width) == pytest.approx(F(1, 8))


def test_u2_general_replicas_information_matches_atom_polynomial_fixed_value():
    law = _general_isolated_record_law(_prior((1, 1), (1, 3)), _measure((_tick(4, "uniform"), 1.)))
    result = law.information(tolerance=1e-12, terms=64)
    assert result.bounds.lower <= .0427916441916780934 <= result.bounds.upper
    assert math.exp(result.log_width) == pytest.approx(5.29231984256609e-12, rel=1e-10)


def test_u3_u6_general_replicas_skip_deterministic_lambda_phi_remainders():
    law = _general_isolated_record_law(_prior((1, 1), (1, 3)), _measure(
        (_tick(4, {"point_ns": 0}), .5), (_tick(4, "uniform"), .5)))
    result = law.information(tolerance=1e-12, terms=64)
    assert result.bounds.lower <= .2371573764346747423 <= result.bounds.upper
    assert math.exp(result.log_width) == pytest.approx(2.646159921283045e-12, rel=1e-10)


def test_d16_general_record_law_checks_overlap_and_same_context_history_partition():
    zero = KernelEvent((HistoryKernel(_isolated_timing(0), _tick(1, "uniform")),))
    one = KernelEvent((HistoryKernel(_isolated_timing(1), _tick(1, "uniform")),))
    history = KernelEvent((HistoryKernel(_history([("s", 0, "start", "a")],
        (AttemptTiming("a", "j", "x", "s", (), None, "pending"),)), _tick(1, "uniform")),))
    valid = GeneralRecordLaw({"x": _unit_uniform_prior(1)}, (1,), {"z": {0: (zero,), 1: (one,)}}, history=(history,))
    valid.information(tolerance=1e-12, terms=0)
    omitted = GeneralRecordLaw({"x": _unit_uniform_prior(1)}, (1,), {"z": {0: (zero,)}}, history=(history,))
    with pytest.raises(ValueError, match="record sum differs"):
        omitted.information(tolerance=1e-12, terms=0)
    overlap = GeneralRecordLaw({"x": _unit_uniform_prior(1)}, (1,), {"z": {0: (zero,), 1: (zero,)}})
    with pytest.raises(ValueError, match="records overlap"):
        overlap.information(tolerance=1e-12, terms=0)


def _previous_run_history(*, report=None, state="pending", boot=8):
    events = {"s": TimingEvent("s", "old", 0, 0, 0, "start", "a"),
              "c": TimingEvent("c", "old", 0, 1, 0, "external", None),
              "boot": TimingEvent("boot", "new", 1, 0, boot, "external", None)}
    if report is not None:
        events["r"] = TimingEvent("r", "new", 1, 1, report, "report", "a")
    return Timing(events, (AttemptTiming("a", "j", "x", "s", ("c",),
                        "r" if report is not None else None, state),))


def test_d24_previous_run_keeps_same_latent_duration_and_new_sample_prediction():
    belief = atoms_posterior({"x": _prior((1, 1), (1, 3))},
                            _measure((_tick(4, {"point_ns": 0}), 1.)), _previous_run_history())
    assert belief.fraction_evidence == F(1, 2)
    assert math.exp(belief.allocated({"a": 1})) == pytest.approx(1/4)
    assert math.exp(belief.allocated({"a": 3})) == pytest.approx(3/4)
    assert belief.fraction_new_value("x") == {1: F(5, 12), 3: F(7, 12)}


def test_d24_cross_run_receipt_conditions_old_draw_finite_without_using_clock():
    priors, measure = {"x": _prior((1, 1), (1, None))}, _measure((_tick(4, {"point_ns": 0}), 1.))
    before = atoms_posterior(priors, measure, _previous_run_history())
    assert before.fraction_evidence == F(5, 8)
    assert math.exp(before.allocated({"a": 1})) == pytest.approx(1/5)
    assert math.exp(before.allocated({"a": None})) == pytest.approx(4/5)
    after = atoms_posterior(priors, measure, _previous_run_history(report=9, state="unknown"))
    assert after.fraction_evidence == F(1, 8)
    assert after.fraction_new_value("x") == {1: F(2, 3), None: F(1, 3)}
    kernel = HistoryKernel(after.timing, measure.candidates[0].spec)
    assert "r" not in kernel.external_ids and kernel.dimension == 2


def test_d24_long_finite_durations_ignore_cross_run_receipt_reading():
    belief = atoms_posterior({"x": _prior((1, 1), (9, 13))},
        _measure((_tick(4, {"point_ns": 0}), 1.)), _previous_run_history(report=8, state="unknown", boot=4))
    assert belief.fraction_evidence == 1
    assert belief.fraction_new_value("x") == {9: F(1, 2), 13: F(1, 2)}


def test_d24_old_run_completion_is_still_complete():
    timing = _history([("s", 0, "start", "a"), ("r", 0, "report", "a")],
                     (AttemptTiming("a", "j", "x", "s", (), "r", "complete"),))
    timing = Timing(dict(timing.events, boot=TimingEvent("boot", "new", 1, 0, 8, "external", None)), timing.attempts)
    kernel = HistoryKernel(timing, _tick(4, {"point_ns": 0}))
    assert kernel.attempts[0].state == "complete"
    assert kernel({"a": 1}) == 1 and kernel({"a": None}) == 0


def test_d25_cross_run_receipt_is_absent_from_free_times_normalizer_and_other_checks():
    events = dict(_previous_run_history(report=8, state="unknown", boot=4).events)
    events["s_b"] = TimingEvent("s_b", "new", 1, 1, 8, "start", "b")
    events["r"] = TimingEvent("r", "new", 1, 2, 8, "report", "a")
    attempts = (AttemptTiming("a", "j_a", "x", "s", ("c",), "r", "unknown"),
                AttemptTiming("b", "j_b", "y", "s_b", ("r",), None, "pending"))
    belief = atoms_posterior({"x": _prior((1,), (9,)), "y": _prior((1, 1), (2, 3))},
        _measure((_tick(4, {"point_ns": 0}), 1.)), Timing(events, attempts))
    kernel = HistoryKernel(belief.timing, belief.measure.candidates[0].spec)
    assert "r" not in kernel.external_ids
    assert kernel.attempts[1].check_events == ()
    assert belief.fraction_new_value("y") == {2: F(1, 2), 3: F(1, 2)}


def _future_belief(prior=None, measure=None):
    timing = _history([("boot", 0, "external", None)], ())
    return posterior({"x": prior or _prior((1, 1), (1, 3))},
        measure or _measure((_tick(4, "uniform"), 1.)), timing)


def test_y7_quantity_public_posterior_protocol_and_old_vs_new_draw_queries():
    belief = posterior({"x": _prior((1, 1), (1, 3))},
        _measure((_tick(4, {"point_ns": 0}), 1.)), _previous_run_history())
    assert isinstance(belief, ValueBelief)
    assert belief.value_space == ValueSpace("quantity", "1")
    old = belief.predictive(QuantityQuery("x", 1, 2, "a"))
    new = belief.predictive(QuantityQuery("x", 1, 2))
    assert math.exp(old.log_lower) == pytest.approx(1/4) and math.exp(old.log_upper) == pytest.approx(1/4)
    assert math.exp(new.log_lower) == pytest.approx(5/12) and math.exp(new.log_upper) == pytest.approx(5/12)


def test_d18_context_preserves_fact_identity_and_adds_distinct_equal_tick_and_thought():
    timing = _checked_history(1)
    measure = _measure((_tick(4, {"point_ns": 0}), 1.))
    priors = {"x": _prior((1, 1), (1, 3))}
    run = next(iter(timing.events.values())).run
    check = timing.attempts[0].check_events[0]
    reading = timing.events[check].reading
    same = timing_context(timing, run=run, observed_ns=reading, check_events=({"fact": str(check)},))
    assert same == timing
    expected = atoms_posterior(priors, measure, timing).fraction_new_value("x")
    assert atoms_posterior(priors, measure, same).fraction_new_value("x") == expected
    for kind in ("tick", "thought"):
        extra = timing_context(timing, run=run, observed_ns=reading,
            check_events=({"unrecorded": {"kind": kind, "reading": reading, "after": ["head"]}},),
            fact_ancestors={"head": frozenset(timing.events)})
        assert len(extra.attempts[0].check_events) == len(timing.attempts[0].check_events) + 1
        assert atoms_posterior(priors, measure, extra).fraction_new_value("x") != expected


def test_d25_excluded_receipt_provenance_never_becomes_a_new_check():
    timing = _previous_run_history(report=8, state="unknown", boot=4)
    context = timing_context(timing, run="new", observed_ns=8, check_events=({"fact": "r"},))
    assert context == timing
    kernel = HistoryKernel(context, _tick(4, {"point_ns": 0}))
    assert "r" not in kernel.external_ids


def test_d16_future_record_cells_sum_to_same_history_kernel_pointwise():
    belief = _future_belief(_prior((1, 1, 1), (1, 3, None)),
        _measure((_tick(4, {"point_ns": 0}), .5), (_tick(4, "uniform"), .5)))
    table = belief.future_records(FutureRecordsQuery("x", 4, "run"))
    cells = table.build()
    for lam, kernel in enumerate(table.kernels):
        for d in (1, 3, None):
            allocation = {table.candidate.attempt: d}
            assert sum(cell[lam](allocation) for row in cells.values() for cell in row.values()) == kernel(allocation)


def test_u2_u3_public_future_record_information_and_cloned_lambda():
    point, uniform = _tick(4, {"point_ns": 0}), _tick(4, "uniform")
    for measure, expected in ((_measure((uniform, 1.)), .0427916441916780934),
                             (_measure((point, .5), (uniform, .5)), .2371573764346747423),
                             (_measure((point, .25), (point, .25), (uniform, .5)), .2371573764346747423)):
        result = _future_belief(measure=measure).information("distribution", FutureRecordsQuery("x", 4, "run"), None)
        assert result.lower <= expected <= result.upper
        assert result.upper - result.lower <= 1e-12


def test_d24_future_old_run_z_retains_finite_and_infinite_without_numeric_time():
    belief = posterior({"x": _prior((1, 1), (1, None)), "y": _prior((1,), (1,))},
        _measure((_tick(4, {"point_ns": 0}), 1.)), _previous_run_history())
    table = belief.future_records(FutureRecordsQuery("y", 12, "new", (("j", "x"),)))
    assert table._labels(table.waiting[0]) == ("finite", "infinite")
    masks = table.arrival_masks(tolerance=1e-12)
    assert math.exp(masks[(True,)][0].log_lower) == pytest.approx(1/5)
    assert math.exp(masks[(False,)][0].log_lower) == pytest.approx(4/5)
    result = table.information()
    assert result.bounds.lower == result.bounds.upper == 0.


def test_u14_public_piecewise_records_preserve_selector_union_and_phi_moments():
    belief = _future_belief(_unit_uniform_prior(1), _measure((_tick(1, "uniform"), 1.)))
    table = belief.future_records(FutureRecordsQuery("x", 1, "run"))
    result = table.information(terms=2)
    assert result.bounds.lower == pytest.approx(math.log(2) - F(31, 48))
    assert result.bounds.upper == pytest.approx(math.log(2) - F(25, 48))
    cells = table.cells[(), ()]
    backend = ReplicaMoments(belief.priors)
    zero, one = cells[1, 0][0], cells[2, 0][0]
    whole = backend.expectation(UnionEvent((zero, one)), tolerance=1e-12)
    assert math.exp(whole.log_value) == pytest.approx(1.)
    square = backend.expectation(ReplicaProduct((zero, zero)), tolerance=1e-12)
    assert math.exp(square.log_value) == pytest.approx(7/24)


def test_u7_model_record_table_carries_concrete_e_and_z_tail_bounds():
    prior = DurationPrior(1., BaseSpec("piecewise", "1", {"edges_ns": [0, 1], "masses": [.5],
        "tail": {"kind": "pareto", "kappa": 1., "mass": .5}, "p_inf": 0.}))
    timing = _history([("boot", 0, "external", None), ("s", 1, "start", "a")],
                     (AttemptTiming("a", "j", "x", "s", (), None, "pending"),))
    belief = posterior({"x": prior}, _measure((_tick(1, "uniform"), 1.)), timing)
    table = belief.future_records(FutureRecordsQuery("x", 2, "run", (("j", "x"),)), tolerance=.1)
    table.cutoff = 8
    table.build()
    assert table.tails.log_e == table.tails.log_z > -math.inf
    assert math.exp(table.tails.log_width) == pytest.approx(3 * math.exp(table.tails.log_e))
    assert (("other",), ("a",)) in table.cells
    assert ("other", 0) in table.cells[("other",), ("a",)]


def test_d13_guaranteed_receipt_horizon_excludes_later_check():
    events = dict(_checked_history(1).events)
    events["later"] = TimingEvent("later", "run", 0, 2, 4, "external", None)
    timing = Timing(events, (AttemptTiming("a", "j", "x", "s", ("c0", "later"), None, "pending"),))
    context = timing_context(timing, run="run", observed_ns=0, check_events=({"fact": "c0"},))
    assert context.attempts[0].check_events == ("c0",)
    belief = posterior({"x": _prior((1, 1), (1, 3))}, _measure((_tick(4, {"point_ns": 0}), 1.)), context)
    assert belief.base.fraction_evidence == F(1, 2)
    assert belief.base.fraction_new_value("x") == {1: F(5, 12), 3: F(7, 12)}


def test_u14_public_piecewise_adaptive_information_reaches_width_without_fixed_replica_degree():
    prior = DurationPrior(2., BaseSpec("piecewise", "1", {"edges_ns": [0, 1, 3], "masses": [0., 1.],
        "tail": {"kind": "pareto", "kappa": 1., "mass": 0.}, "p_inf": 0.}))
    measure = _measure((_tick(4, "uniform"), 1.))
    table = _future_belief(prior, measure).future_records(FutureRecordsQuery("x", 4, "run"))
    fixed = table.information(terms=20)
    adaptive = table.information(series_budget=100)
    assert fixed.bounds.lower <= adaptive.bounds.lower <= adaptive.bounds.upper <= fixed.bounds.upper
    assert adaptive.stats.series_terms > fixed.stats.series_terms
    assert adaptive.bounds.upper - adaptive.bounds.lower <= 1e-12


def _entry_rig(model=None, *, booted=True):
    from sui.agent import Agent
    from sui.clock import FakeClock
    from sui.ids import Ref, RefKind, SequentialIds
    from sui.ledger import Ledger, SequentialSalts
    from sui.records import Producer
    from sui.loop import boot
    model = model or _quantity_model(learnable=frozenset(),
        a={a: np.array([[1.], [0.]]) for a in ("a", "b")},
        duration_priors={a: _prior((1, 1), (1, 3)) for a in ("a", "b")})
    rig = SimpleNamespace(model=model, agent=Agent(model=model, lineage="quantity"),
        clock=FakeClock(run=Ref(RefKind.RUN, "quantity")), ids=SequentialIds(prefix="quantity"),
        ledger=Ledger(salts=SequentialSalts()), membrane=Producer(component="test.quantity", code_version="1"))
    rig.agent.belief_record(clock=rig.clock, ids=rig.ids, ledger=rig.ledger)
    if booted:
        rig.boot = boot(rig.agent, clock=rig.clock, ids=rig.ids, ledger=rig.ledger, membrane=rig.membrane)
        rig.clock.advance(4)
    return rig


def _entry_start(rig, action="a"):
    from sui.ids import Ref, RefKind
    from sui.records import Record, Role, JobOpened, AttemptStarted, Payload
    from sui.s1_contracts import ACTION, ATTEMPT
    # 実際の記録の読みの入力。候補にできない∞を持つ進行中も組み立てる。
    job = Record(id=rig.ids.new(RefKind.JOB), at=rig.clock.now(), writer=Role.MODEL,
        producer=rig.agent.producer, body=JobOpened(decision=Ref(RefKind.DECISION, "history"), step=0,
            contract=ACTION, content=Payload.json({"action": action})))
    rig.ledger.append(job, rig.ledger.heads())
    attempt = Record(id=rig.ids.new(RefKind.ATTEMPT), at=rig.clock.now(), writer=Role.MEMBRANE,
        producer=rig.membrane, body=AttemptStarted(job=job.id, contract=ATTEMPT, content=Payload.json({})))
    rig.ledger.accept(attempt)
    rig.agent.adopt(rig.ledger, clock=rig.clock, ids=rig.ids)
    return job, attempt


def _entry_view(rig, **kwargs):
    """この試験で指定した既存の受け取りを、読みの一致に頼らず渡す。"""
    if "check_events" not in kwargs:
        events = [e for e in rig.agent._reading.timing.events.values()
                  if e.run == rig.clock.run and e.kind != "start" and e.reading == kwargs.get("observed_ns")]
        event = max(events, key=lambda e: (e.seq, str(e.id)))
        kwargs["check_events"] = ({"fact": str(event.id)},)
    return rig.agent.view(**kwargs)


def _entry_receipt(rig, attempt=None, *, outcome="x", contract=None):
    from sui.ids import RefKind
    from sui.records import Record, Role, Observed, Payload
    from sui.s1_contracts import OUTCOME
    record = Record(id=rig.ids.new(RefKind.OBSERVATION), at=rig.clock.now(), writer=Role.MEMBRANE,
        producer=rig.membrane, body=Observed(route="hand", caused_by=None if attempt is None else attempt.id,
            contract=contract or OUTCOME, content=Payload.json({"outcome": outcome}), received_ns=rig.clock.mono_ns()))
    rig.ledger.accept(record)
    rig.agent.adopt(rig.ledger, clock=rig.clock, ids=rig.ids)
    return record


def test_u5_production_one_step_conditions_arrival_mark_before_names_duration_decomposition():
    from sui.agent import plan
    model = _quantity_model(states=("s", "t"), D=np.array([.5, .5]), learnable=frozenset(),
        a={a: np.eye(2) for a in ("a", "b")},
        duration_priors={"a": _prior((1, 1), (1, None)), "b": _prior((1,), (1,))},
        measure=_measure((_tick(4, {"point_ns": 0}), .5), (_tick(4, {"point_ns": 3}), .5)))
    rig = _entry_rig(model)
    _entry_start(rig)
    data = plan(_entry_view(rig, now_ns=8, observed_ns=0), ["b"], u=.5).content.as_json()
    part = data["information_parts"][0]
    assert part["names"] == pytest.approx(math.log(2)/2)
    # §4-6: この端点の閉じた式は計算誤差0、表示の丸めは包みの外。
    rounding = 4 * math.ulp(math.log(2))
    assert part["durations"][0] - rounding <= math.log(2)/2 <= part["durations"][1] + rounding
    lo, hi = data["information_bounds"][0]
    assert lo - rounding <= math.log(2) <= hi + rounding and hi - lo <= data["tolerance"]


def test_d24_production_old_run_infinite_branch_keeps_conditional_name_information():
    from sui.names import NameBelief
    model = _quantity_model(states=("s", "t"), actions=("x", "y"), D=np.array([.5, .5]),
        learnable=frozenset(), a={a: np.eye(2) for a in ("x", "y")},
        duration_priors={"x": _prior((1, 1), (1, None)), "y": _prior((1,), (1,))},
        measure=_measure((_tick(4, {"point_ns": 0}), 1.)))
    quantity = posterior(model.duration_priors, model.measure, _previous_run_history())
    names = NameBelief(model, SimpleNamespace(n={a: np.zeros(2, dtype=int) for a in model.actions}, sequence=()))
    result = one_step_values(quantity, names, (("j", "x"),), FutureRecordsQuery("y", 12, "new"),
                             np.zeros(2), tolerance=1e-12)
    assert result.names_information == pytest.approx(.5545177444479562475)
    assert result.durations_information.lower == result.durations_information.upper == 0.
    assert result.information.lower == pytest.approx((4/5)*math.log(2))


@pytest.mark.parametrize("horizon", [0, 4])
def test_y3_entry_rejects_legacy_lookahead_even_zero_and_permanently_missing_candidate(horizon):
    from sui.agent import plan, plan_s4c
    from sui.lookahead import OutsideEvaluationType
    from sui.records import Preference, Record, Role, Payload
    from sui.ids import RefKind
    from sui.s4d_contracts import PREFERENCE
    rig = _entry_rig()
    with pytest.raises(ValueError, match="plan_s4c: learned durations"):
        plan_s4c(rig.agent.view(), ["a"], u=.5)
    style = Record(id=rig.ids.new(RefKind.PREFERENCE), at=rig.clock.now(), writer=Role.MODEL,
        producer=rig.agent.producer, body=Preference(basis=(), contract=PREFERENCE,
            content=Payload.json({"kind": "style", "H_ns": horizon, "gamma": 1.})))
    rig.ledger.append(style, rig.ledger.heads())
    rig.agent.adopt(rig.ledger, clock=rig.clock, ids=rig.ids)
    with pytest.raises(OutsideEvaluationType, match="lookahead with learned durations is 1d"):
        plan(_entry_view(rig, now_ns=4, observed_ns=0), ["a"], u=.5)
    other = _entry_rig(_quantity_model())
    with pytest.raises(OutsideEvaluationType, match="every candidate"):
        plan(_entry_view(other, now_ns=4, observed_ns=0), ["a"], u=.5)


def test_y4_entry_empty_boot_and_all_quantity_belief_fields_restore_from_facts():
    from sui.agent import Agent
    from sui.s4b_contracts import QUANTITY_BELIEF
    rig = _entry_rig(booted=False)
    before = rig.agent._belief
    data = before.body.content.as_json()
    assert before.body.contract == QUANTITY_BELIEF
    assert data["measure"] == {"weights": [1.]}
    assert data["quantity"] == {"partitions": 1}
    assert data["time"]["anchor"] is None
    restored = Agent.restore(model=rig.model, lineage="restored", ledger=rig.ledger,
                             belief=rig.ledger.entries_of(before.id)[0].cid)
    assert restored._belief.body.content == before.body.content
    rig = _entry_rig()
    _, attempt = _entry_start(rig)
    _entry_receipt(rig, attempt)
    belief = rig.agent._belief
    data = belief.body.content.as_json()
    assert data["durations"]["a"] == {"complete": 1, "pending": 0, "queued": 0, "unknown": 0, "unreadable": 0}
    restored = Agent.restore(model=rig.model, lineage="restored", ledger=rig.ledger,
                             belief=rig.ledger.entries_of(belief.id)[0].cid)
    assert restored._belief.body.content == belief.body.content


@pytest.mark.parametrize("field,bad", [("measure", {"weights": [True]}), ("measure", {"weights": [.5]}),
    ("measure", {"weights": []}), ("quantity", {"partitions": True}), ("quantity", {"partitions": -1}),
    ("durations", {}), ("quantity", {"partitions": 1, "extra": 0})])
def test_y4_entry_quantity_belief_validates_every_new_column_type(field, bad):
    from sui.agent import _check_belief_content
    rig = _entry_rig()
    data = rig.agent._belief.body.content.as_json()
    data[field] = bad
    with pytest.raises(ValueError):
        _check_belief_content(data, quantity_model=rig.model)


def test_y4_entry_duration_impossible_and_broken_axis_have_distinct_boundary_values():
    from sui.clock import FakeClock
    from sui.ids import Ref, RefKind
    from sui.records import Observed, Record, Role, Payload
    from sui.s4_contracts import BOOT
    model = _quantity_model(learnable=frozenset(), duration_priors={a: _prior((1,), (1,)) for a in ("a", "b")},
        measure=_measure((_tick(4, {"point_ns": 0}), 1.)))
    rig = _entry_rig(model)
    _entry_start(rig)
    rig.clock.advance(4)
    _entry_receipt(rig)  # D=1では読み8まで未着である履歴を説明できない。
    data = rig.agent._belief.body.content.as_json()
    assert data["q"] is not None and data["measure"]["weights"] is None
    assert data["quantity"]["partitions"] == 0
    rig = _entry_rig()
    clock = FakeClock(run=Ref(RefKind.RUN, "concurrent"), run_index=0)
    duplicate = Record(id=rig.ids.new(RefKind.OBSERVATION), at=clock.now(), writer=Role.MEMBRANE,
        producer=rig.membrane, body=Observed(route="membrane", content=Payload.json({}), contract=BOOT, received_ns=0))
    rig.ledger.accept(duplicate)
    rig.agent.adopt(rig.ledger, clock=rig.clock, ids=rig.ids)
    data = rig.agent._belief.body.content.as_json()
    assert data["measure"]["weights"] is None and data["quantity"]["partitions"] is None


def test_y5_y8_entry_synchronous_decision_midpoint_cost_contract_and_replay():
    from sui.agent import replay_decision
    from sui.s4b_contracts import DECISION
    from worlds import _write_preferences
    rig = _entry_rig()
    _write_preferences(rig.model, rig.ledger, rig.clock, rig.ids)
    rig.agent.adopt(rig.ledger, clock=rig.clock, ids=rig.ids)
    decided, _ = rig.agent.decide(["a", "b"], u=.5, now_mono_ns=4,
                                clock=rig.clock, ids=rig.ids, ledger=rig.ledger)
    assert decided.body.contract == DECISION
    data = decided.body.content.as_json()
    for c, i, j, bounds in zip(data["expected_cost"], data["information"], data["J"], data["information_bounds"]):
        assert c == pytest.approx(math.log(2))
        assert i == bounds[0] + (bounds[1] - bounds[0])/2
        assert j == c - i and bounds[1] - bounds[0] <= data["tolerance"]
    assert data["time"]["check_events"] == [{"fact": str(rig.boot.id)}]
    cid = rig.ledger.entries_of(decided.id)[0].cid
    assert replay_decision(model=rig.model, ledger=rig.ledger, decision=cid).content == decided.body.content


@pytest.mark.parametrize("column", ["information_parts", "information_bounds", "tolerance", "time"])
def test_y5_entry_replay_rejects_tampered_new_decision_columns(column):
    from dataclasses import replace
    from sui.agent import replay_decision, RebuildMismatch
    from sui.ids import RefKind
    from sui.records import Payload
    rig = _entry_rig()
    decided, _ = rig.agent.decide(["a"], u=.5, now_mono_ns=4,
                                clock=rig.clock, ids=rig.ids, ledger=rig.ledger)
    original = rig.ledger.entries_of(decided.id)[0]
    data = decided.body.content.as_json()
    data[column] = None
    modified = replace(decided, id=rig.ids.new(RefKind.DECISION), body=replace(decided.body, content=Payload.json(data)))
    entry = rig.ledger.append(modified, original.parents)
    with pytest.raises(RebuildMismatch):
        replay_decision(model=rig.model, ledger=rig.ledger, decision=entry.cid)


def test_d14_y8_entry_frozen_view_and_unrecorded_tick_leave_saved_belief_unchanged():
    from sui.agent import plan, replay_decision
    rig = _entry_rig()
    _entry_start(rig)
    saved = rig.agent._belief.body.content
    source = [{"unrecorded": {"kind": "tick", "reading": 4, "after": sorted(rig.ledger.heads())}}]
    view = rig.agent.view(now_ns=8, observed_ns=4, check_events=source)
    draft = plan(view, ["a"], u=.5)
    assert rig.agent._belief.body.content == saved
    source[0]["unrecorded"]["reading"] = 8
    saved_after = tuple(source[0]["unrecorded"]["after"])
    source[0]["unrecorded"]["after"].append("unknown")
    assert view.check_events[0]["unrecorded"]["reading"] == 4
    assert view.check_events[0]["unrecorded"]["after"] == saved_after
    prepared = rig.agent.prepare(draft, clock=rig.clock, ids=rig.ids)
    rig.agent.commit(prepared, ledger=rig.ledger)
    cid = rig.ledger.entries_of(prepared.decided.id)[0].cid
    assert replay_decision(model=rig.model, ledger=rig.ledger, decision=cid).content == draft.content
    rig.clock.advance(4)
    _entry_receipt(rig)
    assert plan(view, ["a"], u=.5).content == draft.content


def test_y11_entry_duration_learning_changes_choice_with_same_u():
    from sui.agent import plan
    model = _quantity_model(learnable=frozenset(), a={a: np.array([[1.], [0.]]) for a in ("a", "b")},
        duration_priors={a: _prior((1, 1), (1, 3)) for a in ("a", "b")},
        measure=_measure((MeasureSpec("exact", "1", {}), 1.)))
    rig = _entry_rig(model)
    before = plan(_entry_view(rig, now_ns=4, observed_ns=0), ["a", "b"], u=.49).content.as_json()
    _, attempt = _entry_start(rig)
    rig.clock.advance(1)
    report = _entry_receipt(rig, attempt)
    after = plan(rig.agent.view(now_ns=6, observed_ns=5, check_events=({"fact": str(report.id)},)),
                 ["a", "b"], u=.49).content.as_json()
    assert before["chosen"] == "a" and after["chosen"] == "b"
    assert before["expected_cost"] == after["expected_cost"] == [0., 0.]
    assert after["information"][0] < after["information"][1]


def test_o5_entry_cloning_measure_preserves_information_and_decision():
    from sui.agent import plan
    point, uniform = _tick(4, {"point_ns": 0}), _tick(4, "uniform")
    results = []
    for measure in (_measure((point, .5), (uniform, .5)), _measure((point, .25), (point, .25), (uniform, .5))):
        rig = _entry_rig(_quantity_model(learnable=frozenset(),
            a={a: np.array([[1.], [0.]]) for a in ("a", "b")},
            duration_priors={a: _prior((1, 1), (1, 3)) for a in ("a", "b")}, measure=measure))
        data = plan(_entry_view(rig, now_ns=4, observed_ns=0), ["a", "b"], u=.5).content.as_json()
        results.append({k: data[k] for k in ("information", "information_bounds", "information_parts", "J", "q_pi", "chosen")})
    assert results[0] == results[1]


@pytest.mark.parametrize("rare,price,expected", [(1e-15, 1e15, 1.), (1e-100, 1e300, 1e-100)])
def test_u9_entry_log_prediction_cost_keeps_tiny_positive_support_and_forbidden_cost(rare, price, expected):
    from sui.names import NameBelief
    from sui.agent import read
    mass = 1. if rare == 1e-15 else 1e-300
    model = _quantity_model(learnable=frozenset(), states=("s", "t"), D=np.array([1. - mass, mass]),
        a={a: np.array([[1., 1.], [rare if mass == 1. else 0., rare]]) for a in ("a", "b")},
        duration_priors={a: _prior((1,), (1,)) for a in ("a", "b")})
    rig = _entry_rig(model)
    quantity = posterior(model.duration_priors, model.measure, rig.agent._reading.timing)
    names = NameBelief(model, read(model, ()))
    query = FutureRecordsQuery("a", 4, rig.clock.run)
    result = one_step_values(quantity, names, (), query, np.array([0., price]), tolerance=1e-12)
    assert result.expected_cost == pytest.approx(expected, rel=1e-12, abs=0.)
    forbidden = one_step_values(quantity, names, (), query, np.array([0., math.inf]), tolerance=1e-12)
    assert forbidden.expected_cost == math.inf


def test_y8_entry_real_window_passes_tick_time_and_provenance_through_commit_and_replay():
    from sui.agent import plan, replay_decision
    from sui.runtime import Window, Pledges, Envelope, Tick, Thought, Reconsider, Think
    from worlds import ScriptDrive
    rig = _entry_rig()
    drive = ScriptDrive(lambda status, event: (Reconsider(candidates=("a", "b"), u=.5),) if isinstance(event, Tick) else ())
    hand = SimpleNamespace(resources=lambda action: frozenset(), execute=lambda action: "x")
    pledges = Pledges()
    window = Window(agent=rig.agent, ledger=rig.ledger, clock=rig.clock, ids=rig.ids,
        membrane=rig.membrane, route="hand", hand=hand, drive=drive, capacity={"think": 1}, pledges=pledges)
    before = rig.agent._belief.body.content
    received_after = sorted(rig.ledger.heads())
    window.accept(Envelope(number=1, event=Tick(mono_ns=4), received_ns=4))
    window.settle()
    thought = next(work for work in window.drain() if isinstance(work, Think))
    assert thought.view.now_ns == thought.view.observed_ns == 4
    assert dict(thought.view.check_events[0]["unrecorded"]) == {"kind": "tick", "reading": 4, "after": tuple(received_after)}
    assert rig.agent._belief.body.content == before
    draft = plan(thought.view, thought.candidates, u=thought.u)
    assert draft.content.as_json()["information"][0] > 0
    window.accept(Envelope(number=2, event=Thought(work=thought.work, draft=draft), received_ns=4))
    window.settle()
    from sui.records import Decided
    decisions = [entry for entry in rig.ledger.entries() if entry.body_type is Decided]
    assert len(decisions) == 1
    rebuilt = replay_decision(model=rig.model, ledger=rig.ledger, decision=decisions[0].cid)
    assert rebuilt.content == draft.content
    assert draft.content.as_json()["J"][0] == -draft.content.as_json()["information"][0]
    duplicate = Thought(work=thought.work, error="duplicate")
    duplicate_after = sorted(rig.ledger.heads())
    window.accept(Envelope(number=3, event=duplicate, received_ns=4))
    assert pledges.latest_check_events == ({"unrecorded": {"kind": "thought", "reading": 4, "after": duplicate_after}},)


def test_d18_entry_window_fact_source_does_not_create_second_equal_check():
    from sui.runtime import Window, Pledges, Envelope, Arrived, Reconsider, Think
    from sui.s1_contracts import OUTCOME
    from worlds import ScriptDrive
    rig = _entry_rig(_quantity_model(learnable=frozenset(),
        duration_priors={a: _prior((1, 1), (1, 3)) for a in ("a", "b")},
        measure=_measure((_tick(4, {"point_ns": 0}), 1.))))
    _entry_start(rig)
    drive = ScriptDrive(lambda status, event: (Reconsider(candidates=("a",), u=.5),) if isinstance(event, Arrived) else ())
    window = Window(agent=rig.agent, ledger=rig.ledger, clock=rig.clock, ids=rig.ids,
        membrane=rig.membrane, route="hand", hand=SimpleNamespace(resources=lambda action: frozenset()),
        drive=drive, capacity={"think": 1}, pledges=Pledges())
    from sui.records import Payload
    window.accept(Envelope(number=1, event=Arrived(route="outside", content=Payload.json({}), contract=OUTCOME), received_ns=4))
    window.settle()
    work = next(item for item in window.drain() if isinstance(item, Think))
    from sui.quantity import _excluded_timing_events
    source = work.view.check_events[0]
    assert set(source) == {"fact"}
    timing = timing_context(work.view.reading.timing, run=rig.clock.run, observed_ns=4, check_events=work.view.check_events)
    assert timing == work.view.reading.timing
    assert not _excluded_timing_events(timing)
    p = posterior(rig.model.duration_priors, rig.model.measure, timing)
    attempt = timing.attempts[0].attempt
    assert math.exp(p.base.allocated({attempt: 3})) == pytest.approx(3/4)


@pytest.mark.parametrize("script,golden", [("s4b1b_golden.py", "golden_s4b1b.json"),
                                         ("s4b1a_golden.py", "golden_s4b1a.json")])
def test_y6_entry_old_decision_and_belief_bytes_match_frozen_golden(script, golden):
    import subprocess
    import sys
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, "-B", str(root / "tools" / script), "--check", str(root / "tests" / golden)],
                            cwd=root, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "P5-a matched" in result.stdout


@pytest.mark.parametrize("prior,measure", [
    (_prior((1, 1), (1, 2)), _measure((_tick(4, "uniform"), 1.))),
    (_prior((1, 1), (1, 3)), _measure((_tick(8, "uniform"), 1.))),
    (DurationPrior(1., _prior((1, 1), (1, 3)).base), _measure((_tick(4, "uniform"), 1.))),
    (_prior((1, 1), (1, 3)), _measure((_tick(4, {"point_ns": 0}), 1.))),
    (_prior((1, 1), (1, 3)), _measure((_tick(4, {"point_ns": 0}), .5), (_tick(4, "uniform"), .5))),
])
def test_y10_public_duration_measure_parameters_change_information(prior, measure):
    value = _future_belief(prior, measure).information("distribution", FutureRecordsQuery("x", 8, "run"), None)
    assert abs(value.midpoint - .0427916441916780934) > 1e-4


def test_o10_u14_general_information_carries_positive_four_variable_quadrature_error_through_small_history():
    priors, measure, timing = _o10_four_history()
    kernel = HistoryKernel(timing, measure.candidates[0].spec)
    history = KernelEvent((kernel,))
    impossible = RecordEvent(kernel, ((kernel.attempts[0].attempt, "infinite", 0, None),))
    # 一般の補助の写しE=λ。K(h|W)は両方同じなので真値はH(1/4,3/4)。
    # hは4変数のパレートの非多項式、R≈7.4e-7。正規化の増幅も検査する。
    cells = {"z": {0: (history, impossible), 1: (impossible, history)}}
    truth = -sum(p * math.log(p) for p in (.25, .75))
    coarse = GeneralRecordLaw(priors, (.25, .75), cells, history=(history, history)).information(tolerance=1e-4, terms=0)
    assert coarse.bounds.lower <= truth <= coarse.bounds.upper
    assert math.exp(coarse.log_width) > 100 * math.ulp(truth)
    tight = GeneralRecordLaw(priors, (.25, .75), cells, history=(history, history)).information(tolerance=1e-12)
    assert tight.bounds.lower <= truth <= tight.bounds.upper
    assert tight.log_width <= math.log(1e-12)
    assert tight.bounds.upper - tight.bounds.lower < coarse.bounds.upper - coarse.bounds.lower


def test_u9_entry_gamma_zero_keeps_structurally_forbidden_candidate_out_of_policy():
    from sui.agent import plan
    from sui.ids import RefKind
    from sui.records import Preference, Record, Role, Payload
    from sui.s4d_contracts import PREFERENCE
    model = _quantity_model(learnable=frozenset(), a={"a": np.array([[1.], [0.]]), "b": np.array([[0.], [1.]])},
        duration_priors={a: _prior((1,), (1,)) for a in ("a", "b")})
    rig = _entry_rig(model)
    for value in ({"kind": "item", "rule": {"name": "table", "version": "1"}, "args": {
                     "feature": {"name": "candidate_outcome", "version": "1"}, "probs": [["x", 1.]]}},
                  {"kind": "style", "H_ns": None, "gamma": 0.}):
        record = Record(id=rig.ids.new(RefKind.PREFERENCE), at=rig.clock.now(), writer=Role.MODEL,
            producer=rig.agent.producer, body=Preference(basis=(), contract=PREFERENCE, content=Payload.json(value)))
        rig.ledger.append(record, rig.ledger.heads())
    rig.agent.adopt(rig.ledger, clock=rig.clock, ids=rig.ids)
    data = plan(_entry_view(rig, now_ns=4, observed_ns=0), ["a", "b"], u=.99).content.as_json()
    assert data["expected_cost"] == [0., "+inf"]
    assert data["q_pi"] == [1., 0.] and data["chosen"] == "a"


def test_y5_entry_large_gamma_preserves_error_bounds_and_midpoint_as_recorded_limit():
    from sui.agent import plan
    from sui.ids import RefKind
    from sui.records import Preference, Record, Role, Payload
    from sui.s4d_contracts import PREFERENCE
    rig = _entry_rig()
    style = Record(id=rig.ids.new(RefKind.PREFERENCE), at=rig.clock.now(), writer=Role.MODEL,
        producer=rig.agent.producer, body=Preference(basis=(), contract=PREFERENCE,
            content=Payload.json({"kind": "style", "H_ns": None, "gamma": 1e12})))
    rig.ledger.append(style, rig.ledger.heads())
    rig.agent.adopt(rig.ledger, clock=rig.clock, ids=rig.ids)
    data = plan(_entry_view(rig, now_ns=4, observed_ns=0), ["a", "b"], u=.5).content.as_json()
    assert data["gamma"] == 1e12
    assert all(lo < hi and hi - lo <= data["tolerance"] for lo, hi in data["information_bounds"])
    assert all(i == lo + (hi - lo)/2 for i, (lo, hi) in zip(data["information"], data["information_bounds"]))


@pytest.mark.parametrize("after_start", [False, True])
def test_d26_unrecorded_receipt_frontier_places_equal_reading_before_or_after_start(after_start):
    timing = _history([("boot", 0, "external", None), ("s", 4, "start", "a")],
        (AttemptTiming("a", "j", "x", "s", (), None, "pending"),))
    ancestors = {"boot-head": frozenset({"boot"}), "start-head": frozenset({"boot", "s"})}
    source = {"unrecorded": {"kind": "tick", "reading": 4,
                             "after": ["start-head" if after_start else "boot-head"]}}
    context = timing_context(timing, run="run", observed_ns=4, check_events=(source,), fact_ancestors=ancestors)
    kernel = HistoryKernel(context, _tick(4, "uniform"))
    expected = (F(7, 16), F(15, 16)) if after_start else (F(1), F(1))
    assert (kernel({"a": 1}), kernel({"a": 3})) == expected
    assert bool(context.attempts[0].check_events) is after_start
    belief = posterior({"x": _prior((1, 1), (1, 3))}, _measure((_tick(4, "uniform"), 1.)), context)
    assert math.exp(belief.base.allocated({"a": 1})) == pytest.approx(F(7, 22) if after_start else F(1, 2))
    assert math.exp(belief.base.allocated({"a": 3})) == pytest.approx(F(15, 22) if after_start else F(1, 2))


@pytest.mark.parametrize("after", [None, ["unknown"], ["b", "a"], ["a", "a"], [1]])
def test_d26_unrecorded_receipt_rejects_missing_unknown_or_noncanonical_frontier(after):
    timing = _future_belief().timing
    value = {"kind": "tick", "reading": 4}
    if after is not None:
        value["after"] = after
    with pytest.raises(ValueError, match="check_events"):
        timing_context(timing, run="run", observed_ns=4, check_events=({"unrecorded": value},),
                       fact_ancestors={"a": frozenset({"boot"}), "b": frozenset({"boot"})})


@pytest.mark.parametrize("after_start", [False, True])
def test_d26_entry_real_window_queued_start_tick_position_decision_and_replay(after_start):
    from sui.agent import plan, replay_decision
    from sui.runtime import Window, Pledges, Envelope, Tick, Reconsider, Think
    from sui.ids import Ref, RefKind
    from sui.records import Record, Role, JobOpened, Payload
    from sui.s1_contracts import ACTION
    from worlds import ScriptDrive
    rig = _entry_rig()
    if after_start:
        _entry_start(rig)
    else:
        job = Record(id=rig.ids.new(RefKind.JOB), at=rig.clock.now(), writer=Role.MODEL,
            producer=rig.agent.producer, body=JobOpened(decision=Ref(RefKind.DECISION, "queued"), step=0,
                contract=ACTION, content=Payload.json({"action": "a"})))
        rig.ledger.append(job, rig.ledger.heads())
        rig.agent.adopt(rig.ledger, clock=rig.clock, ids=rig.ids)
    after = sorted(rig.ledger.heads())
    drive = ScriptDrive(lambda status, event: (Reconsider(candidates=("b",), u=.5),) if isinstance(event, Tick) else ())
    window = Window(agent=rig.agent, ledger=rig.ledger, clock=rig.clock, ids=rig.ids,
        membrane=rig.membrane, route="hand", hand=SimpleNamespace(resources=lambda action: frozenset()),
        drive=drive, capacity={"think": 1}, pledges=Pledges())
    window.accept(Envelope(number=1, event=Tick(mono_ns=4), received_ns=4))
    window.settle()
    work = next(item for item in window.drain() if isinstance(item, Think))
    assert tuple(work.view.check_events[0]["unrecorded"]["after"]) == tuple(after)
    context = timing_context(work.view.reading.timing, run=rig.clock.run, observed_ns=4,
        check_events=work.view.check_events, fact_ancestors=work.view.fact_ancestors)
    attempt = next(a for a in context.attempts if a.action == "a")
    belief = posterior(rig.model.duration_priors, rig.model.measure, context)
    assert math.exp(belief.base.allocated({attempt.attempt: 1})) == pytest.approx(F(7, 22) if after_start else F(1, 2))
    draft = plan(work.view, work.candidates, u=work.u)
    assert draft.content.as_json()["time"]["check_events"][0]["unrecorded"]["after"] == after
    prepared = rig.agent.prepare(draft, clock=rig.clock, ids=rig.ids)
    rig.agent.commit(prepared, ledger=rig.ledger)
    cid = rig.ledger.entries_of(prepared.decided.id)[0].cid
    assert replay_decision(model=rig.model, ledger=rig.ledger, decision=cid).content == draft.content


def test_d18_entry_requires_provenance_even_when_reading_matches_existing_fact():
    from sui.agent import plan
    rig = _entry_rig()
    with pytest.raises(ValueError, match="check_events must identify"):
        plan(rig.agent.view(now_ns=4, observed_ns=0), ["a"], u=.5)
    draft = plan(_entry_view(rig, now_ns=4, observed_ns=0), ["a"], u=.5)
    assert draft.content.as_json()["time"]["check_events"] == [{"fact": str(rig.boot.id)}]


def _slow_atomic_law_case(name):
    """検品で遅かった入口と同じ量の入力。名前とSciPyに依存せず測れる。"""
    candidate, now, after, complete = {
        "D14": ("a", 8, True, False),
        "D26-before": ("b", 4, False, False),
        "D26-after": ("b", 4, True, False),
        "Y11-after-a": ("a", 6, None, True),
        "Y11-after-b": ("b", 6, None, True),
    }[name]
    priors = {a: _prior((1, 1), (1, 3)) for a in ("a", "b")}
    events = [("boot", 0, "external", None), ("s", 4, "start", "attempt")]
    if complete:
        events.append(("r", 5, "report", "attempt"))
    timing = _history(events, (AttemptTiming("attempt", "job", "a", "s", (),
        "r" if complete else None, "complete" if complete else "pending"),))
    measure = _measure((MeasureSpec("exact", "1", {}) if complete else _tick(4, "uniform"), 1.))
    if after is not None:
        timing = timing_context(timing, run="run", observed_ns=4,
            check_events=({"unrecorded": {"kind": "tick", "reading": 4, "after": ["head"]}},),
            fact_ancestors={"head": {"boot", "s"} if after else {"boot"}})
    table = posterior(priors, measure, timing).future_records(FutureRecordsQuery(candidate, now, "run",
        () if complete else (("job", "a"),)), tolerance=1e-12 / 2)
    cells, m = table.build(), AtomicPolynomialMeasure(priors)
    return AtomicRecordLaw(m, (1,), {z: {e: tuple(m.likelihood(p) for p in row) for e, row in values.items()}
                                   for z, values in cells.items()}), table.tolerance


@pytest.mark.parametrize("beta,reference", [((1, 1), F(1, 4)), ((3, 1), F(3, 16)), ((1, 3), F(13, 48))])
def test_u1_y11_degree_elevated_monomial_uses_same_closed_dirichlet_log_moment(beta, reference):
    measure = AtomicPolynomialMeasure({"a": _prior(beta, (1, 3)), "b": _prior((1, 1), (1, 3))})
    f = SimplexPolynomial((2, 2), (1, 0), {(1, 0, 0, 0): F(1)})
    elevated = f.elevate((5, 3))
    assert elevated.reduced() == f
    assert measure.expectation(elevated) == measure.expectation(f)
    series = PhiSeries(measure, elevated, closed_forms=True)
    assert series.log_remainder == -math.inf
    assert math.exp(series.log_value) == pytest.approx(reference, abs=1e-15)


def test_u1_degree_reduction_retains_valid_elevated_controls_when_lower_degree_would_break_contract():
    p = SimplexPolynomial((2,), (3,), {(3, 0): F(1, 10), (2, 1): F(5, 2),
                                      (1, 2): F(5, 2), (0, 3): F(1, 10)})
    assert p.reduced() == p
    measure = AtomicPolynomialMeasure({"x": _prior((1, 1), (1, 3))})
    assert measure.expectation(p) == F(7, 15)


def test_u2_o10_bounded_phi_quadrature_encloses_closed_affine_reference_above_rounding_error():
    measure = AtomicPolynomialMeasure({"x": _prior((1, 1), (1, 3))})
    p = SimplexPolynomial((2,), (1,), {(1, 0): F(3, 4), (0, 1): F(1, 4)})
    primitive = lambda x: x*x*(.25 - .5*math.log(x))
    reference = (primitive(.75) - primitive(.25))/.5
    coarse = _bounded_phi_quadrature(measure, p, math.log(.02), None)
    lower, width = math.exp(coarse.log_value), math.exp(coarse.log_remainder)
    assert lower <= reference <= lower + width and width <= .02
    center = lower + width/2
    assert abs(center - reference) > 100 * math.ulp(reference)
    fine = _bounded_phi_quadrature(measure, p, math.log(1e-12), None)
    assert fine.terms > coarse.terms
    assert math.exp(fine.log_remainder) <= 1e-12
    assert math.exp(fine.log_value) <= reference <= math.exp(fine.log_value) + math.exp(fine.log_remainder)


@pytest.mark.parametrize("scale", [F(1), F(1, 10**400)])
def test_u9_bounded_phi_integrates_positive_tiny_probabilities_in_logs(scale):
    measure = AtomicPolynomialMeasure({"x": _prior((1, 1), (1, 3))})
    p = SimplexPolynomial((2,), (1,), {(1, 0): scale*F(3, 4), (0, 1): scale*F(1, 4)})
    estimate = _bounded_phi_quadrature(measure, p, -math.log(scale.denominator) + math.log(1e-12), None)
    assert math.isfinite(estimate.log_value) and math.isfinite(estimate.log_remainder)
    # φ(scale*Q)=scale*φ(Q)−scale*log(scale)*Q, E[Q]=1/2.
    primitive = lambda x: x*x*(.25 - .5*math.log(x))
    phi_q = (primitive(.75)-primitive(.25))/.5
    log_scale = -math.log(scale.denominator)
    log_reference = log_scale + math.log(phi_q - .5*log_scale)
    rounding = 4 * math.ulp(log_reference)
    assert estimate.log_value - rounding <= log_reference <= np.logaddexp(estimate.log_value, estimate.log_remainder) + rounding


def test_y9_bounded_phi_respects_explicit_series_budget_and_falls_back_for_unproved_lower_bound():
    measure = AtomicPolynomialMeasure({"x": _prior((1, 1), (1, 3))})
    p = SimplexPolynomial((2,), (1,), {(1, 0): F(3, 4), (0, 1): F(1, 4)})
    with pytest.raises(IntegrationIncomplete, match="series-work"):
        _bounded_phi_quadrature(measure, p, math.log(1e-12), 1)
    monomial = SimplexPolynomial((2,), (1,), {(1, 0): F(1)})
    assert _bounded_phi_quadrature(measure, monomial, math.log(1e-12), None) is None
    nonuniform = AtomicPolynomialMeasure({"x": _prior((3, 1), (1, 3))})
    assert _bounded_phi_quadrature(nonuniform, p, math.log(1e-12), None) is None
    law, tolerance = _slow_atomic_law_case("D14")
    with pytest.raises(IntegrationIncomplete, match="quadrature-node budget"):
        law.information(tolerance=tolerance, node_budget=1)


@pytest.mark.parametrize("name", ["D14", "D26-before", "D26-after", "Y11-after-a", "Y11-after-b"])
def test_u2_y11_d26_bounded_phi_finishes_same_slow_history_with_proved_global_width(name):
    law, tolerance = _slow_atomic_law_case(name)
    coarse = law.information(tolerance=tolerance, terms=12)
    fine = law.information(tolerance=tolerance)
    assert fine.log_width <= math.log(tolerance)
    assert coarse.bounds.lower <= fine.bounds.lower <= fine.bounds.upper <= coarse.bounds.upper
    if name.startswith("Y11"):
        assert fine.stats.series_terms == 0 and fine.log_width == -math.inf
    else:
        assert fine.stats.integration_nodes > 0 and fine.stats.series_terms > 12


def _two_run_fact_fixture():
    """状態を手で指定せず、2つのrunの実際の事実を作る。"""
    from sui.clock import FakeClock
    from sui.ids import Ref, RefKind, SequentialIds
    from sui.records import Record, Role, Producer, Observed, AttemptStarted, JobOpened, Payload, BODY_KIND
    from sui.s1_contracts import ACTION, ATTEMPT, OUTCOME
    from sui.s4_contracts import BOOT
    old = FakeClock(run=Ref(RefKind.RUN, "facts-old"), run_index=0, wall_ns=100)
    new = FakeClock(run=Ref(RefKind.RUN, "facts-new"), run_index=1, wall_ns=108)
    ids, records, jobs, attempts = SequentialIds(prefix="two-run-facts"), [], {}, {}
    def add(clock, body, ns):
        clock.advance(ns - clock.mono_ns())
        record = Record(id=ids.new(BODY_KIND[type(body)]), at=clock.now(),
            writer=Role.MEMBRANE if isinstance(body, (Observed, AttemptStarted)) else Role.MODEL,
            producer=Producer(component="test.quantity", code_version="1"), body=body)
        records.append(record)
        return record
    def boot(clock):
        return add(clock, Observed(route="membrane", received_ns=0,
            content=Payload.json({}), contract=BOOT), 0)
    def start(clock, action, ns):
        job = add(clock, JobOpened(decision=Ref(RefKind.DECISION, "two-run-decision"), step=0,
            content=Payload.json({"action": action}), contract=ACTION), ns)
        attempt = add(clock, AttemptStarted(job=job.id, content=Payload.json({}), contract=ATTEMPT), ns)
        jobs[job.id], attempts[attempt.id] = action, action
        return attempt
    def observe(clock, ns, attempt=None):
        return add(clock, Observed(route="executor", received_ns=ns,
            caused_by=None if attempt is None else attempt.id,
            content=Payload.text("unreadable name"), contract=OUTCOME), ns)
    boot(old)
    return SimpleNamespace(old=old, new=new, records=records, jobs=jobs,
                           attempts=attempts, boot=boot, start=start, observe=observe)


def test_d9_fact_read_keeps_previous_run_pending_attempt_and_its_predictive_law():
    from sui.timeline import timeline
    r = _two_run_fact_fixture()
    old = r.start(r.old, "x", 4)
    check = r.observe(r.old, 4)
    r.boot(r.new)
    timing = read_timing(r.records, timeline(r.records), r.jobs, r.attempts, {old.body.job: "x"})
    row, = timing.attempts
    assert row.state == "pending" and row.attempt == old.id and row.report_event is None
    assert row.check_events == (check.id,)
    belief = posterior({"x": _prior((1, 1), (1, 3))}, _measure((_tick(4, {"point_ns": 0}), 1.)), timing)
    old_draw = belief.predictive(QuantityQuery("x", 1, 2, old.id))
    new_draw = belief.predictive(QuantityQuery("x", 1, 2))
    assert math.exp(old_draw.log_lower) == pytest.approx(1/4)
    assert math.exp(old_draw.log_upper) == pytest.approx(1/4)
    assert math.exp(new_draw.log_lower) == pytest.approx(5/12)
    assert math.exp(new_draw.log_upper) == pytest.approx(5/12)
    table = belief.future_records(FutureRecordsQuery("x", 12, r.new.run, ((old.body.job, "x"),)))
    assert tuple(a.attempt for a in table.waiting) == (old.id,)


@pytest.mark.parametrize("receipt_ns", [4, 8])
def test_d24_d25_fact_read_cross_run_receipt_is_unknown_finite_evidence_and_never_a_check(receipt_ns):
    from sui.timeline import timeline
    r = _two_run_fact_fixture()
    old = r.start(r.old, "x", 4)
    check = r.observe(r.old, 4)
    r.boot(r.new)
    current = r.start(r.new, "y", 4)
    receipt = r.observe(r.new, receipt_ns, old)
    axis = timeline(r.records)
    timing = read_timing(r.records, axis, r.jobs, r.attempts, {current.body.job: "y"})
    rows = {a.attempt: a for a in timing.attempts}
    assert rows[old.id].state == "unknown" and rows[old.id].report_event == receipt.id
    assert rows[old.id].check_events == (check.id,)
    assert rows[current.id].state == "pending" and rows[current.id].check_events == ()
    assert all(receipt.id not in a.check_events for a in timing.attempts)
    measure = _measure((_tick(4, {"point_ns": 0}), 1.))
    belief = posterior({"x": _prior((1, 1), (1, None)), "y": _prior((1, 1), (2, 3))}, measure, timing)
    assert belief.base.fraction_evidence == F(1, 8)
    assert belief.base.fraction_new_value("x") == {1: F(2, 3), None: F(1, 3)}
    assert belief.base.fraction_new_value("y") == {2: F(1, 2), 3: F(1, 2)}
    assert receipt.id not in HistoryKernel(timing, measure.candidates[0].spec).external_ids
    context = timing_context(timing, run=r.new.run, observed_ns=axis.received_ns[receipt.id],
                             check_events=({"fact": str(receipt.id)},))
    assert context == timing


def test_d24_fact_read_previous_run_completed_attempt_stays_complete():
    from sui.timeline import timeline
    r = _two_run_fact_fixture()
    old = r.start(r.old, "x", 4)
    receipt = r.observe(r.old, 4, old)
    r.boot(r.new)
    timing = read_timing(r.records, timeline(r.records), r.jobs, r.attempts, {})
    row, = timing.attempts
    assert row.state == "complete" and row.report_event == receipt.id
    assert row.check_events == ()
    kernel = HistoryKernel(timing, _tick(4, {"point_ns": 0}))
    assert kernel({old.id: 1}) == 1 and kernel({old.id: None}) == 0


def test_u2_u4_public_future_records_pending_duration_changes_candidate_information():
    reference, conditional = .0427916441916780934, .0393153919887595056
    unconditioned = _future_belief().future_records(FutureRecordsQuery("x", 12, "run")).information()
    timing = _history([("boot", 0, "external", None), ("s", 4, "start", "p")],
                      (AttemptTiming("p", "pending-job", "x", "s", (), None, "pending"),))
    belief = posterior({"x": _prior((1, 1), (1, 3))}, _measure((_tick(4, "uniform"), 1.)), timing)
    # v0.16 also observes insertion order. Separate the arrival supports so
    # this fixture continues to measure only the original clock-record effect.
    table = belief.future_records(FutureRecordsQuery("x", 12, "run", (("pending-job", "x"),)))
    result = table.information()
    assert ((4,), ("p",)) in table.cells and ((8,), ("p",)) in table.cells
    assert unconditioned.bounds.lower <= reference <= unconditioned.bounds.upper
    assert result.bounds.lower <= conditional <= result.bounds.upper
    assert result.bounds.upper < unconditioned.bounds.lower
    assert result.log_width <= math.log(1e-12)


def test_y9_piecewise_tail_rejects_unsupported_kind():
    spec = _piecewise()
    spec["params"]["tail"]["kind"] = "exponential"
    with pytest.raises(ValueError, match="tail: unsupported kind"):
        BaseSpec(**spec)


def test_d16_d24_atomic_record_law_refuses_missing_history_cell():
    measure = AtomicPolynomialMeasure({"x": _prior((1, 1), (1, 3))})
    p = SimplexPolynomial((2,), (1,), {(1, 0): F(3, 4), (0, 1): F(1, 4)})
    history = (SimplexPolynomial.constant((2,), 1),)
    complete = AtomicRecordLaw(measure, (1,), {"z": {0: (p,), 1: (p.complement(),)}}, history=history)
    assert complete.evidence == 1
    with pytest.raises(ValueError, match="cells do not partition the supplied history"):
        AtomicRecordLaw(measure, (1,), {"z": {0: (p,)}}, history=history)


@pytest.mark.parametrize("spec,start_ns", [(MeasureSpec("exact", "1", {}), 0), (_tick(4, "uniform"), 4)])
def test_d8_d9_same_run_untimed_receipt_conditions_existing_duration_finite(spec, start_ns):
    from sui.timeline import timeline
    r = _timing_fixture()
    old = r.start("a", start_ns)
    receipt = r.observe(old, start_ns + 5, None)
    timing = read_timing(r.records, timeline(r.records), r.jobs, r.attempts, {})
    row, = timing.attempts
    assert row.state == "unknown" and row.report_event == receipt.id and row.check_events == ()
    assert timing.events[receipt.id].reading is None
    belief = posterior({"a": _prior((1, 1), (1, None))}, _measure((spec, 1.)), timing)
    assert belief.base.fraction_evidence == F(1, 2)
    assert belief.base.allocated({old.id: None}) == -math.inf
    assert belief.base.allocated({old.id: 1}) == 0.
    assert belief.base.fraction_new_value("a") == {1: F(2, 3), None: F(1, 3)}
    old_infinite = belief.predictive(QuantityQuery("a", 0, None, old.id, infinite=True))
    assert old_infinite.log_lower == old_infinite.log_upper == -math.inf
    new_finite = belief.predictive(QuantityQuery("a", 0, None))
    assert math.exp(new_finite.log_lower) == pytest.approx(2/3)
    assert math.exp(new_finite.log_upper) == pytest.approx(2/3)


@pytest.mark.parametrize("spec,start_ns", [(MeasureSpec("exact", "1", {}), 0), (_tick(1, {"point_ns": 0}), 4)])
def test_d8_d9_d15_untimed_receipt_keeps_lower_checks_and_ignores_later_timestamp(spec, start_ns):
    from sui.timeline import timeline
    r = _timing_fixture()
    old, witness = r.start("a", start_ns), r.start("b", start_ns)
    check = r.observe(witness, start_ns + 2, start_ns + 2)
    priors, measure = {"a": _prior((1, 2, 1), (1, 3, None)), "b": _prior((1,), (2,))}, _measure((spec, 1.))
    before = posterior(priors, measure, read_timing(r.records, timeline(r.records), r.jobs, r.attempts, {}))
    assert math.exp(before.base.allocated({old.id: 3})) == pytest.approx(2/3)
    assert math.exp(before.base.allocated({old.id: None})) == pytest.approx(1/3)
    first = r.observe(old, start_ns + 3, None)
    r.observe(old, start_ns + 9, start_ns + 9)
    timing = read_timing(r.records, timeline(r.records), r.jobs, r.attempts, {})
    row = next(a for a in timing.attempts if a.attempt == old.id)
    assert row.state == "unknown" and row.report_event == first.id
    assert row.check_events == (check.id,)
    after = posterior(priors, measure, timing)
    assert after.base.fraction_evidence == F(1, 2)
    assert after.base.allocated({old.id: 1}) == after.base.allocated({old.id: None}) == -math.inf
    assert after.base.allocated({old.id: 3}) == 0.
    assert after.base.fraction_new_value("a") == {1: F(1, 5), 3: F(3, 5), None: F(1, 5)}


def test_d8_d9_unknown_without_receipt_keeps_infinite_branch_after_abandonment():
    from sui.ids import Ref, RefKind
    from sui.records import Decided, Record, Role, Payload
    from sui.s3_contracts import ABANDON
    from sui.timeline import timeline
    r = _two_run_fact_fixture()
    old = r.start(r.old, "x", 0)
    r.old.advance(1)
    r.records.append(Record(id=Ref(RefKind.DECISION, "without-receipt-abandon"), at=r.old.now(),
        writer=Role.MODEL, producer=old.producer, body=Decided(inputs=(old.body.job,),
            content=Payload.json({"job": str(old.body.job)}), contract=ABANDON)))
    timing = read_timing(r.records, timeline(r.records), r.jobs, r.attempts, {})
    row, = timing.attempts
    assert row.state == "unknown" and row.report_event is None
    belief = posterior({"x": _prior((1, 1), (1, None))},
                       _measure((MeasureSpec("exact", "1", {}), 1.)), timing)
    assert belief.base.fraction_evidence == 1
    assert math.exp(belief.base.allocated({old.id: None})) == pytest.approx(1/2)
    assert belief.base.fraction_new_value("x") == {1: F(1, 2), None: F(1, 2)}


def test_d8_d9_piecewise_untimed_receipt_conditions_same_old_duration_finite():
    from sui.timeline import timeline
    r = _timing_fixture()
    old = r.start("a", 4)
    r.observe(old, 9, None)
    timing = read_timing(r.records, timeline(r.records), r.jobs, r.attempts, {})
    prior = DurationPrior(2., BaseSpec("piecewise", "1", {
        "edges_ns": [0, 4], "masses": [.5],
        "tail": {"kind": "pareto", "kappa": 1., "mass": 0.}, "p_inf": .5}))
    belief = posterior({"a": prior}, _measure((_tick(4, {"point_ns": 0}), 1.)), timing)
    old_infinite = belief.predictive(QuantityQuery("a", 0, None, old.id, infinite=True))
    assert old_infinite.log_lower == old_infinite.log_upper == -math.inf
    new_finite = belief.predictive(QuantityQuery("a", 0, None))
    assert math.exp(new_finite.log_lower) == pytest.approx(2/3)
    assert math.exp(new_finite.log_upper) == pytest.approx(2/3)


def _tied_report_history(refs, order, spec, *, timed=True):
    reading = 2 if spec.name == "exact" else 0
    if not timed:
        reading = None
    events = [("s" + ref, 0, "start", ref) for ref in refs]
    events += [("r" + ref, reading, "report", ref) for ref in order]
    rows = []
    for ref in refs:
        preceding = order[:order.index(ref)] if ref in order else order
        rows.append(AttemptTiming(ref, "j" + ref, "x", "s" + ref,
            tuple("r" + r for r in preceding), "r" + ref if ref in order else None,
            ("complete" if timed else "unknown") if ref in order else "pending"))
    return _history(events, rows)


@pytest.mark.parametrize("spec", [MeasureSpec("exact", "1", {}), _tick(8, {"point_ns": 0})],
                         ids=["exact", "tick-point"])
@pytest.mark.parametrize("count", [2, 3])
@pytest.mark.parametrize("timed", [True, False], ids=["timed", "untimed"])
def test_d27_all_tied_report_orders_have_factorial_weight_and_sum_one(spec, count, timed):
    refs = tuple("ABC"[:count])
    kernels = tuple(HistoryKernel(_tied_report_history(refs, order, spec, timed=timed), spec)
                    for order in permutations(refs))
    allocation = dict.fromkeys(refs, 2)
    probabilities = tuple(k(allocation) for k in kernels)
    assert probabilities == (F(1, math.factorial(count)),) * math.factorial(count)
    assert sum(probabilities) == 1
    # Same-copy unions/complements share ranks; disjoint orders do not overlap.
    whole = KernelEvent(kernels)
    assert whole(allocation) == 1 and whole.complement()(allocation) == 0
    left, right = (KernelEvent((k,)) for k in kernels[:2])
    assert ConjunctionEvent((left, right))(allocation) == 0
    assert UnionEvent((left, left))(allocation) == probabilities[0]
    belief = posterior({"x": _prior((1,), (2,))}, _measure((spec, 1.)), kernels[0].timing)
    assert belief.base.fraction_evidence == probabilities[0]


@pytest.mark.parametrize("spec", [MeasureSpec("exact", "1", {}), _tick(8, {"point_ns": 0})],
                         ids=["exact", "tick-point"])
@pytest.mark.parametrize("timed", [True, False], ids=["timed", "untimed"])
def test_d27_equal_time_prefix_keeps_ge_root_and_exclusive_ingestion_order(spec, timed):
    refs = tuple("ABC")
    for size in (1, 2):
        probabilities = [HistoryKernel(_tied_report_history(refs, order, spec, timed=timed), spec)(dict.fromkeys(refs, 2))
                         for order in permutations(refs, size)]
        assert probabilities == [F(math.factorial(3-size), math.factorial(3))] * len(probabilities)
        assert sum(probabilities) == 1
    pending = _history([("s", 0, "start", "p"), ("c", 2, "external", None)],
                      (AttemptTiming("p", "j", "x", "s", ("c",), None, "pending"),))
    if spec.name == "exact":
        assert HistoryKernel(pending, spec)({"p": 2}) == 1
    boundary = _tied_report_history(("A", "B"), ("A",), spec, timed=timed)
    if not timed:
        # Match the production reader: a receipt with no numeric reading is
        # omitted from check_events; its ingestion order still supplies a root.
        a, b = boundary.attempts
        boundary = Timing(boundary.events, (a, AttemptTiming(b.attempt, b.job, b.action,
                          b.start_event, (), b.report_event, b.state)))
    prefix = HistoryKernel(boundary, spec)
    assert prefix({"A": 2, "B": 2}) == F(1, 2)
    assert prefix({"A": 2, "B": 1}) == 0
    assert prefix({"A": 2, "B": 3}) == 1


def test_d27_u14_piecewise_shared_block_ties_survive_partition_and_replica_integration():
    prior = DurationPrior(2., BaseSpec("piecewise", "1", {"edges_ns": [0, 4], "masses": [1.],
        "tail": {"kind": "pareto", "kappa": 1., "mass": 0.}, "p_inf": 0.}))
    spec = _tick(8, {"point_ns": 0})
    history = _tied_report_history(("A", "B"), ("A", "B"), spec)
    result = partition_evidence({"x": prior}, _measure((spec, 1.)), history, tolerance=1e-12)
    assert math.exp(result.evidence.log_value) == pytest.approx(.5, abs=1e-14)
    # DP: same block 1/3 contributes 1/6; distinct blocks 2/3 contribute 1/3.
    masses = {rgs: sum(math.exp(e.log_value) * float(entry.weight)
        for entry, e in zip(result.entries, result.estimates) if entry.partitions == (rgs,))
        for rgs in ((0, 0), (0, 1))}
    assert masses == pytest.approx({(0, 0): 1/6, (0, 1): 1/3})
    pending = HistoryKernel(_tied_report_history(("A", "B"), (), spec), spec)
    left, right = (RecordEvent(pending, order=order) for order in (("A", "B"), ("B", "A")))
    backend = ReplicaMoments({"x": prior})
    first = backend.expectation(left, tolerance=1e-12)
    independent = backend.expectation(ReplicaProduct((left, left)), tolerance=1e-12)
    different = backend.expectation(ReplicaProduct((left, right)), tolerance=1e-12)
    intersection = backend.expectation(ConjunctionEvent((left, right)), tolerance=1e-12)
    assert math.exp(first.log_value) == pytest.approx(.5, abs=1e-14)
    assert math.exp(independent.log_value) == pytest.approx(.25, abs=1e-14)
    assert math.exp(different.log_value) == pytest.approx(.25, abs=1e-14)
    assert intersection.log_upper == -math.inf
    # The isolated fast path must agree with the order preimage too: even a
    # singleton reported order excludes infinity, including in its complement.
    marked = DurationPrior(2., BaseSpec("piecewise", "1", {"edges_ns": [0, 4], "masses": [.5],
        "tail": {"kind": "pareto", "kappa": 1., "mass": 0.}, "p_inf": .5}))
    single = HistoryKernel(_tied_report_history(("A",), (), spec), spec)
    present = RecordEvent(single, order=("A",))
    impossible = RecordEvent(single, (("A", "infinite", 0, None),), order=("A",))
    measure = ReplicaMoments({"x": marked})
    assert math.exp(measure.expectation(present, tolerance=1e-12).log_value) == pytest.approx(.5)
    assert math.exp(measure.expectation(present.complement(), tolerance=1e-12).log_value) == pytest.approx(.5)
    assert measure.expectation(impossible, tolerance=1e-12).log_upper == -math.inf


def _u15_order_table(*, second=False, p_inf=False, clone=False):
    priors = {"a": _prior((1,), (3,)), "b": _prior((1, 1), (2, 4))}
    refs = ("B", "C") if second else ("B",)
    if second:
        priors["c"] = _prior((1,), (4,))
    if p_inf:
        priors["b"] = _prior((1, 1, 2), (2, 4, None))
    timing = _history([("s" + r, 0, "start", r) for r in refs],
        tuple(AttemptTiming(r, "j" + r, r.lower(), "s" + r, (), None, "pending") for r in refs))
    spec = _tick(8, {"point_ns": 0})
    measure = _measure((spec, .5), (spec, .5)) if clone else _measure((spec, 1.))
    belief = posterior(priors, measure, timing)
    return belief.future_records(FutureRecordsQuery("a", 0, "run",
        tuple(("j" + r, r.lower()) for r in refs))), belief


@pytest.mark.parametrize("second,reference", [(False, math.log(2)-.5),
                                             (True, .75*math.log(3)-math.log(2))])
def test_u15_public_future_records_information_uses_z_order_and_e_insertion(second, reference):
    table, _ = _u15_order_table(second=second)
    result = table.information()
    assert result.bounds.lower - 1e-15 <= reference <= result.bounds.upper + 1e-15
    assert result.bounds.upper-result.bounds.lower <= 1e-12
    if second:
        allocation = {"B": 4, "C": 4, table.candidate.attempt: 3}
        assert table.cells[((0, 0), ("B", "C"))][0, 0][0](allocation) == F(1, 2)
        assert table.cells[((0, 0), ("C", "B"))][0, 0][0](allocation) == F(1, 2)


def test_u15_second_reference_direct_permutations_distinguishes_two_wrong_z_mappings():
    # Independent oracle: enumerate 3! orders, store affine laws a+b*p as Fraction.
    # Integrate phi(a+b*p) by its elementary antiderivative; no quantity helpers.
    table = {}
    for short in (True, False):
        times = {"A": 3, "B": 2 if short else 4, "C": 4}
        orders = [o for o in permutations(times) if all(times[o[i]] <= times[o[i+1]] for i in range(2))]
        for order in orders:
            key = (tuple(r for r in order if r != "A"), order.index("A"))
            a, b = table.get(key, (F(0), F(0)))
            w = F(1, len(orders))
            table[key] = (a+(0 if short else w), b+(w if short else -w))
    assert table == {(("B", "C"), 1): (F(0), F(1)),
                     (("B", "C"), 0): (F(1, 2), F(-1, 2)),
                     (("C", "B"), 0): (F(1, 2), F(-1, 2))}
    assert tuple(sum(pair[i] for pair in table.values()) for i in (0, 1)) == (1, 0)
    phi = lambda x: -x*math.log(x) if x else 0.
    primitive = lambda x: x*x*(.25-.5*math.log(x)) if x else 0.
    def direct_info(cells):
        rows = {}
        for (z, e), (a, b) in cells.items():
            u, v = rows.get(z, (F(0), F(0)))
            rows[z] = (u+a, v+b)
        integral = lambda pair: ((primitive(float(sum(pair)))-primitive(float(pair[0])))/float(pair[1])
                                if pair[1] else phi(float(pair[0])))
        return (sum(phi(float(a+b/2)) for a, b in cells.values())
                - sum(phi(float(a+b/2)) for a, b in rows.values())
                - sum(integral(pair) for pair in cells.values())
                + sum(integral(pair) for pair in rows.values()))
    correct = direct_info(table)
    assert correct == pytest.approx(.1308120359411369591292, abs=1e-15)
    missing_order = {}
    for (z, e), (a, b) in table.items():
        u, v = missing_order.get(((), e), (F(0), F(0)))
        missing_order[(), e] = (u+a, v+b)
    assert direct_info(missing_order) == pytest.approx(math.log(2)-.5, abs=1e-15)
    assert direct_info({((z, e), 0): pair for (z, e), pair in table.items()}) == pytest.approx(0., abs=1e-15)
    production, _ = _u15_order_table(second=True)
    result = production.information()
    assert result.bounds.lower <= correct <= result.bounds.upper


@pytest.mark.parametrize("second", [False, True])
@pytest.mark.parametrize("p_inf", [False, True])
def test_d16_u15_future_order_cells_partition_history_with_ties_and_infinity(second, p_inf):
    table, _ = _u15_order_table(second=second, p_inf=p_inf)
    table.build()
    candidate = table.candidate.attempt
    for b, a in product((2, 4, None), (3, None)):
        allocation = {"B": b, candidate: a}
        if second:
            allocation["C"] = 4
        assert sum(cell[0](allocation) for row in table.cells.values() for cell in row.values()) == table.kernels[0](allocation)
    if p_inf:
        mask = table.arrival_masks(tolerance=1e-12)
        key = (False, True) if second else (False,)
        assert math.exp(mask[key][0].log_lower) == pytest.approx(.5)


def test_d24_u15_old_run_pending_is_mark_only_and_excluded_from_both_order_coordinates():
    old = TimingEvent("old", "old-run", 0, 0, 0, "start", "B")
    boot = TimingEvent("boot", "new-run", 1, 0, 8, "external", None)
    priors = {"a": _prior((1,), (3,)), "b": _prior((1, 1), (2, 4))}
    timing = Timing({"old": old, "boot": boot},
        (AttemptTiming("B", "jB", "b", "old", (), None, "pending"),))
    belief = posterior(priors, _measure((_tick(8, {"point_ns": 0}), 1.)), timing)
    # Boot is uniform inside [8,16); the point-phase candidate starts at 16.
    table = belief.future_records(FutureRecordsQuery("a", 16, "new-run", (("jB", "b"),)))
    result = table.information()
    assert result.bounds.lower == result.bounds.upper == 0.
    assert all(order == () and readings in (("finite",), ("infinite",)) for readings, order in table.cells)
    assert all(position in (0, None) for row in table.cells.values() for reading, position in row)
    assert all("B" not in cell[0].order for row in table.cells.values() for cell in row.values())


def test_u15_one_step_and_cloned_lambda_keep_order_information_in_public_duration_term():
    table, belief = _u15_order_table(second=True)
    cloned, _ = _u15_order_table(second=True, clone=True)
    reference = .75*math.log(3)-math.log(2)
    first, second = table.information(), cloned.information()
    assert first.bounds.lower <= reference <= first.bounds.upper
    assert second.bounds.lower <= reference <= second.bounds.upper
    from sui.names import NameBelief
    model = GenerativeModel(states=("s",), outcomes=("y",), actions=("a", "b", "c"),
        a={a: np.ones((1, 1)) for a in ("a", "b", "c")}, learnable=frozenset(),
        D=np.ones(1), log_C=np.zeros(1), gamma=1.)
    names = NameBelief(model, SimpleNamespace(n={a: np.zeros(1, dtype=int) for a in model.actions}))
    values = one_step_values(belief, names, (("jB", "b"), ("jC", "c")),
        FutureRecordsQuery("a", 0, "run"), np.zeros(1), tolerance=1e-12)
    assert values.names_information == values.expected_cost == 0.
    assert values.durations_information.lower <= reference <= values.durations_information.upper
    assert values.information == values.durations_information


@pytest.mark.parametrize("spec", [MeasureSpec("exact", "1", {}), _tick(8, {"point_ns": 0})],
                         ids=["exact", "tick-point"])
@pytest.mark.parametrize("count", [2, 3])
@pytest.mark.parametrize("timed", [True, False], ids=["timed", "untimed"])
def test_d27_fact_read_interleaved_starts_preserve_report_order_and_exclude_reverse(spec, count, timed):
    from sui.timeline import timeline
    r = _timing_fixture()
    start, duration = (0, 1) if spec.name == "exact" else (8, 8)
    arrival = start + duration
    attempts = [r.start("a", start)]
    receipts = [r.observe(attempts[0], arrival, arrival if timed else None)]
    for _ in range(count - 1):
        attempts.append(r.start("b", arrival))
        receipts.append(r.observe(attempts[-1], arrival, arrival if timed else None))
    timing = read_timing(r.records, timeline(r.records), r.jobs, r.attempts, {})
    report_refs = tuple(row.attempt for row in timing.attempts)
    assert report_refs == tuple(a.id for a in attempts)
    assert all(not row.check_events for row in timing.attempts)
    assert tuple(timing.events[r.id].reading for r in receipts) == (arrival if timed else None,) * count
    kernel = HistoryKernel(timing, spec)
    allocation = {attempt.id: duration if i == 0 else 0 for i, attempt in enumerate(attempts)}
    expected = F(1)
    # Every next attempt starts after the previous report is ingested, so
    # causality admits only the recorded order, even at equal true arrivals.
    assert kernel(allocation) == expected
    history = KernelEvent((kernel,))
    assert history(allocation) == expected
    for order in permutations(report_refs):
        requested = RecordEvent(kernel, order=order)
        intersection = ConjunctionEvent((history, requested))
        assert intersection(allocation) == (expected if order == report_refs else 0)
    priors = {"a": _prior((1,), (duration,)), "b": _prior((1,), (0,))}
    belief = posterior(priors, _measure((spec, 1.)), timing)
    assert belief.base.fraction_evidence == expected


def _causal_tie_pending_fixture(spec, *, second=False, timed=True):
    r = _timing_fixture()
    start, step = (0, 1) if spec.name == "exact" else (8, 8)
    a = r.start("a", start)
    r.observe(a, start + step, start + step if timed else None)
    waiting = [r.start("b", start + step)]
    if second:
        waiting.append(r.start("c", start + step))
    return r, a, tuple(waiting), start + step, step


@pytest.mark.parametrize("spec", [MeasureSpec("exact", "1", {}), _tick(8, {"point_ns": 0})],
                         ids=["exact", "tick-point"])
def test_d27_d16_fact_read_causal_tie_future_branches_match_completed_histories(spec):
    from sui.timeline import timeline
    r, a, (b,), arrival, step = _causal_tie_pending_fixture(spec)
    timing = read_timing(r.records, timeline(r.records), r.jobs, r.attempts, {})
    priors = {"a": _prior((1,), (step,)), "b": _prior((1, 1), (0, step)),
              "c": _prior((1,), (2 * step,))}
    belief = posterior(priors, _measure((spec, 1.)), timing)
    assert belief.base.fraction_evidence == 1  # not 3/4 on the pending side
    table = belief.future_records(FutureRecordsQuery("c", arrival, b.at.run, ((b.body.job, "b"),)))
    cells = table.build()
    measure = AtomicPolynomialMeasure(priors)
    branches = {}
    for (readings, order), row in cells.items():
        assert order in ((), (b.id,))
        branches[readings[0]] = branches.get(readings[0], F(0)) + sum(
            (measure.expectation(measure.likelihood(cell[0])) for cell in row.values()), F(0))
    assert branches[arrival] == branches[arrival + step] == F(1, 2)
    assert sum(branches.values()) == belief.base.fraction_evidence
    assert branches["other"] == branches["infinite"] == 0
    for b_duration, c_duration in product((0, step, None), (2 * step, None)):
        allocation = {a.id: step, b.id: b_duration, table.candidate.attempt: c_duration}
        assert sum(cell[0](allocation) for row in cells.values() for cell in row.values()) == table.kernels[0](allocation)
    completed = []
    for duration in (0, step):
        real, old, (pending,), now, _ = _causal_tie_pending_fixture(spec)
        real.observe(pending, now + duration, now + duration)
        finished = read_timing(real.records, timeline(real.records), real.jobs, real.attempts, {})
        assert HistoryKernel(finished, spec)({old.id: step, pending.id: duration}) == 1
        evidence = posterior(priors, _measure((spec, 1.)), finished).base.fraction_evidence
        assert evidence == branches[now + duration] == F(1, 2)
        completed.append(evidence)
    assert sum(completed) == belief.base.fraction_evidence == 1


@pytest.mark.parametrize("spec", [MeasureSpec("exact", "1", {}), _tick(8, {"point_ns": 0})],
                         ids=["exact", "tick-point"])
@pytest.mark.parametrize("timed", [True, False], ids=["timed", "untimed"])
def test_d27_d16_causal_three_tie_has_two_allowed_orders_and_future_sum(spec, timed):
    from sui.timeline import timeline
    r, a, (b, c), arrival, step = _causal_tie_pending_fixture(spec, second=True, timed=timed)
    timing = read_timing(r.records, timeline(r.records), r.jobs, r.attempts, {})
    kernel = HistoryKernel(timing, spec)
    allocation = {a.id: step, b.id: 0, c.id: 0}
    assert kernel(allocation) == 1
    refs = (a.id, b.id, c.id)
    # Independent finite reference: only A before B and A before C are imposed.
    allowed = [order for order in permutations(refs)
               if order.index(a.id) < order.index(b.id) and order.index(a.id) < order.index(c.id)]
    assert allowed == [(a.id, b.id, c.id), (a.id, c.id, b.id)]
    events = {order: RecordEvent(kernel, order=order) for order in permutations(refs)}
    assert {order: event(allocation) for order, event in events.items()} == {
        order: F(1, len(allowed)) if order in allowed else F(0) for order in permutations(refs)}
    assert sum(event(allocation) for event in events.values()) == kernel(allocation)
    left, right = (events[order] for order in allowed)
    assert UnionEvent((left, right))(allocation) == 1
    assert ConjunctionEvent((left, right))(allocation) == 0
    priors = {"a": _prior((1,), (step,)), "b": _prior((1,), (0,)),
              "c": _prior((1,), (0,)), "d": _prior((1,), (2 * step,))}
    belief = posterior(priors, _measure((spec, 1.)), timing)
    table = belief.future_records(FutureRecordsQuery("d", arrival, b.at.run,
        ((b.body.job, "b"), (c.body.job, "c"))))
    cells = table.build()
    future_allocation = {**allocation, table.candidate.attempt: 2 * step}
    order_masses = {order: sum(cell[0](future_allocation) for row_key, row in cells.items()
        if row_key[1] == order for cell in row.values()) for order in ((b.id, c.id), (c.id, b.id))}
    assert order_masses == {(b.id, c.id): F(1, 2), (c.id, b.id): F(1, 2)}
    assert sum(cell[0](future_allocation) for row in cells.values() for cell in row.values()) == kernel(allocation) == 1
    assert belief.base.fraction_evidence == 1
    assert table.information().bounds == InformationBounds(0., 0.)
    finished = []
    for order in ((0, 1), (1, 0)):
        real, old, pending, now, _ = _causal_tie_pending_fixture(spec, second=True, timed=timed)
        for index in order:
            real.observe(pending[index], now, now if timed else None)
        history = read_timing(real.records, timeline(real.records), real.jobs, real.attempts, {})
        mass = posterior(priors, _measure((spec, 1.)), history).base.fraction_evidence
        assert mass == F(1, 2)
        finished.append(mass)
    assert sum(finished) == belief.base.fraction_evidence


def test_d27_u14_causal_tie_weight_reaches_piecewise_partition_lambda_sum_and_replicas():
    from sui.timeline import timeline
    spec = _tick(8, {"point_ns": 0})
    r, a, (b, c), arrival, step = _causal_tie_pending_fixture(spec, second=True)
    r.observe(b, arrival, arrival)
    r.observe(c, arrival, arrival)
    r.start("d", arrival + step)
    timing = read_timing(r.records, timeline(r.records), r.jobs, r.attempts, {})
    priors = {"a": _prior((1,), (step,)), "b": _prior((1,), (0,)), "c": _prior((1,), (0,)),
              "d": DurationPrior(2., BaseSpec("piecewise", "1", {"edges_ns": [0, 4], "masses": [1.],
                  "tail": {"kind": "pareto", "kappa": 1., "mass": 0.}, "p_inf": 0.}))}
    kernel = HistoryKernel(timing, spec)
    event = KernelEvent((kernel,))
    for measure in (_measure((spec, 1.)), _measure((spec, .5), (spec, .5))):
        evidence = partition_evidence(priors, measure, timing, tolerance=1e-12).evidence
        assert math.exp(evidence.log_value) == pytest.approx(.5, abs=1e-14)
    backend = ReplicaMoments(priors)
    first = backend.expectation(event, tolerance=1e-12)
    shared = backend.expectation(ConjunctionEvent((event, event)), tolerance=1e-12)
    independent = backend.expectation(ReplicaProduct((event, event)), tolerance=1e-12)
    assert math.exp(first.log_value) == pytest.approx(.5, abs=1e-14)
    assert math.exp(shared.log_value) == pytest.approx(.5, abs=1e-14)
    assert math.exp(independent.log_value) == pytest.approx(.25, abs=1e-14)


def _receipt_reference(durations, *, dynamic=False, external_times=()):
    # Independent finite generator: choose one ready report, then apply the
    # deterministic start rule. It uses no HistoryKernel/rank helpers.
    initial = ("A", "B") if dynamic else tuple(durations)
    pending = {ref: durations[ref] for ref in initial}
    trace = tuple(("start", ref, 0) for ref in initial)
    external = tuple(("external", "X" + str(i), t) for i, t in enumerate(external_times))

    def advance(pending, external, trace, weight, born):
        if not pending and not external:
            yield trace, weight
            return
        now = min((*pending.values(), *(event[2] for event in external)))
        if external and external[0][2] == now:
            yield from advance(pending, external[1:], trace + (external[0],), weight, born)
            return
        ready = tuple(ref for ref, time in pending.items() if time == now)
        for ref in ready:
            rest = {other: time for other, time in pending.items() if other != ref}
            next_trace = trace + (("report", ref, now),)
            next_born = born
            if dynamic and not born:
                next_trace += (("start", "C", now),)
                rest["C"] = now + durations["C"]
                next_born = True
            yield from advance(rest, external, next_trace, weight / len(ready), next_born)

    return tuple(advance(pending, external, trace, F(1), not dynamic))


def _receipt_trace_kernel(trace, durations):
    from sui.timeline import timeline
    r, attempts = _timing_fixture(), {}
    for kind, ref, time in trace:
        if kind == "start":
            attempts[ref] = r.start(ref.lower(), time)
        elif kind == "report":
            r.observe(attempts[ref], time, time)
        else:
            r.external(time)
    timing = read_timing(r.records, timeline(r.records), r.jobs, r.attempts, {})
    return HistoryKernel(timing, MeasureSpec("exact", "1", {})), {
        attempt.id: durations[ref] for ref, attempt in attempts.items()}


@pytest.mark.parametrize("dynamic", [False, True], ids=["all-started", "start-after-first"])
@pytest.mark.parametrize("values", tuple(product(range(3), repeat=3)))
@pytest.mark.parametrize("external_times", [(), (0,), (1,), (2,)])
def test_d27_d16_sequential_receipts_all_exclusive_histories_and_all_prefixes(dynamic, values, external_times):
    durations = dict(zip("ABC", values))
    leaves = _receipt_reference(durations, dynamic=dynamic, external_times=external_times)
    assert len({trace for trace, _ in leaves}) == len(leaves)
    assert sum(weight for _, weight in leaves) == 1
    prefixes, kernels, probabilities = {}, [], {}
    for trace, weight in leaves:
        kernel, allocation = _receipt_trace_kernel(trace, durations)
        probability = kernel(allocation)
        assert probability == weight
        probabilities[trace] = probability
        kernels.append(kernel)
        for cut in range(len(trace) + 1):
            prefix = trace[:cut]
            prefixes[prefix] = prefixes.get(prefix, F(0)) + weight
    assert sum(probabilities.values()) == KernelEvent(tuple(kernels))(allocation) == 1
    assert KernelEvent(tuple(kernels)).complement()(allocation) == 0
    for i, first in enumerate(kernels):
        for second in kernels[i + 1:]:
            assert ConjunctionEvent((KernelEvent((first,)), KernelEvent((second,))))(allocation) == 0
    for prefix, expected in prefixes.items():
        kernel, prefix_allocation = _receipt_trace_kernel(prefix, durations)
        assert kernel(prefix_allocation) == expected
        assert sum(p for trace, p in probabilities.items() if trace[:len(prefix)] == prefix) == expected
        children = {trace[:len(prefix) + 1] for trace, _ in leaves
                    if len(trace) > len(prefix) and trace[:len(prefix)] == prefix}
        if children:
            assert sum(prefixes[child] for child in children) == expected


def test_d27_sequential_dynamic_birth_four_histories_each_quarter_and_shared_union():
    durations = {"A": 1, "B": 1, "C": 0}
    leaves = _receipt_reference(durations, dynamic=True)
    kernels, probabilities = [], {}
    for trace, reference in leaves:
        kernel, allocation = _receipt_trace_kernel(trace, durations)
        probabilities["".join(ref for kind, ref, _ in trace if kind == "report")] = kernel(allocation)
        assert kernel(allocation) == reference
        kernels.append(kernel)
    assert probabilities == dict.fromkeys(("ABC", "ACB", "BAC", "BCA"), F(1, 4))
    events = tuple(KernelEvent((k,)) for k in kernels)
    assert sum(probabilities.values()) == KernelEvent(tuple(kernels))(allocation) == UnionEvent(events)(allocation) == 1
    assert UnionEvent((events[0], events[0]))(allocation) == F(1, 4)
    assert ConjunctionEvent((events[0], events[0]))(allocation) == F(1, 4)
    assert ConjunctionEvent((events[0], events[1])).complement()(allocation) == 1


@pytest.mark.parametrize("new_duration", [0, 1, 2, None])
def test_d27_d16_sequential_new_start_does_not_add_evidence_and_public_future_sums(new_duration):
    trace = (("start", "A", 0), ("start", "B", 0), ("report", "A", 1))
    durations = {"A": 1, "B": 1, "C": new_duration}
    prefix, allocation = _receipt_trace_kernel(trace, durations)
    assert prefix(allocation) == F(1, 2)
    continued, allocation = _receipt_trace_kernel(trace + (("start", "C", 1),), durations)
    assert continued(allocation) == F(1, 2)
    priors = {"a": _prior((1,), (1,)), "b": _prior((1,), (1,)),
              "c": _prior((1, 1, 1, 1), (0, 1, 2, None)), "d": _prior((1,), (2,))}
    belief = posterior(priors, _measure((continued.spec, 1.)), continued.timing)
    assert belief.base.fraction_evidence == F(1, 2)
    assert belief.base.fraction_new_value("c") == dict.fromkeys((0, 1, 2, None), F(1, 4))
    pending = tuple((a.job, a.action) for a in continued.attempts if a.state == "pending")
    run = continued.timing.events[continued.attempts[0].start_event].run
    table = belief.future_records(FutureRecordsQuery("d", 1, run, pending))
    cells = table.build()
    allocation[table.candidate.attempt] = 2
    assert sum(cell[0](allocation) for row in cells.values() for cell in row.values()) == table.kernels[0](allocation) == F(1, 2)


@pytest.mark.parametrize("kind", ["external", "unrecorded"])
def test_d27_d16_equal_time_external_receipt_precedes_report_without_half_weight(kind):
    spec = MeasureSpec("exact", "1", {})
    kernels = []
    for order in (("check", "report"), ("report", "check")):
        events = [("s", 0, "start", "A")]
        events += [(ref, 1, kind if ref == "check" else "report", None if ref == "check" else "A") for ref in order]
        checks = ("check",) if order[0] == "check" else ()
        timing = _history(events, (AttemptTiming("A", "jA", "a", "s", checks, "report", "complete"),))
        kernels.append(HistoryKernel(timing, spec))
    assert tuple(k({"A": 1}) for k in kernels) == (1, 0)
    assert KernelEvent(tuple(kernels))({"A": 1}) == 1
    prefix = _history([("s", 0, "start", "A"), ("check", 1, kind, None)],
        (AttemptTiming("A", "jA", "a", "s", ("check",), None, "pending"),))
    assert HistoryKernel(prefix, spec)({"A": 1}) == kernels[0]({"A": 1}) == 1


def test_d27_u14_sequential_prefix_half_reaches_piecewise_partitions_and_replicas():
    from sui.timeline import timeline
    r = _timing_fixture()
    a, b = r.start("a", 8), r.start("b", 8)
    r.observe(a, 16, 16)
    r.start("c", 16)
    r.start("d", 24)
    timing = read_timing(r.records, timeline(r.records), r.jobs, r.attempts, {})
    spec = _tick(8, {"point_ns": 0})
    priors = {"a": _prior((1,), (8,)), "b": _prior((1,), (8,)), "c": _prior((1,), (0,)),
              "d": DurationPrior(2., BaseSpec("piecewise", "1", {"edges_ns": [0, 4], "masses": [1.],
                  "tail": {"kind": "pareto", "kappa": 1., "mass": 0.}, "p_inf": 0.}))}
    for measure in (_measure((spec, 1.)), _measure((spec, .5), (spec, .5))):
        evidence = partition_evidence(priors, measure, timing, tolerance=1e-12).evidence
        assert math.exp(evidence.log_value) == pytest.approx(.5, abs=1e-14)
    event = KernelEvent((HistoryKernel(timing, spec),))
    backend = ReplicaMoments(priors)
    for probability, expected in ((event, .5), (ConjunctionEvent((event, event)), .5),
                                  (ReplicaProduct((event, event)), .25)):
        assert math.exp(backend.expectation(probability, tolerance=1e-12).log_value) == pytest.approx(expected, abs=1e-14)
