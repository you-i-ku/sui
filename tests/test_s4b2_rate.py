"""S4b-2 v0.6, phase 1: T01–T04 and independent density/M0 rulers.

Expected values use §3-1's COLUMN formula: D0=Q-diag(c*lambda), a marked
arrival diag(lambda*A), and the final survival interval. A signed-matrix Taylor
series with a rational induced-norm remainder is independent of sui's numerical
implementation. No private production source or numerical function is used.

Discrimination (§6-3): M04 normalizes killed columns; M05 omits final survival;
M06 exposes unobserved time; M07 discards observed silence; M24 bounds a density
tail by prior mass. Each has a disjoint explicit wrong-answer ruler. This is
fixture discrimination, NOT a claim that a production mutation was run/KILLED.

Coverage has empty/all/partial/no-match windows and asserts the exact declared
content and public likelihood. No unspecified raw-record route filter is invented;
the specification does not define that filter's four-way fixture at this API.

T01 malformed/shared declarations also live in test_s4b2_contract.py.
T02 named nonuniform arrivals/non-symmetric Q; T03 density >1 and operator error;
T04 known silence/unobserved interval, unknown clock, unknown coverage law.
R03 M0 factorization and Gamma posterior/tail are independent analytic rulers;
general continuous-prior public integration remains outside phase 1/C1.
"""
from copy import deepcopy
from dataclasses import dataclass, replace
from fractions import Fraction as F
from math import factorial
import platform

import pytest

from sui import rate, rate_entry, rate_model
from sui.clock import FakeClock
from sui.clock_contracts import ClockSource, SOURCE
from sui.contracts import ContractRef
from sui.ids import Ref, RefKind, SequentialIds
from sui.ledger import Ledger, SequentialSalts
from sui.s4_contracts import BOOT
from s4b2_worlds import (NS, STANDARD_BUDGET, canonical, c1_declaration,
                        contract, named, observation)

def plus(a, b):
    return (a[0]+b[0], a[1]+b[1])


def times(a, b):
    products = [x*y for x in a for y in b]
    return min(products), max(products)


def scale(a, value):
    return times(a, (F(value), F(value)))


def disjoint(a, b):
    return a[1] < b[0] or b[1] < a[0]


def exp_bounds(x, terms=100):
    """Taylor's absolute tail: first omitted term / (1-|x|/(N+2))."""
    x = F(x)
    assert abs(x) < terms+2
    term = total = F(1)
    for k in range(1, terms+1):
        term *= x/k
        total += term
    tail = abs(term*x/(terms+1))/(1-abs(x)/(terms+2))
    return max(F(0), total-tail), total+tail


def mm(a, b):
    return tuple(tuple(sum((a[i][k]*b[k][j] for k in range(len(a))), F())
                       for j in range(len(a))) for i in range(len(a)))


def matrix_exp(matrix, duration, terms=100):
    """General matrix Taylor, not uniformization, with column 1-norm tail."""
    n = len(matrix)
    a = tuple(tuple(F(x)*duration for x in row) for row in matrix)
    norm = max(sum(abs(a[i][j]) for i in range(n)) for j in range(n))
    assert norm < terms+2
    term = tuple(tuple(F(i == j) for j in range(n)) for i in range(n))
    total = term
    for k in range(1, terms+1):
        term = tuple(tuple(x/k for x in row) for row in mm(a, term))
        total = tuple(tuple(total[i][j]+term[i][j] for j in range(n)) for i in range(n))
    tail = norm**(terms+1)/factorial(terms+1)/(1-norm/(terms+2))
    # All matrices used here have nonnegative off-diagonals: exp is nonnegative.
    return tuple(tuple((max(F(0), value-tail), value+tail) for value in row) for row in total)


def mv(matrix, vector):
    return tuple(tuple(sum(times(matrix[i][j], vector[j])[edge] for j in range(len(vector)))
                       for edge in (0, 1)) for i in range(len(vector)))


Q = ((F(-1), F(2)), (F(1), F(-2)))
INITIAL = (F(3, 5), F(2, 5))
RATES = (F(1, 3), F(7, 5))
MARKS = {"red": (F(4, 5), F(1, 5)), "blue": (F(1, 5), F(4, 5))}
EVENTS = ((F(1, 4), "red"), (F(3, 4), "blue"))
END = F(5, 4)


def forward(*, q=Q, initial=INITIAL, rates=RATES, events=EVENTS, end=END,
            windows=None, marks=MARKS, mutant=None, terms=100):
    """Integrate precisely the declared observation windows; leave gaps unobserved."""
    windows = ((F(0), end),) if windows is None else windows
    cuts = sorted({F(0), end, *(t for t, _ in events),
                   *(x for window in windows for x in window if 0 < x < end)})
    vector = tuple((p, p) for p in initial)
    previous = F(0)
    event_map = dict(events)
    for point in cuts[1:]:
        covered = any(start <= previous and point <= stop for start, stop in windows)
        if mutant == "M06":
            covered = True
        loss = rates if covered and mutant != "M07" else (F(0), F(0))
        matrix = tuple(tuple(q[i][j]-(loss[j] if i == j else 0) for j in range(2)) for i in range(2))
        if not (mutant == "M05" and point == end and point not in event_map):
            transition = matrix_exp(matrix, point-previous, terms)
            if mutant == "M04":
                columns = [tuple(sum(transition[i][j][edge] for i in range(2))
                                 for edge in (0, 1)) for j in range(2)]
                transition = tuple(tuple(times(transition[i][j], (1/columns[j][1], 1/columns[j][0]))
                                         for j in range(2)) for i in range(2))
            vector = mv(transition, vector)
        if point in event_map:
            probabilities = (F(1), F(1)) if event_map[point] is None else marks[event_map[point]]
            vector = tuple(scale(v, rates[s]*probabilities[s]) for s, v in enumerate(vector))
        previous = point
    return plus(*vector)


def rational(value):
    value = F(value)
    return [value.numerator, value.denominator]


def exact_declaration(*, q=Q, initial=INITIAL, rates=RATES, end=END,
                      windows=None, marks=MARKS, gamma_arrival=False):
    """Small complete model.9: two-state CTMC, one exact route, wait control.

    All rates are declared as law variables, including point priors. Gamma
    common arrival is used only for the independent M0/tail ruler, not claimed
    as a supported public posterior calculation in phase 1.
    """
    d = c1_declaration()
    d["state_space"]["initial"] = [rational(p) for p in initial]
    laws = [("q01", q[1][0]), ("q10", q[0][1])]
    laws += [("lambda", rates[0])] if gamma_arrival else [("lambda0", rates[0]), ("lambda1", rates[1])]
    d["variables"] = [{"id": key, "domain": {"kind": "nonnegative-real" if value == 0 else "positive-real"},
        "unit": "second^-1", "role": "law", "scope": "model",
        "prior": named("gamma", {"shape": [2, 1], "rate": [2, 1]}) if key == "lambda" else named("point", {"value": rational(value)}),
        "generated_by": None} for key, value in laws] + [deepcopy(v) for v in d["variables"]
                                                    if v["id"] in ("state", "arrivals", "wait-completion")]
    def expr(key, value):
        return {"kind": "constant", "value": [0, 1]} if value == 0 else {
            "kind": "scaled_variable", "variable": key, "coefficient": [1, 1]}
    zero = {"kind": "constant", "value": [0, 1]}
    state, arrival, _, _, wait = d["processes"]
    state["parents"] = [key for key, value in laws[:2] if value]
    state["params"]["off_diagonal"]["fixed"] = [[zero, expr("q10", q[0][1])], [expr("q01", q[1][0]), zero]]
    lambda_ids = ["lambda", "lambda"] if gamma_arrival else ["lambda0", "lambda1"]
    arrival["parents"] = list(dict.fromkeys(key for key, value in zip(lambda_ids, rates) if value))+["state"]
    arrival["params"]["rates"]["fixed"] = [expr(key, value) for key, value in zip(lambda_ids, rates)]
    arrival["params"]["marks"] = None if marks is None else {
        "labels": list(marks), "probabilities": [[rational(p) for p in row] for row in marks.values()]}
    d["processes"] = [state, arrival, wait]
    d["controls"]["choices"] = [d["controls"]["choices"][1]]
    clock = named("exact", {})
    d["records"] = [{"id": "exact-report", "generator": "arrival-process",
        "kernel": named("exact-arrival", {"arrival_process": "arrival-process", "clock": clock,
                                           "include_mark": marks is not None}),
        "experiment": "exact-window", "clock": clock,
        "alphabet": {"kind": "arrival", "marks": None if marks is None else list(marks)}, "probe": None},
        d["records"][2]]
    windows = ((F(0), end),) if windows is None else windows
    d["coverage"]["intervals"] = [{"record": "exact-report", "start": rational(start), "end": rational(stop),
        "source": {"kind": "exogenous", "id": "exact-window"}} for start, stop in windows]
    d["targets"]["laws"] = [key for key, _ in laws]
    d["targets"]["state_positions"] = [d["targets"]["state_positions"][1]]
    d["measure"] = {"family": contract("marked-arrival-density"), "conditioning": []}
    d["certificate_capabilities"] = [contract("sui.s4b.rate_fixed_mmpp")]
    return d, dict(laws)


@dataclass
class ExactWorld:
    declaration: dict
    theta: dict
    ledger: Ledger
    records: tuple
    context: rate.RateContext


def exact_world(*, events=EVENTS, end=END, boot_ns=0, **kwargs):
    declaration, theta = exact_declaration(end=end, **kwargs)
    clock = FakeClock(run=Ref(RefKind.RUN, "exact"), mono_ns=boot_ns)
    ids, ledger = SequentialIds("exact"), Ledger(salts=SequentialSalts())
    records = []
    def add(record):
        ledger.accept(record)
        records.append(record)
        return record
    boot = add(observation(clock, ids, {}, contract_ref=BOOT, route="membrane", received_ns=boot_ns))
    source = add(observation(clock, ids, ClockSource(run=clock.run, provider="test.exact",
        implementation="FakeClock", python_version=platform.python_version(), resolution_s=F(1, NS),
        monotonic=True, adjustable=False, measurement=ContractRef("exact", "1")).as_json(),
        contract_ref=SOURCE, route="membrane", received_ns=boot_ns))
    for index, (time, mark) in enumerate(events):
        event_ns = boot_ns+time*NS
        assert event_ns.denominator == 1
        clock.advance(int(event_ns)-clock.mono_ns())
        add(observation(clock, ids, {"process": "arrival-process", "mark": mark, "event_ns": int(event_ns)},
            contract_ref=ContractRef("sui.s4b.rate_arrival", "1"), route="c1",
            source_id=f"arrival-{index}", source_ns=int(event_ns), received_ns=int(event_ns)))
    end_ns = boot_ns+end*NS
    assert end_ns.denominator == 1
    clock.advance(int(end_ns)-clock.mono_ns())
    ancestry = {entry.cid: frozenset(str(ledger.record(cid).id) for cid in ledger.ancestors((entry.cid,)) | {entry.cid}
                 if ledger.record(cid).body.contract != SOURCE) for entry in ledger.entries()}
    context = rate.RateContext(run=clock.run, now_ns=int(end_ns), observed_ns=int(end_ns),
        # Use immutable arrays in the Python context. The current public factory
        # rejects a list here, although the legacy View input uses a JSON list.
        check_events=({"unrecorded": {"kind": "tick", "reading": int(end_ns), "after": tuple(sorted(ledger.heads()))}},),
        fact_ancestors=ancestry, clock_source=source.id)
    return ExactWorld(declaration, theta, ledger, tuple(records), context)


def likelihood(world, *, budget=STANDARD_BUDGET):
    model = rate_model.rate_model_from_json(canonical(world.declaration))
    reading = rate_entry.read_rate(model, world.records)
    history = rate_entry.rate_history(model, reading, context=world.context)
    return rate.fixed_likelihood(model, history, theta=world.theta, budget=budget)


def assert_encloses(actual, expected, width=F(1, 10**9)):
    """Two independently bounded computations must intersect at required width."""
    assert actual.lower <= actual.upper
    assert actual.lower <= expected[1] and expected[0] <= actual.upper
    assert actual.upper-actual.lower <= width


def test_exact_fixture_all_content_and_reference_kinds():
    w = exact_world(boot_ns=7*NS)
    assert [r.body.contract for r in w.records] == [BOOT, SOURCE,
        ContractRef("sui.s4b.rate_arrival", "1"), ContractRef("sui.s4b.rate_arrival", "1")]
    assert [r.body.content.as_json() for r in w.records[2:]] == [
        {"process": "arrival-process", "mark": mark, "event_ns": int(7*NS+time*NS)} for time, mark in EVENTS]
    assert len({r.id for r in w.records}) == 4
    assert all(r.id.kind == RefKind.OBSERVATION for r in w.records)
    assert w.context.check_events[0]["unrecorded"]["after"] == tuple(sorted(w.ledger.heads()))
    assert w.context.clock_source == w.records[1].id
    assert w.declaration["measure"] == {"family": contract("marked-arrival-density"), "conditioning": []}
    assert w.declaration["records"][0]["kernel"]["params"]["clock"] == w.declaration["records"][0]["clock"]


def test_M04_M05_M06_M07_wrong_answers_are_disjoint():
    expected = forward()
    assert expected[0] > 0 and expected[1]-expected[0] < F(1, 10**30)
    for mutant in ("M04", "M05", "M07"):
        assert disjoint(expected, forward(mutant=mutant)), mutant
    gap = ((F(0), F(1, 2)), (F(1), END))
    events = ((F(1, 4), "red"),)
    assert disjoint(forward(events=events, windows=gap), forward(events=events, windows=gap, mutant="M06"))


def test_T02_transpose_and_discarded_marks_change_the_likelihood():
    expected = forward()
    assert disjoint(expected, forward(q=tuple(zip(*Q))))
    assert disjoint(expected, forward(events=tuple((t, None) for t, _ in EVENTS), marks=None))


@pytest.mark.parametrize("boot_ns", (0, 7*NS))
def test_T02_fixed_mmpp_column_likelihood_keeps_survival_mass(boot_ns):
    result = likelihood(exact_world(boot_ns=boot_ns))
    assert_encloses(result.value, forward())
    assert result.kind == "density" and result.support == "positive"
    assert result.measure == ContractRef("marked-arrival-density", "1")
    assert result.unit == "second^-2"
    assert result.certificate.budget == STANDARD_BUDGET


@pytest.mark.parametrize("windows", [(), ((F(0), END),),
    ((F(0), F(1, 2)), (F(1), END)), ((F(2), F(3)),)],
    ids=["empty", "all-observed", "partial-gap", "no-matching-window"])
def test_T04_zero_events_distinguish_coverage_from_unobserved_time(windows):
    world = exact_world(events=(), windows=windows)
    assert world.declaration["coverage"]["intervals"] == [
        {"record": "exact-report", "start": rational(start), "end": rational(stop),
         "source": {"kind": "exogenous", "id": "exact-window"}} for start, stop in windows]
    assert [r.body.contract for r in world.records] == [BOOT, SOURCE]
    result = likelihood(world)
    expected = forward(events=(), windows=windows)
    assert_encloses(result.value, expected)
    if not windows or windows[0][0] > END:
        assert expected[0] <= 1 <= expected[1]
        assert_encloses(result.value, (F(1), F(1)))
    else:
        assert expected[1] < 1


def test_T04_unknown_coverage_law_is_not_assumed_independent():
    w = exact_world(events=())
    w.declaration["coverage"]["policy"] = named("state-dependent-coverage", {})
    with pytest.raises(rate.RateSpecificationMissing) as caught:
        likelihood(w)
    assert caught.value.reason in {"missing_kernel", "coverage_law"}


def test_T04_unknown_time_is_not_filled_from_record_at():
    w = exact_world()
    assert likelihood(w).support == "positive"  # same complete history is valid
    record = w.records[2]
    content = {**record.body.content.as_json(), "event_ns": None}
    from sui.records import Payload
    changed = replace(record, body=replace(record.body, content=Payload.json(content), source_time_ns=None))
    w.records = (w.records[0], w.records[1], changed, w.records[3])
    with pytest.raises((rate.RateInputError, rate.RateSpecificationMissing, rate.RateIncomplete)) as caught:
        likelihood(w)
    assert caught.value.reason in {"schema", "clock_law", "latent_clock", "history_scope"}


DENSE_RATES = (F(12), F(12))
DENSE_EVENTS = ((F(1, 50), None), (F(3, 50), None))
DENSE_END = F(1, 10)


def test_T03_density_exceeds_one_and_operator_error_is_amplified():
    expected = scale(exp_bounds(-F(6, 5)), 144)
    assert expected[0] > 1
    assert not disjoint(expected, forward(rates=DENSE_RATES, events=DENSE_EVENTS,
                                         end=DENSE_END, marks=None))
    # An input-vector perturbation is amplified by both exact-arrival operators.
    error = F(1, 10**8)
    propagated = scale(exp_bounds(-F(6, 5)), 144*error)
    assert propagated[0] > error


@pytest.mark.parametrize("common,events,end", [
    (F(12), DENSE_EVENTS, DENSE_END),
    (F(1000), ((F(1, 1000), None), (F(1000001, 10**9), None)), F(1000001, 10**9)),
], ids=["dense", "one-nanosecond-gap"])
def test_T03_public_density_is_not_clipped_and_error_includes_arrival_operators(common, events, end):
    # Equal unmarked arrival rates commute with Q, whose columns sum to zero:
    # 1^T exp((Q-lambda I)t) p * lambda^2 = lambda^2 exp(-lambda*t).
    # This scalar rational Taylor enclosure is independent of the MMPP solver.
    w = exact_world(rates=(common, common), events=events, end=end, marks=None)
    result = likelihood(w)
    expected = scale(exp_bounds(-common*end), common**2)
    assert_encloses(result.value, expected)
    assert result.value.lower <= expected[0] <= expected[1] <= result.value.upper
    assert result.value.lower > 1 and result.kind == "density"
    assert result.unit == "second^-2"


def m0_likelihood_bounds(common, events, end):
    """Independent Poisson factor times the state-only mark experiment."""
    assert len(events) == 1
    time, mark = events[0]
    state = mv(matrix_exp(Q, time), tuple((p, p) for p in INITIAL))
    mark_likelihood = plus(*(scale(state[s], MARKS[mark][s]) for s in range(2)))
    return times(mark_likelihood, scale(exp_bounds(-common*end), common))


def test_R03_M0_factorization_retains_mark_information():
    common = F(7, 10)
    events = ((F(2, 5), "red"),)
    end = F(6, 5)
    independent_factor = scale(exp_bounds(-common*end), common)
    expected = m0_likelihood_bounds(common, events, end)
    assert not disjoint(expected, forward(rates=(common, common), events=events, end=end))
    assert expected[0] > F(177677615935, 10**12)
    assert expected[1] < F(177677615937, 10**12)
    # Drop the mark: arrival evidence then has no state dependence at all.
    assert not disjoint(independent_factor,
        forward(rates=(common, common), events=((F(2, 5), None),), end=end, marks=None))


def test_R03_public_common_rate_matches_independent_M0_factorization():
    common, end = F(7, 10), F(6, 5)
    events = ((F(2, 5), "red"),)
    result = likelihood(exact_world(rates=(common, common), events=events, end=end))
    expected = m0_likelihood_bounds(common, events, end)
    assert_encloses(result.value, expected)
    assert result.unit == "second^-1"


def gamma_tail_integer(shape, rate_parameter, cutoff):
    x = rate_parameter*cutoff
    polynomial = sum((x**j/F(factorial(j)) for j in range(shape)), F())
    return scale(exp_bounds(-x), polynomial)


def test_M24_exact_density_tail_cannot_be_bounded_by_prior_mass():
    """Gamma(2,2), two exact arrivals over 1/10 second, cutoff r=2.

    Integral r^2 exp(-r/10) * 4r exp(-2r) dr is 24/(21/10)^4.
    Its truncated tail is evidence times a Gamma(4,21/10) tail, not the
    Gamma(2,2) prior tail. This bound is needed when integration is implemented.
    """
    alpha, beta, n, exposure, cutoff = 2, F(2), 2, F(1, 10), F(2)
    evidence = beta**alpha*F(factorial(alpha+n-1), factorial(alpha-1))/(beta+exposure)**(alpha+n)
    assert evidence == F(80000, 64827) and evidence > 1
    posterior_shape, posterior_rate = alpha+n, beta+exposure
    assert (posterior_shape, posterior_rate) == (4, F(21, 10))
    density_tail = scale(gamma_tail_integer(posterior_shape, posterior_rate, cutoff), evidence)
    prior_tail = gamma_tail_integer(alpha, beta, cutoff)
    assert density_tail[0] > prior_tail[1]
    # Wrong certificate: exact compact contribution plus unweighted prior tail.
    wrong_upper = evidence-density_tail[0]+prior_tail[1]
    assert wrong_upper < evidence
    d, _ = exact_declaration(rates=(F(1), F(1)), end=exposure, marks=None, gamma_arrival=True)
    assert d["targets"]["laws"] == ["q01", "q10", "lambda"]
    assert d["processes"][1]["parents"] == ["lambda", "state"]
