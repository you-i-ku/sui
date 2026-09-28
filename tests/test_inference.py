import math

import numpy as np
import pytest
from scipy.special import digamma

from sui.inference import (
    ModelViolation, efe, expected_A, learn, novelty, policy_posterior, posterior, select,
)
from worlds import _close, _naive_efe, _naive_novelty, _naive_softmax, _true_A


@pytest.mark.parametrize("q,action,outcome", [
    ([.9, .1], "look1", 1), ([.3, .7], "look2", 0),
    ([1., 0.], "look1", 1), ([0., 1.], "look2", 0),
])
def test_i1_posterior_matches_bayes_and_keeps_prior_zeros(q, action, outcome):
    q = np.array(q)
    A = _true_A()[action]
    old_q, old_A = q.copy(), A.copy()
    joint = [float(A[outcome, s]) * float(q[s]) for s in range(len(q))]
    result = posterior(q, A, outcome)
    _close(result, [value / sum(joint) for value in joint])
    assert np.all(result[q == 0] == 0)
    np.testing.assert_array_equal(q, old_q)
    np.testing.assert_array_equal(A, old_A)


def test_i1_likelihood_zero_and_impossible_observation():
    _close(posterior(np.array([.4, .6]), np.eye(2), 0), [1., 0.])
    with pytest.raises(ModelViolation):
        posterior(np.array([.9, .1]), _true_A()["look1"], 2)


def test_i1_tiny_probabilities_are_computed_in_log_space():
    A = np.array([[1e-200, 1e-310], [1., 1.]])
    result = posterior(np.array([1e-200, 1.]), A, 0)
    expected = math.exp(math.log(1e-200) + math.log(1e-200) - math.log(1e-310))
    assert result[0] == pytest.approx(expected, rel=1e-12, abs=0)
    assert result[1] == 1.0


@pytest.mark.parametrize("q", [
    np.array([]), np.ones((1, 2)), np.array([-.1, 1.1]),
    np.array([.2, .7]), np.array([np.nan, 1.]), np.array([np.inf, 0.]),
    np.array([.5, .5000000001]),
])
def test_i1_invalid_belief(q):
    with pytest.raises(ValueError):
        posterior(q, _true_A()["look1"], 0)


@pytest.mark.parametrize("A", [
    np.ones(2), np.empty((0, 2)), np.empty((3, 0)),
    np.ones((3, 3)) / 3, np.ones((3, 2)),
    np.array([[1.1, .5], [-.1, .5]]),
    np.array([[np.nan, .5], [1., .5]]),
    np.array([[np.inf, .5], [1., .5]]),
    np.array([[.5, .5], [.5, .5000000001]]),
])
def test_i1_invalid_likelihood(A):
    with pytest.raises(ValueError):
        posterior(np.array([.9, .1]), A, 0)


@pytest.mark.parametrize("outcome,error", [(True, TypeError), (0.0, TypeError), (-1, ValueError), (3, ValueError)])
def test_i1_invalid_outcome(outcome, error):
    with pytest.raises(error):
        posterior(np.array([.9, .1]), _true_A()["look1"], outcome)


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


def test_i8_fractional_learning_copies_input_and_preserves_zeros():
    a = np.array([[9., 5.], [1., 5.], [0., 0.]])
    q = np.array([.09 / .14, .05 / .14])
    original_a, original_q = a.copy(), q.copy()
    result = learn(a, q, 1)
    _close(result, [[9, 5], [1.642857142857, 5.357142857143], [0, 0]])
    assert np.all(result[2] == 0)
    np.testing.assert_array_equal(a, original_a)
    np.testing.assert_array_equal(q, original_q)
    _close(learn(np.eye(2), np.array([1., 0.]), 0), [[2., 0.], [0., 1.]])


@pytest.mark.parametrize("outcome,q,error", [
    (2, np.array([.5, .5]), ValueError), (True, np.array([.5, .5]), TypeError),
    (3, np.array([.5, .5]), ValueError), (-1, np.array([.5, .5]), ValueError),
    (1, np.array([1.]), ValueError), (1, np.array([.5, .4]), ValueError),
    (1, np.array([np.nan, 0.]), ValueError),
])
def test_i8_invalid_learning(outcome, q, error):
    with pytest.raises(error):
        learn(np.array([[1., 1.], [1., 1.], [0., 0.]]), q, outcome)


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
        learn(a, np.array([.5, .5]), 0)


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
    lambda: posterior([.5, .5], np.eye(2), 0),
    lambda: posterior(np.array([.5, .5]), [[1., 0.], [0., 1.]], 0),
    lambda: efe(np.array([.5, .5]), np.eye(2), [0., 0.]),
    lambda: policy_posterior([1., 2.], 1.0),
    lambda: select([.5, .5], .5),
    lambda: learn(np.ones((2, 2)), [.5, .5], 0),
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
