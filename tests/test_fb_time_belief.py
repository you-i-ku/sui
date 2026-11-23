"""K38 v3 / K38-d, review R1-R7/R5 remains and count scenes, requests110-116.

Read in full: K38 row/body; Z63/Z64/Z65 including appendices; K25/K26/K28/
K36/K37 rows and K37 body. CE1's original eight-path declaration was read.
No production source body is used as an oracle.
K38-c was read in full. Its new public signatures were inspected at runtime.
K38-d was read in full: the connection/failure/result branches form one
normalized acquisition law. Disconnection c is not a called-failure p.

Chosen declarations (all rational numbers below are Fraction, never float):
  PoissonLaw(run, states, prior, rates, origin_ns, initial_count, time_unit)
  FiniteCountLaw(run, states, prior, origin_ns, initial_count, positions_ns,
                 paths, weights_by_state)
  UniformAcquisitionTime()
  FixedAcquisitionSchedule(run, intervals) -- predeclared exogenous endpoints
  IndependentAcquisitionFailure(unavailable_probability)
  IndependentSourceDisconnection(coefficient) -- c=P(source_called=False)
    masses: c; (1-c)*p; (1-c)*(1-p)*P(taken/empty | S,count history)
  TimedAcquisitionModel(route_slot, law, decision_time, conditioning, failure,
                       control_rule, control_independence, disconnection=None)
  SourceCountReading(independent_of_count, count_shift) -- no matrix values;
    independent_of_count=True and shift=0 declare the source noninterference.
    The outcome matrices come only from the selected model's kernel.
  TimedExecutionDeclaration(allocation, actors, no_effect, cells,
                            source_overlap, actor_overlap, source_readings)
  TimedBeliefUpdater(*, registry)

Chosen read/query surface:
  FThreadHost.belief_expression(*, boot, boundary=None) -> BeliefExpression
  FThreadHost.query_belief(*, belief, quantity, budget) -> BeliefValue
  FThreadHost.query_selection(*, selection, budget) -> SelectionValues
  FThreadHost.verify_belief_value(*, belief, value) -> bool
  FThreadHost.same_belief(*, left, right) -> bool
  BeliefExpression(point, root, model, pool, adoption, result, observations,
                   terminal_ns): observations are ordered original Frame/result Points
  BeliefQuantity(kind, state=None, candidate=None, count=None, at_least=False):
    state=P(S=state | h), candidate=P(M=candidate | h), mass=Z;
    count=P(N=k [,S=state,M=candidate] | h), at_least changes = to >=.
  BeliefValue(root, quantity, lower, upper, exact, proof): exact is the rational
    value when the canonical expression is rational; proof is opaque, durable.
  SelectionValues(belief_root, candidates, information, G, probabilities, proof):
    each numerical entry has Fraction lower/upper. Precision=budget.tolerance.
  TimeBeliefError(kind, reason, targets, field): kind distinguishes invalid,
    unsupported, unavailable, incomplete, model_falsified; targets names the
    declaration slots/candidate IDs at issue; free prose is unpinned.

Native start() is exercised with contiguous scripted acquisition intervals.
Other point-time rulers use a forwarding work port to set the independent
manual clock BEFORE the native SourceMeasurer calls the real acquire. No test
script calls acquire to fabricate a Frame. Source bytes are opaque.

Tight-budget queries may either prove the answer or report incomplete; the
paper supplies no algorithm-independent budget that MUST exhaust a denominator
proof. We do not force a particular expansion/refinement algorithm or treat a
successful proof as an error. This limit is explicit in the coverage map.
"""

from contextlib import contextmanager
from dataclasses import dataclass, fields, replace
from copy import deepcopy
from fractions import Fraction as Q
from functools import lru_cache
from itertools import product
from inspect import signature
import json
from math import factorial
from threading import Event, local
from types import SimpleNamespace

import pytest

from sui import f, fb, fb_contracts as c, f_update2 as u2
from sui.ids import Ref, RefKind
from sui.records import Prediction, Payload, Role
from sui.rate import RateBudget
from test_fb_cycle import (CycleRig, NativeEntryObserver, ObservedEntryPort, Gate,
    P, EMPTY, I, N, ZERO, T, E, U, WATCHDOG, world_document, contract, wire)
from test_fb_pool import PoolRig, OLD, CE1, acquisition_for, public_rounds
from test_fb_belief import BeliefSnapshotReader, belief1_clone


TIME_FIELDS = {
    "PoissonLaw": {"run", "states", "prior", "rates", "origin_ns", "initial_count", "time_unit"},
    "FiniteCountLaw": {"run", "states", "prior", "origin_ns", "initial_count", "positions_ns", "paths", "weights_by_state"},
    "UniformAcquisitionTime": set(),
    "FixedAcquisitionSchedule": {"run", "intervals"},
    "IndependentAcquisitionFailure": {"unavailable_probability"},
    "IndependentSourceDisconnection": {"coefficient"},
    "TimedAcquisitionModel": {"route_slot", "law", "decision_time", "conditioning", "failure", "control_rule", "control_independence", "disconnection"},
    "SourceCountReading": {"independent_of_count", "count_shift"},
    "TimedExecutionDeclaration": {"allocation", "actors", "no_effect", "cells", "source_overlap", "actor_overlap", "source_readings"},
    "BeliefExpression": {"point", "root", "model", "pool", "adoption", "result", "observations", "terminal_ns"},
    "BeliefQuantity": {"kind", "state", "candidate", "count", "at_least"},
    "BeliefValue": {"root", "quantity", "lower", "upper", "exact", "proof"},
    "SelectionValues": {"belief_root", "candidates", "information", "G", "probabilities", "proof"},
}


def time_api():
    missing = [n for n in (*TIME_FIELDS, "TimedBeliefUpdater", "TimeBeliefError") if not hasattr(fb, n)]
    missing += ["FThreadHost." + n for n in ("belief_expression", "query_belief", "query_selection",
                "verify_belief_value", "same_belief") if not hasattr(fb.FThreadHost, n)]
    assert not missing, "K38 public shape missing: " + ", ".join(missing)
    for name, expected in TIME_FIELDS.items():
        assert expected <= {f.name for f in fields(getattr(fb, name))}, "K38-c public shape missing: " + name


def budget(tolerance=Q(1, 2**60), *, tight=False):
    return RateBudget(tolerance=tolerance, max_cells=1 if tight else None,
                      max_terms=1 if tight else None, max_refinements=1 if tight else None)


# Independent rigorous arithmetic. A positive exponential Taylor sum bounds
# exp(y), 0<=y<=1; its omitted positive tail is bounded by a geometric series.
# Reciprocal and integer powering therefore enclose exp(-x), without floats.
def exp_minus(x, terms):
    x = Q(x)
    assert x >= 0
    if not x: return Q(1), Q(1)
    m = max(1, (x.numerator + x.denominator - 1) // x.denominator)
    y, term, total = x / m, Q(1), Q(1)
    for k in range(1, terms + 1):
        term *= y / k; total += term
    tail = term * y / (terms + 1) / (1 - y / (terms + 2))
    return (1 / (total + tail)) ** m, (1 / total) ** m


def log_rational(x, terms):
    assert x > 0
    k, y = 0, Q(x)
    while y < 1: y *= 2; k -= 1
    while y > 2: y /= 2; k += 1
    def near(z):
        v = (z - 1) / (z + 1)
        total = 2 * sum((v ** (2*j + 1) / (2*j + 1) for j in range(terms)), Q(0))
        tail = 2 * v ** (2*terms + 1) / ((2*terms + 1) * (1 - v*v))
        return total, total + tail
    low, high = near(y); l2, h2 = near(Q(2))
    return (low + k*l2, high + k*h2) if k >= 0 else (low + k*h2, high + k*l2)


def rat(x): return ("q", Q(x))
def plus(a, b): return ("+", a, b)
def minus(a, b): return ("-", a, b)
def times(a, b): return ("*", a, b)
def divide(a, b): return ("/", a, b)
def expneg(x): return ("exp", rat(-Q(x)))
def logarithm(a): return ("log", a)
def total(xs):
    result = rat(0)
    for x in xs: result = plus(result, x)
    return result


class RefineOracle(Exception): pass


def outward(low, high, bits):
    """Bound rational denominator growth; never round the symbolic root/time."""
    if low == high: return low, high
    scale = 1 << bits
    left = (low.numerator * scale) // low.denominator
    right = -((-high.numerator * scale) // high.denominator)
    return Q(left, scale), Q(right, scale)


@lru_cache(maxsize=16384)
def enclose(expr, terms):
    return outward(*raw_enclosure(expr, terms), max(64, 4*terms))


def raw_enclosure(expr, terms):
    op, *args = expr
    if op == "q": return args[0], args[0]
    a, b = enclose(args[0], terms)
    if op == "exp":
        def endpoint(x):
            if x <= 0: return exp_minus(-x, terms)
            lo, hi = exp_minus(x, terms); return 1 / hi, 1 / lo
        return endpoint(a)[0], endpoint(b)[1]
    if op == "log":
        if a <= 0: raise RefineOracle()
        return log_rational(a, terms)[0], log_rational(b, terms)[1]
    d, e = enclose(args[1], terms)
    if op == "+": return a + d, b + e
    if op == "-": return a - e, b - d
    if op == "*":
        values = (a*d, a*e, b*d, b*e); return min(values), max(values)
    if d <= 0 <= e: raise RefineOracle()
    values = (a/d, a/e, b/d, b/e); return min(values), max(values)


def assert_contains(value, expr):
    assert isinstance(value.lower, Q) and isinstance(value.upper, Q)
    assert value.lower <= value.upper
    for terms in (8, 16, 32, 64, 128, 256, 512):
        try: low, high = enclose(expr, terms)
        except RefineOracle: continue
        if value.lower <= low <= high <= value.upper: return
        assert not (high < value.lower or value.upper < low), "certified interval excludes the independent value"
    pytest.fail("independent rational oracle could not separate an interval endpoint")


def entropy_term(p):
    if p == rat(0): return rat(0)
    return times(p, logarithm(p))


def information_and_choice(p, rows=((Q(1), Q(1, 2)), (Q(0), Q(1, 2)))):
    probabilities = (p, minus(rat(1), p))
    py = [total(times(probabilities[s], rat(row[s])) for s in range(2)) for row in rows]
    info = minus(rat(0), total(entropy_term(y) for y in py))
    # H(Y|S) uses exact rational row entries, keeping log as a symbolic operation.
    cond = total(times(probabilities[s], total(entropy_term(rat(row[s])) for row in rows))
                 for s in range(2))
    info = plus(info, cond)
    weight = ("exp", info)
    return info, divide(weight, plus(rat(1), weight))


def posterior(likelihoods, prior=(Q(1, 2), Q(1, 2))):
    weights = [times(rat(p), likelihood) for p, likelihood in zip(prior, likelihoods, strict=True)]
    mass = total(weights)
    return divide(weights[0], mass), mass


def first_empty(rate, before, after):
    if not rate: return rat(1)
    if before == after: return expneg(rate * after)
    return divide(minus(expneg(rate * before), expneg(rate * after)), rat(rate * (after-before)))


CE_PATHS = tuple(product((0, 1), repeat=3))
CE_WEIGHTS = ((Q(1, 8),) * 8,
    tuple(Q(n, 64) for n in (1, 3, 3, 9, 3, 9, 9, 27)))


def finite_ce1(end):
    likelihoods = [sum((weight for path, weight in zip(CE_PATHS, weights, strict=True)
                       if sum(path[:end]) == 0), Q(0)) for weights in CE_WEIGHTS]
    mass = sum(likelihoods, Q(0)) / 2
    return likelihoods[0] / (2*mass), mass


@dataclass(frozen=True)
class AcquisitionScript:
    before: int
    after: int
    symbol: str


class TimeSource:
    def __init__(self, rig):
        self.rig, self.calls, self.symbols = rig, [], {}
        self.gates = [Gate() for _ in rig.plan]
        self.payload = b"opaque: not an arrival timestamp"
    def read(self, cursor):
        i = len(self.calls); self.calls.append(cursor)
        gate = self.gates[i]; gate.entered.set()
        if i + 1 == len(self.rig.plan): self.rig.running.stop()
        assert gate.release.wait(WATCHDOG), "timed source not released"
        if self.rig.closing: raise SystemExit("test teardown")
        self.rig.clock.set(self.rig.plan[i].after)
        symbol = self.symbols[i]
        if symbol == U: raise OSError("independent source failure")
        return fb.SourceItem(media_type="application/octet-stream", data=self.payload, claims={}) if symbol == T else None


class TimeActor:
    def __init__(self, rig):
        self.rig, self.calls, self.symbols = rig, [], {}
        self.gates = [Gate() for _ in range(8)]
        self.entered_ns, self.returned_ns = [], []
    def perform(self, execution):
        i = len(self.calls); self.calls.append(execution)
        self.entered_ns.append(self.rig.clock.mono_ns()); self.gates[i].entered.set()
        assert self.gates[i].release.wait(WATCHDOG)
        if self.rig.closing: raise SystemExit("test teardown")
        self.returned_ns.append(self.rig.clock.mono_ns())
        return fb.SourceItem(media_type="application/octet-stream", data=b"state-only sensor", claims={}) if self.symbols[i] == T else None


class AcquisitionTickClock:
    """A test clock that advances during a real acquire, even without a source.

    The first public clock read in the acquire sees before; time then advances
    to after. Later reads see after, without assuming how many reads occur.
    Other host calls use the ordinary clock. Native Frame endpoints are checked
    by the test before using them in any probability calculation.
    """
    def __init__(self, delegate):
        self.delegate, self.scope = delegate, local()
    def __getattr__(self, name): return getattr(self.delegate, name)
    @contextmanager
    def acquisition(self, interval):
        self.scope.after = interval.after
        self.scope.pending = True
        try: yield
        finally: self.scope.pending = False
    def read(self, getter):
        value = getter()
        if getattr(self.scope, "pending", False):
            self.scope.pending = False
            self.delegate.set(self.scope.after)
        return value
    def now(self): return self.read(self.delegate.now)
    def mono_ns(self): return self.read(self.delegate.mono_ns)


class TimedPort(ObservedEntryPort):
    def acquire(self):
        i = len(self.owner.calls)
        script = self.owner.rig.plan[i]
        self.owner.rig.clock.set(script.before)
        self.owner.calls.append((script.before, script.after))
        # Only native SourceMeasurer invokes this port. The optional clock is
        # a public input, not a fabricated Frame or a delay in production code.
        acquisition = getattr(self.owner.rig.clock, "acquisition", None)
        if acquisition is None:
            frame = self.delegate.acquire()
        else:
            with acquisition(script): frame = self.delegate.acquire()
        if getattr(self.owner.rig, "unplugged", False):
            self.owner.stop()  # Finish this acquisition, without starting another.
        return frame


class TimedMeasurer(NativeEntryObserver):
    def __init__(self, rig):
        super().__init__(fb.SourceMeasurer()); self.rig, self.calls = rig, []
    def run(self, work, ctx):
        wid = work.desc.work_id; self.contexts[wid] = ctx
        done = self.returned.setdefault(wid, Event())
        try: return self.worker.run(work, TimedPort(self, work, ctx))
        finally: done.set()
    def stop(self): self.worker.stop()


class TimeRig(PoolRig):
    def __init__(self, plan, *, rates=(Q(1), Q(2)), prior=(Q(1, 2), Q(1, 2)),
                  origin=1000, unit=Q(1), initial_count=0, failure=None, disconnection=None,
                  finite=False, thinking=False, draw_bits=None, start_ns=None):
        super().__init__(component=replace(OLD, prior=prior), thinking=thinking, draw_bits=draw_bits)
        self.plan = tuple(plan); self.origin, self.unit = origin, unit
        self.rates, self.time_prior, self.initial_count = rates, prior, initial_count
        self.failure, self.finite = failure, finite
        self.disconnection = disconnection
        self.passive, self.actor = TimeSource(self), TimeActor(self)
        self.clock.set(self.plan[0].before if start_ns is None else start_ns)
        declaration = self.boot_input.declaration
        original = declaration.observation_models[0].value
        model = self.timing_model(original)
        observation = replace(declaration.observation_models[0],
            contract=contract("sui.fb.timed_acquisition_model"), value=model)
        per = declaration.perception; derivation = per.value.derivation
        per = replace(per, value=replace(per.value, derivation=replace(derivation,
            method=replace(derivation.method, contract=contract("sui.fb.saved_timed_acquisition_update")))))
        execution = declaration.execution
        old = execution.value
        self.state_reading = fb.SourceCountReading(independent_of_count=True, count_shift=0)
        timed = fb.TimedExecutionDeclaration(allocation=old.allocation, actors=old.actors,
            no_effect=old.no_effect, cells=old.cells, source_overlap=old.source_overlap,
            actor_overlap=old.actor_overlap, source_readings={"peek": self.state_reading})
        execution = replace(execution, contract=contract("sui.fb.timed_execution_declaration"), value=timed)
        self.boot_input = replace(self.boot_input, declaration=replace(declaration,
            perception=per, observation_models=(observation,), execution=execution))

    def law(self, *, rates=None, prior=None):
        if self.finite:
            return fb.FiniteCountLaw(run=self.clock.run, states=("A", "B"), prior=self.time_prior,
                origin_ns=self.origin, initial_count=self.initial_count,
                positions_ns=tuple(self.origin + 10*i for i in (1, 2, 3)),
                paths=CE_PATHS, weights_by_state=CE_WEIGHTS)
        return fb.PoissonLaw(run=self.clock.run, states=("A", "B"), prior=prior or self.time_prior,
            rates=self.rates if rates is None else rates, origin_ns=self.origin,
            initial_count=self.initial_count, time_unit=self.unit)

    def timing_model(self, original, *, rates=None, prior=None, law=None):
        return fb.TimedAcquisitionModel(route_slot="route", law=law or self.law(rates=rates, prior=prior),
            decision_time=fb.UniformAcquisitionTime(), conditioning=fb.FixedAcquisitionSchedule(
                run=self.clock.run, intervals=tuple((s.before, s.after) for s in self.plan)),
            failure=None if self.failure is None else fb.IndependentAcquisitionFailure(
                unavailable_probability=self.failure), control_rule=original.control_rule,
            control_independence=original.independence,
            disconnection=None if self.disconnection is None else fb.IndependentSourceDisconnection(
                coefficient=self.disconnection))

    def start(self):
        assert all(a.after == b.before for a, b in zip(self.plan, self.plan[1:])), "native start ruler must be contiguous"
        super().start(); return self

    def direct(self, *, unplugged=False, worker_overrides=None):
        self.measurer = TimedMeasurer(self)
        self.unplugged = unplugged
        if unplugged:
            assert not worker_overrides
            # The missing source has no read() gate. Normally use point time;
            # a public clock that advances inside acquire also permits a span.
            assert len(self.plan) == 1
            assert (self.plan[0].before == self.plan[0].after or
                    callable(getattr(self.clock, "acquisition", None)))
            self.entry_observers.append(self.measurer)
            workers = fb.WorkerBundle({"measure_segment": self.measurer,
                "belief_update": fb.TimedBeliefUpdater(registry=self.registry),
                "candidate_generation": fb.CandidateGenerator(),
                "evaluation_prepare": fb.EvaluationPreparer(registry=self.registry),
                "selection_draw": fb.UniformDraw(randbits=self.randbits),
                "evaluation": fb.Evaluator(), "execute_step": fb.StepExecutor()})
            self.host = fb.FThreadHost(ledger=self.ledger, clock=self.clock, registry=self.registry,
                workers=workers, launcher=self.launcher, sources={}, actors={"toy": self.actor})
            self.running = SimpleNamespace(host=self.host, stop=self.measurer.stop)
            self.host.post(fb.ClockDeclared(declaration=self.clock_declaration))
            self.host.post(self.boot_input)
            self.boot()
            return self
        overrides = {"measure_segment": self.measurer,
                     "belief_update": fb.TimedBeliefUpdater(registry=self.registry)}
        overrides.update(worker_overrides or {})
        super().direct(worker_overrides=overrides)
        self.running.stop = self.measurer.stop
        return self

    def expression(self, *, boundary=None):
        return self.host.belief_expression(boot=self.boot(), boundary=boundary)

    def update(self):
        try: previous = self.expression().adoption
        except fb.TimeBeliefError as error:
            if error.kind not in ("incomplete", "unavailable"): raise
            previous = None
        self.run("belief_update")
        def ready():
            try: return self.expression().adoption != previous
            except fb.TimeBeliefError as error:
                if error.kind in ("incomplete", "unavailable"): return False
                raise
        self.until(ready)
        expression = self.expression()
        assert expression.adoption is not None and self.read_stored(expression.point)
        return expression

    def observe(self, index):
        self.sense(index, self.plan[index].symbol, begin=index == 0)

    def query(self, kind, *, expression=None, state=None, candidate=None, count=None,
              at_least=False, tolerance=Q(1, 2**60), tight=False):
        expression = expression or self.expression()
        quantity = fb.BeliefQuantity(kind=kind, state=state, candidate=candidate, count=count, at_least=at_least)
        value = self.host.query_belief(belief=expression, quantity=quantity,
                                     budget=budget(tolerance, tight=tight))
        assert value.root == expression.root and value.quantity == quantity
        assert value.upper - value.lower <= tolerance
        assert self.host.verify_belief_value(belief=expression, value=value)
        return value

    def check(self, p, mass):
        assert_contains(self.query("state", state="A"), p)
        assert_contains(self.query("state", state="B"), minus(rat(1), p))
        assert_contains(self.query("mass"), mass)

    def check_selection(self, selected, p, expression):
        values = self.host.query_selection(selection=selected.cid, budget=budget())
        assert values.belief_root == expression.root
        for group in (values.information, values.G, values.probabilities):
            assert all(value.upper - value.lower <= budget().tolerance for value in group)
        info, probability = information_and_choice(p)
        assert set(values.candidates) == {"peek", "wait"}
        for i, candidate in enumerate(values.candidates):
            assert_contains(values.information[i], info if candidate == "peek" else rat(0))
            assert_contains(values.G[i], minus(rat(0), info) if candidate == "peek" else rat(0))
            assert_contains(values.probabilities[i], probability if candidate == "peek" else minus(rat(1), probability))
        return values

    def add_time_candidate(self, *, rates=(Q(3), Q(4)), prior=(Q(3, 4), Q(1, 4)), law=None,
                           observation=None):
        doc, _ = world_document(prior=prior)
        record = self.record(Prediction(target="time.added", about=(), basis=(),
            content=Payload.json({"document": doc}), contract=contract("sui.f.model_source")),
            RefKind.PREDICTION, Role.MODEL)
        model = self.ledger.append(record, ()).cid
        original = acquisition_for(OLD)
        observation = observation or self.timing_model(original, rates=rates, prior=prior, law=law)
        candidate = fb.BeliefCandidate(id="later", model=model, observation_model=observation,
            correspondence={"pairs": [["A", "A"], ["B", "B"]]})
        return self.host.add_candidate(boot=self.boot(), candidate=candidate, alpha=Q(1, 3))


@pytest.fixture
def times_rig():
    made = []
    def make(plan, **kwargs):
        time_api(); rig = TimeRig(plan, **kwargs); made.append(rig); return rig
    yield make
    for rig in reversed(made): rig.close()


def script(*items, origin=1000):
    return tuple(AcquisitionScript(origin+b, origin+a, symbol) for b, a, symbol in items)


def negative_update(r, *, falsified=False):
    r.exercise_available_updates()
    rows = r.host.window.status().updates
    assert rows and any(row.reasons for row in rows)
    try: assert not r.expression().adoption
    except fb.TimeBeliefError as error:
        assert error.kind in ({"model_falsified"} if falsified else {"unsupported", "unavailable", "incomplete"})
        assert error.reason
    if falsified:
        assert any(row.outcome == "rejected" and "model_falsified" in row.reasons for row in rows)
    else:
        assert not any("model_falsified" in row.reasons for row in rows)


def test_time1_exact_oracle_and_CE1_table_controls():
    assert finite_ce1(2) == (Q(4, 5), Q(5, 32))
    assert finite_ce1(3) == (Q(8, 9), Q(9, 128))
    for x in (Q(1, 2), Q(2, 3)):
        assert x / (x+x*x) == 1 / (1+x)
        assert (1-x) / ((1-x)+(1-x*x)/2) == 2 / (3+x)
    low, high = exp_minus(Q(1), 20)
    assert Q(1, 3) < low < high < Q(1, 2)
    assert exp_minus(Q(0), 3) == (1, 1)


def test_time1_native_finite_information_and_probability_oracle_control():
    r = CycleRig(draw_bits=lambda n: 15 << (n-5))
    try:
        r.start(); selected = r.think(); value = r.selected_value(selected)
        assert value.evaluation.candidates == ("wait", "peek")
        assert value.choice.id == "peek"
        info, probability = information_and_choice(rat(Q(1, 2)))
        for i, name in enumerate(value.evaluation.candidates):
            assert_contains(value.evaluation.G[i].bounds, minus(rat(0), info) if name == "peek" else rat(0))
            assert_contains(value.evaluation.q_star[i].bounds, probability if name == "peek" else minus(rat(1), probability))
    finally: r.close()


def test_time1_policy_boundary_changes_from_time_one_to_three_oracle_control():
    waits = []
    for t in (1, 3):
        p, _mass = posterior([expneg(t), expneg(2*t)])
        _info, probability = information_and_choice(p)
        waits.append(enclose(minus(rat(1), probability), 64))
    assert waits[0][1] < Q(15, 32) < waits[1][0]


@pytest.mark.parametrize("native_start", [False, True], ids=["point-gaps-port-control", "contiguous-native-start-control"])
def test_time1_real_acquire_clock_and_source_footing_control(native_start):
    r = PoolRig(thinking=False)
    r.plan = script((1, 1, T), (1, 2, E)) if native_start else script((1, 1, T), (3, 3, E))
    r.passive = TimeSource(r); r.clock.set(r.plan[0].before)
    try:
        if native_start: r.start()
        else:
            measurer = TimedMeasurer(r)
            r.direct(worker_overrides={"measure_segment": measurer})
            r.running.stop = measurer.stop
        for i, item in enumerate(r.plan):
            r.sense(i, item.symbol, begin=i == 0); r.adopt(i+1)
        r.assert_answer((P, EMPTY))
        assert r.passive.calls == [0, 1]
        for i, item in enumerate(r.plan):
            frame, = [f for f in r.frame_reports() if f.value["item"]["value"]["sample_seq"] == i]
            interval = frame.value["item"]["value"]["measurement_interval"]
            assert (interval["start_ns"], interval["end_ns"]) == (item.before, item.after)
    finally: r.close()


def test_time1_legacy_CE1_evaluation_is_the_same_independent_value_control():
    r = PoolRig().thinking_seats(1, execution=False)
    declaration = r.boot_input.declaration
    r.boot_input = replace(r.boot_input, declaration=replace(declaration, observation_models=(
        replace(declaration.observation_models[0], value=acquisition_for(CE1)),)))
    try:
        r.start(); r.think()
        for i, symbol in enumerate((T, E)):
            r.sense(i, symbol, begin=i == 0); r.adopt(i+1)
            selected = r.think(); values = r.selected_value(selected).evaluation
            p, _mass = finite_ce1(i+2)
            information, probability = information_and_choice(rat(p))
            for j, name in enumerate(values.candidates):
                assert_contains(values.G[j].bounds, minus(rat(0), information) if name == "peek" else rat(0))
                assert_contains(values.q_star[j].bounds, probability if name == "peek" else minus(rat(1), probability))
    finally: r.close()


@pytest.mark.parametrize("interval", [(2, 2), (0, 2), (1, 2)], ids=["point", "uniform-full", "uniform-half"])
def test_time1_empty_uses_the_declared_interval_not_after_and_precision_refines(times_rig, interval):
    b, a = interval
    r = times_rig(script((b, a, E)), unit=Q(1, 2)).direct(); r.observe(0); expression = r.update()
    likelihoods = [first_empty(rate, Q(b, 2), Q(a, 2)) for rate in r.rates]
    p, mass = posterior(likelihoods); r.check(p, mass)
    if b == a: p = divide(rat(1), plus(rat(1), expneg(1)))
    if b == 0: p = divide(rat(2), plus(rat(3), expneg(1)))
    coarse = r.query("state", state="A", tolerance=Q(1, 16)); assert_contains(coarse, p)
    width = coarse.upper - coarse.lower; assert width > 0
    fine_tolerance = min(Q(1, 2**80), width/8)
    fine = r.query("state", state="A", tolerance=fine_tolerance); assert_contains(fine, p)
    assert fine.upper - fine.lower < width
    assert r.expression().root == expression.root
    assert r.host.same_belief(left=expression, right=r.expression())


def test_time1_uniform_empty_keeps_unobserved_arrivals_between_decision_and_after(times_rig):
    r = times_rig(script((0, 1, E))).start(); r.observe(0); r.update()
    p, mass = posterior([first_empty(rate, 0, 1) for rate in r.rates]); r.check(p, mass)
    no_arrivals_at_after = divide(total(times(rat(Q(1, 2)), expneg(rate)) for rate in r.rates), mass)
    value = r.query("count", count=0)
    assert_contains(value, no_arrivals_at_after)
    assert value.upper < 1  # Omitting P(after-u) falsely says the count is still zero.


@pytest.mark.parametrize("initial_count", [0, 1])
def test_time1_taken_is_availability_not_an_arrival_timestamp(times_rig, initial_count):
    r = times_rig(script((1, 1, T)), initial_count=initial_count).start(); r.observe(0); r.update()
    if initial_count:
        p, mass = rat(Q(1, 2)), rat(1)
    else: p, mass = posterior([minus(rat(1), expneg(rate)) for rate in r.rates])
    r.check(p, mass); assert r.passive.calls == [0]


def test_time1_cursor_threshold_growth_rebuilds_counts_from_the_original_law(times_rig):
    r = times_rig(script((1, 1, T), (1, 1, T), (1, 1, E))).direct()
    for i in range(3): r.observe(i); r.update()
    likelihoods = [times(rat(rate*rate/2), expneg(rate)) for rate in r.rates]
    p, mass = posterior(likelihoods); r.check(p, mass)
    count = r.query("count", count=2)
    assert count.exact == 1 and count.lower <= 1 <= count.upper
    assert r.passive.calls == [0, 1, 2]


@pytest.mark.parametrize("taken_first", [False, True], ids=["empty-empty", "taken-empty-empty"])
@pytest.mark.parametrize("origin,unit", [(1000, Q(1)), (10000, Q(1, 2))])
def test_time1_joint_likelihood_uses_elapsed_time_and_does_not_double_count_survival(times_rig, taken_first, origin, unit):
    scale = unit.denominator
    items = ([(scale, scale, T)] if taken_first else []) + [(2*scale, 2*scale, E), (4*scale, 4*scale, E)]
    r = times_rig(script(*items, origin=origin), origin=origin, unit=unit).direct()
    for i in range(len(items)): r.observe(i); r.update()
    likelihoods = [times(rat(rate if taken_first else 1), expneg(rate*4)) for rate in r.rates]
    p, mass = posterior(likelihoods); r.check(p, mass)
    assert r.passive.calls == ([0, 1, 1] if taken_first else [0, 0])


@pytest.mark.parametrize("declared", [False, True])
def test_time1_unavailable_needs_an_independent_failure_law_and_is_not_empty(times_rig, declared):
    r = times_rig(script((1, 1, U)), failure=Q(1, 4) if declared else None).start()
    r.observe(0)
    if not declared: negative_update(r)
    else:
        r.update(); r.check(rat(Q(1, 2)), rat(Q(1, 4)))
        assert_contains(r.query("count", count=0), total(times(rat(Q(1, 2)), expneg(rate)) for rate in r.rates))


def test_time1_independent_failure_between_empty_reads_does_not_reset_the_count_process(times_rig):
    r = times_rig(script((1, 1, E), (2, 2, U), (3, 3, E)), failure=Q(1, 4)).direct()
    for i in range(3): r.observe(i); r.update()
    p, mass = posterior([times(rat(Q(9, 64)), expneg(rate*3)) for rate in r.rates])
    r.check(p, mass); assert r.passive.calls == [0, 0, 0]


@pytest.mark.parametrize("symbol", [T, E], ids=["taken", "empty"])
@pytest.mark.parametrize("failure", [None, Q(1, 4)], ids=["no-called-failure", "with-called-failure"])
def test_time1_connected_taken_and_empty_scale_mass_by_connection_probability(times_rig, symbol, failure):
    coefficient = Q(1, 3)
    likelihoods = [expneg(rate) if symbol == E else minus(rat(1), expneg(rate))
                   for rate in (Q(1), Q(2))]
    expected_state, count_mass = posterior(likelihoods)
    success = 1 - (failure if failure is not None else Q(0))
    # Both actual acquisitions have the same count law. A constant chance of
    # connection changes their evidence mass, not the conditional S belief.
    for disconnection in (None, coefficient):
        r = times_rig(script((1, 1, symbol)), failure=failure,
                      disconnection=disconnection).start()
        r.observe(0); r.update()
        connected = 1 - (disconnection if disconnection is not None else Q(0))
        expected_mass = times(rat(connected*success), count_mass)
        r.check(expected_state, expected_mass)
        assert r.passive.calls == [0]


@pytest.mark.parametrize("symbol", [T, E, U], ids=["taken", "empty", "called-failure"])
def test_time1_zero_disconnection_matches_an_omitted_declaration(times_rig, symbol):
    failure = Q(1, 4)
    if symbol == U:
        expected_state, expected_mass = rat(Q(1, 2)), rat(failure)
    else:
        likelihoods = [expneg(rate) if symbol == E else minus(rat(1), expneg(rate))
                       for rate in (Q(1), Q(2))]
        expected_state, count_mass = posterior(likelihoods)
        expected_mass = times(rat(1-failure), count_mass)
    # Compare each side to the independent answer, not to overlapping intervals
    # or canonical roots whose declarations/record identities are different.
    for disconnection in (None, Q(0)):
        r = times_rig(script((1, 1, symbol)), failure=failure,
                      disconnection=disconnection).start()
        r.observe(0); r.update(); r.check(expected_state, expected_mass)
        assert r.passive.calls == [0]


def test_time1_one_acquisition_outcomes_normalize_with_distinct_connection_and_failure_kernels(times_rig):
    coefficient, failure = Q(1, 3), Q(1, 4)
    masses, conditional = [], {state: [] for state in ("A", "B")}
    # Four separate single-acquisition histories, with one common origin,
    # point-time measurement, prior and law. These are alternatives, not a
    # four-acquisition sequence or empirical frequency estimates.
    for symbol, unplugged in ((U, True), (U, False), (T, False), (E, False)):
        r = times_rig(script((1, 1, symbol)), failure=failure, disconnection=coefficient)
        if unplugged:
            r.direct(unplugged=True)
            r.run("measure_segment", background=True)
            r.until(lambda: len(r.frame_reports()) == 1)
            expected_state, expected_mass = rat(Q(1, 2)), rat(coefficient)
        else:
            r.start(); r.observe(0)
            if symbol == U:
                expected_state = rat(Q(1, 2))
                expected_mass = rat((1-coefficient)*failure)
            else:
                likelihoods = [expneg(rate) if symbol == E else minus(rat(1), expneg(rate))
                               for rate in r.rates]
                expected_state, count_mass = posterior(likelihoods)
                expected_mass = times(rat((1-coefficient)*(1-failure)), count_mass)
        r.update(); r.check(expected_state, expected_mass)
        frame, = r.frame_reports()
        observed = frame.value["item"]["value"]["value"]["value"]
        assert observed["source_called"] is (not unplugged)
        assert observed["result"]["kind"] == {T: "taken", E: "empty", U: "unavailable"}[symbol]
        assert r.passive.calls == ([] if unplugged else [0])
        mass = r.query("mass"); masses.append(mass)
        for state in conditional:
            belief = r.query("state", state=state)
            # L_s = Z * q_s / prior_s. All bounds here are nonnegative,
            # so interval multiplication encloses each state's outcome mass.
            assert belief.lower >= 0 and mass.lower >= 0
            conditional[state].append((2*mass.lower*belief.lower, 2*mass.upper*belief.upper))
    total_mass = SimpleNamespace(lower=sum(x.lower for x in masses), upper=sum(x.upper for x in masses))
    assert_contains(total_mass, rat(1))
    assert total_mass.upper-total_mass.lower <= 4*budget().tolerance
    for state, bounds in conditional.items():
        total_conditional = SimpleNamespace(lower=sum(x[0] for x in bounds), upper=sum(x[1] for x in bounds))
        assert_contains(total_conditional, rat(1))


@pytest.mark.parametrize("defect", ["missing-conditioning", "different-interval", "different-run"])
def test_time1_time_conditioning_and_clock_binding_are_declared_not_silently_invented(times_rig, defect):
    r = times_rig(script((1, 1, E)))
    observation = r.boot_input.declaration.observation_models[0]
    try:
        model = observation.value
        if defect == "missing-conditioning": model = replace(model, conditioning=None)
        elif defect == "different-interval":
            model = replace(model, conditioning=fb.FixedAcquisitionSchedule(run=r.clock.run,
                intervals=((r.origin+2, r.origin+2),)))
        else: model = replace(model, law=replace(model.law, run=Ref(kind=RefKind.RUN, value="other-run")))
        r.boot_input = replace(r.boot_input, declaration=replace(r.boot_input.declaration,
            observation_models=(replace(observation, value=model),)))
        r.start(); r.observe(0); negative_update(r)
    except fb.TimeBeliefError as error:
        assert error.kind in ("invalid", "unsupported", "unavailable") and error.reason


@pytest.mark.parametrize("rates,initial,symbol", [((Q(0), Q(1)), 0, T), ((Q(0), Q(0)), 0, T),
    ((Q(1), Q(2)), 1, E)], ids=["one-zero-component", "whole-zero", "known-backlog-cannot-be-empty"])
def test_time1_structural_zero_is_proved_from_support(times_rig, rates, initial, symbol):
    r = times_rig(script((1, 1, symbol)), rates=rates, initial_count=initial).start(); r.observe(0)
    if rates == (0, 1):
        r.update(); value = r.query("state", state="A")
        assert value.exact == 0 and value.lower == value.upper == 0
        assert_contains(r.query("mass"), times(rat(Q(1, 2)), minus(rat(1), expneg(1))))
    else: negative_update(r, falsified=True)


def test_time1_tiny_positive_likelihood_survives_coarse_bounds_and_tight_budget(times_rig):
    tiny = Q(1, 2**160)
    r = times_rig(script((1, 1, T)), rates=(tiny, 2*tiny)).start(); r.observe(0); expression = r.update()
    p, mass = posterior([minus(rat(1), expneg(rate)) for rate in r.rates])
    coarse = r.query("mass", tolerance=Q(1, 16)); assert_contains(coarse, mass)
    assert coarse.upper > 0 and expression.adoption is not None
    r.check(p, mass)
    try:
        value = r.query("state", state="A", tolerance=Q(1, 2**80), tight=True)
    except fb.TimeBeliefError as error:
        assert error.kind == "incomplete" and error.reason
    else: assert_contains(value, p)
    assert r.expression().root == expression.root
    assert not any("model_falsified" in row.reasons for row in r.host.window.status().updates)


@pytest.mark.parametrize("another", [False, True], ids=["same-record-rebuild", "distinct-record-same-numbers"])
def test_time1_canonical_identity_is_record_based_not_interval_overlap(times_rig, another):
    plan = script((1, 1, T), (2, 2, E)) if another else script((1, 1, T))
    r = times_rig(plan, rates=(Q(0), Q(0)) if another else (Q(1), Q(2)),
                  initial_count=1 if another else 0).direct()
    r.observe(0); first = r.update(); value = r.query("state", state="A")
    if another:
        r.observe(1); second = r.update()
        assert first.root != second.root and not r.host.same_belief(left=first, right=second)
        assert r.query("state", state="A").exact == value.exact == Q(1, 2)
        assert len(second.observations) == len(first.observations) + 1
        assert not r.host.verify_belief_value(belief=second, value=value)
    else:
        p, mass = posterior([minus(rat(1), expneg(rate)) for rate in r.rates])
        r.check(p, mass)
        r.until(lambda: any(w.purpose == "measure_segment" and w.stop_confirmed for w in r.host.window.status().works))
        r.host.rebuild_window(); public_rounds(r, count=8)
        second = r.expression()
        assert first.root == second.root and r.host.same_belief(left=first, right=second)
        assert first.observations == second.observations and len(r.frame_reports()) == 1
        r.check(p, mass)  # A second application would square a nontrivial likelihood.


def test_time1_numeric_certificate_tampering_is_rejected(times_rig):
    r = times_rig(script((1, 1, E))).start(); r.observe(0); expression = r.update()
    value = r.query("state", state="A")
    assert not r.host.verify_belief_value(belief=expression, value=replace(value, lower=Q(0), upper=Q(0), exact=Q(0)))
    assert not r.host.verify_belief_value(belief=expression, value=replace(value, root="not-the-canonical-root"))
    assert r.host.verify_belief_value(belief=expression, value=value)


@pytest.mark.parametrize("thinking", [False, True])
def test_time1_CE1_eight_path_law_uses_the_new_expression_and_query_entry(times_rig, thinking):
    r = times_rig(script((20, 20, E), (30, 30, E)), unit=Q(1, 10), finite=True, thinking=thinking).direct()
    if thinking: r.think()
    for i, (p, mass) in enumerate(((Q(4, 5), Q(5, 32)), (Q(8, 9), Q(9, 128)))):
        r.observe(i); expression = r.update()
        state, evidence = r.query("state", state="A"), r.query("mass")
        assert state.exact == p and evidence.exact == mass
        if thinking: r.check_selection(r.think(), rat(p), expression)


@pytest.mark.parametrize("elapsed", [1, 3])
def test_time1_different_empty_times_change_actual_evaluation_values(times_rig, elapsed):
    r = times_rig(script((elapsed, elapsed, E)), thinking=True,
                  draw_bits=lambda n: 15 << (n-5)).start()
    # K36-c-a(2): finish the first generation only after this acquisition;
    # its context then reads this adoption. Do not leave an earlier selection's
    # step in its start procedure: a newer selection cannot replace that target
    # before the step enters (K36-c-a(3)).
    r.observe(0); expression = r.update()
    p, mass = posterior([expneg(rate*elapsed) for rate in r.rates]); r.check(p, mass)
    selected = r.think(); r.check_selection(selected, p, expression)
    # u=15/32 is between the two declared wait/peek policy boundaries. Inspect
    # the action actually handed to perform, not only a numerical query adapter.
    if elapsed == 1:
        _request, execution = r.enter_step(selection=selected.cid)
        assert execution.action.id == "peek"
        r.finish_step(0, T)
    else:
        q = r.request_where("execute_step", lambda q: q.value["desc"]["args"]["selection"] == selected.cid)
        r.run_request(q)
        r.until(lambda: any(e.execution.selection == selected.cid and e.outcome == "no_effect"
                            for e in r.host.window.status().executions))
        row, = [e for e in r.host.window.status().executions if e.execution.selection == selected.cid]
        assert row.execution.action.id == "wait" and not r.actor.calls


def test_time1_native_start_noninterfering_step_and_next_acquisition_use_the_belief(times_rig):
    r = times_rig(script((1, 1, E), (1, 2, E)), thinking=True).start()
    r.observe(0); first = r.update()
    p, _mass = posterior([expneg(rate) for rate in r.rates])
    selected = r.think(); r.check_selection(selected, p, first)
    r.enter_step(selection=selected.cid); r.finish_step(0, T); after_step = r.update()
    step_likelihoods = [times(rat(k), expneg(rate)) for rate, k in zip(r.rates, (Q(1), Q(1, 2)), strict=True)]
    step_p, step_mass = posterior(step_likelihoods)
    r.check(step_p, step_mass)
    # K36-c(3,4): a free thinking seat admits the step-adoption root now.
    # Complete and check that activity before releasing the second acquisition;
    # a later adoption must not silently rebind its fixed context.
    step_selected = r.think()
    r.check_selection(step_selected, step_p, after_step)
    r.observe(1); final = r.update()
    likelihoods = [times(rat(k), first_empty(rate, 1, 2)) for rate, k in zip(r.rates, (Q(1), Q(1, 2)), strict=True)]
    p, mass = posterior(likelihoods); r.check(p, mass)
    assert final.root != after_step.root
    r.check_selection(r.think(), p, final)
    # The old selection still refers to its frozen belief, not the latest one.
    r.check_selection(selected, posterior([expneg(rate) for rate in r.rates])[0], first)


@pytest.mark.parametrize("bad", ["count-dependent", "changes-count"])
def test_time1_state_preserving_is_not_sufficient_for_source_noninterference(times_rig, bad):
    r = times_rig(script((1, 1, E)), thinking=True)
    try:
        reading = (fb.SourceCountReading(independent_of_count=False, count_shift=0)
                   if bad == "count-dependent" else replace(r.state_reading, count_shift=-1))
        execution = r.boot_input.declaration.execution
        r.boot_input = replace(r.boot_input, declaration=replace(r.boot_input.declaration,
            execution=replace(execution, value=replace(execution.value, source_readings={"peek": reading}))))
        r.start(); r.observe(0); r.update(); before = r.expression()
        r.think(); r.run("execute_step")
    except fb.TimeBeliefError as error:
        assert error.kind in ("unsupported", "unavailable") and error.reason
    except fb.StartInputError as error:
        assert error.reason
    else:
        r.exercise_available_updates()
        rows = r.host.window.status().executions
        assert rows and any(row.outcome in ("unconnected", "not_performed") and row.reason for row in rows)
        assert not r.actor.calls and r.expression().adoption == before.adoption


@pytest.mark.parametrize("step_elapsed", [0, 1], ids=["at-origin", "before-first-acquire"])
def test_time1_step_before_first_acquisition_uses_the_boot_law_once(times_rig, step_elapsed):
    r = times_rig(script((3, 3, E)), thinking=True,
                  start_ns=1000+step_elapsed).start()
    selected = r.think()
    assert not r.frame_reports() and not r.passive.calls
    r.enter_step(selection=selected.cid); r.finish_step(0, T)
    first = r.update()
    assert not r.frame_reports() and not r.passive.calls
    state, mass = r.query("state", state="A"), r.query("mass")
    assert state.exact == Q(2, 3) and mass.exact == Q(3, 4)
    r.check(rat(Q(2, 3)), rat(Q(3, 4)))
    count0 = total(times(rat(weight), expneg(rate*step_elapsed))
                   for weight, rate in zip((Q(2, 3), Q(1, 3)), r.rates, strict=True))
    assert_contains(r.query("count", count=0), count0)

    # Reconstructing before any Frame must not lose or square this step's kernel.
    r.host.rebuild_window(); public_rounds(r, count=8)
    assert r.expression().root == first.root
    r.check(rat(Q(2, 3)), rat(Q(3, 4)))

    r.clock.set(r.origin+3)
    r.observe(0); final = r.update()
    likelihoods = [times(rat(k), expneg(rate*3))
                   for k, rate in zip((Q(1), Q(1, 2)), r.rates, strict=True)]
    r.check(*posterior(likelihoods))
    assert final.adoption != first.adoption
    assert len(r.actor.calls) == 1 and r.passive.calls == [0]


@pytest.mark.parametrize("coefficient", [None, Q(1), Q(1, 3)],
                         ids=["missing-connection-kernel", "certain-disconnection", "nonunit-disconnection"])
def test_time1_unplugged_source_uses_its_own_kernel_and_advances_counts(times_rig, coefficient):
    # Point time is deliberately later than the origin. No read() is fabricated
    # for the absent source, and no assumption about clock-call counts is needed.
    r = times_rig(script((3, 3, U)), failure=Q(1, 4),
                  disconnection=coefficient).direct(unplugged=True)
    r.run("measure_segment", background=True)
    r.until(lambda: len(r.frame_reports()) == 1)
    frame, = r.frame_reports()
    value = frame.value["item"]["value"]
    assert value["value"]["kind"] == "value"
    observed = value["value"]["value"]
    assert observed["source_called"] is False
    assert observed["result"]["kind"] == "unavailable"
    assert (value["measurement_interval"]["start_ns"],
            value["measurement_interval"]["end_ns"]) == (r.origin+3, r.origin+3)
    assert not r.passive.calls
    if coefficient is None:
        negative_update(r)  # A called-failure declaration alone does not cover it.
        return
    r.update(); r.check(rat(Q(1, 2)), rat(coefficient))
    assert r.query("mass").exact == coefficient
    zero = total(times(rat(Q(1, 2)), expneg(rate*3)) for rate in r.rates)
    assert_contains(r.query("count", count=0), zero)
    assert_contains(r.query("count", count=1, at_least=True), minus(rat(1), zero))
    assert_contains(r.query("count", state="A", count=0), times(rat(Q(1, 2)), expneg(3)))


def test_time1_disconnection_scales_an_existing_step_belief_without_replacing_it(times_rig):
    r = times_rig(script((3, 3, U)), thinking=True, start_ns=1001,
                  failure=Q(1, 5), disconnection=Q(1, 3)).direct(unplugged=True)
    selected = r.think(); r.enter_step(selection=selected.cid); r.finish_step(0, T)
    first = r.update()
    r.check(rat(Q(2, 3)), rat(Q(3, 4)))
    r.run("measure_segment", background=True)
    r.until(lambda: len(r.frame_reports()) == 1)
    final = r.update()
    # Preserve an informative q and scale a nonunit Z: neither restoring the
    # prior nor replacing the old mass with c can pass this contrast.
    r.check(rat(Q(2, 3)), rat(Q(1, 4)))
    assert r.query("state", state="A").exact == Q(2, 3)
    assert r.query("mass").exact == Q(1, 4)
    zero = plus(times(rat(Q(2, 3)), expneg(3)), times(rat(Q(1, 3)), expneg(6)))
    assert_contains(r.query("count", count=0), zero)
    assert final.adoption != first.adoption and not r.passive.calls


@pytest.mark.parametrize("taken_diagonal", [(Q(1), Q(1, 2)), (Q(1, 4), Q(3, 4))],
                         ids=["original-model-kernel", "different-model-kernel"])
def test_time1_step_reading_has_no_matrix_values_and_uses_only_the_model_kernel(times_rig, taken_diagonal):
    # K38-c(3) removes the second set of numerical values, rather than checking
    # them against another set at runtime. The old conflicting declaration
    # (T=E=I/2) cannot bind to the public constructor anymore.
    time_api()
    assert {field.name for field in fields(fb.SourceCountReading)} == {"independent_of_count", "count_shift"}
    half = tuple(tuple(Q(1, 2)*x for x in row) for row in I)
    with pytest.raises(TypeError):
        signature(fb.SourceCountReading).bind(independent_of_count=True, count_shift=0,
                                              zero={T: half, E: half}, positive={T: half, E: half})
    taken = tuple(tuple(taken_diagonal[i] if i == j else Q(0) for j in range(2)) for i in range(2))
    empty = tuple(tuple(I[i][j]-taken[i][j] for j in range(2)) for i in range(2))
    r = times_rig(script((1, 1, E)), rates=(Q(1), Q(1)), thinking=True)
    document, _ = world_document(peek=taken, empty=empty)
    r.replace_model(document, label="time.one.kernel.source")
    r.start(); r.observe(0); r.update()
    selected = r.think(); r.enter_step(selection=selected.cid); r.finish_step(0, T)
    r.update()
    p = taken_diagonal[0] / sum(taken_diagonal)
    mass = times(rat(sum(taken_diagonal)/2), expneg(1))
    r.check(rat(p), mass)
    assert r.query("state", state="A").exact == p
    assert p != Q(1, 2)  # The removed T=I/2 declaration would give this wrong answer.
    assert len(r.actor.calls) == 1


def test_time1_K37_addition_replays_timed_evidence_and_changes_actual_evaluation(times_rig):
    r = times_rig(script((1, 1, E)), thinking=True).start(); r.think(); r.observe(0); old = r.update()
    r.think(); frames = tuple(x.cid for x in r.frame_reports())
    r.add_time_candidate()
    expression = r.update()
    old_weights = [times(rat(Q(1, 3)), expneg(rate)) for rate in (Q(1), Q(2))]
    new_weights = [times(rat(p/3), expneg(rate)) for p, rate in zip((Q(3, 4), Q(1, 4)), (Q(3), Q(4)), strict=True)]
    mass = total((*old_weights, *new_weights))
    p = divide(plus(old_weights[0], new_weights[0]), mass)
    r.check(p, mass)
    assert_contains(r.query("candidate", candidate="later"), divide(total(new_weights), mass))
    assert expression.root != old.root and tuple(x.cid for x in r.frame_reports()) == frames
    assert r.read_stored(expression.adoption)[2].body.content.as_json()["previous"] == old.adoption
    r.check_selection(r.think(), p, expression)


def test_time1_unsupported_law_candidate_is_named_and_never_silently_dropped(times_rig):
    r = times_rig(script((1, 1, E))).start(); r.observe(0); old = r.update()
    unknown = fb.MethodCall(contract=contract("test.unsupported_count_law"), args={})
    try:
        r.add_time_candidate(law=unknown)
        r.exercise_available_updates()
        r.query("state", state="A")
    except fb.TimeBeliefError as error:
        assert error.kind == "unsupported" and error.reason and "later" in error.targets
    else:
        pytest.fail("unsupported positive-weight law was silently accepted or dropped")


def test_time1_candidate_cannot_compare_mass_under_another_time_conditioning(times_rig):
    r = times_rig(script((0, 1, E))).start(); r.observe(0); r.update()
    try:
        other = r.timing_model(acquisition_for(OLD), rates=(Q(3), Q(4)),
                              prior=(Q(3, 4), Q(1, 4)))
        other = replace(other, conditioning=fb.FixedAcquisitionSchedule(run=r.clock.run,
            intervals=((r.origin, r.origin+2),)))
        r.add_time_candidate(observation=other)
        r.exercise_available_updates()
        r.query("mass")
    except fb.TimeBeliefError as error:
        assert error.kind in ("invalid", "unsupported", "unavailable") and error.reason and error.targets
    except (fb.CandidateInputError, fb.CandidatePoolError) as error:
        assert error.reason
    else:
        pytest.fail("candidate evidence compared with a different endpoint-conditioning contract")


@pytest.mark.parametrize("field,value", [("time_unit", Q(0)), ("time_unit", Q(-1)),
    ("rates", (Q(-1), Q(2))), ("prior", (Q(1, 2), Q(1, 4))),
    ("prior", (Q(-1), Q(2))), ("initial_count", -1)])
def test_time1_invalid_numeric_declarations_are_rejected(field, value):
    time_api()
    args = dict(run=Ref(kind=RefKind.RUN, value="test-time-run"), states=("A", "B"),
        prior=(Q(1, 2), Q(1, 2)), rates=(Q(1), Q(2)), origin_ns=1000, initial_count=0, time_unit=Q(1))
    args[field] = value
    with pytest.raises(fb.TimeBeliefError) as error: fb.PoissonLaw(**args)
    assert error.value.kind == "invalid" and error.value.reason and error.value.field


def test_time1_zero_prior_and_negative_integer_origin_are_valid(times_rig):
    r = times_rig(script((1, 1, E), origin=-1000), origin=-1000,
                  prior=(Q(0), Q(1))).start()
    r.observe(0); r.update()
    state = r.query("state", state="A")
    assert state.exact == 0 and state.lower == state.upper == 0
    r.check(rat(0), expneg(2))


@pytest.mark.parametrize("field,value", [("rates", (1.4142135623730951, Q(2))),
    ("origin_ns", Q(1, 2)), ("initial_count", Q(1, 2))])
def test_time1_numbers_outside_the_declared_exact_format_are_not_model_falsification(field, value):
    """The float is an unsupported approximate format, not an exact sqrt(2)."""
    time_api()
    args = dict(run=Ref(kind=RefKind.RUN, value="test-time-run"), states=("A", "B"),
        prior=(Q(1, 2), Q(1, 2)), rates=(Q(1), Q(2)), origin_ns=1000, initial_count=0, time_unit=Q(1))
    args[field] = value
    with pytest.raises(fb.TimeBeliefError) as error: fb.PoissonLaw(**args)
    assert error.value.kind in ({"unsupported"} if field == "rates" else {"invalid", "unsupported"})
    assert error.value.reason and error.value.kind != "model_falsified"


def time_fact_at(r, point):
    record = r.read_stored(point)[2]
    fact, = [x for x in r.facts(record.body.contract) if x.cid == point]
    return fact


def time_step_only_scene(times_rig):
    r = times_rig(script((3, 3, E)), thinking=True, start_ns=1001).start()
    selected = r.think(); r.enter_step(selection=selected.cid); r.finish_step(0, T)
    expression = r.update()
    assert not r.frame_reports() and not r.passive.calls
    return r, expression


def time_direct_update(r, q, value=None):
    """Saved U-only request, with the same real records for both contrasts.

    The host never receives the altered Q*, reading or R*. No synthetic prior,
    Frame, execution result or host evidence is introduced.
    """
    point = q.cid if value is None else belief1_clone(r, q, value)
    records = {p: r.read_stored(p)[2] for p in r.snapshot()}
    return u2.compute_timed_update(point, reader=BeliefSnapshotReader(records),
                                   registry=r.registry, evidence=None)


def time_finish_activity(r):
    """Drive one real native thought, stopping also at regular NoDecision."""
    rows = r.host.window.status().evaluations
    assert len(rows) == 1
    activity = rows[0].activity
    stages = ("candidate_generation", "evaluation_prepare", "selection_draw", "evaluation")
    def row():
        return next(x for x in r.host.window.status().evaluations if x.activity == activity)
    def offers():
        return [(q, body) for stage in stages for q in r.requests(stage)
                for wid, body in r.launcher.attempts
                if wid == q.value["desc"]["work_id"] and wid not in r.executed]
    for _ in range(32):
        r.until(lambda: row().outcome != "running" or bool(offers()))
        if row().outcome != "running": return row()
        q, body = offers()[0]; r.invoke(q, body)
    pytest.fail("finite native activity did not reach a public terminal outcome")


def test_time1_review_R1_tiny_positive_adoption_reaches_native_log_evaluation(times_rig, request):
    tiny = Q(1, 2**160)
    r = times_rig(script((1, 1, T)), rates=(tiny, Q(1)), thinking=True)
    prepare = NativeEntryObserver(fb.EvaluationPreparer(registry=r.registry))
    evaluate = NativeEntryObserver(fb.Evaluator())
    r.direct(
        worker_overrides={"evaluation_prepare": prepare, "evaluation": evaluate})
    r.observe(0); expression = r.update()
    # Do not pre-refine a belief query before exercising the evaluator's log.
    terminal = time_finish_activity(r)
    request.node.user_properties.append(("native_outcome", terminal.outcome))
    assert terminal.outcome in ("selected", "no_decision") and r.host.halted is None
    posts = [pair for observer in (prepare, evaluate) for pairs in observer.posts.values() for pair in pairs]
    assert posts
    for event, issued in posts:
        assert isinstance(event, fb.WorkFinished) and isinstance(event.outcome, fb.WorkOutputs)
        assert issued is not None
        if isinstance(issued.value, f.NoDecision):
            assert issued.value.outcome == "incomplete" and issued.value.reason
            if issued.value.progress is None: continue
            native = issued.value.progress
        elif isinstance(issued.value, f.Selected):
            native = issued.value.evaluation
        else:
            continue  # The regular preparation output is FProblem.
        p, _mass = posterior([minus(rat(1), expneg(tiny)), minus(rat(1), expneg(1))])
        info, probability = information_and_choice(p)
        for index, candidate in enumerate(native.candidates):
            assert_contains(native.G[index].bounds, minus(rat(0), info) if candidate == "peek" else rat(0))
            assert_contains(native.q_star[index].bounds, probability if candidate == "peek" else minus(rat(1), probability))
    if terminal.outcome == "selected":
        selected, = r.facts(c.SELECTION)
        p, _mass = posterior([minus(rat(1), expneg(tiny)), minus(rat(1), expneg(1))])
        r.check_selection(selected, p, expression)


@pytest.mark.parametrize("reading_keys", [(), ("wait",)], ids=["empty-map", "missing-selected-kernel"])
def test_time1_review_R2_missing_source_reading_stops_before_actor_call(times_rig, reading_keys):
    r = times_rig(script((3, 3, E)), thinking=True, start_ns=1001)
    execution = r.boot_input.declaration.execution
    r.boot_input = replace(r.boot_input, declaration=replace(r.boot_input.declaration,
        execution=replace(execution, value=replace(execution.value,
            source_readings={key: r.state_reading for key in reading_keys}))))
    try:
        r.start()
        if any(x.kind == "missing_contract" and x.reason for x in r.host.window.status().pending):
            assert not r.actor.calls
            return  # A reasoned boot-plan refusal is also allowed by R2.
        selected = r.think()
        q = r.request_where("execute_step", lambda q: q.value["desc"]["args"]["selection"] == selected.cid)
        r.run_request(q, background=True)
        r.until(lambda: bool(r.actor.calls) or
                any(e.reason for e in r.host.window.status().executions) or
                any(w.purpose == "execute_step" and w.blocked_by for w in r.host.window.status().works) or
                any(x.reason for x in r.host.window.status().pending))
    except fb.StartInputError as error:
        assert error.reason
    except fb.TimeBeliefError as error:
        assert error.kind in ("invalid", "unsupported", "unavailable") and error.reason
    assert not r.actor.calls


def test_time1_review_R3_step_before_origin_is_unreadable_not_negative_elapsed_probability(times_rig):
    r = times_rig(script((3, 3, E)), thinking=True, start_ns=999)
    try:
        r.start(); selected = r.think()
        q = r.request_where("execute_step", lambda q: q.value["desc"]["args"]["selection"] == selected.cid)
        r.run_request(q, background=True)
        r.until(lambda: bool(r.actor.calls) or
                any(e.reason for e in r.host.window.status().executions) or
                any(w.purpose == "execute_step" and w.blocked_by for w in r.host.window.status().works))
        if r.actor.calls:
            assert r.actor.entered_ns == [r.origin-1]
            r.finish_step(0, T)
        r.exercise_available_updates()
        assert not r.facts(c.BELIEF_ADOPTED)
        assert (any(x.reasons for x in r.host.window.status().updates) or
                any(x.reason for x in r.host.window.status().executions) or
                any(w.purpose == "execute_step" and w.blocked_by for w in r.host.window.status().works))
        try:
            value = r.query("count", count=0)
        except fb.TimeBeliefError as error:
            assert error.kind in ("invalid", "unsupported", "unavailable", "incomplete") and error.reason
        else:
            assert 0 <= value.lower <= value.upper <= 1
    except fb.StartInputError as error:
        assert error.reason
    except fb.TimeBeliefError as error:
        assert error.kind in ("invalid", "unsupported", "unavailable") and error.reason
        assert not r.facts(c.BELIEF_ADOPTED)


@pytest.mark.parametrize("changed", ["rates", "time_unit", "origin_ns"])
def test_time1_review_R4_same_step_under_another_time_law_has_another_root(times_rig, changed):
    r, expression = time_step_only_scene(times_rig)
    saved_result = time_fact_at(r, expression.result)
    q = time_fact_at(r, saved_result.value["request"])
    use, = q.value["desc"]["args"]["observations"]
    reading = time_fact_at(r, use["reading"])
    projection = reading.value["projection"]["args"]
    model = time_fact_at(r, projection["observation_model"])
    correspondence = time_fact_at(r, projection["correspondence"])
    alternate = deepcopy(model.value)
    alternate["value"]["law"][changed] = {"rates": [[3, 1], [4, 1]],
        "time_unit": [1, 2], "origin_ns": r.origin-1}[changed]
    other_model = belief1_clone(r, model, alternate)
    pairs = deepcopy(correspondence.value); pairs["observation_model"] = other_model
    other_pairs = belief1_clone(r, correspondence, pairs)
    plan = deepcopy(reading.value)
    plan["projection"]["args"].update(observation_model=other_model, correspondence=other_pairs)
    other_reading = belief1_clone(r, reading, plan)
    outcomes = []
    # Both Q*s declare the same enlarged view. Only the chosen reading differs.
    points = set(r.snapshot())
    common = deepcopy(q.value)
    common["desc"]["input_points"] = sorted(set(common["desc"]["input_points"]) | points)
    common["desc"]["numerical_view"]["boundary"] = sorted(set(common["desc"]["numerical_view"]["boundary"]) | points)
    for chosen in (reading.cid, other_reading):
        value = deepcopy(common)
        value["desc"]["args"]["observations"][0]["reading"] = chosen
        issued = time_direct_update(r, q, value)
        assert isinstance(issued, u2.IssuedUpdate)
        assert tuple(issued.result["observations"]) == expression.observations
        assert issued.result["entries"][0]["point"] == use["binding"]
        assert issued.result["terminal_ns"] == 1001
        outcomes.append(issued)
    assert outcomes[0].result["entries"] == outcomes[1].result["entries"]
    assert outcomes[0].result["units"] != outcomes[1].result["units"]
    assert outcomes[0].result["root"] != outcomes[1].result["root"]
    assert outcomes[0].application_digest != outcomes[1].application_digest


@pytest.mark.parametrize("entrance", ["query", "verify", "same"])
@pytest.mark.parametrize("rate", [[3, 1], [True, 1]], ids=["changed-rate", "boolean-numerator"])
def test_time1_review_R5_saved_spec_tampering_with_unchanged_root_is_rejected(times_rig, entrance, rate):
    r, original = time_step_only_scene(times_rig)
    certificate = r.query("state", state="A", expression=original)
    assert r.host.same_belief(left=original, right=original)
    assert r.host.verify_belief_value(belief=original, value=certificate)
    saved = time_fact_at(r, original.result)
    original_rate = saved.value["result"]["units"][0]["law"]["rate"]
    assert original_rate == [1, 1] and all(type(n) is int for n in original_rate)
    changed = deepcopy(saved.value)
    changed["result"]["units"][0]["law"]["rate"] = list(rate)
    # Python equality equates True with 1. Confirm that the actual JSON
    # content changed, and that ledger storage did not coerce true back to 1.
    assert json.dumps(changed, sort_keys=True) != json.dumps(saved.value, sort_keys=True)
    assert changed["result"]["root"] == saved.value["result"]["root"] == original.root
    assert changed["application_digest"] == saved.value["application_digest"]
    assert changed["request"] == saved.value["request"]
    other = belief1_clone(r, saved, changed)
    persisted = r.read_stored(other)[2].body.content.as_json()
    assert json.dumps(persisted, sort_keys=True) == json.dumps(changed, sort_keys=True)
    assert type(persisted["result"]["units"][0]["law"]["rate"][0]) is type(rate[0])
    forged = replace(original, point=other, result=other)
    assert r.read_stored(original.result)[2].body.content.as_json() == saved.value
    try:
        if entrance == "query":
            r.query("count", count=0, expression=forged)
            pytest.fail("altered saved spec was accepted for a belief query")
        elif entrance == "verify":
            assert r.host.verify_belief_value(belief=forged, value=certificate) is False
        else:
            assert r.host.same_belief(left=original, right=forged) is False
    except fb.TimeBeliefError as error:
        assert error.kind in ("invalid", "unavailable", "unsupported") and error.reason


def test_time1_review_R6_initial_public_candidate_name_works_for_weight_and_all_counts(times_rig):
    r = times_rig(script((1, 1, E))).start(); r.observe(0); r.update()
    pool = r.pool(); member, = pool.members
    assert isinstance(member.id, str)  # Use the public name, not a naming algorithm.
    weight = r.query("candidate", candidate=member.id)
    all_counts = r.query("count", candidate=member.id, count=0, at_least=True)
    assert weight.exact == all_counts.exact == 1
    assert_contains(r.query("count", candidate=member.id, count=0), rat(1))
    expected, mass = posterior([expneg(rate) for rate in r.rates])
    assert_contains(r.query("state", state="A", candidate=member.id), expected)
    r.check(expected, mass)


def test_time1_review_R7_finite_count_candidate_cannot_join_a_poisson_pool(times_rig):
    r = times_rig(script((1, 1, E))).start(); r.observe(0); r.update()
    finite = fb.FiniteCountLaw(run=r.clock.run, states=("A", "B"), prior=(Q(3, 4), Q(1, 4)),
        origin_ns=r.origin, initial_count=0, positions_ns=(r.origin+1,),
        paths=((0,), (1,)), weights_by_state=((Q(3, 4), Q(1, 4)), (Q(1, 4), Q(3, 4))))
    try:
        r.add_time_candidate(law=finite)
        r.exercise_available_updates(); r.query("mass")
    except fb.TimeBeliefError as error:
        assert error.kind in ("unsupported", "unavailable") and error.reason and "later" in error.targets
    except fb.CandidatePoolError as error:
        assert error.reason and "later" in error.targets
    except fb.CandidateInputError as error:
        assert error.reason and "candidate" in error.field
    else:
        pytest.fail("finite and Poisson laws were mixed or the positive finite candidate was silently dropped")


@pytest.mark.parametrize("threshold", [2, 3])
@pytest.mark.parametrize("uniform", [True, False], ids=["uniform-decision", "point-decision-control"])
def test_time1_M05_uniform_taken_keeps_positive_mass_in_the_upper_count_cell(times_rig, threshold, uniform):
    """Given N(1)=n, n arrival times are uniform: P(taken)=n/(n+1).

    Thus L_s=1-(1-exp(-rate))/rate, and the joint upper-cell mass is
    L_s - sum_{1<=n<C} exp(-rate)*rate**n/n! * n/(n+1).
    The point-time control instead weights every n>=1 by one.
    """
    r = times_rig(script((0 if uniform else 1, 1, T))).start()
    r.observe(0); r.update()
    likelihoods, tails = [], []
    for rate in r.rates:
        likelihood = minus(rat(1), first_empty(rate, 0, 1) if uniform else expneg(rate))
        below = total(times(rat(rate**n / factorial(n) * (Q(n, n+1) if uniform else 1)),
                            expneg(rate)) for n in range(1, threshold))
        likelihoods.append(likelihood); tails.append(minus(likelihood, below))
    p, mass = posterior(likelihoods); r.check(p, mass)
    joint_tail = total(times(rat(prior), tail)
                       for prior, tail in zip(r.time_prior, tails, strict=True))
    upper_cell = r.query("count", count=threshold, at_least=True)
    assert_contains(upper_cell, divide(joint_tail, mass))
    assert 0 < upper_cell.lower <= upper_cell.upper < 1
    assert_contains(r.query("count", state="A", count=threshold, at_least=True),
                    divide(times(rat(r.time_prior[0]), tails[0]), mass))
    assert r.query("count", count=0).exact == 0 and r.passive.calls == [0]


@pytest.mark.parametrize("unplugged", [True, False], ids=["disconnected", "called-failure"])
def test_time1_M06_non_counting_interval_advances_counts_through_after(times_rig, unplugged):
    r = times_rig(script((1, 3, U)), failure=Q(1, 4), disconnection=Q(1, 3))
    if unplugged:
        r.clock = AcquisitionTickClock(r.clock)
        r.direct(unplugged=True)
        r.run("measure_segment", background=True)
        r.until(lambda: len(r.frame_reports()) == 1)
    else:
        r.start(); r.observe(0)
    frame, = r.frame_reports()
    observed = frame.value["item"]["value"]
    interval = observed["measurement_interval"]
    assert (interval["start_ns"], interval["end_ns"]) == (r.origin+1, r.origin+3)
    value = observed["value"]["value"]
    assert value["result"]["kind"] == "unavailable" and value["source_called"] is (not unplugged)
    expression = r.update()
    assert expression.terminal_ns == r.origin+3
    r.check(rat(Q(1, 2)), rat(Q(1, 3) if unplugged else Q(1, 6)))
    zero = total(times(rat(prior), expneg(rate*3))
                 for prior, rate in zip(r.time_prior, r.rates, strict=True))
    one = total(times(rat(prior*rate*3), expneg(rate*3))
                for prior, rate in zip(r.time_prior, r.rates, strict=True))
    assert_contains(r.query("count", count=0), zero)
    assert_contains(r.query("count", count=1), one)
    assert_contains(r.query("count", count=2, at_least=True), minus(minus(rat(1), zero), one))
    assert_contains(r.query("count", state="A", count=0), times(rat(Q(1, 2)), expneg(3)))
    assert r.passive.calls == ([] if unplugged else [0])


@pytest.mark.parametrize("step_elapsed", [1, 3], ids=["same-time-control", "later-terminal"])
def test_time1_M08_count_query_advances_from_last_acquisition_to_step_terminal(times_rig, step_elapsed):
    r = times_rig(script((1, 1, E)), thinking=True).start()
    r.observe(0); before = r.update()
    selected = r.think()
    r.clock.set(r.origin+step_elapsed)
    r.enter_step(selection=selected.cid); r.finish_step(0, T)
    expression = r.update()
    assert before.terminal_ns == r.origin+1
    assert expression.terminal_ns == r.origin+step_elapsed
    assert r.actor.entered_ns == r.actor.returned_ns == [r.origin+step_elapsed]
    assert len(r.frame_reports()) == 1 and len(expression.observations) == 2
    likelihoods = [times(rat(k), expneg(rate))
                   for k, rate in zip((Q(1), Q(1, 2)), r.rates, strict=True)]
    p, mass = posterior(likelihoods); r.check(p, mass)
    # empty at t=1 says N(1)=0. The state-only step at tau provides no
    # count information; arrivals on (1,tau] must remain in the terminal law.
    zero_joint = total(times(rat(prior*k), expneg(rate*step_elapsed))
                       for prior, k, rate in zip(r.time_prior, (Q(1), Q(1, 2)), r.rates, strict=True))
    zero = rat(1) if step_elapsed == 1 else divide(zero_joint, mass)
    count0 = r.query("count", count=0)
    assert_contains(count0, zero)
    assert_contains(r.query("count", count=1, at_least=True), minus(rat(1), zero))
    if step_elapsed == 1: assert count0.exact == 1
    else: assert count0.upper < 1


def test_time1_M16_precision_refinement_limit_returns_incomplete_then_unbounded_succeeds(times_rig):
    r = times_rig(script((1, 1, E))).start(); r.observe(0); expression = r.update()
    quantity = fb.BeliefQuantity(kind="state", state="A")
    tolerance = Q(1, 2**240)
    # Isolate the precision-round cap: neither cells nor terms can exhaust.
    limited = RateBudget(tolerance=tolerance, max_cells=None, max_terms=None, max_refinements=1)
    with pytest.raises(fb.TimeBeliefError) as error:
        r.host.query_belief(belief=expression, quantity=quantity, budget=limited)
    assert error.value.kind == "incomplete" and error.value.reason
    assert r.expression().root == expression.root
    value = r.host.query_belief(belief=expression, quantity=quantity,
        budget=replace(limited, max_refinements=None))
    assert value.root == expression.root and value.quantity == quantity
    assert value.upper-value.lower <= tolerance
    assert_contains(value, divide(rat(1), plus(rat(1), expneg(1))))
    assert r.host.verify_belief_value(belief=expression, value=value)
    assert not any("model_falsified" in row.reasons for row in r.host.window.status().updates)


def test_time1_M17_two_valid_different_roots_are_not_the_same_belief(times_rig):
    r = times_rig(script((1, 1, E), (3, 3, E))).direct()
    r.observe(0); first = r.update()
    r.observe(1); second = r.update()
    # Both expressions are genuine saved adoptions with valid canonical data;
    # a forged-root guard must not mask the different-root equality branch.
    for expression, elapsed in ((first, 1), (second, 3)):
        p, mass = posterior([expneg(rate*elapsed) for rate in r.rates])
        assert_contains(r.query("state", expression=expression, state="A"), p)
        assert_contains(r.query("mass", expression=expression), mass)
        assert r.host.same_belief(left=expression, right=expression)
    assert first.root != second.root
    assert r.host.same_belief(left=first, right=second) is False
    assert r.host.same_belief(left=second, right=first) is False


def test_time1_review_R5_finite_method_cannot_authenticate_a_timed_result_in_query_or_U(times_rig):
    r, original = time_step_only_scene(times_rig)
    saved = time_fact_at(r, original.result)
    q = time_fact_at(r, saved.value["request"])
    assert q.value["desc"]["method"] == wire(c.TIMED_UPDATE_COMPUTE)
    assert isinstance(time_direct_update(r, q), u2.IssuedUpdate)
    assert r.query("state", state="A", expression=original).exact == Q(2, 3)

    altered_q = deepcopy(q.value)
    altered_q["desc"]["method"] = wire(c.FINITE_UPDATE_COMPUTE)
    restored_q = deepcopy(altered_q)
    restored_q["desc"]["method"] = q.value["desc"]["method"]
    assert restored_q == q.value  # No change to observations, reading or view.
    bad_request = belief1_clone(r, q, altered_q)
    changed = deepcopy(saved.value)
    changed["request"] = bad_request
    assert changed["result"] == saved.value["result"]
    assert changed["application_digest"] == saved.value["application_digest"]
    bad_result = belief1_clone(r, saved, changed)
    forged = replace(original, point=bad_result, result=bad_result)

    records = {p: r.read_stored(p)[2] for p in r.snapshot()}
    reader = BeliefSnapshotReader(records)
    for entrance in (u2.compute_timed_update, u2.compute_finite_update):
        try:
            outcome = entrance(bad_request, reader=reader, registry=r.registry, evidence=None)
        except u2.UpdateEntranceError as rejected:
            assert rejected.reason
        else:
            # A normal Rejected is also a refusal, not an issued belief.
            # The paper does not require both U entrances to throw exceptions.
            assert isinstance(outcome, u2.Rejected) and outcome.request == bad_request
            assert outcome.issues and all(issue.code for issue in outcome.issues)
    with pytest.raises(fb.TimeBeliefError) as rejected:
        r.query("count", count=0, expression=forged)
    assert rejected.value.kind in ("invalid", "unsupported", "unavailable") and rejected.value.reason

    # The valid saved request/result still works in the same enlarged ledger.
    assert r.read_stored(original.result)[2].body.content.as_json() == saved.value
    assert isinstance(time_direct_update(r, q), u2.IssuedUpdate)
    assert r.query("state", state="A", expression=original).exact == Q(2, 3)
