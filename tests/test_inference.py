import math

import numpy as np
import pytest
from scipy.special import digamma

import sui.inference as inference
from sui.inference import (
    ModelViolation, belief, efe, expected_A, ledger, log_likelihood, novelty, policy_posterior, select,
)
from worlds import _close, _naive_efe, _naive_novelty, _naive_softmax, _true_A


@pytest.mark.parametrize("q,action,outcome", [
    ([.9, .1], "look1", 1), ([.3, .7], "look2", 0),
    ([1., 0.], "look1", 1), ([0., 1.], "look2", 0),
])
def test_i13_belief_matches_bayes_and_keeps_prior_zeros(q, action, outcome):
    q = np.array(q)
    A = _true_A()[action]
    old_q, old_A = q.copy(), A.copy()
    joint = [float(A[outcome, s]) * float(q[s]) for s in range(len(q))]
    n = np.zeros(len(A), dtype=np.int64)
    n[outcome] = 1
    result = belief(q, [log_likelihood(A, n, learnable=False)])
    _close(result, [value / sum(joint) for value in joint])
    assert np.all(result[q == 0] == 0)
    np.testing.assert_array_equal(q, old_q)
    np.testing.assert_array_equal(A, old_A)


def test_i13_likelihood_zero_and_impossible_observation():
    _close(belief(np.array([.4, .6]), [log_likelihood(np.eye(2), np.array([1, 0]), learnable=False)]), [1., 0.])
    with pytest.raises(ModelViolation):
        belief(np.array([.9, .1]), [log_likelihood(_true_A()["look1"], np.array([0, 0, 1]), learnable=False)])


def test_i13_tiny_probabilities_are_computed_in_log_space():
    A = np.array([[1e-200, 1e-310], [1., 1.]])
    result = belief(np.array([1e-200, 1.]), [log_likelihood(A, np.array([1, 0]), learnable=False)])
    expected = math.exp(math.log(1e-200) + math.log(1e-200) - math.log(1e-310))
    assert result[0] == pytest.approx(expected, rel=1e-12, abs=0)
    assert result[1] == 1.0


@pytest.mark.parametrize("q", [
    np.array([]), np.ones((1, 2)), np.array([-.1, 1.1]),
    np.array([.2, .7]), np.array([np.nan, 1.]), np.array([np.inf, 0.]),
    np.array([.5, .5000000001]),
])
def test_i13_invalid_belief(q):
    with pytest.raises(ValueError):
        belief(q, [])


@pytest.mark.parametrize("q0,action,risk,ambiguity,G", [
    (.9, "look1", .693648803604, .361889394108, 1.055538197712),
    (.9, "look2", .408668530210, .656340759843, 1.065009290053),
    (.9, "wait", 1.098612288668, 0., 1.098612288668),
    (.1, "look1", .408668530210, .656340759843, 1.065009290053),
    (.1, "look2", .693648803604, .361889394108, 1.055538197712),
    (.1, "wait", 1.098612288668, 0., 1.098612288668),
    (.5, "look1", .487747986613, .509115076976, .996863063589),
    (.5, "look2", .487747986613, .509115076976, .996863063589),
    (.5, "wait", 1.098612288668, 0., 1.098612288668),
])
def test_i2_fixed_risk_ambiguity_and_G(q0, action, risk, ambiguity, G):
    actual_risk, actual_ambiguity, q_o = efe(
        np.array([q0, 1 - q0]), _true_A()[action], np.full(3, -math.log(3)),
    )
    _close([actual_risk, actual_ambiguity, actual_risk + actual_ambiguity], [risk, ambiguity, G])
    assert type(actual_risk) is float
    assert type(actual_ambiguity) is float
    assert q_o.dtype == np.float64


@pytest.mark.parametrize("q,A,C", [
    ([.2, .3, .5], [[.7, .2, .1], [.1, .5, .6], [.2, .3, .3]], [.2, .5, .3]),
    ([.4, .6], [[1., 0.], [0., .4], [0., .6]], [.1, .2, .7]),
    ([.1, .2, .7], [[.8, .3, .6], [.2, .7, .4]], [.6, .4]),
])
def test_i3_matches_double_loop(q, A, C):
    q, A, log_C = np.array(q), np.array(A), np.log(C)
    originals = [value.copy() for value in (q, A, log_C)]
    actual = efe(q, A, log_C)
    expected = _naive_efe(q, A, log_C)
    _close(actual[:2], expected[:2])
    _close(actual[2], expected[2])
    for value, original in zip((q, A, log_C), originals):
        np.testing.assert_array_equal(value, original)


@pytest.mark.parametrize("q0,action,fixed", [
    (.9, "look1", 1.055538197712469), (.9, "look2", 1.065009290052806),
    (.3, "look1", 1.017276080513398), (.3, "look2", 1.007206562778727),
])
def test_i4_uniform_preferences_information_identity(q0, action, fixed):
    q, A = np.array([q0, 1 - q0]), _true_A()[action]
    q_o = [sum(float(A[o, s]) * float(q[s]) for s in range(2)) for o in range(3)]
    information = 0.0
    for s in range(2):
        for o in range(3):
            joint = float(q[s]) * float(A[o, s])
            if joint > 0:
                information += joint * math.log(joint / (float(q[s]) * q_o[o]))
    risk, ambiguity, _ = efe(q, A, np.full(3, -math.log(3)))
    _close(risk + ambiguity, math.log(3) - information)
    _close(risk + ambiguity, fixed, atol=1e-14)


def test_i5_softmax_fixed_values_shift_precision_and_ties():
    G = np.array([1.055538197712, 1.065009290053, 1.098612288668])
    original = G.copy()
    result = policy_posterior(G, 64.0)
    _close(result, [.621525219, .339008974, .039465808], atol=1e-9)
    _close(policy_posterior(G + 1234., 64.0), result, atol=1e-9)
    _close(policy_posterior(G, 1.0), _naive_softmax(G, 1.0))
    assert not np.allclose(policy_posterior(G, 1.0), result)
    _close(policy_posterior(np.ones(3), 64.0), [1 / 3] * 3)
    np.testing.assert_array_equal(G, original)


@pytest.mark.parametrize("G,gamma,error", [
    (np.array([]), 1.0, ValueError), (np.array([np.nan]), 1.0, ValueError),
    (np.array([np.inf]), 1.0, ValueError), (np.ones((1, 2)), 1.0, ValueError),
    (np.ones(2), 0.0, ValueError), (np.ones(2), -1.0, ValueError),
    (np.ones(2), np.inf, ValueError), (np.ones(2), np.nan, ValueError),
    (np.ones(2), 64, TypeError), (np.ones(2), True, TypeError),
])
def test_i5_invalid_policy_input(G, gamma, error):
    with pytest.raises(error):
        policy_posterior(G, gamma)


def test_i5_extreme_finite_G_and_gamma_do_not_overflow():
    _close(policy_posterior(np.array([-1e308, 0., 1e308]), 1e308), [1., 0., 0.])


def test_i5_difference_overflow_with_small_gamma_keeps_both_weights():
    denominator = math.e + 1 / math.e
    expected = [math.e / denominator, (1 / math.e) / denominator]
    result = policy_posterior(np.array([-1e308, 1e308]), 1e-308)
    _close(result, expected, atol=1e-12)


def test_i6_same_candidates_changed_evidence_swaps_probabilities():
    probabilities = []
    for q0 in (.9, .1):
        q = np.array([q0, 1 - q0])
        log_C = np.full(3, -math.log(3))
        matrices = list(_true_A().values())
        G = np.array([sum(efe(q, A, log_C)[:2]) for A in matrices])
        expected_G = [sum(_naive_efe(q, A, log_C)[:2]) for A in matrices]
        actual = policy_posterior(G, 64.0)
        _close(actual, _naive_softmax(expected_G, 64.0))
        probabilities.append(actual)
    _close(probabilities[0], probabilities[1][[1, 0, 2]])


@pytest.mark.parametrize("u,index", [(0.0, 0), (.59, 0), (.6, 1), (.95, 2)])
def test_i7_inverse_cdf_boundaries(u, index):
    probabilities = np.array([.6, .3, .1])
    old = probabilities.copy()
    assert select(probabilities, u) == index
    np.testing.assert_array_equal(probabilities, old)


def test_i7_rounding_falls_back_to_last_positive_and_tie_boundary():
    probabilities = np.array([.1] * 10 + [0.])
    assert np.cumsum(probabilities)[-1] == .9999999999999999
    assert select(probabilities, .9999999999999999) == 9
    assert select(np.full(3, 1 / 3), 1 / 3) == 1
    assert select(np.array([0., 1., 0.]), 0.0) == 1


@pytest.mark.parametrize("u,error", [(1.0, ValueError), (-.1, ValueError), (np.nan, ValueError),
                                          (np.inf, ValueError), (True, TypeError), (1, TypeError)])
def test_i7_invalid_uniform_draw(u, error):
    with pytest.raises(error):
        select(np.array([.6, .3, .1]), u)


@pytest.mark.parametrize("probabilities", [np.array([]), np.array([-.1, 1.1]),
    np.array([np.nan, 1.]), np.array([.6, .3]), np.ones((1, 1))])
def test_i7_invalid_probabilities(probabilities):
    with pytest.raises(ValueError):
        select(probabilities, .5)


def test_i8_expected_A_is_column_mean_without_mutating_counts():
    a = np.array([[2, 1], [6, 1], [0, 3]])
    old = a.copy()
    result = expected_A(a)
    _close(result, [[2 / 8, 1 / 5], [6 / 8, 1 / 5], [0, 3 / 5]])
    assert result.dtype == np.float64
    np.testing.assert_array_equal(a, old)
    _close(expected_A(np.full((2, 2), 1e308)), np.full((2, 2), .5))


@pytest.mark.parametrize("a", [np.ones(2), np.empty((0, 2)), np.empty((2, 0)),
    np.array([[0., 1.], [0., 1.]]), np.array([[-1., 1.], [2., 1.]]),
    np.array([[np.nan, 1.], [1., 1.]]), np.array([[np.inf, 1.], [1., 1.]])])
def test_i8_invalid_counts_in_both_functions(a):
    with pytest.raises(ValueError):
        expected_A(a)
    with pytest.raises(ValueError):
        ledger(a, np.zeros(a.shape[0] if a.ndim == 2 and a.size else 1))


def test_i9_nonuniform_preferences_change_ranking():
    actual = [sum(efe(np.array([.9, .1]), A, np.log([.1, .2, .7]))[:2])
              for A in _true_A().values()]
    _close(actual, [2.162470396760013, 1.894682616876371, .356674943938732], atol=1e-14)
    assert actual[2] < actual[1] < actual[0]


@pytest.mark.parametrize("log_C", [np.array([0., 0., 0.]), np.array([-np.inf, 0., 0.]),
    np.array([np.nan, 0., 0.]), np.log([.5, .5]), np.empty(0), np.zeros((3, 1)),
    np.array([1e308, -1e308, 0.])])
def test_i9_invalid_log_preferences(log_C):
    with pytest.raises(ValueError):
        efe(np.array([.9, .1]), _true_A()["look1"], log_C)


@pytest.mark.parametrize("call", [
    lambda: expected_A([[1., 1.]]),
    lambda: log_likelihood([[1., 1.]], np.zeros(1), learnable=False),
    lambda: belief([.5, .5], []),
    lambda: belief(np.array([.5, .5]), [[0., 0.]]),
    lambda: ledger([[1., 1.]], np.zeros(1)),
    lambda: log_likelihood(np.ones((1, 2)), [0.], learnable=False),
    lambda: efe(np.array([.5, .5]), np.eye(2), [0., 0.]),
    lambda: policy_posterior([1., 2.], 1.0),
    lambda: select([.5, .5], .5),
    lambda: expected_A(np.array([["1", "1"]])),
    lambda: expected_A(np.array([[1j, 1j]])),
])
def test_i1_array_types_are_checked(call):
    with pytest.raises(TypeError):
        call()


@pytest.mark.parametrize("q", [[.5, .5], [.9, .1], [.2, .8]])
def test_i11_unknown_counts_have_fixed_novelty(q):
    result = novelty(np.array(q), np.array([[1, 1], [1, 1], [0, 0]]))
    _close(result, math.log(2) - .5, atol=1e-14)
    _close(result, .193147180559945, atol=1e-14)
    assert type(result) is float


@pytest.mark.parametrize("a,q,expected", [
    ([[9, 5], [1, 5], [0, 0]], [.9, .1], .042718759187663),
    ([[9, 5], [1, 5], [0, 0]], [.2, .8], .046447037538944),
    ([[5, 1], [5, 9], [0, 0]], [.9, .1], .046979648731984),
    ([[90, 50], [10, 50], [0, 0]], [.9, .1], .004921741466061),
    ([[0, 0], [0, 0], [4, 2]], [.9, .1], 0.0),
    ([[1, 0], [1, 1], [0, 1]], [.9, .1], .193147180559945),
    ([[9, 5], [1, 5], [0, 0]], [1., 0.], .042186147994622),
    ([[2, 1], [3, 1], [5, 2]], [.3, .7], .172176634283505),
    ([[2, 8], [2, 8], [0, 0]], [.5, .5], .070044588707353),
])
def test_i11_fixed_novelty_and_inputs_are_unchanged(a, q, expected):
    a, q = np.array(a), np.array(q)
    old_a, old_q = a.copy(), q.copy()
    a.setflags(write=False)
    q.setflags(write=False)
    result = novelty(q, a)
    _close(result, expected, atol=1e-14)
    assert type(result) is float and result >= 0
    np.testing.assert_array_equal(a, old_a)
    np.testing.assert_array_equal(q, old_q)


def test_i11_more_counts_reduce_novelty():
    a = np.array([[9, 5], [1, 5], [0, 0]])
    q = np.array([.9, .1])
    assert novelty(q, 10 * a) < novelty(q, a)


@pytest.mark.parametrize("a,q", [
    ([[9, 5], [1, 5], [0, 0]], [.9, .1]),
    ([[9, 5], [1, 5], [0, 0]], [.2, .8]),
    ([[5, 1], [5, 9], [0, 0]], [.9, .1]),
])
def test_i11_matches_independent_general_dirichlet_kl(a, q):
    a, q = np.array(a, dtype=float), np.array(q)
    _close(novelty(q, a), _naive_novelty(q, a), atol=1e-14)


@pytest.mark.parametrize("q", [
    np.array([1.]), np.array([]), np.ones((1, 2)), np.array([-.1, 1.1]),
    np.array([.2, .7]), np.array([np.nan, 1.]), np.array([np.inf, 0.]),
    np.array([.5, .5000000001]),
])
def test_i11_invalid_belief(q):
    with pytest.raises(ValueError):
        novelty(q, np.ones((2, 2)))


@pytest.mark.parametrize("a", [
    np.ones(2), np.empty((0, 2)), np.empty((2, 0)),
    np.array([[0., 1.], [0., 1.]]), np.array([[-1., 1.], [2., 1.]]),
    np.array([[np.nan, 1.], [1., 1.]]), np.array([[np.inf, 1.], [1., 1.]]),
])
def test_i11_invalid_counts(a):
    with pytest.raises(ValueError):
        novelty(np.array([.5, .5]), a)


@pytest.mark.parametrize("q,a", [
    ([.5, .5], np.ones((2, 2))),
    (np.array([.5, .5]), [[1., 1.], [1., 1.]]),
    (np.array([True, False]), np.ones((2, 2))),
    (np.array([.5, .5]), np.ones((2, 2), dtype=bool)),
    (np.array([.5j, .5j]), np.ones((2, 2))),
    (np.array([.5, .5]), np.array([["1", "1"]])),
])
def test_i11_invalid_array_types(q, a):
    with pytest.raises(TypeError):
        novelty(q, a)


def test_i11_overflowing_column_sums_still_give_finite_nonnegative_novelty():
    result = novelty(np.array([.5, .5]), np.full((2, 2), 1e308))
    assert math.isfinite(result)
    assert 0 <= result <= 1e-300


@pytest.mark.parametrize("x", [999.999, 1000.0])
def test_i11_both_sides_of_series_boundary_match_direct_digamma(x):
    g_x = float(digamma(x + 1)) - math.log(x)
    g_total = float(digamma(2 * x + 1)) - math.log(2 * x)
    result = novelty(np.array([1.0]), np.array([[x], [x]]))
    _close(result, g_x - g_total, atol=1e-14)


def test_i11_three_states_match_fixed_value_and_general_dirichlet_kl():
    a = np.array([[1., 2., 3.], [2., 1., 1.], [1., 1., 4.]])
    q = np.array([.2, .3, .5])
    result = novelty(q, a)
    _close(result, .158505857092729, atol=1e-14)
    _close(result, _naive_novelty(q, a), atol=1e-14)


@pytest.mark.parametrize("learnable", [False, True])
def test_i12_empty_counts_are_zero_without_calling_betaln(learnable, monkeypatch):
    def unexpected(*args):
        pytest.fail("betaln must not be called for zero counts")
    monkeypatch.setattr(inference, "_betaln", unexpected)
    result = log_likelihood(np.array([[.9, .1], [.1, .9]]), np.zeros(2), learnable=learnable)
    np.testing.assert_array_equal(result, [0., 0.])
    assert result.dtype == np.float64


def test_i12_fixed_likelihood_and_dirichlet_multinomial_difference():
    a, n = np.array([[.9, .1], [.1, .9]]), np.array([2, 1])
    old_a, old_n = a.copy(), n.copy()
    a.setflags(write=False)
    n.setflags(write=False)
    result = log_likelihood(a, n, learnable=False)
    _close(result, [2 * math.log(.9) + math.log(.1), 2 * math.log(.1) + math.log(.9)])
    np.testing.assert_array_equal(a, old_a)
    np.testing.assert_array_equal(n, old_n)
    a, n = np.array([[9, 5], [1, 5], [0, 0]]), np.array([0., 2., 0.])
    old_a, old_n = a.copy(), n.copy()
    result = log_likelihood(a, n, learnable=True)
    _close(result[0] - result[1], -2.708050201102210)
    np.testing.assert_array_equal(a, old_a)
    np.testing.assert_array_equal(n, old_n)


@pytest.mark.parametrize("learnable", [False, True])
@pytest.mark.parametrize("n,possible", [([1, 0, 0], [True, False]), ([0, 0, 1], [False, True])])
def test_i12_structural_zeros(n, possible, learnable):
    result = log_likelihood(np.array([[1, 0], [1, 1], [0, 1]]), np.array(n), learnable=learnable)
    np.testing.assert_array_equal(np.isfinite(result), possible)
    assert np.all(np.isneginf(result[~np.array(possible)]))


@pytest.mark.parametrize("a,fixed,tolerance", [
    ([[1e15, 2], [3e15, 5]], .058698365201276, 1e-12),
    ([[1e300, 2], [1e300, 5]], .516279474448454, 1e-11),
])
def test_i12_confident_priors_match_fixed_and_independent_rising_products(a, fixed, tolerance):
    a, n = np.array(a), np.array([3, 4])
    exact_logs = []
    for column in a.T:
        terms = [math.log(float(x) + j) for x, count in zip(column, n) for j in range(int(count))]
        terms.extend(-math.log(math.fsum(column) + j) for j in range(7))
        exact_logs.append(math.fsum(terms))
    result = log_likelihood(a, n, learnable=True)
    _close(result[0] - result[1], fixed, atol=tolerance)
    _close(result[0] - result[1], exact_logs[0] - exact_logs[1], atol=tolerance)


def test_i12_random_likelihoods_match_independent_formula():
    rng = np.random.default_rng(20260929)
    for case in range(50):
        states = 2 if case % 2 == 0 else 3
        while True:
            a = rng.uniform(.2, 5, (3, states))
            a[rng.random((3, states)) < .3] = 0
            if np.all(a.sum(axis=0) > 0):
                break
        n = rng.integers(0, 13, size=3)
        learnable = case % 2 == 0
        expected = []
        for column in a.T:
            if any(x == 0 and count > 0 for x, count in zip(column, n)):
                expected.append(-math.inf)
                continue
            total = math.fsum(column)
            if learnable:
                value = math.lgamma(total) - math.lgamma(total + sum(map(int, n)))
                value += math.fsum(math.lgamma(float(x) + int(count)) - math.lgamma(x)
                                   for x, count in zip(column, n) if x > 0)
            else:
                value = math.fsum(int(count) * (math.log(x) - math.log(total))
                                   for x, count in zip(column, n) if count > 0)
            expected.append(value)
        expected = np.array(expected)
        result = log_likelihood(a, n, learnable=learnable)
        finite = np.isfinite(expected)
        np.testing.assert_array_equal(np.isfinite(result), finite)
        assert np.all(np.isneginf(result[~finite]))
        if np.any(finite):
            r = np.flatnonzero(finite)[0]
            _close(result[finite] - result[r], expected[finite] - expected[r])


@pytest.mark.parametrize("n,error", [
    (np.zeros(1), ValueError), (np.array([-1, 0]), ValueError),
    (np.array([1.5, 0]), ValueError), (np.array([np.nan, 0]), ValueError),
    (np.array([np.inf, 0]), ValueError), (np.ones(2, dtype=bool), TypeError),
    ([0, 0], TypeError), (np.zeros((1, 2)), ValueError),
    (np.array([2**53, 0], dtype=np.int64), ValueError),
    (np.array([2**62, 2**62], dtype=np.int64), ValueError),
    (np.array([1e308, 0]), ValueError),
    (np.array([1j, 0j]), TypeError), (np.array(["1", "0"]), TypeError),
])
@pytest.mark.parametrize("function", [ledger, log_likelihood])
def test_i12_i8_invalid_observation_counts(function, n, error):
    kwargs = {"learnable": True} if function is log_likelihood else {}
    with pytest.raises(error):
        function(np.ones((2, 2)), n, **kwargs)


@pytest.mark.parametrize("a", [
    np.ones(2), np.empty((0, 2)), np.empty((2, 0)),
    np.array([[0., 1.], [0., 1.]]), np.array([[-1., 1.], [2., 1.]]),
    np.array([[np.nan, 1.], [1., 1.]]), np.array([[np.inf, 1.], [1., 1.]]),
])
def test_i12_invalid_prior_counts(a):
    n = np.zeros(a.shape[0] if a.ndim == 2 and a.size else 1)
    with pytest.raises(ValueError):
        log_likelihood(a, n, learnable=True)


@pytest.mark.parametrize("value", [1, None, np.bool_(True)])
def test_i12_learnable_requires_bool(value):
    with pytest.raises(TypeError):
        log_likelihood(np.ones((2, 2)), np.zeros(2), learnable=value)


def test_i12_overflowing_column_sums_are_only_rejected_when_learnable():
    a = np.full((3, 2), 1e308)
    for n in (np.zeros(3), np.array([1, 0, 0])):
        with pytest.raises(ValueError):
            log_likelihood(a, n, learnable=True)
        assert np.all(np.isfinite(log_likelihood(a, n, learnable=False)))


def test_i12_fixed_extreme_counts_do_not_lose_possible_observations():
    result = log_likelihood(np.array([[1e-300, 1], [1e300, 1]]), np.array([1, 0]), learnable=False)
    _close(result, [-1381.551055796427, -.693147180559945])
    assert np.all(np.isfinite(result))


@pytest.mark.parametrize("n,expected", [([1, 0], 0.), ([2, 0], .405465108108164)])
def test_i12_subnormal_priors_use_beta_recurrence(n, expected):
    result = log_likelihood(np.array([[1e-310, 1], [1e-310, 1]]), np.array(n), learnable=True)
    assert np.all(np.isfinite(result))
    _close(result[0] - result[1], expected)


def test_i12_numerical_failure_is_not_impossibility(monkeypatch):
    monkeypatch.setattr(inference, "_betaln", lambda *args: np.inf)
    with pytest.raises(FloatingPointError):
        log_likelihood(np.ones((2, 2)), np.array([1, 0]), learnable=True)


@pytest.mark.parametrize("a,n,expected", [
    ([[9, 5], [1, 5], [0, 0]], [0, 1, 0], [[9, 5], [2, 6], [0, 0]]),
    ([[1, 0], [1, 1], [0, 1]], [1, 0, 0], [[2, 0], [1, 1], [0, 1]]),
    ([[1, 0], [1, 1], [0, 1]], [0, 1, 0], [[1, 0], [2, 2], [0, 1]]),
    ([[1, 0], [1, 1], [0, 1]], [0, 0, 1], [[1, 0], [1, 1], [0, 2]]),
    ([[1, 0], [0, 1]], [1, 0], [[2, 0], [0, 1]]),
    ([[1, 1], [0, 0]], [0, 3], [[1, 1], [0, 0]]),
])
def test_i8_ledger_adds_each_count_to_positive_cells_without_mutation(a, n, expected):
    a, n = np.array(a), np.array(n)
    old_a, old_n = a.copy(), n.copy()
    a.setflags(write=False)
    n.setflags(write=False)
    result = ledger(a, n)
    np.testing.assert_array_equal(result, expected)
    assert result.dtype == np.float64
    np.testing.assert_array_equal(a, old_a)
    np.testing.assert_array_equal(n, old_n)


@pytest.mark.parametrize("function", [ledger, log_likelihood])
def test_i12_i8_count_limit_is_inclusive_and_a_is_validated_first(function):
    kwargs = {"learnable": False} if function is log_likelihood else {}
    result = function(np.ones((1, 1)), np.array([2**53 - 1], dtype=np.int64), **kwargs)
    np.testing.assert_array_equal(result, [[2**53]] if function is ledger else [0.])
    with pytest.raises(ValueError):
        function(np.array([[-1.]]), [0], **kwargs)


@pytest.mark.parametrize("D,likelihoods,expected", [
    ([.5, .5], [[-800, -800]], [.5, .5]),
    ([.9, .1], [[-1e20, -1e20]], [.9, .1]),
    ([.9, .1], [[-1e20, 0], [0, -1e20]], [.9, .1]),
    ([.5, .5], [[-800, 0], [0, -800]], [.5, .5]),
    ([.5, .5000000000005], [], [.49999999999975, .50000000000025]),
    # 最大値は、ほかの尤度や D も含めた共通の支持で引く。
    ([.9, .1, 0.], [[-1e20, -1e20, 0]], [.9, .1, 0.]),
    ([.45, .05, .5], [[-1e20, -1e20, 0], [0, 0, -np.inf]], [.9, .1, 0.]),
])
def test_i13_normalization_preserves_prior_and_conflicting_evidence(D, likelihoods, expected):
    D = np.array(D)
    likelihoods = [np.array(value) for value in likelihoods]
    old_D, old_likelihoods = D.copy(), [value.copy() for value in likelihoods]
    result = belief(D, iter(likelihoods))
    _close(result, expected, atol=1e-15)
    _close(result.sum(), 1., atol=1e-15)
    assert result.dtype == np.float64
    np.testing.assert_array_equal(D, old_D)
    for value, old in zip(likelihoods, old_likelihoods):
        np.testing.assert_array_equal(value, old)


def test_i13_final_display_probability_can_underflow():
    result = belief(np.array([.5, .5]), [np.array([0, -800])])
    assert result[1] < 1e-300
    assert result[0] == 1.


@pytest.mark.parametrize("D,likelihoods", [
    ([.5, .5], [[-np.inf, -np.inf]]), ([1., 0.], [[-np.inf, 0]]),
    ([.5, .5], [[0, -np.inf], [-np.inf, 0]]),
])
def test_i13_no_common_support_is_model_violation(D, likelihoods):
    with pytest.raises(ModelViolation):
        belief(np.array(D), [np.array(value) for value in likelihoods])


def test_i13_overflow_is_numerical_failure_without_warnings():
    with pytest.raises(FloatingPointError):
        belief(np.array([.5, .5]), [np.array(value) for value in
               [[-1e308, 0], [0, -1e308], [-1e308, 0], [0, -1e308]]])


@pytest.mark.parametrize("value,error", [
    (np.array([np.inf, 0]), ValueError), (np.array([np.nan, 0]), ValueError),
    (np.zeros(1), ValueError), (np.zeros((1, 2)), ValueError),
    ([0, 0], TypeError), (np.ones(2, dtype=bool), TypeError),
    (np.array([1j, 0j]), TypeError), (np.array(["0", "0"]), TypeError),
])
def test_i13_invalid_log_likelihood(value, error):
    with pytest.raises(error):
        belief(np.array([.5, .5]), [value])
