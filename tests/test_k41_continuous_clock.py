"""K41-e / Z70. Short histories with certified, separated clock likelihoods."""

from fractions import Fraction as Q
from math import factorial

from sui import fb
from sui.rate import RateBudget
from test_fb_clock_belief import budget_contract_call, certified_belief_query, clock_prior
from test_fb_cycle import E, T
from test_fb_time_belief import assert_contains, enclose, exp_minus, script
from test_k41_propagation import rotation_integral
from k41_world import (
    HALF, ONE, adopt, at_entry, divide, entropy, expneg, minus, plus, rat, scaled,
    selection, times, worlds,
)


def switch_average(on, off):
    # Beta(7,1) and one clock part.
    return plus(scaled(Q(7, 8), on), scaled(Q(1, 8), off))


def check_separation(r, correct, alternatives, tolerance):
    lo, hi = correct
    assert hi - lo < tolerance / 64
    for left, right in alternatives:
        assert right - left < tolerance / 64
        assert max(lo - right, left - hi) > 2 * tolerance
    value = certified_belief_query(r, "mass", tolerance=tolerance)
    assert value.lower <= lo <= hi <= value.upper
    for left, right in alternatives:
        assert value.upper < left or right < value.lower


def test_one_rotation_is_shared_across_two_cursor_events(worlds):
    # With equal state rates, the first half-turn hazard H is uniform on [a,b].
    # One shared rotation gives exactly one arrival in that half and none
    # afterwards with probability E[H exp(-1)]. The cursor advances once.
    a, b = Q(1, 16), Q(15, 16)
    clock = clock_prior(phase=None, fractions=(b, a))
    r = worlds(script((1, 1, T), (2, 2, E)), clock=clock, rates=(1, 1),
               a=Q(7), b=Q(1), unit=HALF).direct()
    adopt(r)
    adopt(r, 1)
    shared = scaled(HALF, expneg(1))
    # Redrawing gives E[H exp(-H)] E[exp(-H)], from two independent halves.
    none = scaled(1/(b-a), minus(expneg(a), expneg(b)))
    one = scaled(1/(b-a), minus(scaled(1+a, expneg(a)), scaled(1+b, expneg(b))))
    redrawn = switch_average(times(one, none), shared)
    check_separation(r, enclose(shared, 32), [enclose(redrawn, 32)], Q(1, 256))
    assert r.passive.calls == [0, 1]


def test_full_turn_empty_retains_rotation_dependence_with_moving_state(worlds):
    # The A->B rate and the arrival rate in B are both k. For a full empty
    # turn Z_on = exp(-k) (1+k*J). With uniform rotation, J integrates
    # exp(F(end)-F(start)) over two independent uniform points on the circle.
    # The primitive F of k*(clock_multiplier-1) is triangular, uniform on [0,h].
    k, w, f = Q(3, 2), Q(1, 4), Q(15, 16)
    h = k * (f - w)
    clock = clock_prior(phase=None, widths=(w, 1-w), fractions=(f, 1-f))
    r = worlds(clock=clock, process=((-k, k), (0, 0)), rates=(0, k), a=Q(7), b=Q(1)).start()
    adopt(r)
    down = expneg(h)
    up = divide(ONE, down)
    high_first = scaled(1/h, minus(up, ONE))
    low_first = scaled(1/h, minus(ONE, down))
    off = scaled(1+k, expneg(k))

    def mass(j):
        return switch_average(times(expneg(k), plus(ONE, scaled(k, j))), off)

    correct = enclose(mass(times(high_first, low_first)), 32)
    # Ignoring theta yields the flat-clock result; freezing a single phase at a
    # segment boundary yields the high-first or low-first result.
    wrong = [enclose(x, 32) for x in (off, mass(high_first), mass(low_first))]
    check_separation(r, correct, wrong, Q(1, 80))


def width_world(worlds, rate):
    clock = clock_prior(widths={"kind": "symmetric_dirichlet", "concentration": Q(1)})
    return worlds(clock=clock, process=((-rate, rate), (0, 0)), rates=(0, rate),
                  a=Q(7), b=Q(1)).start()


def width_mass(rate, left, right):
    # Uniform h = 3/4 - w. For each h the primitive has height rate*h,
    # so J(h) = integral_0^1 exp(rate*h*t) dt. Integrate the power series
    # over the retained interval of h with its ORIGINAL prior density.
    n = 32
    assert 0 < rate <= 1 and -1 <= left < right <= 1 and right-left <= 1
    length = right - left
    j = sum(rate**i * (right**(i+1) - left**(i+1)) / ((i+1)*factorial(i+1))
            for i in range(n+1))
    tail = length / factorial(n+2) / (1-Q(1, n+3))
    lo, hi = exp_minus(rate, n)
    off = (1+rate) / 8
    return (lo * (off + Q(7, 8)*(length + rate*(j-tail))),
            hi * (off + Q(7, 8)*(length + rate*(j+tail))))


def test_width_prior_includes_both_ends_with_a_moving_state(worlds):
    rate = Q(1, 16)
    r = width_world(worlds, rate)
    adopt(r)
    correct = width_mass(rate, Q(-1, 4), Q(3, 4))
    # Discarding either end quarter of the width prior also discards evidence.
    wrong = [width_mass(rate, Q(0), Q(3, 4)), width_mass(rate, Q(-1, 4), HALF)]
    check_separation(r, correct, wrong, Q(1, 12))


def test_width_query_respects_small_cell_budget_at_the_adopted_root(worlds, record_property):
    r = width_world(worlds, Q(1))
    expression = adopt(r)
    quantity = fb.BeliefQuantity(kind="mass")
    limits = RateBudget(tolerance=Q(1, 2**20), max_cells=8, max_terms=None, max_refinements=None)
    value = budget_contract_call(r, lambda: r.host.query_belief(
        belief=expression, quantity=quantity, budget=limits))
    lo, hi = width_mass(Q(1), Q(-1, 4), Q(3, 4))
    # A future method may finish within eight cells. Its certificate must
    # enclose the full-width prior at the requested precision on the same root.
    if value is None:
        record_property("budget_outcome", "incomplete")
    else:
        record_property("budget_outcome", "certified")
        assert value.root == expression.root and value.quantity == quantity
        assert value.lower <= lo <= hi <= value.upper
        assert value.upper - value.lower <= limits.tolerance
        assert r.host.verify_belief_value(belief=expression, value=value)
    coarse = certified_belief_query(r, "mass", tolerance=HALF)
    assert coarse.root == expression.root and coarse.lower <= lo <= hi <= coarse.upper


def test_uniform_rotation_posterior_reaches_native_selection(worlds):
    # With cursor zero, empty at one turn already implies empty at half a turn.
    # The one-record scene therefore has the posterior of ruler ④ [uniform].
    r = worlds(clock=clock_prior(phase=None), thinking=True, measurement=at_entry()).direct()
    history = adopt(r)
    # Unnormalized P(A,empty)=exp(-1), Z=exp(-1)*(3+J)/2.
    p_a = divide(rat(2), plus(rat(3), rotation_integral(None)))
    info = entropy(p_a)
    odds = ("exp", info)
    p_peek = divide(odds, plus(ONE, odds))
    tolerance = Q(1, 16)
    # A frozen start gives P(A)=1. Dropping the mood from the target gives
    # information zero and equal choice probabilities for peek and wait.
    assert 1 - enclose(p_a, 32)[1] > 2*tolerance
    assert enclose(info, 32)[0] > 2*tolerance
    assert enclose(p_peek, 32)[0] - HALF > 2*tolerance
    posterior = certified_belief_query(r, "state", state="A", tolerance=tolerance)
    assert_contains(posterior, p_a)
    selection(r, r.think(), history, info, probability=p_peek, tolerance=tolerance)
