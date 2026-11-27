"""K41 v4. Test declarations, toy devices and readers of public results.

state_process uses the law's ordered states, run, origin and time_unit.
The generator is row-oriented (from, to), with rational pairs in JSON.
measurement belongs to the step's source_readings entry. The entry contract
specifies zero model duration. Wall-clock entered and finished may differ.
"""

from dataclasses import replace
from fractions import Fraction as Q

import pytest

from gate_f_facts_cases import diagonal, plain
from sui import fb
from sui.ids import RefKind
from sui.records import Payload, Prediction, Role
from test_fb_belief import BeliefSnapshotReader
from test_fb_clock_belief import ReleasedClockSource
from test_fb_cycle import E, contract, world_document
from test_fb_switch_belief import SwitchRig
from test_fb_time_belief import (
    assert_contains, budget, divide, expneg, logarithm, minus,
    plus, rat, script, times,
)


HALF = Q(1, 2)
START_A = (Q(1), Q(0))
FAIR = (HALF, HALF)
ONE_WAY = ((-1, 1), (0, 0))
ZERO = ((0, 0), (0, 0))
BOTH = ((-1, 1), (1, -1))
READ_B = (Q(0), Q(1))
RECORDED = "recorded_timing_inputs"
INDEPENDENT = "independent_timing_source"
ORIGIN = 1000
X = expneg(1)
ONE = rat(1)


def scaled(k, expr):
    return times(rat(k), expr)


def complement(expr):
    return minus(ONE, expr)


def entropy(p):
    if p in (rat(0), ONE):
        return rat(0)
    q = complement(p)
    return minus(rat(0), plus(times(p, logarithm(p)), times(q, logarithm(q))))


def call(name, args):
    return fb.MethodCall(contract=contract("sui.fb." + name), args=args)


def generator(matrix):
    def pair(x):
        if isinstance(x, (int, Q)) and not isinstance(x, bool):
            x = Q(x)
            return [x.numerator, x.denominator]
        return x
    return call("fixed_state_generator", {"matrix": [[pair(x) for x in row] for row in matrix]})


def at_entry(basis=RECORDED):
    return {"measurement": call("instantaneous_entry_observation", {}),
            "time_basis": call(basis, {}) if basis is not None else None}


def observation_document(prior, sensor, targets, states=("A", "B")):
    doc, _ = world_document()
    doc["states"] = [{"id": state, "target": target} for state, target in zip(states, targets, strict=True)]
    doc["targets"] = list(dict.fromkeys(targets))
    doc["initial"] = plain(prior)
    diagonals = {"t": sensor, "e": tuple(1-x for x in sensor), "done": (Q(1),)*len(states)}
    for kernel in doc["kernels"]:
        for outcome in kernel["outcomes"]:
            outcome["matrix"] = plain(diagonal(diagonals[outcome["id"]]))
    return doc


class MoodWorld(SwitchRig):
    def __init__(self, plan, *, process=ONE_WAY, rates=(0, 1), prior=START_A,
                 mood=False, clock=None, sensor=READ_B, targets=("A", "B"),
                 measurement=None, **kwargs):
        self.process = process
        self.clock_shape = clock
        self.sensor = tuple(map(Q, sensor))
        super().__init__(plan, base=tuple(map(Q, rates)), prior=tuple(map(Q, prior)),
                         factors=((Q(0), Q(1)),) if mood else (), **kwargs)
        self.targets = targets
        self.labels = ("A", "B")
        self.replace_model(observation_document(self.time_prior, self.sensor, targets))
        self.passive = ReleasedClockSource(self)
        decl = self.boot_input.declaration
        if decl.initial is not None:
            initial = decl.initial
            limits = budget(Q(1, 2048))
            self.boot_input = replace(self.boot_input, declaration=replace(decl,
                initial=replace(initial, value=replace(initial.value,
                    prepare_budget=limits, evaluate_budget=limits))))
        if clock is not None:
            self.part_names += ("clock",)
        if measurement is not None:
            self.set_reading(measurement)

    def law(self, *, rates=None, prior=None):
        parts = tuple(fb.SwitchPart(id="mood", kind="mood", multipliers=factor)
                      for factor in self.factors)
        if self.clock_shape is not None:
            part = fb.SwitchPart(id="clock", kind="clock", multipliers=(), clock=self.clock_shape)
            parts += (part,)
        family = {} if self.family is None else {"family": self.family, "a": self.a, "b": self.b}
        process = {} if self.process is None else {"state_process": generator(self.process)}
        return fb.PoissonLaw(run=self.clock.run, states=("A", "B"),
                             prior=self.time_prior if prior is None else prior,
                             rates=self.base if rates is None else rates, origin_ns=self.origin,
                             initial_count=self.initial_count, time_unit=self.unit, parts=parts,
                             state_role=self.state_role, **family, **process)

    def set_reading(self, measurement):
        decl = self.boot_input.declaration
        execution = decl.execution
        reading = replace(self.state_reading, **measurement)
        self.boot_input = replace(self.boot_input, declaration=replace(decl,
            execution=replace(execution, value=replace(execution.value, source_readings={"peek": reading}))))

    def add_law(self, law, *, alpha=HALF, sensor=None):
        # Permute the finite document and its matrices along with the law.
        states = law.states
        targets = tuple(self.targets[self.labels.index(s)] for s in states)
        response = self.sensor if sensor is None else sensor
        ordered = tuple(response[self.labels.index(s)] for s in states)
        doc = observation_document(law.prior, ordered, targets, states)
        record = self.record(Prediction(target="k41.added", about=(), basis=(),
            content=Payload.json({"document": doc}), contract=contract("sui.f.model_source")),
            RefKind.PREDICTION, Role.MODEL)
        model = self.ledger.append(record, ()).cid
        observation = replace(self.boot_input.declaration.observation_models[0].value, law=law)
        candidate = fb.BeliefCandidate(id="later", model=model, observation_model=observation,
                                       correspondence={"pairs": [[s, s] for s in states]})
        return self.host.add_candidate(boot=self.boot(), candidate=candidate, alpha=alpha)

    def resolved(self, declaration):
        reader = BeliefSnapshotReader({p: self.read_stored(p)[2] for p in self.snapshot()})
        return fb.resolve_belief_candidates(declaration, reader=reader, registry=self.registry)


@pytest.fixture
def worlds():
    made = []
    def make(plan=None, **kwargs):
        r = MoodWorld(plan if plan is not None else script((1, 1, E)), **kwargs)
        made.append(r)
        return r
    yield make
    for world in reversed(made):
        world.close()


def adopt(r, i=0):
    r.observe(i)
    return r.update()


def refined(query, reference, *, coarse=Q(1, 128), fine=Q(1, 8192)):
    """Use a tighter request than the width actually obtained, even after overshoot."""
    first = query(coarse)
    assert_contains(first, reference)
    width = first.upper - first.lower
    result = query(min(fine, width/8) if width else fine)
    assert_contains(result, reference)
    if width:
        assert result.upper - result.lower < width
    return result


def selection(r, selected, expression, info, probability=None, *, tolerance=Q(1, 4096)):
    odds = ("exp", info)
    p = probability if probability is not None else divide(odds, plus(ONE, odds))
    values = r.host.query_selection(selection=selected.cid, budget=budget(tolerance))
    assert values.belief_root == expression.root
    assert set(values.candidates) == {"peek", "wait"}
    for i, name in enumerate(values.candidates):
        expected = (info, minus(rat(0), info), p) if name == "peek" else (rat(0), rat(0), complement(p))
        for group, value in zip((values.information, values.G, values.probabilities), expected, strict=True):
            assert group[i].upper - group[i].lower <= tolerance
            assert_contains(group[i], value)
    return values
