"""v0.10 §7: certified refinement, including the four-bin saturated counter.

The independent interval integral is computed from the observation model,
not Claude's noncertified 120-count numerical reference or sui's algorithms.
Runtime is measured by pytest durations / reports, never a correctness limit.
"""
from fractions import Fraction as F
from functools import lru_cache

import pytest

from sui import rate
from s4b2_information_oracle import (
    Box, LOG_TWO, exp_box, exp_point, joint_masses, log_box,
)
from s4b2_fixtures import s4b2_independent_information
from s4b2_worlds import CANDIDATES, c1_world, evaluation_root
from test_s4b2_learning import JOINT_MASS, POSTERIOR


@pytest.fixture(scope="session")
def independent(s4b2_independent_information):
    return s4b2_independent_information


@lru_cache(maxsize=4)
def public_evaluation(n):
    view, resolved = evaluation_root(c1_world(n))
    return rate.evaluate_rate(view, CANDIDATES, resolved, budget=rate.default_rate_budget())


def assert_choice(evaluation, u, expected):
    chosen = rate.certify_choice(evaluation, u=u)
    assert (chosen.index, chosen.choice, chosen.u) == (expected, CANDIDATES[expected], u)
    assert chosen.previous.upper <= u < chosen.current.lower


@pytest.mark.parametrize("n", range(4))
def test_independent_ruler_keeps_all_four_count_bins_and_exact_joint_masses(n):
    z, cells = joint_masses(n)
    assert z == POSTERIOR[n][0]
    assert cells == JOINT_MASS[n]
    assert len(cells) == 4 and all(x > 0 for row in cells for x in row)
    assert sum(sum(row) for row in cells) == z


def test_independent_rational_series_and_signed_outward_arithmetic():
    assert exp_point(0).fractions() == (F(1), F(1))
    assert log_box(Box(1)).fractions() == (F(0), F(0))
    lo, hi = exp_box(LOG_TWO).fractions()
    assert lo <= 2 <= hi and hi-lo < F(1, 10**30)
    for x in (F(1, 10**6), F(2, 3), F(16)):
        lo, hi = (exp_point(x)*exp_point(-x)).fractions()
        assert lo <= 1 <= hi
        lo, hi = log_box(exp_point(x)).fractions()
        assert lo <= x <= hi
    lo, hi = (Box(F(-2, 3), F(-1, 3))*Box(F(2, 7), F(3, 7))).fractions()
    assert lo <= F(-2, 7) <= F(-2, 21) <= hi


@pytest.mark.parametrize("n", range(4))
def test_independent_full_information_integral_has_sub_1e8_probability_width(n, independent):
    information, q = independent[n]
    assert 0 < information[0] <= information[1]
    assert F(1, 2) < q[0] <= q[1] < F(2, 3)
    assert q[1]-q[0] <= F(1, 10**8)


def test_v010_standard_budget_narrows_probability_and_agrees_with_independent_small_budget(request):
    """The certified remainder must make progress with a bounded work budget.

    At 32 cells/refinements, the unmodified public evaluator encloses q(read)
    in an interval of width < 1/100. Accumulating whole-cell envelope widths
    as residuals exhausts this budget instead (M42); no wall-clock assertion.
    """
    budget = rate.RateBudget(F(1, 100), 32, 2000, 32)
    view, resolved = evaluation_root(c1_world(0))
    actual = rate.evaluate_rate(view, CANDIDATES, resolved, budget=budget)
    assert actual.certificate.budget == budget
    independent = request.getfixturevalue("independent")
    for quantity, expected in ((actual.information[0], independent[0][0]),
                               (actual.q_star[0], independent[0][1])):
        assert quantity.status == "finite" and quantity.support == "positive"
        assert quantity.bounds.lower <= expected[0] <= expected[1] <= quantity.bounds.upper
    assert actual.q_star[0].bounds.upper-actual.q_star[0].bounds.lower <= F(1, 100)


@pytest.mark.parametrize("n", range(4))
def test_v010_standard_budget_narrows_probability_and_agrees_with_independent_integral(n, independent):
    actual = public_evaluation(n)
    assert actual.candidates == CANDIDATES
    assert actual.certificate.budget == rate.default_rate_budget()
    # This is a diagnostic mathematical query with no u. Section 7 requires
    # narrowing capability independently of when a public act is certified.
    assert actual.q_star[0].bounds.upper-actual.q_star[0].bounds.lower <= F(1, 10**6)
    for quantity, expected in ((actual.information[0], independent[n][0]),
                               (actual.q_star[0], independent[n][1])):
        assert quantity.status == "finite" and quantity.support == "positive"
        assert quantity.bounds.lower <= expected[1] and expected[0] <= quantity.bounds.upper


@pytest.mark.parametrize("n", range(4))
@pytest.mark.parametrize("side,expected", [("below", 0), ("above", 1)])
def test_v010_standard_budget_certifies_both_sides_1e5_from_true_probability(n, side, expected, independent):
    lower, upper = independent[n][1]
    u = lower-F(1, 10**5) if side == "below" else upper+F(1, 10**5)
    assert 0 <= u < 1
    assert (lower-u if side == "below" else u-upper) >= F(1, 10**5)
    assert_choice(public_evaluation(n), u, expected)


@pytest.mark.parametrize("u,expected", [(F(59, 100), 0), (F(61, 100), 1),
    (F(60031, 100000), 0), (F(60035, 100000), 1), (F(6025, 10000), 1)])
def test_v010_n0_explicit_nearby_u_uses_saturated_observation_not_120_counts(u, expected, independent):
    lower, upper = independent[0][1]
    assert (lower-u if expected == 0 else u-upper) >= F(1, 10**5)
    assert_choice(public_evaluation(0), u, expected)
