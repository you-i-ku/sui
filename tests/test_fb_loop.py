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
        self.measurement_started_posted = Event()
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
            self.measurement_started_posted.set()
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
        event = replace(event, declaration=replace(event.declaration, perception=replace(
            event.declaration.perception, value=replace(event.declaration.perception.value,
                model=self.model_point, derivation=fb.SlottedMethod(slot='delta', method=fb.MethodCall(contract=c.SAVED_SEGMENT_UPDATE, args=delta_args()))))))
        initial = replace(event.declaration.initial.value, generator=fb.MethodCall(contract=c.MODEL_OPERATIONS, args={}), method=fb.MethodCall(contract=contract('sui.f.finite_evaluation'), args={}), draw=fb.MethodCall(contract=contract('stage2.scripted_draw'), args={}), prepare_budget=PREPARE_BUDGET, evaluate_budget=EVALUATE_BUDGET, continuation=fb.MethodCall(contract=c.REUSE_CANDIDATES, args={}) if continuation else None)
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


    def close(self):
        self.workers.release.set()
        if self.thread is not None:
            self.thread.join(2)
            assert not self.thread.is_alive(), "test measurement worker did not stop"




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



def acquisition_loop_rig(**kwargs):
    """K28 host path; no producer Claim or synthetic adoption is substituted."""
    from test_fb_belief import BeliefRig, T, E, U
    class AcquisitionLoopRig(BeliefRig):
        def start(self):
            self.begin()
            for stage in ORDER: self.run_stage(stage)
            self.until(lambda: len(self.facts(c.SELECTION)) == 1)
        def adopt(self, number):
            self.publish(number-1, last=number == 2)
            return self.update()
    matrices = {T: ((F(1,4), 0), (0, F(1,16))),
                E: ((F(1,2), 0), (0, F(1,4))),
                U: ((F(1,4), 0), (0, F(11,16)))}
    return AcquisitionLoopRig(symbols=(T,E), matrices=matrices, targets=("x0","x1"), **kwargs)


@pytest.fixture
def make_acquisition_loop():
    rigs = []
    def make(**kwargs):
        rig = acquisition_loop_rig(**kwargs); rigs.append(rig); return rig
    yield make
    for rig in reversed(rigs): rig.close()


def test_two_acquisition_updates_from_public_boot_read_actual_records(make_acquisition_loop):
    """K28 migration 1: real SourceMeasurer/FiniteUpdater and public B/Q/R/G/A.

    T=diag(1/4,1/16), E=diag(1/2,1/4) give CE1 FIRST and SECOND.
    Claim-overlap arithmetic remains U-direct in test_fb_update_entry.py.
    Dropping E, counting T twice, or forking previous fails the exact chain.
    """
    rig = make_acquisition_loop()
    rig.start()
    previous = None
    for number, answer in ((1, FIRST), (2, SECOND)):
        work, adopted = rig.adopt(number)
        assert_update(rig, work, adopted, answer, previous)
        previous = adopted.cid
        use, = work.desc.args.observations
        binding = rig.one(c.SEGMENT_BINDING, cid=use.binding)
        frame = rig.one(c.SEGMENT_REPORT, cid=binding.value["report"])
        assert frame.value["item"]["kind"] == "frame"
        assert frame.value["item"]["value"]["sample_seq"] == number-1
    assert len(rig.facts(c.BELIEF_ADOPTED)) == len(rig.calls) == 2
    assert not rig.reports("claim")


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




def assert_admitted_evaluation_root(rig, request, adopted=None):
    """K36-c: name the admitted root at o, not a notification's cause."""
    context = request.value["desc"]["args"]["input"]["context"]
    activity, = [row for row in rig.host.window.status().evaluations if row.context == context]
    assert activity.root == ("prior" if adopted is None else "adopted")
    assert activity.root_point == (None if adopted is None else adopted.cid)
    assert activity.outcome == "running" and activity.counted
    return activity.activity


def wait_evaluation_activity_end(rig, activity):
    """Serial rulers deliberately finish/release one activity before the next input."""
    def completed():
        rows = [row for row in rig.host.window.status().evaluations if row.activity == activity]
        return len(rows) == 1 and rows[0].outcome != "running" and not rows[0].counted
    rig.drive(completed)
    assert completed()

def assert_quantity(value, expected):
    assert value.status == "finite" and value.exact is not None
    assert abs(decimal_real(value.exact) - expected) < Decimal("1e-35")


@pytest.mark.parametrize("continuation", (False, True), ids=("none", "reuse_candidates"))
def test_continuation_uses_adopted_joint_in_math_input_and_information(make_acquisition_loop, continuation):
    """F-b :3489,3497(2),3510,3512; F-a M-09/M-17.

    Reusing model.initial fails H(4/5), H(8/9) and the adopted R* input, even if the choice agrees.
    """
    rig = make_acquisition_loop(continuation=continuation)
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
        activity = assert_admitted_evaluation_root(rig, eq, adopted)
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
        wait_evaluation_activity_end(rig, activity)
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
    rig = acquisition_loop_rig(continuation=True, asymmetric=True)
    try:
        rig.start()
        work, adopted = rig.adopt(1)
        result = assert_update(rig, work, adopted, FIRST)
        rig.drive(lambda: len(rig.requests("evaluation_prepare")) == 2)
        eq = rig.requests("evaluation_prepare")[-1]
        activity = assert_admitted_evaluation_root(rig, eq, adopted)
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
        wait_evaluation_activity_end(rig, activity)
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




def execution_for(ctx, work_id):
    return next(observation for observation in ctx.evidence().executions
                if observation.work_id == work_id)


















def row5_report_for_work(rig, work):
    use, = work.desc.args.observations
    binding = rig.one(c.SEGMENT_BINDING, cid=use.binding)
    return rig.one(c.SEGMENT_REPORT, cid=binding.value["report"])














ROW3_ONE_POINT = {"joint": [[2, 3], [1, 3]], "evidence_mass": [3, 8]}


















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
            if self.failed and is_target and getattr(self, "in_host", True):
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
    """Drive bounded public host rounds, including re-entry after the one injected store exception."""

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
        # timeout=0 makes each call one public round, as in the deadline tests.
        # The harness step bound also detects a missing successor under CPU load.
        for _ in range(128):
            self.calls += 1
            try:
                self.rig.host.run_until(lambda _status: done(), timeout=0)
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
            if done():
                return
        raise AssertionError("incomplete observation: public successor not reached within the harness step bound")

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






class Row1StoreCut:
    """One public store/ledger operation fails; the independent C/E oracle never does."""

    def __init__(self, rig, target, operation, *, ordinal=1, read_occurrence=1,
                 report_kind="claim"):
        from hashlib import sha256
        from test_fb_stage1 import SavedFact, entry_from_header, decode_record, encode_header, seal
        self.rig, self.target, self.operation, self.ordinal = rig, target, operation, ordinal
        self.report_kind = report_kind
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
            return value["item"]["kind"] == self.report_kind
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


















class Row1IntervalCut(Row1StoreCut):
    """Count outermost public record reads between actual saved X and not-yet-saved Y."""

    def __init__(self, rig, flow, lap, left, right, k, *, report_kind="claim"):
        from threading import get_ident
        public_reads = ((rig.ledger, "entry", rig.ledger.entry),
                        (rig.ledger, "record", rig.ledger.record), (rig.contents, "get", rig.contents.get))
        super().__init__(rig, "request", "interval", read_occurrence=k,
                         report_kind=report_kind)
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
            reports = [cid for cid, record in facts if record.body.contract == c.SEGMENT_REPORT
                       and record.body.content.as_json()["item"]["kind"] == self.report_kind]
            raw = reports[self.lap - 1] if len(reports) >= self.lap else None
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




# The initial Ep/D/Ee request -> report intervals each had one runner read.
# Their k=2/3 combinations are intentionally absent (observed, not skipped/xfail).












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














class KeepStoreFault:
    """Fail only a real public store call on the keep_running caller's thread."""

    def __init__(self, rig, *, boundary=None, target="request", times=1,
                 exception_type=OSError, each_update=False, guard=None):
        from threading import get_ident
        self.rig, self.boundary, self.target = rig, boundary, target
        self.times, self.exception_type, self.each_update, self.guard = times, exception_type, each_update, guard
        self.enabled, self.runner, self.get_ident = boundary is not None, get_ident(), get_ident
        self.selected, self.raised, self.counts, self.fixed = [], [], {}, {}
        self.message = "keep test store temporarily unavailable"
        put, add, record = rig.contents.put, rig.entry_store.add, rig.ledger.record
        def put_fault(value_seal, salt, content):
            prepared = next((p for p in reversed(rig.ledger.preparations)
                if p.salt == salt and rig.oracle.entry_from_header(p.cid, p.header).seal == value_seal), None)
            if boundary == "before_body":
                self.fail(prepared)
            value = put(value_seal, salt, content)
            if boundary == "after_body_commit":
                self.fail(prepared)
            return value
        rig.contents.put = put_fault
        def add_fault(cid, header):
            value = add(cid, header)
            if boundary == "after_entry_commit":
                self.fail(next((p for p in reversed(rig.ledger.preparations) if p.cid == cid), None))
            return value
        rig.entry_store.add = add_fault
        def record_fault(cid):
            if boundary == "read" and cid in dict(rig.oracle.raw_load()):
                self.fail(next((p for p in reversed(rig.ledger.preparations) if p.cid == cid), None))
            return record(cid)
        rig.ledger.record = record_fault

    def matches(self, prepared):
        if prepared is None:
            return False
        if self.target == "any":
            return True
        ref = {"request": c.WORK_REQUESTED, "result": c.UPDATE_RESULT, "adoption": c.BELIEF_ADOPTED}[self.target]
        if prepared.record.body.contract != ref:
            return False
        return self.target != "request" or prepared.record.body.content.as_json()["desc"]["purpose"] == "belief_update"

    def fail(self, prepared):
        if not self.enabled or self.get_ident() != self.runner or not self.matches(prepared):
            return
        if self.selected and not self.each_update and prepared.cid != self.selected[0]:
            return
        if prepared.cid not in self.selected:
            self.selected.append(prepared.cid)
        count = self.counts.get(prepared.cid, 0)
        if self.times is not None and count >= self.times:
            return
        if self.guard is not None and len(self.raised) >= self.guard:
            raise RuntimeError("test watchdog: zero-timeout keep_running made extra attempts")
        self.fixed.setdefault(prepared.cid, tuple(self.rig.ledger.preparations))
        self.counts[prepared.cid] = count + 1
        self.rig.clock.set(self.rig.clock.mono_ns() + 1)
        error = self.exception_type(self.message)
        self.raised.append(error)
        raise error

    def assert_preparations(self):
        headers = dict(self.rig.oracle.raw_load())
        for snapshot in self.fixed.values():
            for prepared in snapshot:
                assert prepared.cid in headers, "R1: fixed preparation was abandoned"
                assert all(p == prepared for p in self.rig.ledger.preparations if p.record.id == prepared.record.id), \
                    "R1: fixed preparation changed"
                assert self.rig.read_stored(prepared.cid) == (prepared.header, prepared.salt, prepared.record)




def assert_keep_interruption(interruption, error, *, kind, count):
    assert isinstance(interruption, fb.Interruption) and interruption.kind == kind
    assert interruption.operation
    # The contract does not choose qualified versus unqualified Python type spelling.
    assert interruption.error_type in (type(error).__name__, type(error).__module__ + "." + type(error).__name__)
    assert interruption.message == str(error) and interruption.count == count
    assert isinstance(interruption.first_ns, int) and isinstance(interruption.last_ns, int)
    assert interruption.first_ns <= interruption.last_ns
















def test_keep_running_zero_timeout_checks_one_deadline_even_during_store_failure():
    """K16 (2)/(5): timeout=0 returns after the failed round, without an elapsed-time assertion.

    Renewing/skipping the deadline repeats the fault and reaches the store's test watchdog instead of returning False.
    """
    from test_fb_acquisition_keep import AcquisitionKeepRig
    rig = AcquisitionKeepRig(fault={"boundary": "before_body", "target": "any", "times": None, "guard": 4})
    try:
        assert rig.host.keep_running(lambda _s: False, timeout=0) is False
        assert len(rig.fault.raised) == 1
        history, = rig.host.interruptions()
        assert_keep_interruption(history, rig.fault.raised[0], kind="store", count=1)
        assert rig.host.halted is None
    finally:
        rig.close()








def row6_initial_ready(rig):
    errors = rig.workers.errors + rig.launcher.errors + rig.post_errors
    if errors:
        raise errors[0]
    if len(rig.facts(c.SELECTION)) != 1 or len(rig.workers.entries) != 5:
        return False
    for work in rig.workers.entries:
        if work.desc.purpose != "measure_segment" and work.desc.work_id not in rig.workers.stops:
            return False
        if work.desc.purpose not in ("measure_segment", "selection_draw"):
            if len([t for t in rig.facts(c.WORK_TERMINAL) if t.value["request"] == work.request]) != 1:
                return False
    ctx = rig.workers.contexts.get("measure_segment")
    work = next(w for w in rig.workers.entries if w.desc.purpose == "measure_segment")
    return ctx is not None and any(r.point is not None for r in execution_for(ctx, work.desc.work_id).reports)








def test_row6_accept_clock_fault_halts_instead_of_rejecting_a_legal_report():
    """A legal Received at r=40 cannot save at s=20; non-shape fault halts."""
    rig = RealRig(connect=False)
    rig.clock.set(0)
    rig.host = fb.FThreadHost(ledger=rig.ledger, clock=rig.clock, workers=rig.workers, registry=rig.registry)
    try:
        rig.clock.set(40)
        rig.host.post(fb.Received(route_epoch="route-A", media_type="application/octet-stream", data=b"valid-clock-probe", claims={}))
        rig.clock.set(20)
        before = rig.storage_snapshot()
        with pytest.raises(fb.FHalted) as caught:
            rig.host.keep_running(lambda _s: False, timeout=0)
        assert isinstance(caught.value.__cause__, fb.FbHostFault)
        interruption, = rig.host.interruptions()
        assert interruption.kind == "halted" and rig.host.halted == interruption
        assert rig.storage_snapshot() == before
    finally: rig.close()


def test_row6_run_until_still_raises_shape_and_keeps_the_malformed_head():
    """run_until propagates the same shape refusal twice without custody/history."""
    rig = RealRig()
    try:
        before = rig.storage_snapshot()
        rig.host.post(fb.Received(route_epoch="route-A", media_type=999999, data=b"malformed", claims={}))
        for _ in range(2):
            with pytest.raises(fb.FbInputError) as caught:
                rig.host.run_until(lambda _s: False, timeout=0)
            assert caught.value.reason == "shape" and "media_type" in caught.value.field
            assert rig.storage_snapshot() == before
        assert rig.host.halted is None and rig.host.interruptions() == ()
    finally: rig.close()














class Scene17ConcurrentRead:
    """Interleave at public accept/settle return, after releasing that operation's lock but before the driver catches E1."""

    def __init__(self, rig, mode):
        from threading import get_ident
        self.rig, self.mode, self.get_ident, self.runner = rig, mode, get_ident, get_ident()
        self.ready, self.go, self.done = Event(), Event(), Event()
        self.worker = None
        self.armed = self.in_runner_read = self.worker_read = False
        self.runner_error = OSError("scene17 runner store E1" if mode == "store" else "scene17 clock E1 is not storage")
        self.worker_error = OSError("scene17 entered worker ctx.read E2")
        self.order, self.worker_caught, self.fixed = [], [], ()
        get, record, now = rig.contents.get, rig.ledger.record, rig.clock.now

        def get_with_fault(value_seal):
            if get_ident() == self.worker and self.worker_read:
                self.worker_read = False
                self.order.append("worker store E2")
                raise self.worker_error
            if get_ident() == self.runner and self.in_runner_read:
                self.in_runner_read = False
                self.order.append("runner store E1")
                raise self.runner_error
            return get(value_seal)

        def record_with_interleaving(point):
            if get_ident() != self.runner or not self.armed or mode != "store":
                return record(point)
            self.armed = False
            self.fixed = tuple(rig.ledger.preparations)
            self.in_runner_read = True
            try:
                record(point)
            except OSError as error:
                assert error is self.runner_error
                raise
            finally:
                self.in_runner_read = False
            raise AssertionError("CONNECTION: the runner's store fault did not fire")

        def clock_with_interleaving():
            if get_ident() == self.runner and self.armed and mode == "clock":
                self.armed = False
                self.fixed = tuple(rig.ledger.preparations)
                self.order.append("runner clock E1")
                raise self.runner_error
            return now()

        rig.contents.get, rig.ledger.record, rig.clock.now = get_with_fault, record_with_interleaving, clock_with_interleaving
        def interleave(operation):
            def call(*args, **kwargs):
                try:
                    value = operation(*args, **kwargs)
                except OSError as error:
                    if error is self.runner_error:
                        # The public operation has unwound, so ctx.read can acquire its own locks.
                        # keep_running has not received E1 yet; E2 must finish before this rethrow.
                        self.release_worker()
                        self.order.append("runner rethrows E1")
                    raise
                if mode == "worker_only" and self.armed:
                    self.armed = False
                    self.fixed = tuple(rig.ledger.preparations)
                    self.release_worker()
                return value
            return call
        window = rig.host.window
        window.accept = interleave(window.accept)
        window.settle = interleave(window.settle)
        def read_from_entered_worker(work, ctx):
            self.worker = get_ident()
            assert self.worker != self.runner
            assert execution_for(ctx, work.desc.work_id).entered == 1
            self.ready.set()
            assert self.go.wait(30), "CONNECTION: runner did not release the independent worker read"
            self.worker_read = True
            try:
                ctx.read(rig.model_point)
            except OSError as error:
                self.worker_caught.append(error)
            else:
                raise AssertionError("CONNECTION: ctx.read did not encounter E2")
            finally:
                self.worker_read = False
        rig.workers.commands.put((read_from_entered_worker, self.done, rig.post_errors))
        assert self.ready.wait(30), "CONNECTION: measurement worker did not reach the read gate"
        self.armed = True

    def release_worker(self):
        self.go.set()
        assert self.done.wait(30), "CONNECTION: entered ctx.read could not finish while the runner was suspended"
        assert not self.rig.post_errors and self.worker_caught == [self.worker_error]

    def assert_fixed(self):
        for prepared in self.fixed:
            assert self.rig.read_stored(prepared.cid) == (prepared.header, prepared.salt, prepared.record)
            assert all(p == prepared for p in self.rig.ledger.preparations if p.record.id == prepared.record.id)


























































