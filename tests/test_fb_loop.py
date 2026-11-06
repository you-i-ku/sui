"""First loop, round 1: paper F-b :3497 (1)/(2), narrowed by Z41 :3736.

Read only the papers, public declarations and existing tests (including the
permitted 890b66c stage-3 fixture). No implementation is inspected or patched.
The test owns workers and launch scheduling; records come from the real host
and C/E stores. FStatus supplies no expectation. Watchdogs only bound incomplete
observations. Monitoring, input acquisition, budgets for U and fault cases are
outside this round; result acquisition remains part of the positive path.
"""

from dataclasses import replace
from decimal import Decimal, localcontext
from fractions import Fraction as F
import json
from queue import Empty, Queue
from threading import Event, Thread

import pytest

from sui import f, fb, fb_contracts as c, f_contracts as fc, f_facts as ff
from sui import f_update2 as u
from sui.ids import RefKind
from sui.records import Payload, Prediction, Role

from gate_f_facts_cases import finite_world, plain
from test_fb_skeleton import boot, contract, source
from test_fb_stage1 import RealRig, wire
from test_fb_stage2 import (
    CG, CLOCK, CLOCK_SOURCE, MATH, ORIGIN, ORDER, REQUESTS,
    PREPARE_BUDGET, EVALUATE_BUDGET, LaunchCut, Stage2Rig,
    Workers as Stage2Workers, closure, registry as stage2_registry,
)


ACQUIRED = contract("sui.f.content_acquired")
ROUTE = contract("sui.f.route_config")
FIRST = {"joint": [[4, 5], [1, 5]], "evidence_mass": [5, 32]}
SECOND = {"joint": [[8, 9], [1, 9]], "evidence_mass": [9, 128]}
DOUBLE = {"joint": [[16, 17], [1, 17]], "evidence_mass": [17, 512]}
# Literal CE1 declaration, F-b :2904-2917; not obtained from U's output.
CE1_ROWS = (
    ((0, 0, 0), F(1, 8), F(1, 64)), ((0, 0, 1), F(1, 8), F(3, 64)),
    ((0, 1, 0), F(1, 8), F(3, 64)), ((0, 1, 1), F(1, 8), F(9, 64)),
    ((1, 0, 0), F(1, 8), F(3, 64)), ((1, 0, 1), F(1, 8), F(9, 64)),
    ((1, 1, 0), F(1, 8), F(9, 64)), ((1, 1, 1), F(1, 8), F(27, 64)),
)


def delta_args():
    """K2 :3502: declare the law before either report exists."""
    return {
        "route": "route",
        "law": {
            "carrier_by_state": ["a", "b"],
            "channels": [{"id": "arrivals", "route_slots": ["route"],
                          "domain": {"start_ns": 0, "end_ns": 3,
                                     "closure": "(start,end]"}}],
            "rows": [{"marks": [{"channel": "arrivals", "time_ns": i + 1,
                                 "count": count} for i, count in enumerate(bits) if count],
                      "mass": [plain(a), plain(b)]} for bits, a, b in CE1_ROWS],
        },
        "claims": [{"meaning": plain(c.NO_ARRIVAL), "channel": "arrivals"}],
        "generation": {"scope": "whole_window"},
    }


def registry():
    """Combine public registries, retaining identities of shared capabilities."""
    declarations, implementations = {}, {}
    for reg in (u.fb_registry_v1(), stage2_registry()):
        for declaration in reg.declarations:
            key = declaration.kind, declaration.ref
            if key in declarations:
                assert declarations[key] == declaration
            declarations[key] = declaration
        for implementation in reg.implementations:
            key = implementation.kind, implementation.ref
            if key in implementations:
                assert implementations[key].identity == implementation.identity
            else:
                implementations[key] = implementation
    return f.make_f_registry(declarations=tuple(declarations.values()),
                             implementations=tuple(implementations.values()))


class Workers(Stage2Workers):
    def __init__(self, rig):
        super().__init__(rig)
        self.commands, self.release = Queue(), Event()
        self.updates, self.prepared_by_request, self.evaluated_by_request = {}, {}, {}

    def prepare(self, work, ctx):
        artifact = super().prepare(work, ctx)
        self.prepared_by_request[work.request] = artifact
        return artifact

    def evaluate(self, work, ctx):
        actual, reader = ctx.prepared(), ctx.reader()
        assert actual is not None and reader is not None
        args = work.desc.args
        saved = self.rig.one(c.PREPARED, cid=args.prepared)
        assert saved.value["request"] == args.evaluation_request
        assert self.rig.one(MATH, cid=saved.value["artifact"]).value == json.loads(actual.canonical_bytes)
        artifact = ff.evaluate_f_from_draw(actual, args.draw, reader=reader, budget=args.budget)
        self.evaluated_by_request[work.request] = artifact
        return artifact

    def normal(self, work, ctx):
        if work.desc.purpose == "measure_segment":
            assert isinstance(work.desc.args.requested, fb.Ongoing)
            self.post(ctx, fb.SegmentReport(segment=work.request, item_slot="started",
                item=fb.SegmentBoundary(kind="started", work=work.desc.work_id,
                    reading=self.rig.actual_reading(), reason="test actual entry", evidence=())))
            while not self.release.is_set():
                try:
                    action, done, errors = self.commands.get(timeout=.05)
                except Empty:
                    continue
                try:
                    action(work, ctx)
                except BaseException as error:
                    errors.append(error)
                finally:
                    done.set()
            return None, None
        if work.desc.purpose == "belief_update":
            reader = ctx.reader()
            assert reader is not None
            returned = u.compute_finite_update(work.request, reader=reader,
                registry=self.rig.registry, evidence=ctx.evidence())
            self.updates[work.request] = returned
            issued = returned if isinstance(returned, u.IssuedUpdate) else None
            return self.finished(work, fb.WorkOutputs(outputs=u.update_response(returned))), issued
        return super().normal(work, ctx)


class LoopRig(Stage2Rig):
    """Reuse stage-2 store observation/drive; initialize only the positive path."""

    def __init__(self, *, continuation=False):
        RealRig.__init__(self, connect=False)
        self.clock.set(0)
        self.registry, self.launcher = registry(), LaunchCut()
        self.workers, self.thread, self.executed = Workers(self), None, set()
        self.host = fb.FThreadHost(ledger=self.ledger, clock=self.clock,
            workers=self.workers, registry=self.registry, launcher=self.launcher)
        self.document, _ = finite_world("FA01")  # equal prior, quiet Q / perfect measurement M
        model = self.record(Prediction(target="model.11", about=(), basis=(),
            content=Payload.json({"document": self.document}),
            contract=contract("sui.f.model_source")), RefKind.PREDICTION, Role.MODEL)
        self.model_point = self.ledger.append(model, ()).cid
        event = boot(True)
        initial = replace(event.declaration.initial.value, model=self.model_point,
            generator=fb.MethodCall(contract=c.MODEL_OPERATIONS, args={}),
            method=fb.MethodCall(contract=contract("sui.f.finite_evaluation"), args={}),
            draw=fb.MethodCall(contract=contract("stage2.scripted_draw"), args={}),
            prepare_budget=PREPARE_BUDGET, evaluate_budget=EVALUATE_BUDGET,
            derivation=fb.SlottedMethod(slot="delta", method=fb.MethodCall(
                contract=c.SAVED_SEGMENT_UPDATE, args=delta_args())),
            continuation=fb.MethodCall(contract=c.REUSE_CANDIDATES, args={}) if continuation else None)
        self.boot_input = replace(event, declaration=replace(event.declaration,
            initial=replace(event.declaration.initial, value=initial),
            routes=tuple(replace(route, value=replace(route.value,
                config=replace(route.value.config,
                    sampling_contract=contract("sui.f.finite_measurement"),
                    clock_contract=contract("sui.f.simulated_clock"))))
                for route in event.declaration.routes)))
        self.host.post(fb.ClockDeclared(declaration=replace(source(), run=self.clock.run,
            measurement=contract("sui.f.simulated_clock"))))
        self.host.post(self.boot_input)
        self.drive(lambda: bool(self.requests("candidate_generation")))

    def facts(self, wanted):
        facts = super().facts(wanted)
        positions = {prepared.cid: i for i, prepared in enumerate(self.ledger.preparations)}
        return sorted(facts, key=lambda fact: positions[fact.cid])

    def requests(self, stage):
        wanted = c.WORK_REQUESTED if stage == "belief_update" else REQUESTS[stage]
        return [fact for fact in self.facts(wanted) if fact.value["desc"]["purpose"] == stage]

    def callback(self, stage):
        self.drive(lambda: bool(self.requests(stage)) and any(
            key == self.requests(stage)[-1].value["desc"]["work_id"]
            for key, _ in self.launcher.attempts))
        fact = self.requests(stage)[-1]
        callbacks = [body for key, body in self.launcher.attempts
                     if key == fact.value["desc"]["work_id"]]
        assert len(callbacks) == 1
        return fact, callbacks[0]

    def run_stage(self, stage):
        fact, callback = self.callback(stage)
        work_id = fact.value["desc"]["work_id"]
        assert work_id not in self.executed
        self.executed.add(work_id)
        callback()
        raw = c.DRAW_REPORT if stage == "selection_draw" else c.WORK_REPORT
        self.drive(lambda: any(item.value["work"] == work_id for item in self.facts(raw)))
        self.settle_steps()
        return next(work for work in self.workers.entries if work.desc.work_id == work_id)

    def start(self):
        _, callback = self.callback("measure_segment")
        self.thread = Thread(target=callback, daemon=True)
        self.thread.start()
        assert self.workers.entered.setdefault("measure_segment", Event()).wait(2)
        self.drive(lambda: any(item.value["item"]["kind"] == "started"
                               for item in self.facts(c.SEGMENT_REPORT)))
        for stage in ORDER:
            self.run_stage(stage)
        self.drive(lambda: len(self.facts(c.SELECTION)) == 1)

    def adopt(self, number):
        self.clock.set(number + 1)
        span = f.MeasurementInterval(clock=self.clock.run, start_ns=number - 1,
            end_ns=number + 1, closure="(start,end]")
        done, errors = Event(), []
        def emit(work, ctx):
            self.workers.post(ctx, fb.SegmentReport(segment=work.request,
                item_slot=f"claim-{number}", item=f.CoverageClaim(route_epoch="route-A",
                    interval=span, kind="no_arrival", contract=c.NO_ARRIVAL, evidence=())))
        self.workers.commands.put((emit, done, errors))
        assert done.wait(2), "incomplete observation: measurement worker did not answer"
        if errors:
            raise errors[0]
        self.drive(lambda: len(self.requests("belief_update")) == number)
        work = self.run_stage("belief_update")
        self.drive(lambda: len(self.facts(c.BELIEF_ADOPTED)) == number)
        return work, self.facts(c.BELIEF_ADOPTED)[-1]

    def close(self):
        self.workers.release.set()
        if self.thread is not None:
            self.thread.join(2)
            assert not self.thread.is_alive(), "test measurement worker did not stop"


@pytest.fixture
def make_rig():
    rigs = []
    def make(**kwargs):
        rig = LoopRig(**kwargs)
        rigs.append(rig)
        return rig
    yield make
    for rig in reversed(rigs):
        rig.close()


def assert_update(rig, work, adopted, expected, previous=None):
    """K7-K9 :3507-3509: compare actual Q*/R*/G/A* and the live issue."""
    desc = work.desc
    assert rig.one(c.WORK_REQUESTED, cid=work.request).value == {"desc": wire(desc)}
    assert desc.method == c.FINITE_UPDATE_COMPUTE and desc.output_contract == c.UPDATE_RESPONSE
    assert desc.args.model == rig.model_point and desc.args.prior == previous
    issued = rig.workers.updates[work.request]
    assert isinstance(issued, u.IssuedUpdate), issued
    assert issued.request == work.request and plain(issued.result) == expected
    result = rig.one(c.UPDATE_RESULT, cid=adopted.value["result"])
    assert result.value == {"request": issued.request, "result": expected,
        "application_digest": issued.application_digest,
        "numerical_view": wire(desc.numerical_view), "registry_key": issued.registry_key}
    assert issued.numerical_view == u.FixedViewValue(boundary=desc.numerical_view.boundary,
        reader_view_key=desc.numerical_view.reader_view_key,
        registry_key=desc.numerical_view.registry_key)
    assert adopted.value == {"origin": rig.one(ORIGIN).cid, "model": rig.model_point,
        "previous": previous, "request": work.request, "result": result.cid,
        "acquisition": adopted.value["acquisition"]}
    assert desc.reader == adopted.value["origin"]
    acquired = rig.one(ACQUIRED, cid=adopted.value["acquisition"])
    assert acquired.value["origin"] == desc.reader and result.cid in acquired.value["contents"]
    clock = rig.one(CLOCK, cid=acquired.value["clock"])
    assert clock.value["source"] == rig.one(CLOCK_SOURCE).cid
    assert clock.value["reading"]["run"] == str(rig.clock.run)
    assert any(e.origin == desc.reader and result.cid in e.contents
               and e.acquired_ns == clock.value["reading"]["time_ns"]
               for e in rig.workers.contexts["belief_update"].evidence().acquisitions)
    return result


def test_ce1_two_updates_from_public_boot_read_actual_records(make_rig):
    """F-b :2605,2904-2923,3497(1),3502-3509; both updates use the public host.

    Dropping the second report fails the second adoption/result == SECOND.
    Counting the overlap twice fails SECOND, explicitly distinct from DOUBLE.
    """
    assert [sum(row[i] for row in CE1_ROWS) for i in (1, 2)] == [1, 1]
    weights = [sum(row[i] for row in CE1_ROWS if row[0] == (0, 0, 0)) / 2 for i in (1, 2)]
    mass = sum(weights)
    assert {"joint": plain([w / mass for w in weights]), "evidence_mass": plain(mass)} == SECOND
    rig = make_rig()
    rig.start()
    w1, a1 = rig.adopt(1)
    r1 = assert_update(rig, w1, a1, FIRST)
    w2, a2 = rig.adopt(2)
    r2 = assert_update(rig, w2, a2, SECOND, a1.cid)
    assert r2.value["result"] not in (FIRST, DOUBLE)
    assert w2.desc.work_id != w1.desc.work_id and w2.desc.args.prior == a1.cid
    assert r1.cid in closure(rig, w2.desc.numerical_view.boundary)
    assert r1.value["application_digest"] != r2.value["application_digest"]
    segment = rig.one(c.SEGMENT_REQUESTED)
    assert rig.thread.is_alive(), "finite reports must not stop the ongoing measurement"
    law, reading = rig.one(c.FINITE_JOINT_COUNT_LAW), rig.one(c.OBSERVATION_PLAN_2)
    declared = delta_args()["law"]
    assert law.value == {"model": rig.model_point, "extends": None,
        "carrier_by_state": declared["carrier_by_state"],
        "channels": [{"id": "arrivals", "process": {
            "declaration": rig.one(c.BOOT_DECLARATION).cid, "slot": "sensing"},
            "route_configs": [rig.one(ROUTE).cid],
            "domain": {**declared["channels"][0]["domain"], "clock": str(rig.clock.run)}}],
        "rows": declared["rows"], "frame_relation": "independent_given_carrier"}
    assert reading.value == {"model": rig.model_point,
        "projection": {"contract": plain(c.FINITE_SEGMENT_PROJECTION), "args": {
            "frame": None, "claims": [{"meaning": plain(c.NO_ARRIVAL),
                "law": law.cid, "channel": "arrivals"}],
            "time_projection": {"contract": plain(c.SEGMENT_VALUE_ONLY), "args": {}}}},
        "generation": {"contract": plain(c.BOOTSTRAP_GENERATION), "args": {"scope": "whole_window"}}}
    for number, work in enumerate((w1, w2), 1):
        use, = work.desc.args.observations
        assert use.reading == reading.cid
        binding = rig.one(c.SEGMENT_BINDING, cid=use.binding)
        assert binding.value["segment"] == segment.cid
        raw = rig.one(c.SEGMENT_REPORT, cid=binding.value["report"])
        assert raw.value["segment"] == segment.cid and raw.value["item_slot"] == f"claim-{number}"
        claim = raw.value["item"]["value"]
        assert claim["kind"] == "no_arrival" and claim["contract"] == plain(c.NO_ARRIVAL)
        assert claim["interval"] == {"clock": str(rig.clock.run), "start_ns": number - 1,
                                     "end_ns": number + 1, "closure": "(start,end]"}


def decimal_real(value):
    """Evaluate only the public ExactReal grammar (f.py :160-169)."""
    if value.op == "rational":
        return Decimal(value.value.numerator) / Decimal(value.value.denominator)
    if value.op == "log":
        return decimal_real(value.arg).ln()
    if value.op == "exp":
        return decimal_real(value.arg).exp()
    if value.op == "neg":
        return -decimal_real(value.arg)
    if value.op == "add":
        return sum((decimal_real(arg) for arg in value.args), Decimal(0))
    if value.op == "mul":
        result = Decimal(1)
        for arg in value.args:
            result *= decimal_real(arg)
        return result
    if value.op == "div":
        return decimal_real(value.numerator) / decimal_real(value.denominator)
    raise AssertionError("unknown public ExactReal operator: " + value.op)


def assert_quantity(value, expected):
    assert value.status == "finite" and value.exact is not None
    assert abs(decimal_real(value.exact) - expected) < Decimal("1e-35")


@pytest.mark.parametrize("continuation", (False, True), ids=("none", "reuse_candidates"))
def test_continuation_uses_adopted_joint_in_math_input_and_information(make_rig, continuation):
    """F-b :3489,3497(2),3510,3512; F-a M-09/M-17.

    Reusing model.initial fails H(4/5), H(8/9) and the adopted R* input, even if the choice agrees.
    """
    rig = make_rig(continuation=continuation)
    rig.start()
    old_eq = rig.requests("evaluation_prepare")[0]
    old_prepared = rig.workers.prepared_by_request[old_eq.cid]
    assert isinstance(old_prepared.value, f.FProblem)
    old_result = next(iter(rig.workers.evaluated_by_request.values())).value
    assert isinstance(old_result, f.Selected)
    assert old_prepared.value.K.belief is None
    previous, evaluations = None, []
    for number, expected, probability in ((1, FIRST, F(4, 5)), (2, SECOND, F(8, 9))):
        work, adopted = rig.adopt(number)
        result = assert_update(rig, work, adopted, expected, previous)
        previous = adopted.cid
        rig.settle_steps()
        if not continuation:
            assert [eq.cid for eq in rig.requests("evaluation_prepare")] == [old_eq.cid]
            assert rig.workers.prepared_by_request[old_eq.cid] is old_prepared
            assert len(rig.requests("selection_draw")) == len(rig.requests("evaluation")) == 1
            continue
        rig.drive(lambda: len(rig.requests("evaluation_prepare")) == number + 1)
        eq = rig.requests("evaluation_prepare")[-1]
        desc = eq.value["desc"]
        assert {trigger["point"] for trigger in desc["trigger"]} == {adopted.cid}
        assert {adopted.cid, result.cid, adopted.value["acquisition"]} <= closure(
            rig, desc["numerical_view"]["boundary"])
        assert adopted.cid in closure(rig, desc["args"]["input"]["fixed_parents"])
        assert desc["args"]["input"]["model"] == rig.model_point
        assert desc["args"]["input"]["candidates"] == rig.one(CG).cid
        ep = rig.run_stage("evaluation_prepare")
        prepared = rig.workers.prepared_by_request[eq.cid]
        assert isinstance(prepared.value, f.FProblem), prepared.value
        assert ep.desc.method == c.EVALUATION_PREPARE and ep.desc.args.compiler == fc.PREPARE_FACTS
        assert prepared.value.K.belief == rig.read_stored(result.cid)[2].id
        saved_math = json.loads(prepared.canonical_bytes)
        assert saved_math["input"]["value"]["fixed_parents"] == desc["args"]["input"]["fixed_parents"]
        rig.run_stage("selection_draw")
        ee = rig.run_stage("evaluation")
        selected = rig.workers.evaluated_by_request[ee.request].value
        assert isinstance(selected, f.Selected), selected
        assert selected.root.problem_key == prepared.value.problem_key
        assert selected.root.K.belief == rig.read_stored(result.cid)[2].id
        assert selected.evaluation.candidates == ("Q", "M")
        rig.drive(lambda: len(rig.facts(c.SELECTION)) == number + 1)
        evaluations.append((selected.evaluation, probability))
    assert len(rig.facts(CG)) == 1
    if continuation:
        for stage in ("evaluation_prepare", "selection_draw", "evaluation"):
            descriptions = [request.value["desc"] for request in rig.requests(stage)]
            assert len({desc["work_id"] for desc in descriptions}) == 3
            assert len({desc["stage_slot"] for desc in descriptions}) == 3
    # Independent entropy oracle: CE1 posterior p, perfect M, no information from Q.
    with localcontext() as context:
        context.prec = 60
        assert_quantity(old_result.evaluation.information[1].additional, Decimal(2).ln())
        for evaluation, p in evaluations:
            probability = Decimal(p.numerator) / Decimal(p.denominator)
            entropy = -(probability * probability.ln() + (1 - probability) * (1 - probability).ln())
            assert abs(entropy - Decimal(2).ln()) > Decimal("0.1")
            assert_quantity(evaluation.information[0].additional, Decimal(0))
            assert_quantity(evaluation.information[1].additional, entropy)
            assert_quantity(evaluation.G[1], -entropy)
            assert_quantity(evaluation.q_star[1], entropy.exp() / (1 + entropy.exp()))


def test_continuation_preserves_adopted_state_order_in_asymmetric_information():
    """F-a :289,295,320-323; F-b CE1 :2917-2923, J6/K10/K12 :3489,3510,3512.

    Asymmetry: P(Y=1|a)=1/2, P(Y=1|b)=0 gives I_M(p)=h(p/2)-p*ln(2), p=P(a).
    Correct p=4/5: I=ln(5)-6/5*ln(2)-3/5*ln(3)=0.11849392256130018846, q_M=0.52958886776763468267.
    Reversed joint p=1/5: I=ln(5)+4/5*ln(2)-9/5*ln(3)=0.18645353727945917762, q_M=0.54647880959434444414.
    """
    from gate_f_facts_cases import diagonal, outcome

    class AsymmetricLoopRig(LoopRig):
        def record(self, body, *args, **kwargs):
            # Change only the test's primary model declaration, before Boot.
            # The host, workers and adopted values are left on the public path.
            if isinstance(body, Prediction) and body.contract == contract("sui.f.model_source"):
                document, _ = finite_world("FA01")
                measurement, = (kernel for kernel in document["kernels"] if kernel["id"] == "measure")
                measurement["outcomes"] = [
                    outcome("y0", diagonal((F(1, 2), F(1))), value=0),
                    outcome("y1", diagonal((F(1, 2), F(0))), value=1),
                ]
                self.document = document
                body = replace(body, content=Payload.json({"document": document}))
            return super().record(body, *args, **kwargs)

    rig = AsymmetricLoopRig(continuation=True)
    try:
        rig.start()
        work, adopted = rig.adopt(1)
        result = assert_update(rig, work, adopted, FIRST)
        rig.drive(lambda: len(rig.requests("evaluation_prepare")) == 2)
        eq = rig.requests("evaluation_prepare")[-1]
        assert {trigger["point"] for trigger in eq.value["desc"]["trigger"]} == {adopted.cid}
        assert eq.value["desc"]["args"]["input"]["model"] == rig.model_point
        rig.run_stage("evaluation_prepare")
        prepared = rig.workers.prepared_by_request[eq.cid]
        assert isinstance(prepared.value, f.FProblem), prepared.value
        assert prepared.value.K.belief == rig.read_stored(result.cid)[2].id
        rig.run_stage("selection_draw")
        ee = rig.run_stage("evaluation")
        selected = rig.workers.evaluated_by_request[ee.request].value
        assert isinstance(selected, f.Selected), selected
        assert selected.root.problem_key == prepared.value.problem_key
        assert selected.root.K.belief == rig.read_stored(result.cid)[2].id
        rig.drive(lambda: len(rig.facts(c.SELECTION)) == 2)
        evaluation = selected.evaluation
        assert evaluation.candidates == ("Q", "M")
        with localcontext() as context:
            context.prec = 60
            ln2, ln3, ln5 = Decimal(2).ln(), Decimal(3).ln(), Decimal(5).ln()
            # Hand-derived from the declared channel and CE1, never from U or FStatus.
            information = ln5 - Decimal(6) / 5 * ln2 - Decimal(3) / 5 * ln3
            reversed_information = ln5 + Decimal(4) / 5 * ln2 - Decimal(9) / 5 * ln3
            assert abs(information - reversed_information) > Decimal("0.06")
            assert_quantity(evaluation.information[0].additional, Decimal(0))
            assert_quantity(evaluation.information[1].additional, information)
            assert_quantity(evaluation.G[1], -information)
            assert_quantity(evaluation.q_star[1], information.exp() / (1 + information.exp()))
    finally:
        rig.close()
