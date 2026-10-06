"""S4b-2 v0.8: T05/T06/T10/T16/T21/T22, R02/R06 learning rulers.

Fraction integration of the specified likelihood and an independent eight-state
uniformization bound cover M01/M02/M03/M10/M27/M32. Conditional branch contents,
wait marginalization and scope failures cover T05/T06/T13/T21. R02/R06 and the
stationary two-state example are mathematical rulers, not wider certification.
M13/M22/M35 boundaries distinguish auxiliary labels, unproved evidence and
positive forbidden mass; production information/selection belongs to phase 3.
"""
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction as F
from functools import lru_cache
from math import comb, factorial, prod

import pytest

from sui import rate, rate_entry, rate_model
from sui.action_types import FixedLabel
from sui.contracts import ContractRef
from sui.records import Payload
from s4b2_worlds import (
    JOINT_MASS as EXACT_ROOT_MASS, POSTERIOR as EXACT_ROOT_POSTERIOR,
    ROOT_OVERFLOW, STANDARD_BUDGET, canonical,
    c1_declaration, c1_world, four_rate_declaration, independent_arrival_declaration,
    millisecond_declaration, reduction_declaration, report_content, tick_declaration,
)
from test_s4b2_rate import disjoint, exp_bounds, plus, scale, times


POSTERIOR = EXACT_ROOT_POSTERIOR + ((F(13, 64), F(93, 52), F(1, 9)),)
JOINT_MASS = EXACT_ROOT_MASS + ((
    (F(7, 2700), F(793, 60750)),
    (F(23, 10125), F(100267, 3645000)),
    (F(1453, 1215000), F(1260133, 36450000)),
    (F(899, 1215000), F(17669773, 145800000)),
),)
ROOTS = tuple(range(4))


def label(time):
    return FixedLabel(time_s=F(time), causal_stage=0, causal_position=0, side="post")


def root_moment_mass(n, power=0):
    """Integrate r**power against each state likelihood and Gamma(2,2)."""
    if n == 3:
        total = gamma_integral(power, 2)
        zero = gamma_integral(power, 3)  # no natural transition by time 1
        return tuple(value-sum(root_moment_mass(j, power)[s] for j in range(3))
                     for s, value in enumerate((zero, total-zero)))
    a = F(2**(n+1)-1, n+1)
    zero = F(4*factorial(n+power+1), factorial(n)*4**(n+power+2))
    one = a*F(4*factorial(n+power+2), factorial(n)*4**(n+power+3))
    return zero, one


def future_moment_mass(n, power=0):
    """§6-4 with r**power inside the SAME two-window integral."""
    if n == 3:
        whole = unobserved_first_window_cells(power)
        return tuple(tuple(whole[k][s]-sum(future_moment_mass(j, power)[k][s] for j in range(3))
                           for s in range(2)) for k in range(4))
    a = lambda j: F(2**(j+1)-1, j+1)
    cells = tuple((
        F(4*factorial(n+k+power+1), factorial(n)*factorial(k)*6**(n+k+power+2)),
        F(4*factorial(n+k+power+2), factorial(n)*factorial(k)*6**(n+k+power+3))
        * (2**k*a(n)+a(k)),
    ) for k in range(3))
    total0 = F(4*factorial(n+power+1), factorial(n)*5**(n+power+2))
    totals = total0, sum(root_moment_mass(n, power))-total0
    return cells + (tuple(totals[s]-sum(cell[s] for cell in cells) for s in range(2)),)


def gamma_integral(power, decay):
    """Integral of 4*r**(power+1)*exp(-decay*r), from zero to infinity."""
    return F(4*factorial(power+1), decay**(power+2))


def unobserved_first_window_cells(power=0):
    """Sum out the first count, then integrate the second count and S2.

    S2=0 has likelihood exp(-3r)*r**k/k!. S2=1 combines a transition
    before time 1 with a transition during the second window: respectively
    (exp(-2r)-exp(-3r))*(2r)**k/k! and exp(-3r)*r**(k+1)*a_k/k!.
    """
    cells = tuple((
        gamma_integral(k+power, 5)/factorial(k),
        (2**k*(gamma_integral(k+power, 4)-gamma_integral(k+power, 5))
         + F(2**(k+1)-1, k+1)*gamma_integral(k+power+1, 5))/factorial(k),
    ) for k in range(3))
    zero = gamma_integral(power, 4)  # no natural transition by time 2
    totals = zero, gamma_integral(power, 2)-zero
    return cells + (tuple(totals[s]-sum(cell[s] for cell in cells) for s in range(2)),)


def dirichlet_moment(alpha, powers):
    """Product of rising factorials / rising factorial of total concentration."""
    assert len(alpha) == len(powers)
    numerator = prod(prod(F(a+j) for j in range(power)) for a, power in zip(alpha, powers))
    denominator = prod(F(sum(alpha)+j) for j in range(sum(powers)))
    return F(numerator, denominator)


def count_generator():
    """G/r on (count,state), with the count saturated at three; COLUMN form."""
    g = [[0]*8 for _ in range(8)]
    for count in range(4):
        for state in range(2):
            source = 2*count+state
            if state == 0:
                g[source+1][source] += 1
                g[source][source] -= 1
            if count < 3:
                g[source+2][source] += state+1
                g[source][source] -= state+1
    return tuple(tuple(row) for row in g)


@lru_cache(maxsize=1)
def uniformized_cells():
    """Two windows, same r: retain total Poisson order ell <= 140.

    With Omega=2r, K=2P=2I+G/r has integer entries. Inserting the
    first-window count projection/reset between K**i and K**j gives
    4*(ell+1)/6**(ell+2) * sum_i binom(ell,i) K**j R_n K**i.
    Gamma integration is performed AFTER multiplying the two windows.
    Each conditional binomial average is substochastic. Its omitted mass
    is bounded by sum_(ell>=141) (ell+1)/9*(2/3)**ell = 48*(2/3)**141.
    """
    g = count_generator()
    k = tuple(tuple(g[i][j]+2*(i == j) for j in range(8)) for i in range(8))
    powers = []
    for initial in (0, 1):
        columns = [tuple(int(i == initial) for i in range(8))]
        for _ in range(140):
            columns.append(tuple(sum(k[i][j]*columns[-1][j] for j in range(8)) for i in range(8)))
        powers.append(columns)
    sums = [[F(0) for _ in range(8)] for _ in range(4)]
    roots = [F(0)]*8
    for ell in range(141):
        for cell in range(8):
            roots[cell] += F(4*(ell+1), 4**(ell+2))*powers[0][ell][cell]
        coefficients = [comb(ell, i) for i in range(ell+1)]
        for n in range(4):
            for cell in range(8):
                coefficient = sum(coefficients[i]*sum(
                    powers[0][i][2*n+s]*powers[s][ell-i][cell] for s in range(2)
                ) for i in range(ell+1))
                sums[n][cell] += F(4*(ell+1)*coefficient, 6**(ell+2))
    return tuple(tuple(row) for row in sums), tuple(roots)


def assert_interval(actual, expected, width=F(1, 10**9)):
    assert isinstance(actual.lower, F) and isinstance(actual.upper, F)
    assert actual.lower <= expected <= actual.upper
    assert 0 <= actual.upper-actual.lower <= width


def assert_quantity(actual, expected, *, support="positive", width=F(1, 10**9)):
    assert (actual.status, actual.support, actual.reason) == ("finite", support, None)
    assert actual.bounds is not None and actual.certificate is not None
    assert_interval(actual.bounds, expected, width)


def build(n=0, *, declaration=None, budget=STANDARD_BUDGET, boot_ns=0):
    world = c1_world(n, declaration=declaration, boot_ns=boot_ns)
    model = rate_model.rate_model_from_json(world.declaration)
    reading = rate_entry.read_rate(model, world.records)
    belief = rate.rebuild_rate_belief(model, reading, context=world.context, budget=budget)
    return world, model, reading, belief


def marginal(belief, time):
    result = rate.state_marginal(belief, targets=(label(time),), budget=STANDARD_BUDGET)
    values = dict(result)
    assert len(result) == len(values) == 2
    assert set(values) == {("0",), ("1",)}
    return values


def moment(belief, power):
    powers = (("r", power),) if power else ()
    return rate.parameter_moment(belief, powers=powers, budget=STANDARD_BUDGET)


def branches_by_content(belief, *, boot_ns=0):
    branches = rate.rate_branches(belief, choice="read", budget=STANDARD_BUDGET)
    by_content = {canonical(branch.report): branch for branch in branches}
    expected = {canonical(report_content("read", k, y, boot_ns=boot_ns))
                for k in range(4) for y in ("y0", "y1")}
    assert len(branches) == len(by_content) == len({b.key for b in branches}) == 8
    assert all(isinstance(b.key, str) and b.key for b in branches)
    assert set(by_content) == expected
    return by_content


def test_T06_eight_state_generator_has_absorbing_counter_not_killed_overflow():
    g = count_generator()
    assert all(sum(g[i][j] for i in range(8)) == 0 for j in range(8))
    assert all(g[i][j] >= 0 for i in range(8) for j in range(8) if i != j)
    assert g[6][4] == 1 and g[7][5] == 2
    assert g[6][6] == -1 and g[7][6] == 1 and g[7][7] == 0
    assert all(g[i][7] == 0 for i in range(8))


@pytest.mark.parametrize("n", range(4))
def test_T05_T06_independent_8_state_uniformization_contains_all_32_masses(n):
    lower, roots = uniformized_cells()
    remainder = 48*F(2, 3)**141
    root_remainder = F(143, 2)*F(1, 2)**141
    assert remainder < F(712, 10**26)
    z = sum(root_moment_mass(n))
    zero = root_moment_mass(n)[0]
    assert (z, sum(root_moment_mass(n, 1))/z, zero/z) == POSTERIOR[n]
    assert future_moment_mass(n) == JOINT_MASS[n]
    assert sum(lower[n]) <= z <= sum(lower[n])+remainder
    for k in range(4):
        for state in range(2):
            actual = JOINT_MASS[n][k][state]
            assert lower[n][2*k+state] <= actual <= lower[n][2*k+state]+remainder
    for state in range(2):
        assert roots[2*n+state] <= root_moment_mass(n)[state] <= roots[2*n+state]+root_remainder
    assert sum(roots[6:]) <= ROOT_OVERFLOW <= sum(roots[6:])+root_remainder
    assert ROOT_OVERFLOW == 1-sum(row[0] for row in POSTERIOR[:3]) == F(13, 64)


@pytest.mark.parametrize("n", range(3))
def test_M01_M02_M03_M10_have_disjoint_wrong_answers(n):
    z, mean, p0 = POSTERIOR[n]
    correct = p0*F(4, 5)**(n+2)
    product_of_marginals = p0*(p0*F(4, 5)**(n+2)+(1-p0)*F(4, 5)**(n+3))
    independent_future_prior = p0*F(2, 3)**2
    mean_rate = scale(exp_bounds(-mean), p0)
    truncated = sum(JOINT_MASS[n][k][0] for k in range(3))/sum(
        sum(JOINT_MASS[n][k]) for k in range(3))
    assert correct == sum(row[0] for row in JOINT_MASS[n])/z
    assert correct != product_of_marginals != independent_future_prior
    assert disjoint((correct, correct), mean_rate)
    assert truncated != correct
    assert all(x > 0 for x in JOINT_MASS[n][3])


def test_M01_M32_mean_rate_and_unmoved_gamma_scale_are_distinct_experiments():
    assert disjoint((F(1, 2), F(1, 2)), exp_bounds(-1))  # Gamma(1,1)
    assert disjoint((F(4, 9), F(4, 9)), exp_bounds(-1))  # C1 Gamma(2,2)
    # Keeping Gamma's numerical rate at 2 while changing r to ms^-1 makes
    # the physical rate 1000 times larger: Gamma(2,1/500) per second.
    beta = F(1, 500)
    for n in range(3):
        a = F(2**(n+1)-1, n+1)
        wrong = beta**2/F(factorial(n))*(
            F(factorial(n+1))/(beta+2)**(n+2)
            + a*F(factorial(n+2))/(beta+2)**(n+3))
        assert abs(wrong-POSTERIOR[n][0]) > F(1, 10)


@pytest.mark.parametrize("n", ROOTS)
def test_T05_public_all_root_rationals_and_higher_moments(n):
    world, model, _, belief = build(n)
    z, mean, p0 = POSTERIOR[n]
    assert belief.model_ref == model.ref and belief.history.context == world.context
    assert (belief.evidence.kind, belief.evidence.support, belief.evidence.measure) == (
        "mass", "positive", ContractRef("finite-record-counting", "1"))
    assert_interval(belief.evidence.value, z)
    assert_quantity(moment(belief, 1), mean)
    for power in (0, 2, 3):
        assert_quantity(moment(belief, power), sum(root_moment_mass(n, power))/z)
    states = marginal(belief, 1)
    assert_quantity(states[("0",)], p0)
    assert_quantity(states[("1",)], 1-p0)
    future0 = sum(row[0] for row in future_moment_mass(n))/z
    assert_quantity(marginal(belief, 2)[("0",)], future0)


@pytest.mark.parametrize("powers", [(), (("r", 2),), (("missing", 1), ("r", 1)), (("missing", 1),)],
                         ids=["empty", "all-known", "partial-known", "none-known"])
def test_T05_parameter_query_validates_every_requested_id(powers):
    _, _, _, belief = build(1)
    if any(name != "r" for name, _ in powers):
        with pytest.raises(rate.RateInputError) as caught:
            rate.parameter_moment(belief, powers=powers, budget=STANDARD_BUDGET)
        assert caught.value.reason in {"schema", "shape"}
    else:
        result = rate.parameter_moment(belief, powers=powers, budget=STANDARD_BUDGET)
        expected = F(1) if not powers else sum(root_moment_mass(1, 2))/POSTERIOR[1][0]
        assert_quantity(result, expected)


def component_queries():
    return (
        ((), 0, (0, 0)),
        ((("p", "y0", 1),), 0, (1, 0)),
        ((("p", "y1", 1),), 0, (0, 1)),
        ((("p", "y0", 2),), 0, (2, 0)),
        ((("p", "y1", 2),), 0, (0, 2)),
        ((("p", "y0", 1), ("p", "y1", 1)), 0, (1, 1)),
        ((("p", "y0", 2), ("p", "y1", 1)), 0, (2, 1)),
        ((("r", 1), ("p", "y0", 1)), 1, (1, 0)),
        ((("r", 1), ("p", "y1", 1)), 1, (0, 1)),
        ((("r", 2), ("p", "y0", 1), ("p", "y1", 1)), 2, (1, 1)),
    )


def test_T05_simplex_component_ruler_discriminates_products_and_swapped_labels():
    assert dirichlet_moment((1, 1), (1, 0)) == F(1, 2)
    assert dirichlet_moment((1, 1), (2, 0)) == F(1, 3)
    assert dirichlet_moment((1, 1), (1, 1)) == F(1, 6) != F(1, 4)
    for alpha in ((2, 1), (1, 2)):
        p0, p1 = (dirichlet_moment(alpha, powers) for powers in ((1, 0), (0, 1)))
        assert {p0, p1} == {F(1, 3), F(2, 3)}
        assert dirichlet_moment(alpha, (1, 1)) == F(1, 6) != p0*p1
        assert dirichlet_moment(alpha, (2, 0)) != dirichlet_moment(alpha, (0, 2))
    # Exact reports (C,Y) retain a product likelihood g(C,r,S)*p_Y.
    # There is no r-p dependence in this C1 experiment, even after read.
    mean_after_c0 = sum(future_moment_mass(0, 1)[0])/sum(JOINT_MASS[0][0])
    assert mean_after_c0 == F(2, 5)
    assert mean_after_c0*dirichlet_moment((2, 1), (1, 0)) == F(4, 15)
    assert mean_after_c0*dirichlet_moment((1, 2), (1, 0)) == F(2, 15)


@pytest.mark.parametrize("n", ROOTS)
def test_T05_public_root_simplex_and_mixed_moments(n):
    _, _, _, belief = build(n)
    z = POSTERIOR[n][0]
    for powers, rate_power, simplex_powers in component_queries():
        # The prior on p is unchanged by a root count, including saturation.
        expected = sum(root_moment_mass(n, rate_power))/z*dirichlet_moment((1, 1), simplex_powers)
        result = rate.parameter_moment(belief, powers=powers, budget=STANDARD_BUDGET)
        assert_quantity(result, expected)
        if not powers:
            assert result.bounds == rate.RationalInterval(F(1), F(1))


@pytest.mark.parametrize("n", ROOTS)
@pytest.mark.parametrize("k", range(4))
def test_T05_public_read_child_updates_components_and_joint_moments(n, k):
    world, _, _, belief = build(n)
    before = world.ledger.entries()
    branches = branches_by_content(belief)
    for outcome, alpha in (("y0", (2, 1)), ("y1", (1, 2))):
        branch = branches[canonical(report_content("read", k, outcome))]
        denominator = sum(JOINT_MASS[n][k])
        for powers, rate_power, simplex_powers in component_queries():
            rate_mean = sum(future_moment_mass(n, rate_power)[k])/denominator
            expected = rate_mean*dirichlet_moment(alpha, simplex_powers)
            result = rate.parameter_moment(branch.child, powers=powers, budget=STANDARD_BUDGET)
            assert_quantity(result, expected)
            if simplex_powers == (1, 1):
                wrong_product = rate_mean*dirichlet_moment(alpha, (1, 0))*dirichlet_moment(alpha, (0, 1))
                assert wrong_product != expected
                assert not result.bounds.lower <= wrong_product <= result.bounds.upper
        # A count changes r's posterior; swapping only Y changes p, not r.
        assert_quantity(moment(branch.child, 1), sum(future_moment_mass(n, 1)[k])/denominator)
    assert world.ledger.entries() == before


@pytest.mark.parametrize("powers,reasons", [
    ((("p", 1),), {"shape"}),
    ((("r", 1), ("p", 1)), {"shape"}),
    ((("r", 0),), {"shape", "noncanonical"}),
    ((("p", "y0", 0),), {"shape", "noncanonical"}),
    ((("p", "y0", -1),), {"shape"}),
    ((("p", "y0", True),), {"shape"}),
    ((("p", "missing", 1),), {"shape"}),
    ((("r", "y0", 1),), {"shape"}),
    ((("p", "y0", 1), ("r", 1)), {"shape", "noncanonical"}),
    ((("p", "y1", 1), ("p", "y0", 1)), {"shape", "noncanonical"}),
    ((("p", "y0", 1), ("p", "y0", 2)), {"shape", "noncanonical"}),
], ids=["no-component", "mixed-no-component", "zero-scalar", "zero-component",
        "negative", "bool", "unknown-label", "scalar-with-label", "law-order",
        "label-order", "duplicate-component"])
def test_T05_component_queries_reject_malformed_and_noncanonical_powers(powers, reasons):
    _, _, _, belief = build()
    with pytest.raises(rate.RateInputError) as caught:
        rate.parameter_moment(belief, powers=powers, budget=STANDARD_BUDGET)
    assert caught.value.reason in reasons


def test_T05_component_order_uses_declarations_not_lexical_or_first_label():
    declaration = deepcopy(c1_declaration())
    declaration["variables"][:2] = list(reversed(declaration["variables"][:2]))
    declaration["targets"]["laws"] = ["p", "r"]
    declaration["variables"][0]["domain"]["labels"] = ["y1", "y0"]
    next(v for v in declaration["variables"] if v["id"] == "measurement")["domain"]["labels"] = ["y1", "y0"]
    declaration["processes"][2]["params"]["labels"] = ["y1", "y0"]
    for record in declaration["records"]:
        if record["probe"] is not None:
            values = record["alphabet"]["values"]
            record["alphabet"]["values"] = [cell for k in range(4) for cell in reversed(values[2*k:2*k+2])]
    _, _, _, belief = build(declaration=declaration)
    branch = branches_by_content(belief)[canonical(report_content("read", 0, "y0"))]
    powers = (("p", "y1", 1), ("p", "y0", 2), ("r", 1))
    result = rate.parameter_moment(branch.child, powers=powers, budget=STANDARD_BUDGET)
    # Dirichlet alpha in declaration order is (1,2), not (2,1).
    assert_quantity(result, F(2, 5)*dirichlet_moment((1, 2), (1, 2)))


@pytest.mark.parametrize("n", ROOTS)
@pytest.mark.parametrize("boot_ns", (0, 7_000_000_000))
def test_T06_public_branch_content_joint_cells_and_conditioned_moments(n, boot_ns):
    world, model, _, belief = build(n, boot_ns=boot_ns)
    before = world.ledger.entries()
    z = POSTERIOR[n][0]
    actual = branches_by_content(belief, boot_ns=boot_ns)
    weighted = future_moment_mass(n, 1)
    total_lower = total_upper = F(0)
    for k in range(4):
        cell_mass = sum(JOINT_MASS[n][k])
        for y in ("y0", "y1"):
            branch = actual[canonical(report_content("read", k, y, boot_ns=boot_ns))]
            assert branch.child.model_ref == model.ref
            assert_quantity(branch.probability, cell_mass/(2*z))
            total_lower += branch.probability.bounds.lower
            total_upper += branch.probability.bounds.upper
            states = marginal(branch.child, 2)
            for state in range(2):
                assert_quantity(states[(str(state),)], JOINT_MASS[n][k][state]/cell_mass)
                # Check the joint mass, not only the separately normalized counts.
                joint = times((branch.probability.bounds.lower, branch.probability.bounds.upper),
                              (states[(str(state),)].bounds.lower, states[(str(state),)].bounds.upper))
                assert joint[0] <= JOINT_MASS[n][k][state]/(2*z) <= joint[1]
            assert_quantity(moment(branch.child, 1), sum(weighted[k])/cell_mass)
    assert total_lower <= 1 <= total_upper
    assert world.ledger.entries() == before


def test_T06_root_saturation_is_certified():
    _, _, _, belief = build(3)
    assert_interval(belief.evidence.value, ROOT_OVERFLOW)
    zero = F(4, 9)-sum(root_moment_mass(n)[0] for n in range(3))
    assert zero/ROOT_OVERFLOW == F(1, 9)
    assert_quantity(marginal(belief, 1)[("0",)], F(1, 9))
    expected_mean = (1-sum(sum(root_moment_mass(n, 1)) for n in range(3)))/ROOT_OVERFLOW
    assert_quantity(moment(belief, 1), expected_mean)
    assert_quantity(moment(belief, 2), F(399, 104))
    assert_quantity(marginal(belief, 1)[("1",)], F(8, 9))
    assert_quantity(marginal(belief, 2)[("0",)], F(272, 8125))
    result = rate.natural_change(belief, start=label(1), end=label(2), budget=STANDARD_BUDGET)
    assert set(result) == {"jump_probability", "expected_jump_count", "endpoint_change_probability"}
    for value in result.values():
        assert_quantity(value, F(5677, 73125))


@pytest.mark.parametrize("n", ROOTS)
def test_T21_wait_has_one_constant_report_preserves_rate_and_moves_state(n):
    world, _, _, belief = build(n)
    before = world.ledger.entries()
    branches = rate.rate_branches(belief, choice="wait", budget=STANDARD_BUDGET)
    assert len(branches) == 1
    branch = branches[0]
    assert canonical(branch.report) == canonical(report_content("wait"))
    assert branch.report["arrival_count"] is None and branch.report["outcome"] is None
    assert_quantity(branch.probability, F(1))
    z, mean, p0 = POSTERIOR[n]
    expected0 = sum(row[0] for row in JOINT_MASS[n])/z
    assert expected0 < p0
    assert_quantity(marginal(branch.child, 2)[("0",)], expected0)
    assert_quantity(moment(branch.child, 1), mean)
    assert_quantity(moment(branch.child, 2), sum(root_moment_mass(n, 2))/z)
    false_count_zero = sum(future_moment_mass(n, 1)[0])/sum(JOINT_MASS[n][0])
    assert false_count_zero != mean
    assert world.ledger.entries() == before


@pytest.mark.parametrize("n", ROOTS)
def test_T16_seconds_ms_push_forward_evidence_state_branches_and_rate_moments(n):
    world, _, _, belief = build(n)
    ms_world, _, _, ms = build(n, declaration=millisecond_declaration())
    assert [r.body.content.data for r in world.records] == [r.body.content.data for r in ms_world.records]
    assert_interval(ms.evidence.value, POSTERIOR[n][0])
    for power in (1, 2):
        expected = sum(root_moment_mass(n, power))/POSTERIOR[n][0]
        assert_quantity(moment(belief, power), expected)
        assert_quantity(moment(ms, power), expected/F(1000)**power)
    for time in (1, 2):
        expected = root_moment_mass(n)[0]/POSTERIOR[n][0] if time == 1 else (
            sum(row[0] for row in JOINT_MASS[n])/POSTERIOR[n][0])
        assert_quantity(marginal(ms, time)[("0",)], expected)
    actual = branches_by_content(ms)
    for k in range(4):
        for y in ("y0", "y1"):
            child = actual[canonical(report_content("read", k, y))]
            assert_quantity(child.probability, sum(JOINT_MASS[n][k])/(2*POSTERIOR[n][0]))
            assert_quantity(moment(child.child, 1),
                            sum(future_moment_mass(n, 1)[k])/sum(JOINT_MASS[n][k])/1000)


@pytest.mark.parametrize("n", ROOTS)
def test_T22_public_c1_natural_change_has_three_separate_quantities(n):
    _, _, _, belief = build(n)
    expected = POSTERIOR[n][2]-sum(row[0] for row in JOINT_MASS[n])/POSTERIOR[n][0]
    result = rate.natural_change(belief, start=label(1), end=label(2), budget=STANDARD_BUDGET)
    assert set(result) == {"jump_probability", "expected_jump_count", "endpoint_change_probability"}
    for value in result.values():
        assert_quantity(value, expected)


def test_T22_empty_change_window_is_structural_zero():
    _, _, _, belief = build()
    result = rate.natural_change(belief, start=label(1), end=label(1), budget=STANDARD_BUDGET)
    assert set(result) == {"jump_probability", "expected_jump_count", "endpoint_change_probability"}
    for value in result.values():
        assert_quantity(value, F(0), support="zero", width=F(0))


def test_T22_stationary_two_state_ruler_separates_belief_jump_count_and_endpoint():
    e1, e2 = exp_bounds(-1), exp_bounds(-2)
    jump = 1-e1[1], 1-e1[0]
    endpoint = (1-e2[1])/2, (1-e2[0])/2
    stay = (1+e2[0])/2, (1+e2[1])/2
    for state in range(2):
        predicted = plus(scale(stay, F(1, 2)), scale(endpoint, F(1, 2)))
        assert predicted[0] <= F(1, 2) <= predicted[1]
    assert F(6321205588, 10**10) < jump[0] < jump[1] < F(6321205589, 10**10)
    assert F(4323323583, 10**10) < endpoint[0] < endpoint[1] < F(4323323584, 10**10)
    assert disjoint(jump, endpoint) and disjoint(jump, (F(0), F(0)))
    expected_jump_count, belief_difference = F(1), F(0)
    assert jump[1] < expected_jump_count and endpoint[0] > belief_difference


def fixed_root(n, value, *, budget=STANDARD_BUDGET):
    declaration = c1_declaration()
    declaration["variables"][0]["domain"] = {"kind": "nonnegative-real"}
    declaration["variables"][0]["prior"] = {
        "name": "point", "version": "1", "params": {"value": [value.numerator, value.denominator]}}
    world = c1_world(n, declaration=declaration)
    model = rate_model.rate_model_from_json(world.declaration)
    reading = rate_entry.read_rate(model, world.records)
    history = rate_entry.rate_history(model, reading, context=world.context)
    return rate.fixed_likelihood(model, history,
        theta={"r": value, "p": (F(1, 2), F(1, 2))}, budget=budget)


@pytest.mark.parametrize("n,expected,support", [(0, F(1), "positive"), (1, F(0), "zero")])
def test_T10_structural_zero_rate_distinguishes_empty_and_impossible_count(n, expected, support):
    actual = fixed_root(n, F(0))
    assert actual.support == support and actual.kind == "mass"
    assert_interval(actual.value, expected, width=F(0))


def test_T10_M27_tiny_positive_rate_is_not_structural_zero():
    r = F(1, 10**60)
    coarse = fixed_root(1, r)
    assert coarse.support in {"positive", "unproved"} and coarse.value.upper > 0
    budget = rate.RateBudget(F(1, 10**80), 20000, 2000, 20000)
    actual = fixed_root(1, r, budget=budget)
    expected = scale(exp_bounds(-2*r, terms=4), r+F(3, 2)*r*r)
    assert actual.support == "positive" and actual.value.lower > 0
    assert actual.value.lower <= expected[1] and expected[0] <= actual.value.upper
    assert actual.value.upper-actual.value.lower <= budget.tolerance
    assert expected[0] > 0


def test_T10_M22_insufficient_series_budget_is_not_model_falsification():
    budget = rate.RateBudget(F(1, 10**30), 1, 1, 1)
    with pytest.raises(rate.RateIncomplete) as caught:
        fixed_root(1, F(1), budget=budget)
    assert caught.value.reason in {"budget", "accuracy", "evidence_lower_bound"}


@pytest.mark.parametrize("factory,reason", [
    (four_rate_declaration, "rate_prior_scope"),
    (independent_arrival_declaration, "rate_prior_scope"),
    (tick_declaration, "latent_clock"),
    (lambda: reduction_declaration("all-point"), "rate_prior_scope"),
])
def test_T13_outside_C1_stops_with_typed_reason(factory, reason):
    world = c1_world(declaration=factory())
    model = rate_model.rate_model_from_json(world.declaration)
    reading = rate_entry.read_rate(model, world.records)
    before = world.ledger.entries()
    with pytest.raises(rate.RateIncomplete) as caught:
        rate.rebuild_rate_belief(model, reading, context=world.context, budget=STANDARD_BUDGET)
    assert caught.value.reason == reason
    assert world.ledger.entries() == before


def test_T04_M33_missing_root_time_is_not_assumed_zero():
    world = c1_world()
    content = world.root.body.content.as_json()
    content["window_start_ns"] = None
    changed = replace(world.root, body=replace(world.root.body, content=Payload.json(content)))
    model = rate_model.rate_model_from_json(world.declaration)
    with pytest.raises((rate.RateInputError, rate.RateSpecificationMissing, rate.RateIncomplete)) as caught:
        reading = rate_entry.read_rate(model, (world.boot, world.source, changed))
        rate.rebuild_rate_belief(model, reading, context=world.context, budget=STANDARD_BUDGET)
    assert caught.value.reason in {"schema", "clock_law", "latent_clock", "history_scope"}


def test_R02_all_point_parameters_leave_state_information_in_counts():
    # r=1, p=1/2, h_0. Laws are certain but (S2,C) are dependent.
    joint_zero_zero = scale(exp_bounds(-2), F(1, 2))
    state_zero = scale(exp_bounds(-1), F(1, 2))
    count_zero = scale(exp_bounds(-2), F(3, 2))
    independent = times(state_zero, count_zero)
    assert joint_zero_zero[0] > independent[1]
    # Pinsker: I(S2;C) >= 2*TV**2, and TV >= this one-cell discrepancy.
    information_lower = 2*(joint_zero_zero[0]-independent[1])**2
    assert information_lower > 0
    declaration = reduction_declaration("all-point")
    assert [v["prior"]["name"] for v in declaration["variables"][:2]] == ["point", "point"]


def test_R06_concentrating_gamma_prior_and_positive_forbidden_counterexample():
    e = exp_bounds(-1)
    survival = [(F(k, k+1)**k) for k in (2, 8, 32, 128)]
    assert all(a > b > e[1] for a, b in zip(survival, survival[1:]))
    assert survival[-1]-e[0] < F(1, 500)
    # Gamma(k,k^2) concentrates at the structural zero rate. For every finite k
    # the forbidden event "at least one jump" still has positive probability.
    forbidden = [1-F(k*k, k*k+1)**k for k in (2, 8, 32, 128)]
    assert all(a > b > 0 for a, b in zip(forbidden, forbidden[1:]))
    assert all(0 < probability < F(1, k) for probability, k in zip(forbidden, (2, 8, 32, 128)))
    assert forbidden[-1] < F(1, 100)
    # Truncating the infinite forbidden cost at B gives probability*B. It is
    # unbounded even for the smallest finite-k probability, hence expectation
    # +infinity; a small-mass threshold would incorrectly make this zero.
    for probability in forbidden:
        assert [probability*(bound/probability) for bound in (1, 100, 10**10)] == [1, 100, 10**10]
    # The point-zero limit forbids no path; positive mass times +infinity at
    # finite k cannot be replaced by that limit. This is not a public cost test.
    assert fixed_root(1, F(0)).support == "zero"


def test_T21_M13_constant_wait_report_has_zero_information_even_with_auxiliary_labels():
    # Any partition of the posterior gives the same constant report. The two
    # computational labels below are not additional observations or targets.
    for weights in ((F(1),), (F(1, 3), F(2, 3)), (F(1, 4),)*4):
        assert sum(weights) == 1
        report_probability = sum(weights)
        likelihood_ratios = tuple(F(1)/report_probability for _ in weights)
        assert likelihood_ratios == (F(1),)*len(weights)
        # log(x) = 2*sum z**(2j+1)/(2j+1), z=(x-1)/(x+1).
        # All terms AND the remainder vanish at x=1; no label entropy is added.
        z = tuple((ratio-1)/(ratio+1) for ratio in likelihood_ratios)
        information = 2*sum(w*sum(value**(2*j+1)/F(2*j+1) for j in range(28))
                            for w, value in zip(weights, z))
        remainder = sum(w*2*value**57/(57*(1-value*value)) for w, value in zip(weights, z))
        assert (information, remainder) == (F(0), F(0))


def test_T21_public_wait_information_is_exactly_zero():
    from s4b2_worlds import evaluation_root
    world = c1_world()
    view, resolved = evaluation_root(world)
    evaluation = rate.evaluate_rate(view, world.candidates, resolved, budget=STANDARD_BUDGET)
    assert evaluation.candidates == ("read", "wait")
    assert_quantity(evaluation.information[1], F(0), support="zero", width=F(0))
