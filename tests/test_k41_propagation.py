"""K41 decisions 1–5, 8–10. Query the native adopted belief after source records."""

from fractions import Fraction as Q
from math import factorial
from pathlib import Path

import pytest

from sui import fb
from test_fb_clock_belief import clock_prior, conditional_on
from test_fb_cycle import E, T
from test_fb_time_belief import assert_contains, exp_minus, negative_update, script
from k41_world import (
    BOTH, FAIR, HALF, ONE, ONE_WAY, X, ZERO, adopt, at_entry, complement, divide, entropy,
    expneg, minus, plus, rat, refined, scaled, selection, times, worlds,
)


def test_copy_and_static_control(worlds):
    assert Path(fb.__file__).resolve() == Path(__file__).resolve().parents[1] / "src/sui/fb.py"
    r = worlds(process=None, rates=(1, 2), prior=FAIR).start()
    adopt(r)
    refined(lambda tol: r.query("mass", tolerance=tol), scaled(HALF, plus(X, expneg(2))))


@pytest.mark.parametrize("uniform", [False, True], ids=["point", "interval"])
def test_empty_observes_once_and_returns_terminal_mood(worlds, uniform):
    r = worlds(script((0 if uniform else 1, 1, E)), family=None).start()
    expression = adopt(r)
    assert expression.terminal_ns == r.origin + 1 and len(expression.observations) == 1
    z = minus(rat(2), scaled(3, X)) if uniform else scaled(2, X)
    b = divide(minus(rat(2), scaled(4, X)), z) if uniform else rat(HALF)
    refined(lambda tol: r.query("mass", tolerance=tol), z)
    refined(lambda tol: r.query("state", state="B", tolerance=tol), b)
    # N(1)=0 implies empty at every earlier U. A later arrival is possible only for a span.
    count0 = divide(scaled(2, X), z) if uniform else ONE
    refined(lambda tol: r.query("count", count=0, tolerance=tol), count0)


def test_switch_off_keeps_motion_and_one_beta_bit(worlds):
    r = worlds(mood=True, rates=(1, 1)).start()
    adopt(r)
    for part, z in [(True, scaled(2, X)), (False, X)]:
        event = {"on" if part else "off": ("mood",)}
        refined(lambda tol: conditional_on(r, "mass", tolerance=tol, **event), z)
        b = rat(HALF) if part else complement(X)
        refined(lambda tol: conditional_on(r, "state", state="B", tolerance=tol, **event), b)
    assert_contains(r.sq("switch", on=("mood",)), rat(Q(2, 3)))
    assert_contains(r.sq("p_mean"), rat(Q(5, 9)))
    mixture = r.mixture()
    assert {(c.a, c.b) for c in mixture.components} == {(1, 2), (2, 1)}


@pytest.mark.parametrize("bad,kind,target", [
    ("role", "unsupported", "state_role"), ("mood-base", "unsupported", "rates"),
    ("sign", "invalid", "matrix"), ("diagonal", "invalid", "matrix"),
    ("size", "invalid", "matrix"), ("format", "unsupported", "matrix"),
])
def test_generator_and_mood_component_have_separate_domains(worlds, bad, kind, target):
    matrices = {"sign": ((1, -1), (0, 0)), "diagonal": ((0, 1), (0, 0)),
                "size": ((0,),), "format": ((-0.5, 0.5), (0, 0))}
    with pytest.raises(fb.TimeBeliefError) as caught:
        r = worlds(process=matrices.get(bad, ONE_WAY), state_role=None if bad == "role" else "mood",
                   mood=bad == "mood-base").start()
        r.resolved(r.boot())
    error = caught.value
    assert error.kind == kind
    assert target in (*error.targets, error.field) or (
        target == "matrix" and "state_process" in (*error.targets, error.field)
    )


def spectral_bounds(n):
    # cosh(sqrt(2)) + sqrt(2) sinh(sqrt(2)), two positive rational series.
    sums = []
    for odd in (0, 1):
        terms = [Q(2**(k+odd), factorial(2*k+odd)) for k in range(n+1)]
        ratio = Q(2, (2*n+odd+1)*(2*n+odd+2))
        sums.append((sum(terms), sum(terms) + terms[-1]*ratio/(1-ratio)))
    lo, hi = exp_minus(2, n)
    return lo*sum(x for x, _ in sums), hi*sum(y for _, y in sums)


def four_state_bounds(n):
    # Uniformization with nu=3. Order A0,B0,A+,B+; transitions continue in the '+' cells.
    a, b, c, d = Q(1), Q(0), Q(0), Q(0)
    weight, empty = Q(1), Q(0)
    for k in range(n+1):
        assert a+b+c+d == 1
        empty += weight*(a+b)
        a, b, c, d = (2*a+b)/3, a/3, (2*c+d)/3, (2*b+c+2*d)/3
        weight *= Q(3, k+1)
    lo, hi = exp_minus(3, n)
    return lo*empty, hi*(empty+weight/(1-Q(3, n+2)))


def test_irrational_reference_two_independent_enclosures():
    s, u = spectral_bounds(24), four_state_bounds(36)
    assert max(s[0], u[0]) <= min(s[1], u[1])
    for lo, hi in (s, u):
        assert Q(66514331, 10**8) < lo <= hi < Q(66514333, 10**8)
        assert hi-lo < Q(1, 2**64)


def test_reversible_generator_certifies_irrational_spectrum(worlds):
    r = worlds(process=BOTH, rates=(0, 2)).start()
    adopt(r)
    previous = None
    for tol in (Q(1, 128), Q(1, 2**28), Q(1, 2**68)):
        if previous is not None:
            tol = min(tol, previous/4)
        result = r.query("mass", tolerance=tol)
        assert isinstance(result.lower, Q) and isinstance(result.upper, Q)
        width = result.upper-result.lower
        assert width > 0 and (previous is None or width < previous)
        for oracle in (spectral_bounds, four_state_bounds):
            for n in (24, 48, 96, 192):
                lo, hi = oracle(n)
                if hi-lo < tol/64 and result.lower <= lo <= hi <= result.upper:
                    break
            else:
                pytest.fail("certified query did not enclose the independent series")
        previous = width


def test_unfinished_tight_query_keeps_the_positive_belief_for_refinement(worlds):
    r = worlds().start()
    expression = adopt(r)
    tolerance = Q(1, 2**80)
    try:
        value = r.query("mass", expression=expression, tolerance=tolerance, tight=True)
    except fb.TimeBeliefError as error:
        assert error.kind == "incomplete" and error.reason
    else:
        assert_contains(value, scaled(2, X))
    assert r.expression().root == expression.root
    assert_contains(r.query("mass", tolerance=tolerance), scaled(2, X))
    assert not any("model_falsified" in row.reasons for row in r.host.window.status().updates)


@pytest.mark.parametrize("forward,tick,initial,possible", [
    (0, 1, 0, False), (Q(1, 2**24), 1, 0, True), (1, 0, 0, False),
    (1, 1, 0, True), (0, 0, 1, True),
])
def test_taken_support_needs_positive_time_and_a_reachable_arrival(worlds, forward, tick, initial, possible):
    # B -> A remains positive even when B is unreachable.
    r = worlds(script((tick, tick, T)), process=((-forward, forward), (1, -1)),
               initial_count=initial).start()
    r.observe(0)
    if not possible:
        negative_update(r, falsified=True)
        assert not r.actor.calls
        return
    r.update()
    assert r.query("mass", tolerance=Q(1, 2**48)).lower > 0
    assert_contains(r.query("count", count=1, at_least=True), ONE)


def test_saturated_count_keeps_moving_and_a_gap_is_unobserved(worlds):
    r = worlds(script((0, 0, T), (2, 2, T)), initial_count=1, rates=(1, 1)).direct()
    adopt(r)
    adopt(r, 1)
    assert r.passive.calls == [0, 1]
    expected = complement(expneg(2))
    refined(lambda tol: r.query("mass", tolerance=tol), expected)
    refined(lambda tol: r.query("state", state="B", tolerance=tol), expected)
    assert_contains(r.query("count", count=2, at_least=True), ONE)


def rotation_integral(phase):
    # Z=e^-1*(1+J), J=int_0^1 exp(H(x)) dx, H(x)=int_0^x(c(u)-1)du.
    # Fixed rotation gives a triangle H. For uniform phase and 0<=x<=1/2,
    # E exp(H)=(1/2-x)(exp(x/2)+exp(-x/2))+2(exp(x/2)-exp(-x/2)).
    # Reflection supplies the other half of the integral.
    up = divide(ONE, expneg(Q(1, 4)))
    down = expneg(Q(1, 4))
    if phase is None:
        return scaled(16, minus(plus(up, down), rat(2)))
    if phase == 0:
        return scaled(4, minus(up, ONE))
    return scaled(4, complement(down))


@pytest.mark.parametrize("phase,digits", [
    (Q(0), 785827887450), (HALF, 693378018416), (None, 737678917305),
])
def test_clock_reference_reproduces_printed_rulers(phase, digits):
    from test_fb_time_belief import enclose

    z = times(X, plus(ONE, rotation_integral(phase)))
    lo, hi = enclose(z, 32)
    # The printed values identify the ruler only. The native assertions use
    # the full analytic value, including for rotation integrated over the turn.
    assert Q(digits-1, 10**12) < lo <= hi < Q(digits+1, 10**12)


@pytest.mark.parametrize("phase", [Q(0), HALF, pytest.param(None, marks=pytest.mark.fc)],
                         ids=["high-first", "low-first", "uniform"])
def test_clock_changes_arrivals_in_order_with_one_phase_for_history(worlds, phase):
    r = worlds(script((1, 1, E), (2, 2, E)), unit=HALF, clock=clock_prior(phase=phase),
               thinking=True, measurement=at_entry()).direct()
    r.think()
    adopt(r)
    r.think()
    last = adopt(r, 1)
    # Both empty, cursor zero: the first is implied by N(1)=0 even after integrating theta.
    j = rotation_integral(phase)
    mass_on = times(X, plus(ONE, j))
    refined(lambda tol: conditional_on(r, "mass", on=("clock",), tolerance=tol),
            mass_on, coarse=Q(1, 64), fine=Q(1, 512))
    mass = scaled(HALF, plus(scaled(2, X), mass_on))
    refined(lambda tol: r.query("mass", tolerance=tol), mass, coarse=Q(1, 64), fine=Q(1, 512))
    # No transition from A has unnormalized mass e^-1 for every theta.
    refined(lambda tol: r.query("state", state="A", tolerance=tol), divide(X, mass),
            coarse=Q(1, 64), fine=Q(1, 512))
    selection(r, r.think(), last, entropy(divide(X, mass)), tolerance=Q(1, 512))


@pytest.mark.parametrize("moving", [False, True], ids=["K39", "same-R"])
def test_clock_off_uses_same_moving_law_with_updated_beta_prior(worlds, moving):
    r = worlds(clock=clock_prior(), mood=True, rates=(1, 1), process=ONE_WAY if moving else ZERO).start()
    control = worlds(mood=True, rates=(1, 1), b=Q(2), process=ONE_WAY if moving else None).start()
    for scene in (r, control):
        adopt(scene)
    # Prior P(mood-on|clock-off)=1/3. Using a=b=1 gives 3/(2e) instead of 4/(3e).
    z = scaled(Q(4, 3), X) if moving else scaled(Q(1, 3), plus(ONE, scaled(2, X)))
    p_a = plus(rat(Q(1, 4)), scaled(HALF, X)) if moving else ONE
    mood_on = rat(HALF) if moving else divide(ONE, plus(ONE, scaled(2, X)))
    for kind, kwargs, expected in [("mass", {}, z), ("state", {"state":"A"}, p_a)]:
        refined(lambda tol: conditional_on(r, kind, off=("clock",), tolerance=tol, **kwargs), expected)
        refined(lambda tol: control.query(kind, tolerance=tol, **kwargs), expected)
    assert_contains(control.sq("switch", on=("mood",)), mood_on)
    den = r.sq("switch", off=("clock",))
    num = r.sq("switch", on=("mood",), off=("clock",))
    assert den.lower > 0
    from test_fb_clock_belief import Bounds
    assert_contains(Bounds(num.lower/den.upper, num.upper/den.lower), mood_on)


@pytest.mark.parametrize("random_coordinate", [pytest.param("width", marks=pytest.mark.fc), "fraction"])
def test_clock_continuous_simplex_keeps_boundary_mass_with_moving_state(worlds, random_coordinate):
    # w~Beta(1,1), f=3/4 or w=1/2, f~Beta(1,1). At phase zero H is a
    # triangle with height h=f-w. Its integral of exp(H) is int_0^1 exp(th)dt.
    if random_coordinate == "width":
        clock = clock_prior(widths={"kind": "symmetric_dirichlet", "concentration": Q(1)})
        left, right = Q(-1, 4), Q(3, 4)
    else:
        clock = clock_prior(fractions={"kind": "conditional_dirichlet", "concentration": Q(2)})
        left, right = -HALF, HALF
    r = worlds(clock=clock).start()
    adopt(r)
    width = None
    for tolerance in (Q(1, 16), Q(1, 64)):
        if width:
            tolerance = min(tolerance, width/16)
        v = r.query("mass", tolerance=tolerance)
        # Uniform h over a unit interval: E[h^k] is a difference of powers.
        # |h|<1 bounds the absolute remainder by a factorial tail.
        for n in (12, 24, 48, 96):
            j = sum((right**(k+1)-left**(k+1))/((k+1)*factorial(k+1)) for k in range(n+1))
            tail = Q(1, factorial(n+2))/(1-Q(1, n+3))
            lo, hi = exp_minus(1, n)
            low, high = lo*(3+j-tail)/2, hi*(3+j+tail)/2
            if high-low < tolerance/64 and v.lower <= low <= high <= v.upper:
                break
        else:
            pytest.fail("clock belief did not contain the whole-domain reference")
        if width is not None:
            assert v.upper - v.lower < width
        width = v.upper - v.lower


@pytest.mark.fc
def test_one_continuous_clock_draw_serves_distinct_cursor_events(worlds):
    r = worlds(script((1, 1, T), (2, 2, E)), clock=clock_prior(phase=None),
               rates=(1, 1), unit=HALF).direct()
    adopt(r)
    adopt(r, 1)
    # Exactly one arrival before half a turn and none afterwards. For rotation
    # theta its probability is H_theta(1/2)*exp(-H_theta(1)); H_theta(1)=1.
    # Redrawing the rotation between observations breaks that identity.
    z = scaled(HALF, X)
    refined(lambda tol: conditional_on(r, "mass", on=("clock",), tolerance=tol), z)
    refined(lambda tol: r.query("mass", tolerance=tol), z)
    assert_contains(r.query("count", count=1), ONE)
    assert_contains(r.query("state", state="B"), complement(X))
    assert r.passive.calls == [0, 1]
