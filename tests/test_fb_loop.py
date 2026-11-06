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


def cut_first_update_launch(rig, outcome):
    """Inject only Wu's first OS launch result; keep successful callbacks deferred."""
    normal_launch, attempts = rig.launcher.launch, []
    def launch(work_id, body):
        is_update = any(q.value["desc"]["work_id"] == work_id
                        for q in rig.requests("belief_update"))
        if is_update and (not attempts or work_id == attempts[0][0]):
            result = outcome if not attempts else "launched"
            attempts.append((work_id, body, result))
            if result == "raises":
                raise OSError("test: OS launch outcome is unavailable")
            if result != "launched":
                return result
        return normal_launch(work_id, body)
    rig.launcher.launch = launch
    return attempts


def post_loop_claim(rig, number):
    """Post a normal CE1 report from the still-running measurement worker."""
    rig.clock.set(number + 1)
    span = f.MeasurementInterval(clock=rig.clock.run, start_ns=number - 1,
        end_ns=number + 1, closure="(start,end]")
    done, errors, sent = Event(), [], []
    def emit(work, ctx):
        event = fb.SegmentReport(segment=work.request, item_slot=f"claim-{number}",
            item=f.CoverageClaim(route_epoch="route-A", interval=span,
                kind="no_arrival", contract=c.NO_ARRIVAL, evidence=()))
        rig.workers.post(ctx, event)
        sent.append(event)
    rig.workers.commands.put((emit, done, errors))
    assert done.wait(2), "incomplete observation: measurement worker did not answer"
    if errors:
        raise errors[0]
    rig.drive(lambda: any(raw.value == wire(sent[0]) for raw in rig.facts(c.SEGMENT_REPORT)))
    return next(raw for raw in rig.facts(c.SEGMENT_REPORT) if raw.value == wire(sent[0]))


def execution_for(ctx, work_id):
    return next(observation for observation in ctx.evidence().executions
                if observation.work_id == work_id)


def test_update_not_started_retries_once_and_continues_ce1(make_rig):
    """Row 7 x 1/2/3/5: v2 :17-24,37; F-b :329; FLauncher/FWorkContext docs.

    No retry fails adoption; a second admission fails enter()==False; double counting fails FIRST/SECOND.
    """
    rig = make_rig(continuation=True)
    rig.start()
    attempts = cut_first_update_launch(rig, "not_started")
    extra_admissions = []
    def finish_once(work, ctx):
        extra_admissions.append(ctx.enter())  # the normal worker already entered
        event, issued = rig.workers.normal(work, ctx)
        rig.workers.post(ctx, event, issued)
    rig.workers.overrides["belief_update"] = finish_once
    w1, a1 = rig.adopt(1)
    assert_update(rig, w1, a1, FIRST)
    assert [(work_id, result) for work_id, _body, result in attempts] == [
        (w1.desc.work_id, "not_started"), (w1.desc.work_id, "launched")]
    for stage in ORDER[1:]:
        rig.run_stage(stage)
    rig.drive(lambda: len(rig.facts(c.SELECTION)) == 2)
    w2, a2 = rig.adopt(2)
    assert_update(rig, w2, a2, SECOND, a1.cid)
    for stage in ORDER[1:]:
        rig.run_stage(stage)
    rig.drive(lambda: len(rig.facts(c.SELECTION)) == 3)
    assert extra_admissions == [False, False]
    assert len(rig.requests("belief_update")) == len(rig.facts(c.UPDATE_RESULT)) == 2
    assert len(rig.facts(c.BELIEF_ADOPTED)) == 2
    for work, launches in ((w1, ("not_started", "launched")), (w2, ("launched",))):
        assert [ok for key, ok in rig.workers.entry_attempts if key == work.desc.work_id] == [True]
        observed = execution_for(rig.workers.contexts["measure_segment"], work.desc.work_id)
        assert observed.launches == launches and observed.entered == 1 and observed.stopped


@pytest.mark.parametrize("outcome", ("unknown", "raises"))
def test_update_unknown_launch_does_not_retry_and_measurement_keeps_reporting(make_rig, outcome):
    """Row 7 x 4/5: v2 :20-21,37,40-44; F-b :329; FLauncher :651.

    Retrying unknown fails the launch count/evidence; blocking reception fails the later measurement report.
    """
    rig = make_rig()
    rig.start()
    attempts = cut_first_update_launch(rig, outcome)
    post_loop_claim(rig, 1)
    rig.drive(lambda: bool(attempts))
    request, = rig.requests("belief_update")
    work_id = request.value["desc"]["work_id"]
    measurement = rig.workers.contexts["measure_segment"]
    before = execution_for(measurement, work_id)
    assert before.launches == ("unknown",) and before.entered == 0 and not before.stopped
    # A concrete other worker executes another command and its Post is saved.
    later = post_loop_claim(rig, 2)
    assert later.value["segment"] == rig.one(c.SEGMENT_REQUESTED).cid
    assert later.value["item_slot"] == "claim-2" and rig.thread.is_alive()
    received = fb.Received(route_epoch="route-A", media_type="application/octet-stream",
                           data=b"row7-reception-after-unknown", claims={})
    rig.host.post(received)
    rig.drive(lambda: any(raw.value == wire(received) for raw in rig.facts(c.RECEIVED)))
    rig.settle_steps()
    assert [(key, result) for key, _body, result in attempts] == [(work_id, outcome)]
    after = execution_for(measurement, work_id)
    assert after.launches == ("unknown",) and after.entered == 0 and not after.stopped
    assert after.reports == ()
    assert not [work for work in rig.workers.entries if work.desc.work_id == work_id]
    assert not rig.facts(c.UPDATE_RESULT) and not rig.facts(c.BELIEF_ADOPTED)
    assert not [fact for fact in rig.facts(c.WORK_TERMINAL) if fact.value["request"] == request.cid]


@pytest.mark.parametrize("operation", ("read", "monitored"))
def test_unentered_update_port_cannot_record_evidence_but_entered_port_can(make_rig, operation):
    """Row 7 admission boundary: F-b J8 :3491, K11 :3511; FWorkContext :609.

    An unentered read/monitored recording evidence fails the unchanged-snapshot and RuntimeError checks.
    The denied port never entered; stopped former workers are outside this probe (CG-ROW7-STOPPED-PORT).
    """
    rig = make_rig()
    rig.start()
    attempts = cut_first_update_launch(rig, "not_started")
    span = f.MeasurementInterval(clock=rig.clock.run, start_ns=0, end_ns=2, closure="(start,end]")
    seen = {}
    normal_run = rig.workers.run
    def observe(ctx):
        before, rejected, returned = ctx.evidence(), False, None
        try:
            returned = ctx.read(rig.model_point) if operation == "read" else ctx.monitored(span)
        except RuntimeError:
            rejected = True
        return ctx, before, ctx.evidence(), rejected, returned
    def run(work, ctx):
        if work.desc.purpose == "belief_update" and seen.get("probing"):
            seen["denied_enter"] = ctx.enter()
            seen["denied"] = observe(ctx)
            return
        normal_run(work, ctx)
    def finish(work, ctx):
        seen["allowed"] = observe(ctx)  # the normal worker has actually entered
        seen["probing"] = True
        try:
            attempts[0][1]()  # canceled not_started launch, while the valid worker is still active
        finally:
            seen["probing"] = False
        event, issued = rig.workers.normal(work, ctx)
        rig.workers.post(ctx, event, issued)
    rig.workers.run = run
    rig.workers.overrides["belief_update"] = finish
    post_loop_claim(rig, 1)
    work = rig.run_stage("belief_update")
    allowed, before, after, rejected, returned = seen["allowed"]
    assert not rejected
    if operation == "read":
        assert isinstance(returned, bytes) and returned
        added = tuple(use for use in after.uses if use not in before.uses)
        assert len(after.uses) == len(before.uses) + 1 and len(added) == 1
        assert (added[0].work_id, added[0].point) == (work.desc.work_id, rig.model_point)
        assert after.intervals == before.intervals
    else:
        added = tuple(item for item in after.intervals if item not in before.intervals)
        assert len(after.intervals) == len(before.intervals) + 1 and len(added) == 1
        assert (added[0].work_id, added[0].interval) == (work.desc.work_id, span)
        assert after.uses == before.uses
    denied, before, after, rejected, _returned = seen["denied"]
    assert denied is not allowed and seen["denied_enter"] is False
    assert (rejected, after.uses, after.intervals) == (True, before.uses, before.intervals), (
        f"{operation}: RuntimeError={rejected}, uses_added={len(after.uses) - len(before.uses)}, "
        f"intervals_added={len(after.intervals) - len(before.intervals)}")
    rig.drive(lambda: len(rig.facts(c.BELIEF_ADOPTED)) == 1)
    assert_update(rig, work, rig.one(c.BELIEF_ADOPTED), FIRST)


def drive_loop_observation(rig, predicate):
    """A harness watchdog, not a product latency or computation-time limit (F8)."""
    rig.host.run_until(lambda _status: predicate(), timeout=30)
    if rig.workers.errors:
        raise rig.workers.errors[0]
    assert predicate(), "incomplete observation: public transition not witnessed before harness watchdog"


def post_ce1_interval(rig, *, slot, start, end):
    """A fresh raw report, with a finite interval inside the fixed CE1 law."""
    done, errors, sent = Event(), [], []
    span = f.MeasurementInterval(clock=rig.clock.run, start_ns=start, end_ns=end,
                                 closure="(start,end]")
    def emit(work, ctx):
        event = fb.SegmentReport(segment=work.request, item_slot=slot,
            item=f.CoverageClaim(route_epoch="route-A", interval=span,
                kind="no_arrival", contract=c.NO_ARRIVAL, evidence=()))
        rig.workers.post(ctx, event)
        sent.append(event)
    rig.workers.commands.put((emit, done, errors))
    assert done.wait(30), "incomplete observation: measurement worker did not answer"
    if errors:
        raise errors[0]
    rig.drive(lambda: any(raw.value == wire(sent[0]) for raw in rig.facts(c.SEGMENT_REPORT)))
    return next(raw for raw in rig.facts(c.SEGMENT_REPORT) if raw.value == wire(sent[0]))


def test_running_update_keeps_receiving_and_resumes_with_waiting_ce1_report(make_rig):
    """Row 4: v2 :17-24,34,40-42; F-b J9-d/K13 :3495,3513; CE1 :2917-2923.

    Blocking Post or the measurement worker while Wu is held prevents their saved reports before release.
    Premature R*/adoption/terminal fails the held snapshots; dropping E2 or double-applying E1 fails FIRST/SECOND.
    """
    rig = make_rig()
    rig.drive = lambda predicate: drive_loop_observation(rig, predicate)
    rig.start()
    holding, release, returned, received = Event(), Event(), Event(), Event()
    update_errors, receiving_errors, seen = [], [], {}
    update_thread = receiving_thread = None
    def hold_then_finish(work, ctx):
        seen["work"] = work
        holding.set()  # the normal worker has already taken the actual entry ticket
        release.wait()  # only test cleanup or the witnessed reception permits release
        event, issued = rig.workers.normal(work, ctx)
        rig.workers.post(ctx, event, issued)
    rig.workers.overrides["belief_update"] = hold_then_finish
    try:
        rig.clock.set(2)
        first = post_ce1_interval(rig, slot="row4-first", start=0, end=2)
        q1, callback = rig.callback("belief_update")
        def run_update():
            try:
                callback()
            except BaseException as error:
                update_errors.append(error)
            finally:
                returned.set()
        update_thread = Thread(target=run_update, daemon=True)
        update_thread.start()
        assert holding.wait(30), "incomplete observation: Wu did not enter its held body"
        assert update_thread.is_alive() and not returned.is_set()
        def receive_while_held():
            try:
                rig.clock.set(3)
                # This command is executed by the other, still-running measurement worker.
                seen["second"] = post_ce1_interval(rig, slot="row4-waiting", start=1, end=3)
                event = fb.Received(route_epoch="route-A", media_type="application/octet-stream",
                                    data=b"row4-receiving-while-update-is-held", claims={})
                rig.host.post(event)
                rig.drive(lambda: any(raw.value == wire(event) for raw in rig.facts(c.RECEIVED)))
                rig.settle_steps()
                work_id = q1.value["desc"]["work_id"]
                seen["held_execution"] = execution_for(rig.workers.contexts["measure_segment"], work_id)
                seen["held_requests"] = tuple(q.cid for q in rig.requests("belief_update"))
                seen["held_results"] = tuple(rig.facts(c.UPDATE_RESULT))
                seen["held_adoptions"] = tuple(rig.facts(c.BELIEF_ADOPTED))
                seen["held_terminals"] = tuple(t for t in rig.facts(c.WORK_TERMINAL)
                                               if t.value["request"] == q1.cid)
                seen["held_reports"] = tuple(t for t in rig.facts(c.WORK_REPORT)
                                             if t.value["work"] == work_id)
            except BaseException as error:
                receiving_errors.append(error)
            finally:
                received.set()
        # A bad host lock must not trap the test thread before its finally can release Wu.
        receiving_thread = Thread(target=receive_while_held, daemon=True)
        receiving_thread.start()
        assert received.wait(30), "incomplete observation: reception did not progress while Wu was held"
        if receiving_errors:
            raise receiving_errors[0]
        assert not release.is_set() and not returned.is_set() and update_thread.is_alive()
        observed = seen["held_execution"]
        assert observed.launches == ("launched",) and observed.entered == 1 and not observed.stopped
        assert seen["held_requests"] == (q1.cid,)  # K13: waiting is permitted; a new Q* is not yet due
        assert seen["held_results"] == seen["held_adoptions"] == ()
        assert seen["held_terminals"] == seen["held_reports"] == ()
        assert seen["second"].value["segment"] == first.value["segment"] == rig.one(c.SEGMENT_REQUESTED).cid
        assert rig.thread.is_alive()
        release.set()
        assert returned.wait(30), "incomplete observation: released Wu did not return"
        if update_errors:
            raise update_errors[0]
        rig.drive(lambda: len(rig.facts(c.BELIEF_ADOPTED)) >= 1)
        w1, a1 = seen["work"], rig.facts(c.BELIEF_ADOPTED)[0]
        assert w1.request == q1.cid
        assert_update(rig, w1, a1, FIRST)
        rig.drive(lambda: len(rig.requests("belief_update")) == 2)
        w2 = rig.run_stage("belief_update")
        rig.drive(lambda: len(rig.facts(c.BELIEF_ADOPTED)) == 2)
        a2 = rig.facts(c.BELIEF_ADOPTED)[1]
        assert_update(rig, w2, a2, SECOND, a1.cid)
        use, = w2.desc.args.observations
        assert rig.one(c.SEGMENT_BINDING, cid=use.binding).value["report"] == seen["second"].cid
        assert len(rig.facts(c.UPDATE_RESULT)) == len(rig.facts(c.BELIEF_ADOPTED)) == 2
        assert w1.desc.work_id != w2.desc.work_id
        for work in (w1, w2):
            assert [ok for key, ok in rig.workers.entry_attempts if key == work.desc.work_id] == [True]
            observed = execution_for(rig.workers.contexts["measure_segment"], work.desc.work_id)
            assert observed.launches == ("launched",) and observed.entered == 1 and observed.stopped
    finally:
        release.set()
        for thread in (update_thread, receiving_thread):
            if thread is not None:
                thread.join(30)
                assert not thread.is_alive(), "incomplete observation: test worker did not stop"


def test_eight_updates_preserve_one_adoption_chain_and_ce1_conjunction(make_rig):
    """Row 4 history: v2 :17-24,51; F-b :2605,2733-2741,2917-2923,3513.

    E1=(0,2], E2=(1,3] alternate in eight distinct reports: FIRST, then SECOND seven times.
    From E3 on, A entails E: Z(A and E)/Z(A)=1, so joint and cumulative mass stay (8/9,1/9;9/128).
    A wrong prior or a fork fails every previous/prior link and the final single-chain check.
    """
    rig = make_rig()
    rig.drive = lambda predicate: drive_loop_observation(rig, predicate)
    rig.start()
    n, previous, reports, adoptions, work_ids = 8, None, [], [], []
    for number in range(1, n + 1):
        rig.clock.set(number + 1)
        start, end = (0, 2) if number % 2 else (1, 3)
        report = post_ce1_interval(rig, slot=f"row4-round-{number}", start=start, end=end)
        reports.append(report)
        rig.drive(lambda: len(rig.requests("belief_update")) == number)
        work = rig.run_stage("belief_update")
        rig.drive(lambda: len(rig.facts(c.BELIEF_ADOPTED)) == number)
        adopted = rig.facts(c.BELIEF_ADOPTED)[-1]
        assert_update(rig, work, adopted, FIRST if number == 1 else SECOND, previous)
        use, = work.desc.args.observations
        assert rig.one(c.SEGMENT_BINDING, cid=use.binding).value["report"] == report.cid
        assert [ok for key, ok in rig.workers.entry_attempts if key == work.desc.work_id] == [True]
        observed = execution_for(rig.workers.contexts["measure_segment"], work.desc.work_id)
        assert observed.launches == ("launched",) and observed.entered == 1 and observed.stopped
        adoptions.append(adopted)
        work_ids.append(work.desc.work_id)
        previous = adopted.cid
    assert len(set(work_ids)) == n and len({report.cid for report in reports}) == n
    assert len(rig.requests("belief_update")) == len(rig.facts(c.UPDATE_RESULT)) == n
    assert rig.facts(c.BELIEF_ADOPTED) == adoptions
    assert [adopted.value["previous"] for adopted in adoptions] == [None] + [a.cid for a in adoptions[:-1]]
    assert {adopted.value["origin"] for adopted in adoptions} == {rig.one(ORIGIN).cid}
    assert {adopted.value["model"] for adopted in adoptions} == {rig.model_point}
    assert {report.value["segment"] for report in reports} == {rig.one(c.SEGMENT_REQUESTED).cid}
    assert len(rig.facts(c.FINITE_JOINT_COUNT_LAW)) == len(rig.facts(c.OBSERVATION_PLAN_2)) == 1
    assert rig.thread.is_alive()


def post_row5_claim(rig, *, slot, start, end):
    """Identify this delivery by its new saved Point, even when its payload repeats."""
    before = {raw.cid for raw in rig.facts(c.SEGMENT_REPORT)}
    done, errors, sent = Event(), [], []
    span = f.MeasurementInterval(clock=rig.clock.run, start_ns=start, end_ns=end,
                                 closure="(start,end]")
    def emit(work, ctx):
        event = fb.SegmentReport(segment=work.request, item_slot=slot,
            item=f.CoverageClaim(route_epoch="route-A", interval=span,
                kind="no_arrival", contract=c.NO_ARRIVAL, evidence=()))
        rig.workers.post(ctx, event)
        sent.append(event)
    rig.workers.commands.put((emit, done, errors))
    assert done.wait(30), "incomplete observation: measurement worker did not post the delivery"
    if errors:
        raise errors[0]
    rig.drive(lambda: any(raw.cid not in before and raw.value == wire(sent[0])
                          for raw in rig.facts(c.SEGMENT_REPORT)))
    return next(raw for raw in rig.facts(c.SEGMENT_REPORT)
                if raw.cid not in before and raw.value == wire(sent[0]))


def row5_report_for_work(rig, work):
    use, = work.desc.args.observations
    binding = rig.one(c.SEGMENT_BINDING, cid=use.binding)
    return rig.one(c.SEGMENT_REPORT, cid=binding.value["report"])


def row5_receive_behind_pending_update(rig, *, completed, token):
    rig.drive(lambda: len(rig.requests("belief_update")) > completed)
    pending = rig.requests("belief_update")[-1]
    work_id = pending.value["desc"]["work_id"]
    assert not [work for work in rig.workers.entries if work.desc.work_id == work_id]
    event = fb.Received(route_epoch="route-A", media_type="application/octet-stream",
                        data=token, claims={})
    rig.host.post(event)
    rig.drive(lambda: any(raw.value == wire(event) for raw in rig.facts(c.RECEIVED)))
    assert len(rig.facts(c.BELIEF_ADOPTED)) == completed


def test_row5_two_waiting_reports_are_each_used_once_in_one_adoption_chain(make_rig):
    """Row 5: v2 :17-24,35; F-b :2605,2733-2741,2904-2923,3484,3509,3513.

    Dropping a pending report or using one twice fails exact report coverage; parallel same-prior Q*s fail the chain.
    No queue-order oracle is declared in J1/K2/K13 (CG-ROW5-PENDING-ORDER); neither FIFO nor CID order is asserted.
    """
    rig = make_rig()
    rig.drive = lambda predicate: drive_loop_observation(rig, predicate)
    rig.start()
    rig.clock.set(3)
    first = post_row5_claim(rig, slot="row5-first", start=0, end=1)
    rig.drive(lambda: len(rig.requests("belief_update")) == 1)
    # The first Wu's launcher defers its body. Both following reports wait together.
    second = post_row5_claim(rig, slot="row5-waiting-two", start=0, end=2)
    third = post_row5_claim(rig, slot="row5-waiting-three", start=1, end=3)
    received = fb.Received(route_epoch="route-A", media_type="application/octet-stream",
                           data=b"row5-post-behind-two-waiting-reports", claims={})
    rig.host.post(received)
    rig.drive(lambda: any(raw.value == wire(received) for raw in rig.facts(c.RECEIVED)))
    rig.settle_steps()
    assert len(rig.requests("belief_update")) == 1
    assert not [work for work in rig.workers.entries if work.desc.purpose == "belief_update"]
    assert not rig.facts(c.UPDATE_RESULT) and not rig.facts(c.BELIEF_ADOPTED)
    work = rig.run_stage("belief_update")
    rig.drive(lambda: len(rig.facts(c.BELIEF_ADOPTED)) == 1)
    adopted = rig.facts(c.BELIEF_ADOPTED)[0]
    # N((0,1])=0: weights (1/4,1/8), mass 3/8, joint (2/3,1/3).
    one_point = {"joint": [[2, 3], [1, 3]], "evidence_mass": [3, 8]}
    assert row5_report_for_work(rig, work).cid == first.cid
    assert_update(rig, work, adopted, one_point)
    previous, used, adoptions = adopted.cid, set(), [adopted]
    for number in (2, 3):
        rig.drive(lambda: len(rig.requests("belief_update")) == number)
        work = rig.run_stage("belief_update")
        report = row5_report_for_work(rig, work)
        assert report.cid in {second.cid, third.cid} and report.cid not in used
        used.add(report.cid)
        # With x1=0 already: E1 alone gives FIRST; any inclusion of E2 covers x1,x2,x3.
        expected = FIRST if used == {second.cid} else SECOND
        rig.drive(lambda: len(rig.facts(c.BELIEF_ADOPTED)) == number)
        adopted = rig.facts(c.BELIEF_ADOPTED)[-1]
        assert_update(rig, work, adopted, expected, previous)
        previous = adopted.cid
        adoptions.append(adopted)
    assert used == {second.cid, third.cid}
    assert len(rig.requests("belief_update")) == len(rig.facts(c.UPDATE_RESULT)) == 3
    assert rig.facts(c.BELIEF_ADOPTED) == adoptions
    assert [a.value["previous"] for a in adoptions] == [None, adoptions[0].cid, adoptions[1].cid]
    assert {raw.cid for raw in rig.facts(c.SEGMENT_REPORT)} >= {first.cid, second.cid, third.cid}


@pytest.mark.parametrize("same_claim", (True, False), ids=("redelivery", "distinct_slot"))
def test_row5_repeated_claim_keeps_every_raw_delivery_without_recounting(make_rig, same_claim):
    """ClaimKey=(segment,item_slot), F-b :2768-2778,3484; CE1 :2917-2923.

    Counting a repeated Claim twice fails FIRST/SECOND; dropping its raw delivery fails the distinct-Point check.
    A new slot is a distinct report, but its identical predicate is entailed and adds likelihood 1 (:2741,2770).
    """
    rig = make_rig()
    rig.drive = lambda predicate: drive_loop_observation(rig, predicate)
    rig.start()
    rig.clock.set(2)
    first = post_row5_claim(rig, slot="row5-original", start=0, end=2)
    w1 = rig.run_stage("belief_update")
    rig.drive(lambda: len(rig.facts(c.BELIEF_ADOPTED)) == 1)
    a1 = rig.facts(c.BELIEF_ADOPTED)[0]
    assert row5_report_for_work(rig, w1).cid == first.cid
    assert_update(rig, w1, a1, FIRST)
    rig.clock.set(3)
    repeat = post_row5_claim(rig, slot="row5-original" if same_claim else "row5-distinct",
                            start=0, end=2)
    assert repeat.cid != first.cid
    first_key = first.value["segment"], first.value["item_slot"]
    repeat_key = repeat.value["segment"], repeat.value["item_slot"]
    assert (repeat_key == first_key) is same_claim
    assert (repeat.value == first.value) is same_claim
    rig.clock.set(4)
    later = post_row5_claim(rig, slot="row5-new-information", start=1, end=3)
    row5_receive_behind_pending_update(rig, completed=1, token=b"row5-post-behind-repeated-claim")
    # J1 may coalesce redelivery: its extra Q*/adoption count is not an oracle.
    # A different slot and the later interval must each be used, even if either is a numerical no-op.
    required = {later.cid} if same_claim else {repeat.cid, later.cid}
    used, previous, completed = set(), a1.cid, {w1.request}
    for number in (2, 3):
        if number == 2 or not required <= used:
            rig.drive(lambda: len(rig.requests("belief_update")) >= number)
        else:
            rig.settle_steps()
            if len(rig.requests("belief_update")) < number:
                break
        work = rig.run_stage("belief_update")
        assert work.request not in completed
        completed.add(work.request)
        report = row5_report_for_work(rig, work)
        permitted = {first.cid, repeat.cid, later.cid} if same_claim else {repeat.cid, later.cid}
        assert report.cid in permitted and report.cid not in used
        used.add(report.cid)
        rig.drive(lambda: len(rig.facts(c.BELIEF_ADOPTED)) == number)
        adopted = rig.facts(c.BELIEF_ADOPTED)[-1]
        assert_update(rig, work, adopted, SECOND if later.cid in used else FIRST, previous)
        previous = adopted.cid
    assert required <= used
    assert {raw.cid for raw in rig.facts(c.SEGMENT_REPORT)} >= {first.cid, repeat.cid, later.cid}
    assert len({first.cid, repeat.cid, later.cid}) == 3
    assert len(rig.requests("belief_update")) == len(rig.facts(c.BELIEF_ADOPTED)) == len(completed)
    assert 2 <= len(completed) <= 3
    assert rig.one(c.UPDATE_RESULT, cid=rig.facts(c.BELIEF_ADOPTED)[-1].value["result"]).value["result"] == SECOND


def test_row5_later_interval_arriving_first_has_correct_intermediate_and_final_belief(make_rig):
    """F-b CE1 :2904-2923 and conjunction :2733-2741; row 5 v2 :35.

    Reversed arrival with wrong intermediate or final weights fails FIRST then SECOND, irrespective of interval time order.
    E2 alone has Z=(1/4,1/16), weights (1/8,1/32); E2 and E1 have weights (1/16,1/128).
    """
    rig = make_rig()
    rig.drive = lambda predicate: drive_loop_observation(rig, predicate)
    rig.start()
    previous = None
    for number, (start, end, expected) in enumerate(((1, 3, FIRST), (0, 2, SECOND)), 1):
        rig.clock.set(number + 2)
        report = post_row5_claim(rig, slot=f"row5-reversed-{number}", start=start, end=end)
        if number == 1:
            row5_receive_behind_pending_update(rig, completed=0, token=b"row5-post-behind-reversed-report")
        work = rig.run_stage("belief_update")
        assert row5_report_for_work(rig, work).cid == report.cid
        rig.drive(lambda: len(rig.facts(c.BELIEF_ADOPTED)) == number)
        adopted = rig.facts(c.BELIEF_ADOPTED)[-1]
        assert_update(rig, work, adopted, expected, previous)
        previous = adopted.cid
    assert len(rig.requests("belief_update")) == len(rig.facts(c.BELIEF_ADOPTED)) == 2


def test_row5_delayed_reports_keep_their_interval_evidence_and_are_adopted(make_rig):
    """F-b :2605,2733-2741,2917-2923,3484; row 5 v2 :35.

    Discarding old reports fails the saved-Point/adoption checks; using receipt age as likelihood fails FIRST/SECOND.
    """
    rig = make_rig()
    rig.drive = lambda predicate: drive_loop_observation(rig, predicate)
    rig.start()
    previous = None
    for number, (start, end, expected) in enumerate(((0, 2, FIRST), (1, 3, SECOND)), 1):
        received_ns = 10**12 + number
        rig.clock.set(received_ns)
        report = post_row5_claim(rig, slot=f"row5-delayed-{number}", start=start, end=end)
        assert report.received_ns == received_ns and received_ns - end > 10**11
        assert report.value["item"]["value"]["interval"] == {
            "clock": str(rig.clock.run), "start_ns": start, "end_ns": end, "closure": "(start,end]"}
        if number == 1:
            row5_receive_behind_pending_update(rig, completed=0, token=b"row5-post-behind-delayed-report")
        work = rig.run_stage("belief_update")
        assert row5_report_for_work(rig, work).cid == report.cid
        rig.drive(lambda: len(rig.facts(c.BELIEF_ADOPTED)) == number)
        adopted = rig.facts(c.BELIEF_ADOPTED)[-1]
        assert_update(rig, work, adopted, expected, previous)
        previous = adopted.cid
    assert len(rig.facts(c.BELIEF_ADOPTED)) == 2 and rig.thread.is_alive()


def test_row5_pending_order_follows_received_time_and_envelope_not_report_sort_keys(make_rig):
    """K14 F-b :3514; K13 :3513; CE1/conjunction :2733-2741,2904-2923.

    CID sorting fails the source sequence: the fixture rejects both monotone CID orders before any adoption.
    Reversing reception fails the source sequence of at least three distinct waiting reports.
    Sorting interval starts fails the source sequence: reception begins with starts 2,0,1.
    Sorting item_slot names also fails: reception begins with names z,a,m.
    """
    rig = make_rig()
    rig.drive = lambda predicate: drive_loop_observation(rig, predicate)
    rig.start()
    rig.clock.set(3)  # equal r throughout: the public envelope observation must break ties
    first = post_row5_claim(rig, slot="row5-k14-blocker", start=0, end=1)
    rig.drive(lambda: len(rig.requests("belief_update")) == 1)
    # Q* for the blocker exists, but its worker has not entered. Three others wait without Q*s.
    pending = [
        post_row5_claim(rig, slot="row5-k14-z", start=2, end=3),
        post_row5_claim(rig, slot="row5-k14-a", start=0, end=2),
        post_row5_claim(rig, slot="row5-k14-m", start=1, end=2),
    ]
    # Actual CIDs include saved IDs/salts. Inspect them rather than assuming a useful hash order.
    for extra in range(16):
        posted_points = [report.cid for report in pending]
        if posted_points not in (sorted(posted_points), sorted(posted_points, reverse=True)):
            break
        pending.append(post_row5_claim(rig, slot=f"row5-k14-extra-{extra}", start=1, end=2))
    posted_points = [report.cid for report in pending]
    assert posted_points not in (sorted(posted_points), sorted(posted_points, reverse=True)), (
        "incomplete fixture: CID order did not discriminate reception")
    measurement = next(work for work in rig.workers.entries if work.desc.purpose == "measure_segment")
    ctx = rig.workers.contexts["measure_segment"]
    rig.drive(lambda: set(posted_points) <= {
        report.point for report in execution_for(ctx, measurement.desc.work_id).reports})
    witnesses = [report for report in execution_for(ctx, measurement.desc.work_id).reports
                 if report.point in set(posted_points)]
    assert len(witnesses) == len(pending)
    assert {report.received_ns for report in witnesses} == {3}
    assert len({report.envelope for report in witnesses}) == len(pending)
    received = sorted(witnesses, key=lambda report: (report.received_ns, report.envelope))
    received_points = [report.point for report in received]
    assert received_points == posted_points  # cross-check posting against the host's independent EH
    by_point = {report.cid: report for report in pending}
    assert all(by_point[report.point].received_ns == report.received_ns for report in received)
    assert received_points != sorted(posted_points)
    assert received_points != list(reversed(received_points))
    assert received_points != [report.cid for report in sorted(pending,
        key=lambda report: report.value["item"]["value"]["interval"]["start_ns"])]
    assert received_points != [report.cid for report in sorted(pending,
        key=lambda report: report.value["item_slot"])]
    rig.settle_steps()
    assert len(rig.requests("belief_update")) == 1
    assert not [work for work in rig.workers.entries if work.desc.purpose == "belief_update"]
    assert not rig.facts(c.BELIEF_ADOPTED)
    first_work = rig.run_stage("belief_update")
    rig.drive(lambda: len(rig.facts(c.BELIEF_ADOPTED)) == 1)
    first_adopted = rig.facts(c.BELIEF_ADOPTED)[0]
    one_point = {"joint": [[2, 3], [1, 3]], "evidence_mass": [3, 8]}
    assert row5_report_for_work(rig, first_work).cid == first.cid
    assert_update(rig, first_work, first_adopted, one_point)
    previous, actual_points, adoptions = first_adopted.cid, [], [first_adopted]
    for position, expected_point in enumerate(received_points):
        number = position + 2
        rig.drive(lambda: len(rig.requests("belief_update")) == number)
        work = rig.run_stage("belief_update")
        actual_points.append(row5_report_for_work(rig, work).cid)
        assert actual_points == received_points[:position + 1], (
            "K14 reception order", received_points, "actual sources", actual_points)
        assert actual_points[-1] == expected_point
        rig.drive(lambda: len(rig.facts(c.BELIEF_ADOPTED)) == number)
        adopted = rig.facts(c.BELIEF_ADOPTED)[-1]
        # x1=0, then x3=0 -> two zeros (FIRST); adding x2=0 -> SECOND; the rest is entailed.
        assert_update(rig, work, adopted, FIRST if position == 0 else SECOND, previous)
        previous = adopted.cid
        adoptions.append(adopted)
    assert actual_points == received_points
    assert len(rig.requests("belief_update")) == len(rig.facts(c.UPDATE_RESULT)) == len(pending) + 1
    assert rig.facts(c.BELIEF_ADOPTED) == adoptions
    assert [a.value["previous"] for a in adoptions] == [None] + [a.cid for a in adoptions[:-1]]


ROW3_ONE_POINT = {"joint": [[2, 3], [1, 3]], "evidence_mass": [3, 8]}


def prepare_row3_rig(make_rig, with_prior):
    rig = make_rig()
    rig.start()
    head = None
    if with_prior:
        rig.clock.set(1)
        report = post_row5_claim(rig, slot="row3-seed", start=0, end=1)
        work = rig.run_stage("belief_update")
        rig.drive(lambda: len(rig.facts(c.BELIEF_ADOPTED)) == 1)
        head = rig.one(c.BELIEF_ADOPTED)
        assert row5_report_for_work(rig, work).cid == report.cid
        assert_update(rig, work, head, ROW3_ONE_POINT)
    return rig, head


def stop_row3_update(rig, head, mode, *, retain_issue=False):
    """A real entered FWorkers body; only the test's worker and witnesses are replaced."""
    normal_run = rig.workers.run
    seen = {"raised": False, "error": MemoryError("row3 simulated worker exhaustion")}
    def run(work, ctx):
        if work.desc.purpose != "belief_update":
            return normal_run(work, ctx)
        entered = ctx.enter()
        rig.workers.entry_attempts.append((work.desc.work_id, entered))
        if not entered:
            return
        rig.workers.entries.append(work)
        rig.workers.contexts["belief_update"] = ctx
        seen.update(work=work, ctx=ctx, reading=rig.actual_reading())
        try:
            if retain_issue:
                reader = ctx.reader()
                assert reader is not None
                issued = u.compute_finite_update(work.request, reader=reader,
                    registry=rig.registry, evidence=ctx.evidence())
                assert isinstance(issued, u.IssuedUpdate), issued
                seen["issued"] = issued
                rig.workers.updates[work.request] = issued
            if mode == "failure":
                try:
                    raise ValueError("row3 unexpected calculation value")
                except ValueError as error:
                    failure = fb.FailureInfo(failure_kind="row3.value_error",
                        content={"message": str(error)}, readings=(seen["reading"],), basis=())
                    seen["failure"] = failure
                    event = rig.workers.finished(work, fb.WorkFailure(failure=failure))
                    rig.workers.post(ctx, event)
            elif mode == "exception":
                seen["raised"] = True
                raise seen["error"]
            else:
                assert mode == "return"
                # Returning is an actual stop, but is not a WorkFinished report.
        finally:
            rig.workers.stops.append(work.desc.work_id)
    rig.workers.run = run
    try:
        rig.clock.set(3)
        report = post_row5_claim(rig, slot="row3-stopped",
            start=1 if head is not None else 0, end=3 if head is not None else 2)
        request, callback = rig.callback("belief_update")
        try:
            callback()
        except BaseException:
            # OS wrappers may propagate or contain the injected worker exception.
            # Its propagation is not the oracle; the host's independent EW is.
            if not seen["raised"]:
                raise
    finally:
        rig.workers.run = normal_run
    work = seen["work"]
    assert work.request == request.cid
    assert work.desc.args.prior == (head.cid if head is not None else None)
    assert row5_report_for_work(rig, work).cid == report.cid
    rig.drive(lambda: execution_for(rig.workers.contexts["measure_segment"], work.desc.work_id).stopped)
    rig.settle_steps()
    return report, seen


def assert_row3_stopped_without_adoption(rig, report, seen):
    work = seen["work"]
    assert not [r for r in rig.facts(c.UPDATE_RESULT) if r.value["request"] == work.request]
    assert not [a for a in rig.facts(c.BELIEF_ADOPTED) if a.value["request"] == work.request]
    assert rig.one(c.SEGMENT_REPORT, cid=report.cid).value == report.value
    assert [ok for key, ok in rig.workers.entry_attempts if key == work.desc.work_id] == [True]
    observed = execution_for(rig.workers.contexts["measure_segment"], work.desc.work_id)
    assert observed.launches == ("launched",) and observed.entered == 1 and observed.stopped
    return observed


def continue_row3_with_new_report(rig, head, stopped_report, seen):
    rig.clock.set(4)
    report = post_row5_claim(rig, slot="row3-after-stop", start=2, end=3)
    received = fb.Received(route_epoch="route-A", media_type="application/octet-stream",
                           data=b"row3-reception-after-worker-stop", claims={})
    rig.host.post(received)
    rig.drive(lambda: any(raw.value == wire(received) for raw in rig.facts(c.RECEIVED)))
    assert rig.thread.is_alive()
    assert rig.one(c.SEGMENT_REPORT, cid=stopped_report.cid).value == stopped_report.value
    number = 3 if head is not None else 2
    rig.drive(lambda: len(rig.requests("belief_update")) == number)
    work = rig.run_stage("belief_update")
    assert work.request != seen["work"].request
    assert row5_report_for_work(rig, work).cid == report.cid
    rig.drive(lambda: len(rig.facts(c.BELIEF_ADOPTED)) == (2 if head is not None else 1))
    adopted = rig.facts(c.BELIEF_ADOPTED)[-1]
    assert_update(rig, work, adopted, FIRST if head is not None else ROW3_ONE_POINT,
                  head.cid if head is not None else None)
    assert_row3_stopped_without_adoption(rig, stopped_report, seen)
    return adopted


@pytest.mark.parametrize("with_prior", (False, True), ids=("initial", "after_adoption"))
def test_row3_reported_failure_keeps_failure_terminal_and_resumes_from_current_head(make_rig, with_prior):
    """Row 3 v2 :17-24,33; F-b C10/6-2 :3319,3328-3334; J9-c/K9/K13/K15 :3494,3509,3513,3515.

    Waiting forever on the failed Wu fails the next-Q* observation; inventing a successful R*/adoption fails its absence.
    Wrong prior or including the failed report fails ONE_POINT (no prior) / FIRST (prior x1=0), not SECOND.
    Stopping reception fails the saved later Claim and Received before the next-Q* check.
    """
    rig, head = prepare_row3_rig(make_rig, with_prior)
    report, seen = stop_row3_update(rig, head, "failure")
    request = seen["work"].request
    rig.drive(lambda: any(t.value["request"] == request for t in rig.facts(c.WORK_TERMINAL)))
    terminal, = (t for t in rig.facts(c.WORK_TERMINAL) if t.value["request"] == request)
    raw = rig.one(c.WORK_REPORT, cid=terminal.value["first_receipt"])
    assert terminal.value["terminal_kind"] == "failure" and terminal.value["returned"] is None
    assert terminal.value["basis"]["failure"] == wire(seen["failure"])
    assert raw.value["outcome"] == {"kind": "failure", "value": wire(seen["failure"])}
    observed = assert_row3_stopped_without_adoption(rig, report, seen)
    assert len(observed.reports) == 1 and observed.reports[0].point == raw.cid
    continue_row3_with_new_report(rig, head, report, seen)
    assert rig.one(c.WORK_TERMINAL, cid=terminal.cid).value == terminal.value


@pytest.mark.parametrize("with_prior", (False, True), ids=("initial", "after_adoption"))
@pytest.mark.parametrize("mode", ("return", "exception"), ids=("no_report_return", "no_report_exception"))
def test_row3_unreported_stop_unblocks_next_update_without_inventing_terminal(make_rig, with_prior, mode):
    """K15(1)-(3) F-b :3515, J9-c :3494; CE1 :2904-2923 and conditioning :2733-2741.

    Waiting on the stopped Wu fails the next-Q* observation after both later Posts were saved.
    Inventing T/R*/adoption or relaunching fails the missing-record and EW single-entry checks.
    Wrong head or folding in the stopped Claim fails ONE_POINT / FIRST instead of the forbidden SECOND.
    Stopping reception fails the saved later Claim and Received before the next-Q* check.
    """
    rig, head = prepare_row3_rig(make_rig, with_prior)
    report, seen = stop_row3_update(rig, head, mode)
    observed = assert_row3_stopped_without_adoption(rig, report, seen)
    assert observed.reports == ()
    assert not [t for t in rig.facts(c.WORK_TERMINAL) if t.value["request"] == seen["work"].request]
    assert not [r for r in rig.facts(c.WORK_REPORT) if r.value["work"] == seen["work"].desc.work_id]
    continue_row3_with_new_report(rig, head, report, seen)
    assert not [t for t in rig.facts(c.WORK_TERMINAL) if t.value["request"] == seen["work"].request]


@pytest.mark.parametrize("with_prior", (False, True), ids=("initial", "after_adoption"))
@pytest.mark.parametrize("advance_head", (False, True), ids=("head_unchanged", "head_advanced"))
def test_row3_late_terminal_from_stopped_port_adopts_or_is_stale_by_current_head(make_rig, with_prior, advance_head):
    """K15(4) F-b :3515 and K9/6-2 :3509,3330-3332; use only a real retained issue and ctx.post.

    Dropping the late terminal fails T/R*/A* or Stale; overwriting an advanced head fails the unchanged adoption chain.
    Relaunching the stopped body fails EW launches/entered; no stopped-port read/monitored contract is assumed.
    """
    rig, head = prepare_row3_rig(make_rig, with_prior)
    report, seen = stop_row3_update(rig, head, "return", retain_issue=True)
    observed = assert_row3_stopped_without_adoption(rig, report, seen)
    request, work_id = seen["work"].request, seen["work"].desc.work_id
    assert observed.reports == ()
    assert not [t for t in rig.facts(c.WORK_TERMINAL) if t.value["request"] == request]
    newer = continue_row3_with_new_report(rig, head, report, seen) if advance_head else None
    before = tuple(rig.facts(c.BELIEF_ADOPTED))
    rig.clock.set(5)
    event = fb.WorkFinished(work=work_id, started=seen["reading"], finished=seen["reading"],
        outcome=fb.WorkOutputs(outputs=u.update_response(seen["issued"])))
    seen["ctx"].post(event, issued=seen["issued"])
    rig.drive(lambda: any(t.value["request"] == request for t in rig.facts(c.WORK_TERMINAL)))
    terminal, = (t for t in rig.facts(c.WORK_TERMINAL) if t.value["request"] == request)
    assert terminal.value["terminal_kind"] == "outputs"
    assert rig.one(c.WORK_REPORT, cid=terminal.value["first_receipt"]).value == wire(event)
    rig.drive(lambda: any(r.value["request"] == request for r in rig.facts(c.UPDATE_RESULT)))
    result, = (r for r in rig.facts(c.UPDATE_RESULT) if r.value["request"] == request)
    late_expected = SECOND if head is not None else FIRST
    assert result.value["result"] == plain(seen["issued"].result) == late_expected
    if advance_head:
        rig.drive(lambda: any(s.value["request"] == request for s in rig.facts(c.STALE)))
        stale, = (s for s in rig.facts(c.STALE) if s.value["request"] == request)
        assert stale.value == {"origin": seen["work"].desc.reader, "request": request,
            "result": result.cid, "expected_previous": head.cid if head is not None else None,
            "actual_previous": newer.cid}
        assert tuple(rig.facts(c.BELIEF_ADOPTED)) == before
        assert not [a for a in rig.facts(c.BELIEF_ADOPTED) if a.value["request"] == request]
    else:
        rig.drive(lambda: any(a.value["request"] == request for a in rig.facts(c.BELIEF_ADOPTED)))
        adopted, = (a for a in rig.facts(c.BELIEF_ADOPTED) if a.value["request"] == request)
        assert_update(rig, seen["work"], adopted, late_expected, head.cid if head is not None else None)
        assert len(rig.facts(c.BELIEF_ADOPTED)) == len(before) + 1
        assert not [s for s in rig.facts(c.STALE) if s.value["request"] == request]
    observed = execution_for(rig.workers.contexts["measure_segment"], work_id)
    assert observed.launches == ("launched",) and observed.entered == 1 and observed.stopped
    assert len(observed.reports) == 1 and observed.reports[0].point == terminal.value["first_receipt"]


@pytest.mark.parametrize("advance_head", (False, True), ids=("late_adopted", "late_stale"))
def test_row3_next_update_after_late_terminal_uses_current_head_and_keeps_one_chain(make_rig, advance_head):
    """F-b K15(4)/K9/K13 :3515,3509,3513; conjunction/CE1 :2733-2741,2904-2923.

    A late adoption missing from the head fails next.prior, SECOND, and the unique previous chain.
    Using the stale result as head fails next.prior/FIRST; mixing its x2=0 claim changes FIRST to SECOND.
    """
    rig, seed = prepare_row3_rig(make_rig, True)  # adopted x1=0: ONE_POINT
    report, seen = stop_row3_update(rig, seed, "return", retain_issue=True)  # x2=x3=0, not yet reported
    assert_row3_stopped_without_adoption(rig, report, seen)
    assert not [t for t in rig.facts(c.WORK_TERMINAL) if t.value["request"] == seen["work"].request]
    newer = continue_row3_with_new_report(rig, seed, report, seen) if advance_head else None
    # In the stale branch the live head has x1=x3=0 (FIRST), without the stopped x2=0 claim.
    before_late = tuple(rig.facts(c.BELIEF_ADOPTED))
    request = seen["work"].request
    rig.clock.set(5)
    event = fb.WorkFinished(work=seen["work"].desc.work_id,
        started=seen["reading"], finished=seen["reading"],
        outcome=fb.WorkOutputs(outputs=u.update_response(seen["issued"])))
    seen["ctx"].post(event, issued=seen["issued"])
    rig.drive(lambda: any(t.value["request"] == request for t in rig.facts(c.WORK_TERMINAL)))
    terminal, = (t for t in rig.facts(c.WORK_TERMINAL) if t.value["request"] == request)
    assert terminal.value["terminal_kind"] == "outputs"
    assert rig.one(c.WORK_REPORT, cid=terminal.value["first_receipt"]).value == wire(event)
    rig.drive(lambda: any(r.value["request"] == request for r in rig.facts(c.UPDATE_RESULT)))
    result, = (r for r in rig.facts(c.UPDATE_RESULT) if r.value["request"] == request)
    assert result.value["result"] == SECOND  # seed x1=0 plus the late x2=x3=0
    if advance_head:
        rig.drive(lambda: any(s.value["request"] == request for s in rig.facts(c.STALE)))
        stale, = (s for s in rig.facts(c.STALE) if s.value["request"] == request)
        assert stale.value == {"origin": seen["work"].desc.reader, "request": request,
            "result": result.cid, "expected_previous": seed.cid, "actual_previous": newer.cid}
        assert tuple(rig.facts(c.BELIEF_ADOPTED)) == before_late
        assert not [a for a in rig.facts(c.BELIEF_ADOPTED) if a.value["request"] == request]
        current_head = newer
    else:
        rig.drive(lambda: any(a.value["request"] == request for a in rig.facts(c.BELIEF_ADOPTED)))
        current_head, = (a for a in rig.facts(c.BELIEF_ADOPTED) if a.value["request"] == request)
        assert_update(rig, seen["work"], current_head, SECOND, seed.cid)
        assert not [s for s in rig.facts(c.STALE) if s.value["request"] == request]
    rig.clock.set(6)
    start, end = (0, 1) if advance_head else (2, 3)
    following = post_row5_claim(rig, slot="row3-following-late-terminal", start=start, end=end)
    rig.drive(lambda: len(rig.requests("belief_update")) == (4 if advance_head else 3))
    work = rig.run_stage("belief_update")
    assert work.desc.args.prior == current_head.cid
    assert row5_report_for_work(rig, work).cid == following.cid
    rig.drive(lambda: len(rig.facts(c.BELIEF_ADOPTED)) == 3)
    adopted = rig.facts(c.BELIEF_ADOPTED)[-1]
    # Each next predicate is entailed by the correct head, so cumulative mass is unchanged.
    # Old seed head would give ONE_POINT (stale branch) or FIRST (late-adopted branch).
    assert_update(rig, work, adopted, FIRST if advance_head else SECOND, current_head.cid)
    adoptions = rig.facts(c.BELIEF_ADOPTED)
    assert len(adoptions) == 3 and adoptions[0].cid == seed.cid
    assert adoptions[1].cid == current_head.cid and adoptions[2].cid == adopted.cid
    assert len({a.cid for a in adoptions}) == len(adoptions)
    assert len({a.value["previous"] for a in adoptions}) == len(adoptions)
    assert [a.value["previous"] for a in adoptions] == [None] + [a.cid for a in adoptions[:-1]]
    assert {a.value["origin"] for a in adoptions} == {rig.one(ORIGIN).cid}
    assert {a.value["model"] for a in adoptions} == {rig.model_point}


class Row2AckLoss:
    """Test adapters around the actual public ledger/stores, never window state."""

    def __init__(self, rig, target, boundary):
        from hashlib import sha256
        from test_fb_stage1 import entry_from_header, decode_record, encode_header, seal
        self.rig, self.target, self.boundary = rig, target, boundary
        self.ref = {"request": c.WORK_REQUESTED, "terminal": c.WORK_TERMINAL,
            "result": c.UPDATE_RESULT, "acquisition_clock": CLOCK, "acquisition": ACQUIRED,
            "adoption": c.BELIEF_ADOPTED, "continuation_request": c.EVALUATION_REQUESTED}[target]
        self.prepared, self.attempts = None, []
        self.failed = self.confirmed = False
        self.loss_error = None
        self.normal_get, normal_write = rig.contents.get, rig.ledger.write
        normal_prepare = rig.ledger.prepare
        self.entry_from_header, self.decode_record, self.seal = entry_from_header, decode_record, seal
        def observe(cid):
            # Same independent C/E observer as RealRig, bypassing this test's readback witness.
            header = dict(rig.entry_store.load())[cid]
            assert sha256(header).hexdigest() == cid.removeprefix("sha256:")
            entry = entry_from_header(cid, header)
            salt, payload = self.normal_get(entry.seal)
            assert seal(payload, salt) == entry.seal
            record = decode_record(header, payload)
            assert encode_header(record, entry.seal, entry.parents) == header
            return header, salt, record
        rig.read_stored = observe
        def prepare(record, parents):
            if target == "adoption" and self.failed and record.body.contract == c.WORK_REQUESTED:
                if record.body.content.as_json()["desc"]["purpose"] == "belief_update":
                    assert self.confirmed, "K9/K13: next Q* prepared before the pending A* was read back"
            return normal_prepare(record, parents)
        rig.ledger.prepare = prepare
        def get(value_seal):
            is_target = self.prepared is not None and value_seal == self.target_seal
            value = self.normal_get(value_seal)
            if self.failed and is_target:
                if dict(rig.entry_store.load()).get(self.prepared.cid) == self.prepared.header:
                    self.confirmed = True
            return value
        rig.contents.get = get
        def write(prepared):
            first = self.prepared is None and self.matches(prepared)
            if first:
                self.prepared = prepared
                self.target_seal = entry_from_header(prepared.cid, prepared.header).seal
                rig.fail_next(boundary)
            if self.prepared is not None and not self.confirmed and prepared.record.body.contract == self.ref:
                self.attempts.append(prepared)
            try:
                result = normal_write(prepared)
            except OSError as error:
                if first and rig.faults.observed == [boundary]:
                    self.failed, self.loss_error = True, error
                    self.body_at_loss = self.normal_get(self.target_seal)
                    self.header_at_loss = dict(rig.entry_store.load()).get(prepared.cid)
                raise
            if self.failed and prepared.cid == self.prepared.cid:
                self.confirmed = True
            return result
        rig.ledger.write = write

    def matches(self, prepared):
        if prepared.record.body.contract != self.ref:
            return False
        value = prepared.record.body.content.as_json()
        if self.target == "request":
            return value["desc"]["purpose"] == "belief_update"
        if self.target == "acquisition_clock":
            return bool(self.rig.facts(c.UPDATE_RESULT))
        if self.target == "acquisition":
            return any(r.cid in value["contents"] for r in self.rig.facts(c.UPDATE_RESULT))
        return True

    def assert_commit_at_loss(self):
        prepared = self.prepared
        salt, payload = self.body_at_loss
        assert salt == prepared.salt and self.seal(payload, salt) == self.target_seal
        assert self.decode_record(prepared.header, payload) == prepared.record
        assert self.header_at_loss == (prepared.header if self.boundary == "after_entry_commit" else None)


class Row2Driver:
    """The test calls run_until again after a store exception; production is not retried by a mock."""

    def __init__(self, rig, cut, on_loss):
        self.rig, self.cut, self.on_loss = rig, cut, on_loss
        self.handled = self.handling = False
        self.calls, self.call_at_loss = 0, None
        self.executed = {work.desc.work_id for work in rig.workers.entries}
        rig.drive = self.drive

    def handle_loss(self):
        self.handled, self.handling, self.call_at_loss = True, True, self.calls
        try:
            self.on_loss()
        finally:
            self.handling = False

    def drive(self, predicate, *, require_confirmation=True):
        def done():
            return predicate() and (not require_confirmation or not self.cut.failed or self.cut.confirmed)
        for _ in range(16):  # harness watchdog, not a product latency limit
            self.calls += 1
            try:
                self.rig.host.run_until(lambda _status: done(), timeout=2)
            except OSError as error:
                if error is self.cut.loss_error and not self.handled:
                    self.handle_loss()
                    continue  # a new public run_until call, without executing the worker again
                raise
            if self.cut.failed and not self.handled:
                self.handle_loss()
                continue
            if self.rig.workers.errors:
                raise self.rig.workers.errors[0]
            assert done(), "incomplete observation: row 2 transition was not reached"
            return
        raise AssertionError("incomplete observation: store acknowledgment did not recover")

    def advance_until(self, predicate):
        def pending():
            return [(key, body) for key, body in self.rig.launcher.attempts if key not in self.executed]
        while not predicate():
            self.drive(lambda: predicate() or bool(pending()))
            if predicate():
                return
            work_id, body = pending()[0]
            assert sum(key == work_id for key, _ in self.rig.launcher.attempts) == 1
            self.executed.add(work_id)
            body()  # run the host's actual deferred OS body, in its observed launch order


def post_row2_claim(driver, *, slot, start, end, wait_saved=True):
    rig = driver.rig
    before = {raw.cid for raw in rig.facts(c.SEGMENT_REPORT)}
    done, errors, sent = Event(), [], []
    def emit(work, ctx):
        event = fb.SegmentReport(segment=work.request, item_slot=slot,
            item=f.CoverageClaim(route_epoch="route-A", interval=f.MeasurementInterval(
                clock=rig.clock.run, start_ns=start, end_ns=end, closure="(start,end]"),
                kind="no_arrival", contract=c.NO_ARRIVAL, evidence=()))
        rig.workers.post(ctx, event)
        sent.append(event)
    rig.workers.commands.put((emit, done, errors))
    assert done.wait(30), "incomplete observation: measurement worker did not post"
    if errors:
        raise errors[0]
    if not wait_saved:
        return sent[0]  # the real worker's Post completed; EH independently witnesses receipt
    driver.drive(lambda: any(raw.cid not in before and raw.value == wire(sent[0])
                            for raw in rig.facts(c.SEGMENT_REPORT)))
    return next(raw for raw in rig.facts(c.SEGMENT_REPORT)
                if raw.cid not in before and raw.value == wire(sent[0]))


@pytest.mark.parametrize("boundary", ("after_body_commit", "after_entry_commit"))
@pytest.mark.parametrize("target", ("request", "terminal", "result", "acquisition_clock",
                                    "acquisition", "adoption", "continuation_request"))
def test_row2_committed_write_ack_loss_keeps_one_record_and_one_ce1_adoption_chain(make_rig, target, boundary):
    """Row 2 v2 :17-24,32,64; F-b :324-327,3332,3488,3509,3513; CE1 :2917-2923.

    Regenerating an ID/time/salt changes PreparedEntry or the final target Point and fails exact retry/one-record checks.
    Treating unknown A* as absent/present fails the prepare-before-readback check; rebuild preserves the pending entry.
    A permanently stuck update fails the next run_until progression; double counting fails FIRST then SECOND.
    """
    rig = make_rig(continuation=True)
    rig.start()
    cut = Row2AckLoss(rig, target, boundary)
    second = {}
    def on_loss():
        cut.assert_commit_at_loss()
        rig.clock.set(rig.clock.mono_ns() + 10)  # make regeneration observable without reversing M
        if target == "adoption":
            assert not cut.confirmed
            measurement = next(work for work in rig.workers.entries if work.desc.purpose == "measure_segment")
            ctx = rig.workers.contexts["measure_segment"]
            before_receipt = {report.envelope for report in execution_for(ctx, measurement.desc.work_id).reports}
            receipt_time = rig.clock.mono_ns() + 1
            rig.clock.set(receipt_time)
            second["event"] = post_row2_claim(driver, slot="row2-second", start=1, end=3, wait_saved=False)
            receipt, = (report for report in execution_for(ctx, measurement.desc.work_id).reports
                        if report.envelope not in before_receipt)
            assert receipt.received_ns == receipt_time and receipt.point is None
            event = fb.Received(route_epoch="route-A", media_type="application/octet-stream",
                                data=b"row2-reception-during-unknown-adoption", claims={})
            rig.host.post(event)
            second["received"] = event
            assert not cut.confirmed and len(rig.requests("belief_update")) == 1
            assert rig.thread.is_alive()
            if boundary == "after_entry_commit":
                before = dict(rig.entry_store.load())
                rig.host.rebuild_window()
                assert dict(rig.entry_store.load()) == before
                assert len(rig.requests("belief_update")) == 1
    driver = Row2Driver(rig, cut, on_loss)
    rig.clock.set(10)
    first = post_row2_claim(driver, slot="row2-first", start=0, end=2)
    driver.advance_until(lambda: len(rig.facts(c.BELIEF_ADOPTED)) >= 1)
    a1 = rig.facts(c.BELIEF_ADOPTED)[0]
    w1 = next(work for work in rig.workers.entries if work.request == a1.value["request"])
    r1 = assert_update(rig, w1, a1, FIRST)
    rig.clock.set(max(30, rig.clock.mono_ns() + 1))
    if "event" in second:
        driver.drive(lambda: any(raw.value == wire(second["event"]) for raw in rig.facts(c.SEGMENT_REPORT)))
        second["report"] = next(raw for raw in rig.facts(c.SEGMENT_REPORT) if raw.value == wire(second["event"]))
        driver.drive(lambda: any(raw.value == wire(second["received"]) for raw in rig.facts(c.RECEIVED)))
    else:
        second["report"] = post_row2_claim(driver, slot="row2-second", start=1, end=3)
    driver.advance_until(lambda: len(rig.facts(c.BELIEF_ADOPTED)) == 2
        and len(rig.facts(c.SELECTION)) == 3 and cut.failed and cut.confirmed)
    a2 = rig.facts(c.BELIEF_ADOPTED)[1]
    w2 = next(work for work in rig.workers.entries if work.request == a2.value["request"])
    assert_update(rig, w2, a2, SECOND, a1.cid)
    assert row5_report_for_work(rig, w1).cid == first.cid
    assert row5_report_for_work(rig, w2).cid == second["report"].cid
    assert len(rig.requests("belief_update")) == len(rig.facts(c.UPDATE_RESULT)) == 2
    adoptions = rig.facts(c.BELIEF_ADOPTED)
    assert len(adoptions) == 2 and [a.value["previous"] for a in adoptions] == [None, a1.cid]
    terminal, = (t for t in rig.facts(c.WORK_TERMINAL) if t.value["request"] == w1.request)
    acquired = rig.one(ACQUIRED, cid=a1.value["acquisition"])
    acquired_clock = rig.one(CLOCK, cid=acquired.value["clock"])
    eq1 = rig.requests("evaluation_prepare")[1]
    prepared, = (p for p in rig.facts(c.PREPARED) if p.value["request"] == eq1.cid)
    assert prepared.value["request"] == eq1.cid
    assert {trigger["point"] for trigger in eq1.value["desc"]["trigger"]} == {a1.cid}
    actual_target = {"request": w1.request, "terminal": terminal.cid, "result": r1.cid,
        "acquisition_clock": acquired_clock.cid, "acquisition": acquired.cid,
        "adoption": a1.cid, "continuation_request": eq1.cid}[target]
    assert actual_target == cut.prepared.cid
    assert driver.handled and cut.failed and cut.confirmed and driver.calls > driver.call_at_loss
    assert rig.faults.observed == [boundary]
    assert cut.attempts and all(attempt == cut.prepared for attempt in cut.attempts)
    assert rig.read_stored(cut.prepared.cid) == (cut.prepared.header, cut.prepared.salt, cut.prepared.record)
    # This one logical record has the same contract and causal parents throughout its retries.
    same_preparations = [p for p in rig.ledger.preparations
                         if p.record.body.contract == cut.ref and p.parents == cut.prepared.parents]
    assert same_preparations and all(p == cut.prepared for p in same_preparations)
    assert [fact.cid for fact in rig.facts(cut.ref) if fact.parents == cut.prepared.parents] == [cut.prepared.cid]
    for work in (w1, w2):
        assert [ok for key, ok in rig.workers.entry_attempts if key == work.desc.work_id] == [True]
        observed = execution_for(rig.workers.contexts["measure_segment"], work.desc.work_id)
        assert observed.launches == ("launched",) and observed.entered == 1 and observed.stopped


class Row1StoreCut:
    """One public store/ledger operation fails; the independent C/E oracle never does."""

    def __init__(self, rig, target, operation, *, ordinal=1, read_occurrence=1):
        from hashlib import sha256
        from test_fb_stage1 import SavedFact, entry_from_header, decode_record, encode_header, seal
        self.rig, self.target, self.operation, self.ordinal = rig, target, operation, ordinal
        self.ref = {"report": c.SEGMENT_REPORT, "binding": c.SEGMENT_BINDING,
            "request": c.WORK_REQUESTED, "work_report": c.WORK_REPORT,
            "terminal": c.WORK_TERMINAL, "result": c.UPDATE_RESULT,
            "acquisition_clock": CLOCK, "acquisition": ACQUIRED,
            "adoption": c.BELIEF_ADOPTED, "continuation_request": c.EVALUATION_REQUESTED,
            "boot": c.BOOT_DECLARATION, "candidate": c.CANDIDATE_REQUEST,
            "prepare": c.EVALUATION_REQUESTED, "draw": c.DRAW_REQUESTED,
            "evaluate": c.WORK_REQUESTED,
            "candidates": CG, "prepared": c.PREPARED, "draw_report": c.DRAW_REPORT,
            "route": ROUTE}[target]
        self.in_host = self.failed = self.confirmed = False
        self.hits, self.selected, self.prepared = 0, [], None
        self.read_occurrence, self.read_calls = read_occurrence, {}
        self.loss_error = OSError(f"row1 one temporary {operation} failure: {target}/{ordinal}")
        raw_load, raw_get = rig.entry_store.load, rig.contents.get
        self.raw_load, self.raw_get = raw_load, raw_get
        self.entry_from_header = entry_from_header

        def observe(cid):
            header = dict(raw_load())[cid]
            assert sha256(header).hexdigest() == cid.removeprefix("sha256:")
            entry = entry_from_header(cid, header)
            salt, payload = raw_get(entry.seal)
            assert seal(payload, salt) == entry.seal
            record = decode_record(header, payload)
            assert encode_header(record, entry.seal, entry.parents) == header
            return header, salt, record
        rig.read_stored = observe

        def facts(wanted):
            positions = {p.cid: i for i, p in enumerate(rig.ledger.preparations)}
            result = []
            for cid, _ in raw_load():
                header, _salt, record = observe(cid)
                if record.body.contract == wanted:
                    result.append(SavedFact(cid=cid, record_id=record.id, contract=wanted,
                        received_ns=getattr(record.body, "received_ns", None), at_ns=record.at.mono_ns,
                        parents=entry_from_header(cid, header).parents, value=record.body.content.as_json()))
            return sorted(result, key=lambda fact: positions[fact.cid])
        rig.facts = facts

        normal_write, normal_add = rig.ledger.write, rig.entry_store.add
        normal_entry, normal_record = rig.ledger.entry, rig.ledger.record
        self.writing = None
        def write(prepared):
            self.writing = prepared
            try:
                if operation == "before_body":
                    self.trip(prepared)
                result = normal_write(prepared)
                if self.failed and prepared.cid == self.prepared.cid:
                    self.confirmed = True
                return result
            finally:
                self.writing = None
        rig.ledger.write = write
        def add(cid, header):
            if operation == "before_entry" and self.writing is not None:
                self.trip(self.writing)
            return normal_add(cid, header)
        rig.entry_store.add = add

        def entry(cid):
            prepared = self.saved_preparation(cid)
            if operation == "entry" and prepared is not None:
                self.trip(prepared, reading=True)
            value = normal_entry(cid)
            if self.failed and prepared is not None and prepared.cid == self.prepared.cid:
                self.confirmed = True
            return value
        rig.ledger.entry = entry

        def record(cid):
            prepared = self.saved_preparation(cid)
            if operation == "record" and prepared is not None:
                self.trip(prepared, reading=True)
            value = normal_record(cid)
            if self.failed and prepared is not None and prepared.cid == self.prepared.cid:
                self.confirmed = True
            return value
        rig.ledger.record = record
        def get(value_seal):
            # The host-only guard excludes the test worker and every oracle read.
            if operation == "body" and self.in_host:
                prepared = next((p for p in rig.ledger.preparations
                    if entry_from_header(p.cid, p.header).seal == value_seal
                    and p.cid in dict(raw_load())), None)
                if prepared is not None:
                    self.trip(prepared, reading=True)
            else:
                prepared = None
            value = raw_get(value_seal)
            if self.failed and prepared is not None and prepared.cid == self.prepared.cid:
                self.confirmed = True
            return value
        rig.contents.get = get

    def saved_preparation(self, cid):
        if not self.in_host or cid not in dict(self.raw_load()):
            return None
        return next((p for p in self.rig.ledger.preparations if p.cid == cid), None)

    def matches(self, prepared):
        if prepared.record.body.contract != self.ref:
            return False
        value = prepared.record.body.content.as_json()
        if self.target == "report":
            return value["item"]["kind"] == "claim"
        if self.target == "request":
            return value["desc"]["purpose"] == "belief_update"
        if self.target == "evaluate":
            return value["desc"]["purpose"] == "evaluation"
        if self.target in ("work_report", "terminal"):
            return value.get("work") in {q.value["desc"]["work_id"] for q in self.rig.requests("belief_update")}
        if self.target == "acquisition_clock":
            ctx = self.rig.workers.contexts.get("measure_segment")
            return ctx is not None and any(result.cid in a.contents
                and a.acquired_ns == value["reading"]["time_ns"]
                for result in self.rig.facts(c.UPDATE_RESULT) for a in ctx.evidence().acquisitions)
        if self.target == "acquisition":
            return any(r.cid in value["contents"] for r in self.rig.facts(c.UPDATE_RESULT))
        if self.target == "continuation_request":
            return any(t["point"] in {a.cid for a in self.rig.facts(c.BELIEF_ADOPTED)}
                       for t in value["desc"]["trigger"])
        return True

    def trip(self, prepared, *, reading=False):
        if not self.in_host or self.failed or not self.matches(prepared):
            return
        if reading:
            self.read_calls[prepared.cid] = self.read_calls.get(prepared.cid, 0) + 1
            if self.read_calls[prepared.cid] != self.read_occurrence:
                return
        if prepared.cid not in self.selected:
            self.selected.append(prepared.cid)
        if self.selected.index(prepared.cid) + 1 != self.ordinal:
            return
        self.prepared = prepared
        self.fixed = tuple(self.rig.ledger.preparations)
        self.headers_at_loss = dict(self.raw_load())
        self.seals_at_loss = self.rig.contents.seals()
        self.failed, self.hits = True, self.hits + 1
        raise self.loss_error

    def assert_fixed_preparations(self):
        assert self.hits == 1, f"fixture: requested {self.target}/{self.operation} fault did not fire exactly once"
        for prepared in self.fixed:
            attempts = [p for p in self.rig.ledger.preparations if p.record.id == prepared.record.id]
            assert attempts and all(p == prepared for p in attempts), "R1: changed a fixed preparation"
            assert prepared.cid in dict(self.raw_load()), f"R2: prepared record was never saved: {prepared.record.body.contract}"
            assert self.rig.read_stored(prepared.cid) == (prepared.header, prepared.salt, prepared.record), \
                "R1: name/time/body/parents/CID changed on re-entry"


class Row1Driver(Row2Driver):
    def drive(self, predicate, **kwargs):
        self.cut.in_host = True
        try:
            return super().drive(predicate, **kwargs)
        except AssertionError as error:
            if "incomplete observation" in str(error):
                raise AssertionError(f"R2: {self.cut.target}/{self.cut.operation}: re-entry did not reach its successor; "
                    f"read_occurrence={self.cut.read_occurrence}, faults={self.cut.hits}, confirmed={self.cut.confirmed}, "
                    f"measure={len(self.rig.requests('measure_segment'))}, Q={len(self.rig.requests('belief_update'))}, "
                    f"R={len(self.rig.facts(c.UPDATE_RESULT))}, A={len(self.rig.facts(c.BELIEF_ADOPTED))}, "
                    f"selection={len(self.rig.facts(c.SELECTION))}, "
                    f"entered={[w.desc.purpose for w in self.rig.workers.entries]}") from None
            raise
        finally:
            self.cut.in_host = False

    def advance_until(self, predicate):
        def pending():
            return [(key, body) for key, body in self.rig.launcher.attempts if key not in self.executed]
        while not predicate():
            self.drive(lambda: predicate() or bool(pending()))
            if predicate():
                return
            work_id, body = pending()[0]
            assert sum(key == work_id for key, _ in self.rig.launcher.attempts) == 1, "R3: duplicate launch"
            self.executed.add(work_id)
            request = next(q for stage in (*ORDER, "measure_segment", "belief_update")
                           for q in self.rig.requests(stage) if q.value["desc"]["work_id"] == work_id)
            if request.value["desc"]["purpose"] == "measure_segment":
                self.rig.thread = Thread(target=body, daemon=True)
                self.rig.thread.start()
                assert self.rig.workers.entered.setdefault("measure_segment", Event()).wait(30)
            else:
                body()


def finish_row1_loop(rig, cut, *, already_started=True):
    """CE1's two literal expectations; use only the public run_until re-entry."""
    second = {}
    route_before = rig.facts(ROUTE)
    def on_loss():
        assert cut.hits == 1
        if cut.operation in ("before_body", "before_entry"):
            assert cut.prepared.cid not in cut.headers_at_loss, "fixture: entry was already committed"
            present = cut.entry_from_header(cut.prepared.cid, cut.prepared.header).seal in cut.seals_at_loss
            assert present == (cut.operation == "before_entry"), "fixture: wrong pre-commit boundary"
        # CE1's absolute domain starts at zero; a Boot cut before measurement entry must retain it.
        if "measure_segment" in rig.workers.contexts:
            rig.clock.set(rig.clock.mono_ns() + 10)
        if cut.target == "request" and cut.ordinal == 1:
            ctx = rig.workers.contexts["measure_segment"]
            measurement = next(w for w in rig.workers.entries if w.desc.purpose == "measure_segment")
            before = {r.envelope for r in execution_for(ctx, measurement.desc.work_id).reports}
            second["event"] = post_row2_claim(driver, slot="row1-second", start=1, end=3, wait_saved=False)
            receipt, = (r for r in execution_for(ctx, measurement.desc.work_id).reports if r.envelope not in before)
            assert receipt.point is None
            second["envelope"] = receipt.envelope
    driver = Row1Driver(rig, cut, on_loss)
    if not already_started:
        driver.advance_until(lambda: len(rig.facts(c.SELECTION)) == 1 and bool(rig.thread))
    rig.clock.set(max(20, rig.clock.mono_ns() + 1))
    first = post_row2_claim(driver, slot="row1-first", start=0, end=2)
    driver.advance_until(lambda: len(rig.facts(c.BELIEF_ADOPTED)) >= 1)
    a1 = rig.facts(c.BELIEF_ADOPTED)[0]
    w1 = next(w for w in rig.workers.entries if w.request == a1.value["request"])
    assert_update(rig, w1, a1, FIRST)
    if "event" not in second:
        rig.clock.set(rig.clock.mono_ns() + 10)
        second["event"] = post_row2_claim(driver, slot="row1-second", start=1, end=3, wait_saved=False)
    driver.advance_until(lambda: len(rig.facts(c.BELIEF_ADOPTED)) == 2 and len(rig.facts(c.SELECTION)) == 3)
    a2 = rig.facts(c.BELIEF_ADOPTED)[1]
    w2 = next(w for w in rig.workers.entries if w.request == a2.value["request"])
    assert_update(rig, w2, a2, SECOND, a1.cid)
    assert [a.value["previous"] for a in rig.facts(c.BELIEF_ADOPTED)] == [None, a1.cid], "R2: adoption fork"
    assert row5_report_for_work(rig, w1).cid == first.cid
    second_report, = (r for r in rig.facts(c.SEGMENT_REPORT) if r.value == wire(second["event"]))
    assert row5_report_for_work(rig, w2).cid == second_report.cid
    if "envelope" in second:
        ctx = rig.workers.contexts["measure_segment"]
        measurement = next(w for w in rig.workers.entries if w.desc.purpose == "measure_segment")
        receipt, = (r for r in execution_for(ctx, measurement.desc.work_id).reports if r.envelope == second["envelope"])
        assert receipt.point == second_report.cid
    assert cut.hits == 1, f"fixture: {cut.target}/{cut.operation}/read-{cut.read_occurrence} did not fire"
    assert driver.handled and driver.calls > driver.call_at_loss and cut.confirmed
    cut.assert_fixed_preparations()
    assert len(rig.requests("belief_update")) == len(rig.facts(c.UPDATE_RESULT)) == 2
    assert len(rig.workers.entries) == 13, "R3: unexpected extra work body"
    ctx = rig.workers.contexts["measure_segment"]
    for work in rig.workers.entries:
        assert [ok for key, ok in rig.workers.entry_attempts if key == work.desc.work_id] == [True], "R3: duplicate entry"
        observed = execution_for(ctx, work.desc.work_id)
        assert observed.entered == 1 and observed.launches == ("launched",), "R3: duplicate execution"
        assert sum(key == work.desc.work_id for key, _ in rig.launcher.attempts) == 1, "R3: duplicate launch"
    assert len([event for event, _ in rig.workers.sent if isinstance(event, fb.DrawReturned)]) == 3, "R3: extra draw use"
    for result in rig.facts(c.UPDATE_RESULT):
        acquisitions = [a for a in ctx.evidence().acquisitions if result.cid in a.contents]
        assert len(acquisitions) == 1, f"R3: result acquisition repeated {len(acquisitions)} times at " \
            f"{[a.acquired_ns for a in acquisitions]}"
        saved, = (g for g in rig.facts(ACQUIRED) if result.cid in g.value["contents"])
        clock = rig.one(CLOCK, cid=saved.value["clock"])
        assert clock.value["reading"]["time_ns"] == acquisitions[0].acquired_ns, "R3: acquisition time resampled"
    if cut.target == "acquisition_clock":
        assert cut.prepared.cid in {g.value["clock"] for g in rig.facts(ACQUIRED)
            if any(r.cid in g.value["contents"] for r in rig.facts(c.UPDATE_RESULT))}
    route, = rig.facts(ROUTE)
    if route_before:
        assert [route] == route_before, "R3: route application/time changed on re-entry"
    route_preparations = [p for p in rig.ledger.preparations if p.record.body.contract == ROUTE]
    assert route_preparations and all(p == route_preparations[0] for p in route_preparations), "R3: route effective time resampled"


@pytest.mark.parametrize("operation", ("before_body", "before_entry"))
@pytest.mark.parametrize("target", ("report", "binding", "request", "work_report", "terminal", "result",
                                    "acquisition_clock", "acquisition", "adoption", "continuation_request"))
def test_row1_precommit_failure_reenters_same_ce1_loop_without_extra_effects(make_rig, target, operation):
    """Row 1 v2 :17-25,31; F-b :324-329,3328-3332,3488,3505,3509,3513-3515.

    A stuck retry fails R2's mandatory Q*/R*/A*/selection successors after run_until re-entry.
    Regenerating a time/name/boundary fails R1's saved PreparedEntry equality.
    Reacquiring R* or resampling route application fails R3's acquisition/time/route witnesses.
    Relaunching/re-entering/redrawing or recounting a report fails R3's counts or FIRST/SECOND.
    """
    rig = make_rig(continuation=True)
    rig.start()
    finish_row1_loop(rig, Row1StoreCut(rig, target, operation))


@pytest.mark.parametrize("read_occurrence", (1, 2))
@pytest.mark.parametrize("operation", ("entry", "record", "body"))
@pytest.mark.parametrize("target", ("report", "binding", "request", "work_report", "terminal", "result",
                                    "acquisition_clock", "acquisition", "adoption", "continuation_request"))
def test_row1_public_host_read_failure_reenters_same_ce1_loop_without_extra_effects(make_rig, target, operation, read_occurrence):
    """F-b ConfirmWrite :327, K5 :3505; first/second host ledger.entry/record or store.get of one saved Point.

    A failed read permanently losing its successor fails R2; each requested cut must actually fire once.
    Re-preparing a fixed record/boundary after a read error fails R1's exact stored preparation.
    Repeated acquisition/application/draw/entry fails R3; duplicate report use changes FIRST/SECOND.
    """
    rig = make_rig(continuation=True)
    rig.start()
    finish_row1_loop(rig, Row1StoreCut(rig, target, operation, read_occurrence=read_occurrence))


class Row1DeferredBootRig(LoopRig):
    def drive(self, predicate):
        # LoopRig queues actual Boot/ClockDeclared; the test installs the store cut before running them.
        pass


@pytest.mark.parametrize("target", ("boot", "candidate", "prepare", "draw", "evaluate"))
def test_row1_boot_and_initial_thinking_read_failure_still_complete_both_continuations(target):
    """F-b :324-329, K9/K13 and v2 :18-25: Boot plus candidate -> Ep -> draw -> Ee.

    A lost Boot/thinking successor fails R2's initial and two continued selections.
    Re-sampling an already fixed stage/boundary fails R1's exact preparation check.
    Re-entering/redrawing/reacquiring or changing route application fails R3's public witnesses.
    """
    rig = Row1DeferredBootRig(continuation=True)
    try:
        finish_row1_loop(rig, Row1StoreCut(rig, target, "body"), already_started=False)
    finally:
        rig.close()


def test_row1_second_update_precommit_failure_keeps_adopted_prior_and_one_chain(make_rig):
    """K9/K13 :3509,3513: fail Q* only after A1 exists, then require SECOND/prior=A1.

    A lost next Q* fails R2; changed preparation fails R1; repeated work/acquisition fails R3.
    Counting either report twice fails CE1's literal FIRST/SECOND expectations (:2917-2923).
    """
    rig = make_rig(continuation=True)
    rig.start()
    finish_row1_loop(rig, Row1StoreCut(rig, "request", "before_body", ordinal=2))


@pytest.mark.parametrize(("target", "operation", "read_occurrence"), (
    ("candidates", "body", 2), ("prepared", "body", 2),
    ("draw_report", "body", 2), ("route", "body", 2),
))
def test_row1_saved_boot_and_thinking_inputs_read_failure_preserves_the_loop(target, operation, read_occurrence):
    """Row 1 :19,31; F-b PrepareOne/ConfirmWrite :324-327 and stage-2 ORDER.

    A lost successor after reading saved CG/PR/draw/route fails R2's mandatory selections/updates.
    Replacing fixed records/boundaries fails R1; extra entry/draw/acquisition/application time fails R3.
    """
    rig = Row1DeferredBootRig(continuation=True)
    try:
        finish_row1_loop(rig, Row1StoreCut(rig, target, operation, read_occurrence=read_occurrence), already_started=False)
    finally:
        rig.close()


class Row1IntervalCut(Row1StoreCut):
    """Count outermost public record reads between actual saved X and not-yet-saved Y."""

    def __init__(self, rig, flow, lap, left, right, k):
        from threading import get_ident
        public_reads = ((rig.ledger, "entry", rig.ledger.entry),
                        (rig.ledger, "record", rig.ledger.record), (rig.contents, "get", rig.contents.get))
        super().__init__(rig, "request", "interval", read_occurrence=k)
        self.flow, self.lap, self.left, self.right, self.k = flow, lap, left, right, k
        self.target = f"{flow}{lap}:{left}->{right}:k={k}"
        self.loss_error = OSError("one interval read failed: " + self.target)
        self.runner, self.get_ident, self.depth = get_ident(), get_ident, 0
        self.reads, self.committed, self.points = [], {}, {}
        self.preexisting = {cid for cid, _ in self.raw_load()}
        self.points_size = -1
        self.clock_before_g = None
        self.committed = {cid: rig.read_stored(cid)[2] for cid, _ in self.raw_load()}
        normal_add = rig.entry_store.add
        def add(cid, header):
            result = normal_add(cid, header)
            # Observe the actual saved bytes, not the caller's proposed record or a write flag.
            self.committed[cid] = rig.read_stored(cid)[2]
            return result
        rig.entry_store.add = add
        # Install before the real host is constructed, including callbacks it may retain.
        for owner, name, normal in public_reads:
            def read(key, _normal=normal, _name=name):
                if not self.in_host or self.get_ident() != self.runner or self.depth:
                    return _normal(key)
                self.depth += 1
                try:
                    points = self.saved_points()
                    if not self.failed and self.left in points and self.right not in points:
                        self.reads.append((_name, key))
                        if len(self.reads) == self.k:
                            self.fixed = tuple(rig.ledger.preparations)
                            self.prepared = next((p for p in self.fixed if p.cid == key), self.fixed[-1])
                            self.headers_at_loss = dict(self.raw_load())
                            assert set(self.committed) == set(self.headers_at_loss), "fixture: incomplete saved-point observer"
                            self.seals_at_loss = rig.contents.seals()
                            self.left_at_loss = points[self.left]
                            assert self.left_at_loss in self.headers_at_loss
                            self.failed, self.hits = True, self.hits + 1
                            raise self.loss_error
                    value = _normal(key)
                    if self.failed:
                        self.confirmed = True
                    return value
                finally:
                    self.depth -= 1
            setattr(owner, name, read)

    def saved_points(self):
        # The public add adapter refreshes this cache from actual C/E after each commit.
        if self.points_size == len(self.committed):
            return self.points
        self.points_size = len(self.committed)
        positions = {p.cid: i for i, p in enumerate(self.rig.ledger.preparations)}
        assert set(self.committed) <= set(positions) | self.preexisting
        facts = sorted(self.committed.items(), key=lambda item: positions.get(item[0], -1))
        def find(ref, predicate=lambda value: True):
            return next((cid for cid, record in facts if record.body.contract == ref
                         and predicate(record.body.content.as_json())), None)
        def value(cid):
            return self.committed[cid].body.content.as_json()
        def request(stage, ref):
            return find(ref, lambda v: v["desc"]["purpose"] == stage)
        def report(q, ref=c.WORK_REPORT):
            return find(ref, lambda v: v["work"] == value(q)["desc"]["work_id"]) if q else None
        if self.flow == "initial":
            cgq = request("candidate_generation", c.CANDIDATE_REQUEST)
            epq = request("evaluation_prepare", c.EVALUATION_REQUESTED)
            dq = request("selection_draw", c.DRAW_REQUESTED)
            eeq = request("evaluation", c.WORK_REQUESTED)
            points = {"candidate_request": cgq, "candidate_report": report(cgq),
                "candidates": find(CG), "prepare_request": epq, "prepare_report": report(epq),
                "prepared": find(c.PREPARED), "draw_request": dq,
                "draw_report": report(dq, c.DRAW_REPORT), "draw_fact": find(contract("sui.f.draw_fact")),
                "evaluate_request": eeq, "evaluate_report": report(eeq),
                "evaluated": find(c.EVALUATED), "selection": find(c.SELECTION)}
        else:
            claims = [cid for cid, record in facts if record.body.contract == c.SEGMENT_REPORT
                      and record.body.content.as_json()["item"]["kind"] == "claim"]
            raw = claims[self.lap - 1] if len(claims) >= self.lap else None
            binding = find(c.SEGMENT_BINDING, lambda v: v["report"] == raw) if raw else None
            q = find(c.WORK_REQUESTED, lambda v: v["desc"]["purpose"] == "belief_update"
                and any(o["binding"] == binding for o in v["desc"]["args"]["observations"])) if binding else None
            terminal = find(c.WORK_TERMINAL, lambda v: v["request"] == q) if q else None
            result = find(c.UPDATE_RESULT, lambda v: v["request"] == q) if q else None
            acquired = find(ACQUIRED, lambda v: result in v["contents"]) if result else None
            clock = value(acquired)["clock"] if acquired else None
            if result and not clock:
                ctx = self.rig.workers.contexts.get("measure_segment")
                times = {a.acquired_ns for a in ctx.evidence().acquisitions if result in a.contents} if ctx else set()
                clock = next((cid for cid, record in facts if record.body.contract == CLOCK
                    and positions[cid] > positions[result]
                    and record.body.content.as_json()["reading"]["time_ns"] in times), None)
                if clock:
                    self.clock_before_g = clock
            adopted = find(c.BELIEF_ADOPTED, lambda v: v["request"] == q) if q else None
            eq = find(c.EVALUATION_REQUESTED, lambda v: any(t["point"] == adopted
                for t in v["desc"]["trigger"])) if adopted else None
            points = {"report": raw, "binding": binding, "request": q, "work_report": report(q),
                "terminal": terminal, "result": result, "acquisition_clock": clock,
                "acquisition": acquired, "adoption": adopted, "continuation_request": eq}
        self.points = {name: cid for name, cid in points.items() if cid in self.committed}
        return self.points


class Row1IntervalRig(LoopRig):
    """The same literal CE1 Boot, with the read adapter installed before host construction."""

    def __init__(self, flow, lap, left, right, k):
        RealRig.__init__(self, connect=False)
        self.clock.set(0)
        self.registry, self.launcher = registry(), LaunchCut()
        self.workers, self.thread, self.executed = Workers(self), None, set()
        self.document, _ = finite_world("FA01")
        model = self.record(Prediction(target="model.11", about=(), basis=(),
            content=Payload.json({"document": self.document}), contract=contract("sui.f.model_source")),
            RefKind.PREDICTION, Role.MODEL)
        self.model_point = self.ledger.append(model, ()).cid
        event = boot(True)
        initial = replace(event.declaration.initial.value, model=self.model_point,
            generator=fb.MethodCall(contract=c.MODEL_OPERATIONS, args={}),
            method=fb.MethodCall(contract=contract("sui.f.finite_evaluation"), args={}),
            draw=fb.MethodCall(contract=contract("stage2.scripted_draw"), args={}),
            prepare_budget=PREPARE_BUDGET, evaluate_budget=EVALUATE_BUDGET,
            derivation=fb.SlottedMethod(slot="delta", method=fb.MethodCall(
                contract=c.SAVED_SEGMENT_UPDATE, args=delta_args())),
            continuation=fb.MethodCall(contract=c.REUSE_CANDIDATES, args={}))
        self.boot_input = replace(event, declaration=replace(event.declaration,
            initial=replace(event.declaration.initial, value=initial),
            routes=tuple(replace(route, value=replace(route.value, config=replace(route.value.config,
                sampling_contract=contract("sui.f.finite_measurement"),
                clock_contract=contract("sui.f.simulated_clock")))) for route in event.declaration.routes)))
        self.cut = Row1IntervalCut(self, flow, lap, left, right, k)
        self.host = fb.FThreadHost(ledger=self.ledger, clock=self.clock, workers=self.workers,
                                  registry=self.registry, launcher=self.launcher)
        self.host.post(fb.ClockDeclared(declaration=replace(source(), run=self.clock.run,
            measurement=contract("sui.f.simulated_clock"))))
        self.host.post(self.boot_input)


# The initial Ep/D/Ee request -> report intervals each had one runner read.
# Their k=2/3 combinations are intentionally absent (observed, not skipped/xfail).
@pytest.mark.parametrize(("flow", "lap", "left", "right", "k"), (
    ("initial", 1, "candidate_request", "candidate_report", 1),
    ("initial", 1, "candidate_request", "candidate_report", 2),
    ("initial", 1, "candidate_request", "candidate_report", 3),
    ("initial", 1, "candidate_report", "candidates", 1),
    ("initial", 1, "candidate_report", "candidates", 2),
    ("initial", 1, "candidate_report", "candidates", 3),
    ("initial", 1, "candidates", "prepare_request", 1),
    ("initial", 1, "candidates", "prepare_request", 2),
    ("initial", 1, "candidates", "prepare_request", 3),
    ("initial", 1, "prepare_request", "prepare_report", 1),
    ("initial", 1, "prepare_report", "prepared", 1),
    ("initial", 1, "prepare_report", "prepared", 2),
    ("initial", 1, "prepare_report", "prepared", 3),
    ("initial", 1, "prepared", "draw_request", 1),
    ("initial", 1, "prepared", "draw_request", 2),
    ("initial", 1, "prepared", "draw_request", 3),
    ("initial", 1, "draw_request", "draw_report", 1),
    ("initial", 1, "draw_report", "draw_fact", 1),
    ("initial", 1, "draw_report", "draw_fact", 2),
    ("initial", 1, "draw_report", "draw_fact", 3),
    ("initial", 1, "draw_fact", "evaluate_request", 1),
    ("initial", 1, "draw_fact", "evaluate_request", 2),
    ("initial", 1, "draw_fact", "evaluate_request", 3),
    ("initial", 1, "evaluate_request", "evaluate_report", 1),
    ("initial", 1, "evaluate_report", "evaluated", 1),
    ("initial", 1, "evaluate_report", "evaluated", 2),
    ("initial", 1, "evaluate_report", "evaluated", 3),
    ("initial", 1, "evaluated", "selection", 1),
    ("initial", 1, "evaluated", "selection", 2),
    ("initial", 1, "evaluated", "selection", 3),
    ("update", 1, "report", "binding", 1),
    ("update", 1, "report", "binding", 2),
    ("update", 1, "report", "binding", 3),
    ("update", 1, "binding", "request", 1),
    ("update", 1, "binding", "request", 2),
    ("update", 1, "binding", "request", 3),
    ("update", 1, "request", "work_report", 1),
    ("update", 1, "request", "work_report", 2),
    ("update", 1, "request", "work_report", 3),
    ("update", 1, "work_report", "terminal", 1),
    ("update", 1, "work_report", "terminal", 2),
    ("update", 1, "work_report", "terminal", 3),
    ("update", 1, "terminal", "result", 1),
    ("update", 1, "terminal", "result", 2),
    ("update", 1, "terminal", "result", 3),
    ("update", 1, "result", "acquisition_clock", 1),
    ("update", 1, "result", "acquisition_clock", 2),
    ("update", 1, "result", "acquisition_clock", 3),
    ("update", 1, "acquisition_clock", "acquisition", 1),
    ("update", 1, "acquisition_clock", "acquisition", 2),
    ("update", 1, "acquisition_clock", "acquisition", 3),
    ("update", 1, "acquisition", "adoption", 1),
    ("update", 1, "acquisition", "adoption", 2),
    ("update", 1, "acquisition", "adoption", 3),
    ("update", 1, "adoption", "continuation_request", 1),
    ("update", 1, "adoption", "continuation_request", 2),
    ("update", 1, "adoption", "continuation_request", 3),
    ("update", 2, "binding", "request", 1),
    ("update", 2, "binding", "request", 2),
    ("update", 2, "binding", "request", 3),
    ("update", 2, "acquisition", "adoption", 1),
    ("update", 2, "acquisition", "adoption", 2),
    ("update", 2, "acquisition", "adoption", 3),
))
def test_row1_read_between_saved_public_transitions_reenters_without_losing_or_duplicating_successors(flow, lap, left, right, k):
    """F-b :323-327,3328-3332,3505,3509-3514; CE1 :2917-2923; v2 :17-25,31.

    Losing a successor after the interval's kth read fails R2's bounded mandatory progress, not just safety.
    Replacing a fixed preparation fails R1; duplicated T/PR/EV/EQ/draw/result/adoption fails explicit counts.
    Re-entering/relaunching/redrawing/reacquiring fails R3; recounting a report changes FIRST/SECOND.
    """
    rig = Row1IntervalRig(flow, lap, left, right, k)
    cut = rig.cut
    try:
        try:
            finish_row1_loop(rig, cut, already_started=False)
        except AssertionError:
            if cut.hits == 0:
                raise AssertionError(f"UNFIRED_INTERVAL {cut.target}; available_reads={len(cut.reads)}") from None
            raise
        points = cut.saved_points()
        assert set(cut.committed) == {cid for cid, _ in cut.raw_load()}, "fixture: incomplete saved-point observer"
        assert cut.hits == 1 and len(cut.reads) == k
        assert points[left] == cut.left_at_loss and points[right] in dict(cut.raw_load())
        if cut.clock_before_g:
            assert points["acquisition_clock"] == cut.clock_before_g, "fixture: wrong result acquisition clock boundary"
        assert len(rig.requests("evaluation_prepare")) == len(rig.facts(c.PREPARED)) == 3, "R2: duplicate prepare successor"
        assert len(rig.requests("selection_draw")) == len(rig.facts(contract("sui.f.draw_fact"))) == 3, "R2: duplicate draw successor"
        assert len(rig.requests("evaluation")) == len(rig.facts(c.EVALUATED)) == 3, "R2: duplicate evaluation successor"
        assert len(rig.facts(CG)) == 1, "R2: duplicate candidate successor"
        for work in rig.workers.entries:
            terminals = [t for t in rig.facts(c.WORK_TERMINAL) if t.value["request"] == work.request]
            assert len(terminals) <= 1, "R2: duplicate terminal"
            if work.desc.purpose not in ("measure_segment", "selection_draw"):
                assert len(terminals) == 1, "R2: missing terminal"
                assert len([r for r in rig.facts(c.WORK_REPORT) if r.value["work"] == work.desc.work_id]) == 1
    finally:
        rig.close()


def complete_row1_tail_scene(rig, *, inject):
    """Use the identical public Boot/Post schedule for calibration and the fault walk."""
    cut = rig.cut
    def on_loss():
        assert cut.hits == 1
        if "measure_segment" in rig.workers.contexts:
            rig.clock.set(rig.clock.mono_ns() + 10)
    driver = Row1Driver(rig, cut, on_loss)
    driver.advance_until(lambda: len(rig.facts(c.SELECTION)) == 1 and bool(rig.thread))
    rig.clock.set(max(20, rig.clock.mono_ns() + 1))
    first = post_row2_claim(driver, slot="tail-first", start=0, end=2)
    driver.advance_until(lambda: len(rig.facts(c.BELIEF_ADOPTED)) >= 1)
    a1 = rig.facts(c.BELIEF_ADOPTED)[0]
    w1 = next(w for w in rig.workers.entries if w.request == a1.value["request"])
    assert_update(rig, w1, a1, FIRST)
    rig.clock.set(rig.clock.mono_ns() + 10)
    second = post_row2_claim(driver, slot="tail-second", start=1, end=3, wait_saved=False)
    driver.advance_until(lambda: len(rig.facts(c.BELIEF_ADOPTED)) == 2 and len(rig.facts(c.SELECTION)) == 3)
    a2 = rig.facts(c.BELIEF_ADOPTED)[1]
    w2 = next(w for w in rig.workers.entries if w.request == a2.value["request"])
    assert_update(rig, w2, a2, SECOND, a1.cid)
    assert row5_report_for_work(rig, w1).cid == first.cid
    assert row5_report_for_work(rig, w2).value == wire(second)
    assert [a.value["previous"] for a in rig.facts(c.BELIEF_ADOPTED)] == [None, a1.cid], "R2: adoption fork"
    assert len(rig.requests("belief_update")) == len(rig.facts(c.UPDATE_RESULT)) == 2
    assert len(rig.requests("evaluation_prepare")) == len(rig.facts(c.PREPARED)) == 3, "R2: duplicate prepare successor"
    assert len(rig.requests("selection_draw")) == len(rig.facts(contract("sui.f.draw_fact"))) == 3, "R2: duplicate draw successor"
    assert len(rig.requests("evaluation")) == len(rig.facts(c.EVALUATED)) == 3, "R2: duplicate evaluation successor"
    assert len(rig.facts(CG)) == 1
    assert len(rig.workers.entries) == len(rig.launcher.attempts) == 13, "R3: extra launch or body"
    ctx = rig.workers.contexts["measure_segment"]
    for work in rig.workers.entries:
        assert [ok for key, ok in rig.workers.entry_attempts if key == work.desc.work_id] == [True], "R3: duplicate entry"
        observed = execution_for(ctx, work.desc.work_id)
        assert observed.entered == 1 and observed.launches == ("launched",), "R3: duplicate execution"
        terminals = [t for t in rig.facts(c.WORK_TERMINAL) if t.value["request"] == work.request]
        assert len(terminals) <= 1, "R2: duplicate terminal"
        if work.desc.purpose not in ("measure_segment", "selection_draw"):
            assert len(terminals) == 1, "R2: missing terminal"
            assert len([r for r in rig.facts(c.WORK_REPORT) if r.value["work"] == work.desc.work_id]) == 1
    assert len([event for event, _ in rig.workers.sent if isinstance(event, fb.DrawReturned)]) == 3, "R3: extra draw use"
    for result in rig.facts(c.UPDATE_RESULT):
        acquisitions = [a for a in ctx.evidence().acquisitions if result.cid in a.contents]
        assert len(acquisitions) == 1, f"R3: repeated acquisition at {[a.acquired_ns for a in acquisitions]}"
        acquired, = (g for g in rig.facts(ACQUIRED) if result.cid in g.value["contents"])
        clock = rig.one(CLOCK, cid=acquired.value["clock"])
        assert clock.value["reading"]["time_ns"] == acquisitions[0].acquired_ns, "R3: acquisition time changed"
    points = cut.saved_points()
    assert set(cut.committed) == {cid for cid, _ in cut.raw_load()}, "fixture: incomplete saved-point observer"
    assert cut.left in points and cut.right in points, "R2: missing interval successor"
    if inject:
        assert cut.hits == 1, f"UNFIRED_TAIL {cut.target}; available_reads={len(cut.reads)}"
        assert len(cut.reads) == cut.k and points[cut.left] == cut.left_at_loss
        assert driver.handled and driver.calls > driver.call_at_loss and cut.confirmed
        cut.assert_fixed_preparations()
    else:
        assert cut.hits == 0 and not cut.failed, "fixture: calibration must have no injected failure"


@pytest.fixture(scope="module")
def row1_tail_profile(request):
    flow, lap, left, right = request.param
    rig = Row1IntervalRig(flow, lap, left, right, None)
    try:
        complete_row1_tail_scene(rig, inject=False)
        count = len(rig.cut.reads)
        assert count >= 3, f"TAIL_BASELINE_TOO_SHORT {flow}{lap}:{left}->{right}; reads={count}"
        print(f"TAIL_BASELINE {flow}{lap}:{left}->{right} reads={count}", flush=True)
        return flow, lap, left, right, count
    finally:
        rig.close()


def check_row1_tail_target(profile, k):
    flow, lap, left, right, count = profile
    rig = Row1IntervalRig(flow, lap, left, right, k)
    try:
        try:
            complete_row1_tail_scene(rig, inject=True)
        except AssertionError as error:
            if rig.cut.hits == 0:
                raise AssertionError(f"UNFIRED_TAIL {flow}{lap}:{left}->{right}; "
                    f"baseline_reads={count}, target={k}, available_reads={len(rig.cut.reads)}; {error}") from None
            raise
    finally:
        rig.close()


@pytest.mark.parametrize("from_end", (0, 1, 2), ids=("last", "last-minus-1", "last-minus-2"))
@pytest.mark.parametrize("row1_tail_profile", (
    pytest.param(("update", 1, "binding", "request"), id="update1-binding-request"),
    pytest.param(("update", 2, "binding", "request"), id="update2-binding-request"),
    pytest.param(("update", 1, "work_report", "terminal"), id="update1-report-terminal"),
    pytest.param(("update", 2, "work_report", "terminal"), id="update2-report-terminal"),
    pytest.param(("update", 1, "terminal", "result"), id="update1-terminal-result"),
    pytest.param(("update", 2, "terminal", "result"), id="update2-terminal-result"),
    pytest.param(("update", 1, "acquisition", "adoption"), id="update1-acquisition-adoption"),
    pytest.param(("update", 2, "acquisition", "adoption"), id="update2-acquisition-adoption"),
    pytest.param(("update", 1, "adoption", "continuation_request"), id="update1-adoption-continuation"),
    pytest.param(("update", 2, "adoption", "continuation_request"), id="update2-adoption-continuation"),
    pytest.param(("initial", 1, "candidate_report", "candidates"), id="initial-report-candidates"),
    pytest.param(("initial", 1, "candidates", "prepare_request"), id="initial-candidates-prepare"),
    pytest.param(("initial", 1, "prepare_report", "prepared"), id="initial-report-prepared"),
    pytest.param(("initial", 1, "draw_fact", "evaluate_request"), id="initial-draw-evaluate"),
    pytest.param(("initial", 1, "evaluate_report", "evaluated"), id="initial-report-evaluated"),
), indirect=True)
def test_row1_interval_tail_reads_reenter_without_losing_or_duplicating_successors(row1_tail_profile, from_end):
    """F-b :323-327,3328-3332,3437,3509-3513; CE1 :2917-2923; v2 :19,31.

    A lost request/terminal successor after a late read fails R2's bounded mandatory progression.
    New preparation/time/boundary fails R1; duplicate successors or external effects fail R2/R3.
    Select N, N-1, N-2 from this scene's fault-free count; a shorter fault walk fails UNFIRED_TAIL.
    Positions are relative to the measured baseline, never silently recalibrated or skipped after a miss.
    """
    count = row1_tail_profile[-1]
    check_row1_tail_target(row1_tail_profile, count - from_end)


@pytest.mark.parametrize("row1_tail_profile", (
    pytest.param(("update", 1, "binding", "request"), id="update1-binding-request"),
    pytest.param(("update", 2, "binding", "request"), id="update2-binding-request"),
), indirect=True)
def test_row1_interval_middle_read_reenters_without_losing_the_update_request(row1_tail_profile):
    """Use the measured midpoint ceil(N/2) as well as the tail for the two B -> Q* intervals.

    Losing Q* after this read fails R2; replacing a preparation or repeating work/acquisition fails R1/R3.
    """
    count = row1_tail_profile[-1]
    check_row1_tail_target(row1_tail_profile, (count + 1) // 2)


class Row1ReadsBeforeAttempt(list):
    """The old interval recorder stops appending at the physical store's first attempt."""

    def __init__(self, boundary):
        super().__init__()
        self.boundary = boundary

    def append(self, item):
        if self.boundary.first is None:
            super().append(item)


class Row1FirstWriteAttempt:
    """Observe put/add arguments, without treating a proposed Point as a saved Point."""

    def __init__(self, rig):
        from test_fb_stage1 import decode_record, seal
        self.rig, self.cut, self.first = rig, rig.cut, None
        self.target_k = self.cut.k
        self.cut.reads = Row1ReadsBeforeAttempt(self)
        normal_put, normal_add = rig.contents.put, rig.entry_store.add
        def put(value_seal, salt, content):
            prepared = next((p for p in reversed(rig.ledger.preparations)
                if p.salt == salt and self.cut.entry_from_header(p.cid, p.header).seal == value_seal), None)
            if prepared is not None and self.matches(prepared):
                assert seal(content, salt) == value_seal
                assert decode_record(prepared.header, content) == prepared.record
                self.observe(prepared, "put")
            return normal_put(value_seal, salt, content)
        rig.contents.put = put
        def add(cid, header):
            prepared = next((p for p in reversed(rig.ledger.preparations) if p.cid == cid), None)
            if prepared is not None and self.matches(prepared):
                assert header == prepared.header
                self.observe(prepared, "add")
            return normal_add(cid, header)
        rig.entry_store.add = add

    def matches(self, prepared):
        refs = {"request": c.WORK_REQUESTED, "candidates": CG, "evaluated": c.EVALUATED,
                "terminal": c.WORK_TERMINAL, "adoption": c.BELIEF_ADOPTED}
        if prepared.record.body.contract != refs[self.cut.right]:
            return False
        points = self.cut.saved_points()
        if self.cut.left not in points:
            return False
        value = prepared.record.body.content.as_json()
        if self.cut.right == "request":
            return value["desc"]["purpose"] == "belief_update" and any(
                o["binding"] == points["binding"] for o in value["desc"]["args"]["observations"])
        if self.cut.right in ("terminal", "adoption"):
            return value["request"] == points.get("request")
        # Only the initial CG/EV can follow the first candidate/evaluation report in this scene.
        return self.cut.flow == "initial"

    def observe(self, prepared, port):
        if self.first is not None:
            return
        points = self.cut.saved_points()
        headers = dict(self.cut.raw_load())
        value_seal = self.cut.entry_from_header(prepared.cid, prepared.header).seal
        self.first = {"port": port, "prepared": prepared, "reads": len(self.cut.reads),
            "left": points[self.cut.left], "fault_already_fired": self.cut.failed,
            "entry_present": prepared.cid in headers, "body_present": value_seal in self.rig.contents.seals()}
        assert self.cut.right not in points and not self.first["entry_present"], "fixture: cutoff was after entry commit"
        if not self.cut.failed:
            # A shorter fault walk must never move the injection into put's/add's later reads.
            self.cut.k = None

    def assert_boundary(self, *, inject):
        assert self.first is not None, "fixture: target write attempt was not observed"
        assert self.first["port"] == "put" and not self.first["body_present"], \
            "fixture: the first body-put boundary was missed"
        points = self.cut.saved_points()
        assert points[self.cut.left] == self.first["left"]
        assert points[self.cut.right] == self.first["prepared"].cid, "R1/R2: first attempted record was replaced"
        assert len(self.cut.reads) == self.first["reads"], "fixture: reads after the first attempt were counted"
        assert self.first["fault_already_fired"] == inject, "fixture: failure was not before the first write attempt"


def make_row1_prewrite_rig(flow, lap, left, right, k):
    rig = Row1IntervalRig(flow, lap, left, right, k)
    # Boot is only queued so far; attach both public store ports before the first run_until.
    rig.prewrite = Row1FirstWriteAttempt(rig)
    return rig


@pytest.fixture(scope="module")
def row1_prewrite_profile(request):
    flow, lap, left, right = request.param
    rig = make_row1_prewrite_rig(flow, lap, left, right, None)
    try:
        complete_row1_tail_scene(rig, inject=False)
        rig.prewrite.assert_boundary(inject=False)
        count = len(rig.cut.reads)
        required = 12 if right == "request" else 4
        assert count >= required, f"PREWRITE_BASELINE_TOO_SHORT {flow}{lap}:{left}->{right}; reads={count}"
        print(f"PREWRITE_BASELINE {flow}{lap}:{left}->{right} reads={count} first=put", flush=True)
        return flow, lap, left, right, count
    finally:
        rig.close()


def check_row1_prewrite_target(profile, from_end):
    flow, lap, left, right, count = profile
    k = count - from_end
    rig = make_row1_prewrite_rig(flow, lap, left, right, k)
    try:
        try:
            complete_row1_tail_scene(rig, inject=True)
        except AssertionError as error:
            if rig.cut.hits == 0:
                raise AssertionError(f"UNFIRED_PREWRITE {flow}{lap}:{left}->{right}; "
                    f"baseline_reads={count}, target={k}, before_first_attempt={len(rig.cut.reads)}; {error}") from None
            raise
        rig.prewrite.assert_boundary(inject=True)
        assert rig.cut.k == k and rig.cut.hits == 1
    finally:
        rig.close()


@pytest.mark.parametrize("from_end", (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11))
@pytest.mark.parametrize("row1_prewrite_profile", (
    pytest.param(("update", 1, "binding", "request"), id="update1-binding-request"),
    pytest.param(("update", 2, "binding", "request"), id="update2-binding-request"),
), indirect=True)
def test_row1_before_first_request_put_last_twelve_reads_keep_the_update_chain(row1_prewrite_profile, from_end):
    """F-b PrepareOne/PutBody :324-325, update request :3328, K13 :3513; CE1 :2917-2923.

    A lost Q* after a read before its first put fails R2's mandatory successors, even if no write was attempted.
    Replacing a fixed preparation or duplicating a successor fails R1/R2; repeated external effects fail R3.
    Count N before the first physical put/add, then inject N..N-11; UNFIRED is a failure, never a late injection.
    """
    check_row1_prewrite_target(row1_prewrite_profile, from_end)


@pytest.mark.parametrize("from_end", (0, 1, 2, 3))
@pytest.mark.parametrize("row1_prewrite_profile", (
    pytest.param(("initial", 1, "candidate_report", "candidates"), id="initial-report-candidates"),
    pytest.param(("initial", 1, "evaluate_report", "evaluated"), id="initial-report-evaluated"),
    pytest.param(("update", 1, "work_report", "terminal"), id="update1-report-terminal"),
    pytest.param(("update", 1, "acquisition", "adoption"), id="update1-acquisition-adoption"),
), indirect=True)
def test_row1_before_first_successor_put_last_four_reads_preserve_progress(row1_prewrite_profile, from_end):
    """F-b :323-327,3330-3332,3442-3444,3509: the permitted four-position smaller range.

    A missing CG/EV/T/A* after a pre-put read fails R2; duplicate records or repeated work/acquisition fail R1/R2/R3.
    """
    check_row1_prewrite_target(row1_prewrite_profile, from_end)
