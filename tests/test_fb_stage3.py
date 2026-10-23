"""F-b stage 3: fixtures plus paper through v0.36; public interfaces only.

Oracle: specs/関所F_Fb_今の約束.md:3293-3360,3395-3399,3468-3501 and
2596-2931,3080-3092, v0.31:3530-3665 and v0.32:3698-4510; F-a paper V/A/M/E.
No implementation was inspected.
Round 15's normative source is src/sui/fb_rules.md v1.2:26-50,292-299,
370-397,1615-1712; paper v0.35 Z25-Z28:3706-3709 and v0.36 Z29:3710.
The fixture owns workers, a deterministic clock, and public store adapters.
It does not inject P, private workers, a belief, or an issued handle.
FStatus is never used to compute an expectation. Timeouts are incomplete
observations, not a specified latency. ContractGap is a failing assertion.
An explicitly unreachable public scenario is documented and skipped, not
counted as verified. The cases below do not claim to close all of stage 3.

Discrimination is specified in each test before choosing its fixture. In
particular, CE1 distinguishes dropping the second claim from counting its
overlap twice; continuation checks the information calculation, not choice.
Only this file is authorized for writing. Obsidian/Heat and commits are not
modified in this task (the latest, narrower user instruction takes priority).
Reused knowledge: stage-2 independent C/E observer and deferred launcher;
their scope is the real stores in one process, including window rebuilds.
"""

from collections import Counter
from dataclasses import replace
from fractions import Fraction as F
from hashlib import sha256
from itertools import product
import json
from pathlib import Path
import ast
from decimal import Decimal, localcontext
from queue import Queue, Empty
from threading import Event, Thread, get_ident
from time import monotonic

import pytest

from sui import f, fb, fb_contracts as c, f_contracts as fc, f_facts as ff
from sui import f_update2 as u
from sui.contracts import ContractRef
from sui.ids import RefKind
from sui.ledger import entry_from_header
from sui.rate import RateBudget
from sui.records import Decided, Observed, Payload, Prediction, Role, Category

from gate_f_facts_cases import finite_world, plain, Reader
from test_fb_skeleton import ContractGap, boot, contract, source, segment_items
from test_fb_stage1 import (
    RealRig, ObservedContents, TestClock, wire, received,
    decode_record, encode_header, seal,
)
from test_fb_stage2 import (
    Stage2Ledger, Stage2Rig, LaunchCut, Workers as Stage2Workers, registry as stage2_registry,
    canonical, closure, front, events_for, assert_parents, captured_reader_key,
    MATH, CG, ORIGIN, CLOCK, CLOCK_SOURCE, PREPARE_BUDGET, EVALUATE_BUDGET,
)


PAPER = "specs/関所F_Fb_今の約束.md"
# 予算 C (紙 F-b Z34 (a)): 論理の仕事の上限 logical_limit と、読み手の像・数値計算の RateBudget を分けた UpdateBudget
UPDATE_BUDGET = u.UpdateBudget(contract=c.UPDATE_BUDGET, logical_limit=10**6,
                               numerical=RateBudget(F(1, 10**20), 16384, 32768, 48))


# 評価の準備が前の採用の系列を作り直す時の全体の論理の上限 (Z34 (a) 案 B)。更新の論理の上限と別の値にする (取り違えの識別)
REPLAY_LOGICAL_LIMIT = 10**6 + 7

# Harness watchdog, not a specified API latency. U may run for several seconds
# on another thread; scheduling under parallel pytest is not a semantic failure.
OBSERVATION_TIMEOUT = 60.0


def logical(budget, limit):
    """論理の上限だけを変えた予算 (数値計算の RateBudget はそのまま)。"""
    return replace(budget, logical_limit=limit)


def cells(budget, max_cells):
    """読み手の像の上限 (RateBudget.max_cells) だけを変えた予算。"""
    return replace(budget, numerical=replace(budget.numerical, max_cells=max_cells))
ACQUIRED = contract("sui.f.content_acquired")
ROUTE = contract("sui.f.route_config")
CE1_ROWS = (
    ((0, 0, 0), F(1, 8), F(1, 64)),
    ((0, 0, 1), F(1, 8), F(3, 64)),
    ((0, 1, 0), F(1, 8), F(3, 64)),
    ((0, 1, 1), F(1, 8), F(9, 64)),
    ((1, 0, 0), F(1, 8), F(3, 64)),
    ((1, 0, 1), F(1, 8), F(9, 64)),
    ((1, 1, 0), F(1, 8), F(9, 64)),
    ((1, 1, 1), F(1, 8), F(27, 64)),
)
FIRST = {"joint": [[4, 5], [1, 5]], "evidence_mass": [5, 32]}
SECOND = {"joint": [[8, 9], [1, 9]], "evidence_mass": [9, 128]}
DOUBLE = {"joint": [[16, 17], [1, 17]], "evidence_mass": [17, 512]}
REQUEST_CONTRACT = {
    "measure_segment": c.SEGMENT_REQUESTED,
    "candidate_generation": c.CANDIDATE_REQUEST,
    "evaluation_prepare": c.EVALUATION_REQUESTED,
    "selection_draw": c.DRAW_REQUESTED,
    "evaluation": c.WORK_REQUESTED,
    "belief_update": c.WORK_REQUESTED,
}


def delta_args():
    """K2:3490; literal CE1 table, independent of the reported observations."""
    return {
        "route": "route",
        "law": {
            "carrier_by_state": ["a", "b"],
            "channels": [{"id": "arrivals", "route_slots": ["route"],
                          "domain": {"start_ns": 0, "end_ns": 3,
                                     "closure": "(start,end]"}}],
            "rows": [{"marks": [{"channel": "arrivals", "time_ns": i + 1,
                                 "count": count} for i, count in enumerate(bits) if count],
                      # R is V-01's [numerator, denominator], not a decimal.
                      "mass": [plain(a), plain(b)]} for bits, a, b in CE1_ROWS],
        },
        "claims": [{"meaning": plain(c.NO_ARRIVAL), "channel": "arrivals"}],
        "generation": {"scope": "whole_window"},
    }


def registry():
    """J7:3478: native stage-3 capabilities, preserving old identities."""
    native, fixture = u.fb_registry_v1(), stage2_registry()
    declarations, implementations = {}, {}
    for reg in (native, fixture):
        for decl in reg.declarations:
            key = (decl.kind, decl.ref)
            if key in declarations:
                assert declarations[key] == decl, "old declaration changed"
            declarations[key] = decl
        for impl in reg.implementations:
            key = (impl.kind, impl.ref)
            if key in implementations:
                assert implementations[key].identity == impl.identity, "old identity changed"
            else:
                implementations[key] = impl
    required = (c.SAVED_SEGMENT_UPDATE, c.FINITE_UPDATE_COMPUTE,
                c.REUSE_CANDIDATES, c.FINITE_SEGMENT_PROJECTION,
                c.FINITE_JOINT_COUNT_LAW, c.OBSERVATION_PLAN_2,
                c.NO_ARRIVAL, c.BOOTSTRAP_GENERATION, c.SEGMENT_VALUE_ONLY)
    for ref in required:
        if not any(key[1] == ref for key in declarations):
            raise ContractGap("CG-FB3-REGISTRY-DECLARATION: " + ref.name)
        if not any(key[1] == ref for key in implementations):
            raise ContractGap("CG-FB3-REGISTRY-IMPLEMENTATION: " + ref.name)
    return f.make_f_registry(declarations=tuple(declarations.values()),
                             implementations=tuple(implementations.values()))


class ConfirmationContents(ObservedContents):
    """Public storage failure, independent of whether the entry index sees A*."""

    def __init__(self, original):
        super().__init__(original.store, original.faults)
        self.blocked = set()

    def get(self, value_seal):
        if value_seal in self.blocked:
            raise OSError("test: committed adoption body cannot yet be confirmed")
        return super().get(value_seal)


class Stage3Ledger(Stage2Ledger):
    def __init__(self, *, contents, **kwargs):
        super().__init__(contents=contents, **kwargs)
        self.observed_contents = contents
        self.hold_adoption_confirmation = False
        self.uncertain = None
        self.hold_result_confirmation = False
        self.uncertain_result = None
        self.hold_claim_confirmation = False
        self.uncertain_claim = None
        self.held_claim_attempts = []
        self.hold_context_before_write = False
        self.held_context = None
        self.held_context_attempts = []
        self.acquisition_phase = "input"

    def write(self, prepared):
        if (self.hold_context_before_write
                and prepared.record.body.contract == contract("sui.f.context_observed")):
            if self.held_context is None:
                self.held_context = prepared
            self.held_context_attempts.append(prepared)
            raise OSError("test: continuation context held before write")
        if (self.hold_claim_confirmation
                and prepared.record.body.contract == c.SEGMENT_REPORT
                and prepared.record.body.content.as_json()["item"]["kind"] == "claim"):
            if self.uncertain_claim is None:
                self.uncertain_claim = prepared
            self.held_claim_attempts.append(prepared)
            raise OSError("test: accepted Claim write held before commit")
        if (self.hold_result_confirmation and self.uncertain_result is None
                and prepared.record.body.contract == c.UPDATE_RESULT):
            result = super().write(prepared)
            self.uncertain_result = prepared
            self.observed_contents.blocked.add(entry_from_header(prepared.cid, prepared.header).seal)
            raise OSError("test: R* saved, confirmation held before adoption")
        # WORK_REQUESTED is also used by Ee. A stage-3 Q* fault must not be
        # consumed by that legal, earlier stage-2 request.
        saved_cut = None
        if (self.cut is not None and self.cut[0] == c.WORK_REQUESTED
                and prepared.record.body.contract == c.WORK_REQUESTED
                and prepared.record.body.content.as_json()["desc"]["purpose"] != "belief_update"):
            saved_cut, self.cut = self.cut, None
        if (self.cut is not None and self.cut[0] == ACQUIRED
                and prepared.record.body.contract == ACQUIRED):
            results = {p.cid for p in self.writes if p.record.body.contract == c.UPDATE_RESULT}
            is_result = bool(results & set(prepared.record.body.content.as_json()["contents"]))
            if is_result != (self.acquisition_phase == "result"):
                saved_cut, self.cut = self.cut, None
        if (self.hold_adoption_confirmation and self.uncertain is None
                and prepared.record.body.contract == c.BELIEF_ADOPTED):
            result = super().write(prepared)
            self.uncertain = prepared
            self.observed_contents.blocked.add(entry_from_header(prepared.cid, prepared.header).seal)
            raise OSError("test: A* saved, write acknowledgement lost")
        try:
            return super().write(prepared)
        finally:
            if saved_cut is not None:
                self.cut = saved_cut


class Workers(Stage2Workers):
    """K4/K7/K12: live measurement, public U, and the existing F-a Ep factory."""

    def __init__(self, rig):
        super().__init__(rig)
        self.commands = Queue()
        self.release = Event()
        self.before_enter = None
        self.update_calls = []
        self.returns = {}
        self.update_evidence = {}
        self.readers = {}
        self.prepared_by_request = {}
        self.evaluated_by_request = {}
        self.prepares = []
        self.evidence_change = None
        self.omit_use = set()

    def run(self, work, ctx):
        if self.before_enter is not None:
            self.before_enter(work, ctx)
        super().run(work, ctx)

    def prepare(self, work, ctx, *, budget=None, request=None):
        a = work.desc.args
        request = a.input if request is None else request
        reader = ctx.reader()
        assert reader is not None
        self.prepares.append((work, reader))
        kwargs = dict(fixed_parents=request.fixed_parents, model_ref=request.model,
                      candidate_ref=request.candidates, preference_refs=request.preferences,
                      scope_request=request.scope, context_ref=request.context,
                      registry=self.rig.registry, method=request.method,
                      budget=a.budget if budget is None else budget,
                      replay_logical_limit=a.replay_logical_limit)
        assert a.compiler == fc.PREPARE_FACTS
        artifact = u.prepare_fb_from_facts(reader, evidence=ctx.evidence(), **kwargs)
        self.prepared_by_request[work.request] = artifact
        return artifact

    def evaluate(self, work, ctx, *, prepared=None, budget=None):
        actual, reader = ctx.prepared(), ctx.reader()
        assert actual is not None and reader is not None
        a = work.desc.args
        pr = self.rig.by_cid(c.PREPARED, a.prepared)
        assert pr.value["request"] == a.evaluation_request
        assert self.rig.by_cid(MATH, pr.value["artifact"]).value == json.loads(actual.canonical_bytes)
        artifact = ff.evaluate_f_from_draw(actual if prepared is None else prepared,
            a.draw, reader=reader, budget=a.budget if budget is None else budget)
        self.evaluated_by_request[work.request] = artifact
        return artifact

    def compute(self, work, ctx):
        reader = ctx.reader()
        assert reader is not None
        assert reader.record(work.request).body.contract == c.WORK_REQUESTED
        # Q* is available to U but excluded from Xnum. Read real inputs through
        # ctx.read, rather than treating input_points as proof of use.
        for entry in sorted(reader.entries(), key=lambda row: row.cid):
            if entry.cid != work.request and entry.cid not in self.omit_use:
                ctx.read(entry.cid)
        self.readers[work.request] = reader
        evidence = ctx.evidence()
        self.update_evidence[work.request] = evidence
        if self.evidence_change is not None:
            evidence = self.evidence_change(work, evidence)
        self.update_calls.append((work.request, work.desc.args.budget))
        ret = u.compute_finite_update(work.request, reader=reader, registry=self.rig.registry,
                                     evidence=evidence, budget=work.desc.args.budget)
        self.returns[work.request] = ret
        return ret

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
            ret = self.compute(work, ctx)
            return self.finished(work, fb.WorkOutputs(outputs=u.update_response(ret))), (
                ret if isinstance(ret, u.IssuedUpdate) else None)
        return super().normal(work, ctx)


class Rig(RealRig):
    """Real public C/E and host; time 0,1,2,3 is exactly the CE1 coordinate."""

    def __init__(self, *, continuation=False, partial=False, budget=UPDATE_BUDGET,
                 cut=None, rebuild=False, acquisition_phase="input", derivation_args=None,
                 second_route=False):
        super().__init__(connect=False)
        self.clock = TestClock()
        self.clock.set(0)
        self.contents = ConfirmationContents(self.contents)
        self.ledger = Stage3Ledger(contents=self.contents, entries=self.entry_store, faults=self.faults)
        self.registry = registry()
        self.launcher = LaunchCut()
        self.workers = Workers(self)
        self.host = fb.FThreadHost(ledger=self.ledger, clock=self.clock,
            workers=self.workers, registry=self.registry, launcher=self.launcher)
        self.document, _ = finite_world("FA01")
        model = self.record(Prediction(target="model.11", about=(), basis=(),
            content=Payload.json({"document": self.document}),
            contract=contract("sui.f.model_source")), RefKind.PREDICTION, Role.MODEL)
        self.model_point = self.ledger.append(model, ()).cid
        event = boot(True)
        initial = replace(event.declaration.initial.value, model=self.model_point,
            generator=fb.MethodCall(contract=c.MODEL_OPERATIONS, args={}),
            method=fb.MethodCall(contract=contract("sui.f.finite_evaluation"), args={}),
            draw=fb.MethodCall(contract=contract("stage2.scripted_draw"), args={}),
            prepare_budget=PREPARE_BUDGET, prepare_replay_logical_limit=REPLAY_LOGICAL_LIMIT,
            evaluate_budget=EVALUATE_BUDGET, update_budget=budget,
            derivation=fb.SlottedMethod(slot="delta", method=fb.MethodCall(
                contract=c.SAVED_SEGMENT_UPDATE,
                args=delta_args() if derivation_args is None else derivation_args)),
            continuation=fb.MethodCall(contract=c.REUSE_CANDIDATES, args={}) if continuation else None)
        self.boot_input = replace(event, declaration=replace(event.declaration,
            initial=replace(event.declaration.initial, value=initial),
            routes=tuple(replace(route, value=replace(route.value,
                config=replace(route.value.config,
                    sampling_contract=contract("sui.f.finite_measurement"),
                    clock_contract=contract("sui.f.simulated_clock"))))
                for route in event.declaration.routes)))
        if second_route:
            original_route = self.boot_input.declaration.routes[0]
            other_route = replace(original_route, slot="unused-route", value=replace(
                original_route.value, process_slot="unused-sensing",
                config=replace(original_route.value.config, route_epoch="route-B"),
                allocation=replace(original_route.value.allocation, slot="unused-allocation")))
            self.boot_input = replace(self.boot_input, declaration=replace(self.boot_input.declaration,
                capacity=replace(self.boot_input.declaration.capacity, value=3),
                routes=(original_route, other_route)))
        self.clock_event = fb.ClockDeclared(declaration=replace(source(), run=self.clock.run,
            measurement=contract("sui.f.simulated_clock")))
        self.executed = set()
        self.partial = partial
        self.thread = None
        self.rebuild_on_fault = rebuild
        self.rebuilt = False
        self.ledger.cut = cut
        self.ledger.acquisition_phase = acquisition_phase
        self.host.post(self.clock_event)
        self.host.post(self.boot_input)
        self.drive(lambda: bool(self.facts(c.CANDIDATE_REQUEST)))

    def read_stored(self, cid):
        # Independent observer bypasses the *test fault adapter*, not the real
        # stores. It can see a committed body while the host's get() fails.
        header = dict(self.entry_store.load())[cid]
        assert sha256(header).hexdigest() == cid.removeprefix("sha256:")
        entry = entry_from_header(cid, header)
        salt, payload = self.contents.store.get(entry.seal)
        assert seal(payload, salt) == entry.seal
        record = decode_record(header, payload)
        assert encode_header(record, entry.seal, entry.parents) == header
        return header, salt, record

    def storage_snapshot(self):
        # As in read_stored(), the observer sees the real stores even while
        # the test fault adapter makes a committed A* unreadable to the host.
        return (tuple(sorted(self.entry_store.load())),
                tuple((key, self.contents.store.get(key)) for key in sorted(self.contents.seals())))

    def by_cid(self, ref, cid):
        values = [fact for fact in self.facts(ref) if fact.cid == cid]
        assert len(values) == 1, (ref, cid)
        return values[0]

    def facts(self, wanted):
        # Store enumeration order is not publication order. The test-owned
        # public prepare observer supplies order; CID sorting cannot identify
        # the first/second update or its predecessor.
        facts = super().facts(wanted)
        positions = {prepared.cid: i for i, prepared in enumerate(self.ledger.preparations)}
        assert all(fact.cid in positions for fact in facts)
        return sorted(facts, key=lambda fact: positions[fact.cid])

    def one(self, ref):
        facts = self.facts(ref)
        assert len(facts) == 1, (ref, [item.cid for item in facts])
        return facts[0]

    def requests(self, stage):
        return [fact for fact in self.facts(REQUEST_CONTRACT[stage])
                if fact.value["desc"]["purpose"] == stage]

    def step(self):
        try:
            self.host.window.settle()
        except OSError:
            if not (self.ledger.hit or self.ledger.store_cut_hits or self.ledger.uncertain
                    or self.ledger.uncertain_result or self.ledger.uncertain_claim or self.ledger.held_context):
                raise
        if self.rebuild_on_fault and self.ledger.hit and not self.rebuilt:
            old, snapshot = self.host.window, self.storage_snapshot()
            self.host.rebuild_window()
            assert snapshot == self.storage_snapshot()
            with pytest.raises(RuntimeError):
                old.settle()
            self.rebuilt = True

    def drive(self, predicate, *, timeout=OBSERVATION_TIMEOUT):
        deadline = monotonic() + timeout
        while not predicate():
            try:
                self.host.run_until(lambda _status: predicate(), timeout=.03)
            except OSError:
                if not (self.ledger.hit or self.ledger.store_cut_hits or self.ledger.uncertain
                        or self.ledger.uncertain_result or self.ledger.uncertain_claim or self.ledger.held_context):
                    raise
            if self.workers.errors:
                raise self.workers.errors[0]
            self.step()
            if monotonic() >= deadline and not predicate():
                status = self.host.window.status()
                raise AssertionError("incomplete observation: required public transition not reached; "
                    f"pending={[(p.kind, p.reason) for p in status.pending]}; "
                    f"updates={len(self.requests('belief_update'))}, "
                    f"bindings={len(self.facts(c.SEGMENT_BINDING))}, "
                    f"spans={len(self.facts(c.MONITOR_SPAN))}, "
                    f"adoptions={len(self.facts(c.BELIEF_ADOPTED))}")

    def settle_steps(self, n=8):
        for _ in range(n):
            self.step()

    def callback(self, stage, index=-1):
        self.drive(lambda: bool(self.requests(stage)) and any(
            key == self.requests(stage)[index].value["desc"]["work_id"]
            for key, _ in self.launcher.attempts))
        fact = self.requests(stage)[index]
        callbacks = [body for key, body in self.launcher.attempts
                     if key == fact.value["desc"]["work_id"]]
        assert len(callbacks) == 1
        return fact, callbacks[0]

    def run_stage(self, stage, index=-1):
        fact, callback = self.callback(stage, index)
        work_id = fact.value["desc"]["work_id"]
        assert work_id not in self.executed
        self.executed.add(work_id)
        callback()
        raw = c.DRAW_REPORT if stage == "selection_draw" else c.WORK_REPORT
        self.drive(lambda: any(item.value["work"] == work_id for item in self.facts(raw)))
        self.settle_steps()
        return next(work for work in self.workers.entries if work.desc.work_id == work_id)

    def start_measurement(self, index=-1):
        if self.partial:
            self.clock.set(1)
        fact, callback = self.callback("measure_segment", index)
        self.thread = Thread(target=callback, daemon=True)
        self.thread.start()
        assert self.workers.entered.setdefault("measure_segment", Event()).wait(2)
        self.drive(lambda: any(item.value["item"]["kind"] == "started"
                              for item in self.facts(c.SEGMENT_REPORT)))
        return fact

    def command(self, action):
        done, errors = Event(), []
        self.workers.commands.put((action, done, errors))
        assert done.wait(2), "incomplete observation: measurement worker did not answer"
        if errors:
            raise errors[0]

    def claim(self, number=1, *, slot=None, kind="no_arrival", meaning=c.NO_ARRIVAL,
              interval=None, monitored=False, now=None, evidence=()):
        self.clock.set((2 if number == 1 else 3) if now is None else now)
        i = interval or f.MeasurementInterval(clock=self.clock.run,
            start_ns=0 if number == 1 else 1, end_ns=2 if number == 1 else 3,
            closure="(start,end]")
        report = []
        def emit(work, ctx):
            if monitored:
                ctx.monitored(i)
            event = fb.SegmentReport(segment=work.request, item_slot=slot or f"claim-{number}",
                item=f.CoverageClaim(route_epoch="route-A", interval=i, kind=kind,
                                     contract=meaning, evidence=evidence))
            report.append(event)
            self.workers.post(ctx, event)
        self.command(emit)
        self.drive(lambda: any(item.value == wire(report[0]) for item in self.facts(c.SEGMENT_REPORT)))
        self.settle_steps()
        return report[0]

    def initial_evaluation(self):
        for stage in ("candidate_generation", "evaluation_prepare", "selection_draw", "evaluation"):
            self.run_stage(stage)
        self.drive(lambda: bool(self.facts(c.SELECTION)))

    def adopt(self, number=1):
        work = self.run_stage("belief_update")
        self.drive(lambda: len(self.facts(c.BELIEF_ADOPTED)) >= number)
        return work, self.facts(c.BELIEF_ADOPTED)[number - 1]

    def close(self):
        self.contents.blocked.clear()
        self.workers.release.set()
        for gate in self.workers.gates.values():
            gate.set()
        for thread in [self.thread, *self.workers.threads]:
            if thread is not None:
                thread.join(OBSERVATION_TIMEOUT)
                assert not thread.is_alive(), "test worker did not stop"


@pytest.fixture
def make_rig():
    rigs = []
    def make(**kwargs):
        rig = Rig(**kwargs)
        rigs.append(rig)
        return rig
    yield make
    for rig in reversed(rigs):
        rig.close()


def assert_no_adoption(rig, request):
    rig.settle_steps()
    assert not [a for a in rig.facts(c.BELIEF_ADOPTED) if a.value["request"] == request]
    assert not [r for r in rig.facts(c.UPDATE_RESULT) if r.value["request"] == request]


def result_for(rig, request):
    values = [r for r in rig.facts(c.UPDATE_RESULT) if r.value["request"] == request]
    assert len(values) == 1
    return values[0]


def assert_update(rig, work, adopted, expected, previous=None, *, check_parents=False):
    """Independent C/E equations: K3-K9:3491-3497, V-01/02, A-03/04."""
    q = rig.by_cid(c.WORK_REQUESTED, work.request)
    desc = work.desc
    assert q.value == {"desc": wire(desc)}
    assert desc.purpose == "belief_update" and desc.method == c.FINITE_UPDATE_COMPUTE
    assert desc.output_contract == c.UPDATE_RESPONSE
    assert desc.args.model == rig.model_point and desc.args.prior == previous
    assert desc.args.budget == rig.boot_input.declaration.initial.value.update_budget
    assert desc.reader == rig.one(ORIGIN).cid
    assert desc.process.slot == rig.boot_input.declaration.initial.value.process_slot
    assert len(desc.args.observations) == 1
    use = desc.args.observations[0]
    b = rig.by_cid(c.SEGMENT_BINDING, use.binding)
    raw = rig.by_cid(c.SEGMENT_REPORT, b.value["report"])
    reading = rig.by_cid(c.OBSERVATION_PLAN_2, use.reading)
    law = rig.one(c.FINITE_JOINT_COUNT_LAW)
    assert reading.value == {"model": rig.model_point,
        "projection": {"contract": plain(c.FINITE_SEGMENT_PROJECTION), "args": {
            "frame": None, "claims": [{"meaning": plain(c.NO_ARRIVAL),
                "law": law.cid, "channel": "arrivals"}],
            "time_projection": {"contract": plain(c.SEGMENT_VALUE_ONLY), "args": {}}}},
        "generation": {"contract": plain(c.BOOTSTRAP_GENERATION), "args": {"scope": "whole_window"}}}
    declaration = rig.one(c.BOOT_DECLARATION)
    route, clock = rig.by_cid(ROUTE, b.value["route"]), rig.one(CLOCK_SOURCE)
    expected_law = delta_args()["law"]
    assert law.value == {"model": rig.model_point, "extends": None,
        "carrier_by_state": expected_law["carrier_by_state"],
        "channels": [{"id": "arrivals", "process": {
            "declaration": declaration.cid, "slot": "sensing"}, "route_configs": [route.cid],
            "domain": {**expected_law["channels"][0]["domain"], "clock": str(rig.clock.run)}}],
        "rows": expected_law["rows"], "frame_relation": "independent_given_carrier"}
    necessary = {desc.reader, rig.model_point, law.cid, reading.cid, b.cid, raw.cid}
    spans = [s for s in rig.facts(c.MONITOR_SPAN) if s.value["segment"] == b.value["segment"]
             and s.value["entered_ns"] <= raw.value["item"]["value"]["interval"]["start_ns"]
             and s.value["observed_ns"] >= raw.value["item"]["value"]["interval"]["end_ns"]]
    assert spans, "K4: Claim and Started alone are not whole-window evidence"
    x = closure(rig, desc.numerical_view.boundary)
    assert necessary <= x and any(span.cid in x for span in spans)
    assert work.request not in x
    reader = rig.workers.readers[work.request]
    assert work.request in {e.cid for e in reader.entries()}
    # Captured worker reader includes Q*. Its key must not replace Xnum's key.
    assert captured_reader_key(rig, reader) != desc.numerical_view.reader_view_key
    assert {t.point for t in desc.trigger} == {raw.cid}
    declared_uses = ({desc.process.declaration, desc.reader, desc.args.model,
                      desc.allocation.declaration, b.cid, reading.cid}
                     | set(desc.input_points) | {t.point for t in desc.trigger}
                     | {p.declaration for p in desc.permissions})
    if previous is not None:
        declared_uses.add(previous)
    qrecord = rig.read_stored(q.cid)[2]
    assert isinstance(qrecord.body, Decided) and qrecord.writer == Role.MODEL
    assert qrecord.category == Category.FACT
    assert set(qrecord.body.inputs) == {rig.read_stored(point)[2].id for point in declared_uses}
    parent_events = {raw.cid, b.cid, desc.reader} | events_for(rig, (reading.cid,))
    parent_events |= {s.cid for s in spans if s.cid in x}
    if previous is not None:
        parent_events.add(previous)
        assert previous in x
    if check_parents:
        assert_parents(rig, q, parent_events)
    for span in spans:
        assert set(span.value) == {"segment", "work", "route", "clock", "entered_ns", "observed_ns"}
        assert span.value["route"] == route.cid and span.value["clock"] == clock.cid
        assert span.received_ns == span.value["observed_ns"] <= span.at_ns
        assert span.value["entered_ns"] == (1 if rig.partial else 0)
        if check_parents:
            assert_parents(rig, span, (b.value["segment"], clock.cid))
    for fact, target, about, basis in (
        (law, "count_law", rig.model_point, {rig.model_point, declaration.cid, route.cid, clock.cid}),
        (reading, None, rig.model_point, {rig.model_point, law.cid}),
    ):
        record = rig.read_stored(fact.cid)[2]
        assert isinstance(record.body, Prediction) and record.writer == Role.MODEL
        assert record.category == Category.PREDICTION
        if target is not None:
            assert record.body.target == target
        assert record.body.about == (rig.read_stored(about)[2].id,)
        assert set(record.body.basis) == {rig.read_stored(p)[2].id for p in basis}
        if check_parents:
            assert_parents(rig, fact, (declaration.cid, route.cid, clock.cid))
    ret = rig.workers.returns[work.request]
    assert isinstance(ret, u.IssuedUpdate) and plain(ret.result) == expected
    r = result_for(rig, work.request)
    assert r.value == {"request": q.cid, "result": expected,
        "application_digest": ret.application_digest, "numerical_view": wire(desc.numerical_view),
        "registry_key": ret.registry_key}
    assert ret.application_digest
    terminals = [t for t in rig.facts(c.WORK_TERMINAL) if t.value["request"] == q.cid]
    assert len(terminals) == 1
    terminal = terminals[0]
    raw_return = rig.by_cid(c.WORK_REPORT, terminal.value["first_receipt"])
    assert raw_return.value["outcome"] == {"kind": "outputs", "value": {
        "contract": plain(c.UPDATE_RESPONSE), "value": {"kind": "issued", "value": expected}}}
    assert set(terminal.parents) == {q.cid, raw_return.cid}
    rbody = rig.read_stored(r.cid)[2].body
    assert isinstance(rbody, Prediction) and rbody.target == "belief_update"
    assert rbody.about == (q.record_id,)
    if check_parents:
        basis_points = {fact.record_id: (fact.cid, fact.contract.name)
                        for ref in (c.WORK_REQUESTED, c.WORK_TERMINAL, c.WORK_REPORT)
                        for fact in rig.facts(ref)}
        assert set(rbody.basis) == {q.record_id, raw_return.record_id}, {
            "K8_expected": [(q.cid, c.WORK_REQUESTED.name), (raw_return.cid, c.WORK_REPORT.name)],
            "actual": [basis_points.get(ref, str(ref)) for ref in rbody.basis]}
        assert_parents(rig, r, (q.cid, raw_return.cid))
    a = adopted
    assert set(a.value) == {"origin", "model", "previous", "request", "result", "acquisition"}
    assert {k: a.value[k] for k in ("origin", "model", "previous", "request", "result")} == {
        "origin": desc.reader, "model": rig.model_point, "previous": previous,
        "request": q.cid, "result": r.cid}
    g = rig.by_cid(ACQUIRED, a.value["acquisition"])
    assert g.value["origin"] == desc.reader and r.cid in g.value["contents"]
    output_clock = rig.by_cid(CLOCK, g.value["clock"])
    assert output_clock.value["source"] == clock.cid
    assert output_clock.value["reading"]["run"] == str(rig.clock.run)
    acquired_ns = output_clock.value["reading"]["time_ns"]
    after = rig.workers.contexts["belief_update"].evidence()
    assert any(e.origin == desc.reader and r.cid in e.contents and e.acquired_ns == acquired_ns
               for e in after.acquisitions)
    assert acquired_ns <= g.received_ns <= g.at_ns <= a.at_ns
    # Apply the common Ev/Front convention (2060-2062) to Predictions in
    # K5/K9's parent expressions, as with every other used Prediction.
    if check_parents:
        assert_parents(rig, output_clock, events_for(rig, {clock.cid} | set(g.value["contents"])))
        assert_parents(rig, a, events_for(rig, {r.cid, g.cid} | ({previous} if previous else set())))
    assert isinstance(rig.read_stored(a.cid)[2].body, Decided)
    abody = rig.read_stored(a.cid)[2].body
    adoption_uses = {desc.reader, rig.model_point, q.cid, r.cid, g.cid}
    if previous:
        adoption_uses.add(previous)
    assert set(abody.inputs) == {rig.read_stored(point)[2].id for point in adoption_uses}
    evidence = rig.workers.update_evidence[work.request]
    for point in (b.cid, raw.cid, reading.cid, law.cid, *[s.cid for s in spans if s.cid in x]):
        acquired = [e.acquired_ns for e in evidence.acquisitions
                    if e.origin == desc.reader and point in e.contents]
        used = [e.used_ns for e in evidence.uses if e.work_id == desc.work_id and e.point == point]
        assert acquired and used and min(acquired) <= min(used)
    for fact in [*rig.facts(c.SEGMENT_REPORT), *rig.facts(c.WORK_REPORT),
                 *rig.facts(c.MONITOR_SPAN), terminal, g]:
        assert fact.received_ns is not None and fact.received_ns <= fact.at_ns
    return r


def first_claim(rig):
    # Finish the initial computation so that the other seat can run Wu while
    # the measurement seat stays occupied. Capacity is not a timing oracle.
    rig.initial_evaluation()
    rig.start_measurement()
    rig.claim(1)
    rig.drive(lambda: bool(rig.requests("belief_update")))


class PublicReader(Reader):
    """Only the public FReader protocol; explicit entry selection/body absence."""

    def __init__(self, ledger, *, points=None, missing=()):
        super().__init__(ledger)
        self.points = frozenset(e.cid for e in ledger.entries()) if points is None else frozenset(points)
        self.missing = frozenset(missing)

    def entries(self):
        return tuple(e for e in super().entries() if e.cid in self.points)

    def entry(self, cid):
        if cid not in self.points:
            raise KeyError(cid)
        return super().entry(cid)

    def record(self, cid):
        self.entry(cid)
        if cid in self.missing:
            raise KeyError(cid)
        return super().record(cid)

    def sealed_content(self, cid):
        self.entry(cid)
        if cid in self.missing:
            raise KeyError(cid)
        return super().sealed_content(cid)

    def ancestors(self, frontier):
        return super().ancestors(frontier) & self.points


def public_registry_key(registry):
    """F-a paper:452-459,470: independent declaration/identity encoding."""
    implementations = {(i.kind, i.ref): i.identity for i in registry.implementations}
    capabilities = [{"kind": d.kind, "ref": plain(d.ref), "declaration": plain(d),
        "implemented": (d.kind, d.ref) in implementations,
        "implementation_id": implementations.get((d.kind, d.ref))}
        for d in sorted(registry.declarations, key=lambda d: (d.kind, d.ref.name, d.ref.version))]
    return "sha256:" + sha256(canonical({"domain": "sui.f.registry_view/1",
                                       "capabilities": capabilities})).hexdigest()


def fixed_view(rig, boundary, *, registry=None):
    boundary = frozenset(boundary)
    reader = PublicReader(rig.ledger, points=closure(rig, boundary))
    return fb.FixedView(boundary=boundary, reader_view_key=captured_reader_key(rig, reader),
                        registry_key=public_registry_key(rig.registry if registry is None else registry))


def save_copy(rig, point, *, value=None, inputs=None, parents=None, received_ns=None,
              about=None, basis=None):
    """New real ID/header/salt/CID through the public ledger, never reader tampering."""
    header, _salt, original = rig.read_stored(point)
    body = original.body
    if value is not None:
        body = replace(body, content=Payload.json(wire(value)))
    if inputs is not None:
        body = replace(body, inputs=tuple(inputs))
    if received_ns is not None:
        body = replace(body, received_ns=received_ns)
    if about is not None:
        body = replace(body, about=tuple(about))
    if basis is not None:
        body = replace(body, basis=tuple(basis))
    record = rig.record(body, original.id.kind, original.writer)
    parent_points = entry_from_header(point, header).parents if parents is None else parents
    return rig.ledger.write(rig.ledger.prepare(record, parent_points)).cid


def save_request(rig, work, *, desc=None, inputs=None, parents=None):
    return save_copy(rig, work.request, value={"desc": wire(work.desc if desc is None else desc)},
                     inputs=inputs, parents=parents)


def direct_update(rig, request, evidence, *, registry=None, budget=UPDATE_BUDGET):
    return u.compute_finite_update(request, reader=PublicReader(rig.ledger),
        registry=rig.registry if registry is None else registry, evidence=evidence, budget=budget)


def direct_first(rig):
    first_claim(rig)
    work, adoption = rig.adopt()
    evidence = rig.workers.update_evidence[work.request]
    ret = direct_update(rig, work.request, evidence)
    assert isinstance(ret, u.IssuedUpdate) and plain(ret.result) == FIRST
    assert ret.registry_key == public_registry_key(rig.registry)
    assert ret.numerical_view.boundary == work.desc.numerical_view.boundary
    assert ret.numerical_view.reader_view_key == work.desc.numerical_view.reader_view_key
    assert ret.numerical_view.registry_key == work.desc.numerical_view.registry_key
    return work, adoption, evidence


def prepare_kwargs(work, *, fixed_parents=None):
    request = work.desc.args.input
    return dict(fixed_parents=request.fixed_parents if fixed_parents is None else fixed_parents,
        model_ref=request.model, candidate_ref=request.candidates, preference_refs=request.preferences,
        scope_request=request.scope, context_ref=request.context, method=request.method,
        budget=work.desc.args.budget, replay_logical_limit=work.desc.args.replay_logical_limit)


def fa_kwargs(kwargs):
    """F-a の入口 (`prepare_f_from_facts`) の引数: F-b の入口だけの replay_logical_limit (Z34 (a) 案 B) を除く。"""
    return {k: v for k, v in kwargs.items() if k != "replay_logical_limit"}


def accept_posted(rig, event, post):
    """Accept the actual Post's envelope before settle; status supplies routing only.

    Expected content/outcome comes from the test's event and real C/E. No
    private queue/P is accessed. The normal host pump may redeliver the same
    already-accepted envelope later, which must not change its identity.
    """
    old = {r.envelope for r in rig.host.window.status().receipts}
    post()
    received = [r for r in rig.host.window.status().receipts if r.envelope not in old]
    assert len(received) == 1 and received[0].state == "received"
    receipt = received[0]
    rig.host.window.accept(fb.Envelope(number=receipt.envelope, event=event,
                                      received_ns=receipt.received_ns))
    return receipt.envelope


def test_ce1_fixture_rejects_both_plausible_wrong_algorithms():
    """Paper:2897-2916,3398. Bug: multiply two marginal likelihoods or drop E2."""
    assert [sum(row[i] for row in CE1_ROWS) for i in (1, 2)] == [1, 1]
    weights = [sum(row[i] for row in CE1_ROWS if row[0] == (0, 0, 0)) / 2 for i in (1, 2)]
    mass = sum(weights)
    assert {"joint": plain([v / mass for v in weights]), "evidence_mass": plain(mass)} == SECOND
    assert SECOND != DOUBLE and SECOND != FIRST and FIRST != DOUBLE


def test_k2_law_mass_wire_uses_exact_integer_pairs():
    """Paper:3490-3491 (00:3x correction),2687; F-a:27. Bug: string/float mass encoding."""
    rows = delta_args()["law"]["rows"]
    assert [row["mass"] for row in rows] == [[plain(a), plain(b)] for _bits, a, b in CE1_ROWS]
    assert all(type(n) is int for row in rows for mass in row["mass"] for n in mass)


def test_issued_update_cannot_be_forged_from_correct_explanation():
    """Paper:3335,3495; f_update2.py:76-87. Bug: accept a matching DTO as factory issue."""
    with pytest.raises(TypeError):
        u.IssuedUpdate(request="not-an-issued-request", result=FIRST,
            application_digest="copied-description", numerical_view=u.FixedViewValue(
                boundary=frozenset(), reader_view_key="copied", registry_key="copied"),
            registry_key="copied")


def test_registry_includes_old_bundle_without_changing_declarations_or_identities():
    """Paper:3478,3086-3090. Bug: replace old /1 capabilities with /2 definitions."""
    old, new = f.builtin_f_registry(), registry()
    declarations = {(d.kind, d.ref): d for d in new.declarations}
    identities = {(i.kind, i.ref): i.identity for i in new.implementations}
    assert all(declarations[(d.kind, d.ref)] == d for d in old.declarations)
    assert all(identities[(i.kind, i.ref)] == i.identity for i in old.implementations)


def test_ce1_two_updates_from_public_boot_read_actual_records(make_rig):
    """Paper:3246,3299-3309,3485,3490-3497,2897-2916. Bugs: double-count/drop E2, fake G, old R joint."""
    rig = make_rig()
    first_claim(rig)
    w1, a1 = rig.adopt(1)
    r1 = assert_update(rig, w1, a1, FIRST)
    rig.claim(2)
    rig.drive(lambda: len(rig.requests("belief_update")) == 2)
    w2, a2 = rig.adopt(2)
    r2 = assert_update(rig, w2, a2, SECOND, a1.cid)
    assert plain(rig.workers.returns[w2.request].result) not in (FIRST, DOUBLE)
    assert r1.value["application_digest"] != r2.value["application_digest"]
    assert w1.desc.work_id != w2.desc.work_id
    assert w2.desc.args.prior == a1.cid
    assert r1.cid in closure(rig, w2.desc.numerical_view.boundary)
    assert rig.thread.is_alive(), "the whole measurement must not end for a finite claim"
    for old_only in ("sui.f.computation_requested", "sui.f.computation_proof",
                     "sui.f.computation_completed", "sui.f.knowledge_adopted"):
        assert not rig.facts(contract(old_only)), "Q*/Wu must not fabricate the removed proof/completion path"
    # Check graph equations after BOTH arithmetic updates. A graph failure
    # must not mask whether the second claim or continuation uses the belief.
    assert_update(rig, w1, a1, FIRST, check_parents=True)
    assert_update(rig, w2, a2, SECOND, a1.cid, check_parents=True)


def decimal_real(value):
    """Independent evaluation of the public ExactReal expression grammar."""
    if value.op == "rational":
        return Decimal(value.value.numerator) / Decimal(value.value.denominator)
    if value.op == "log":
        return decimal_real(value.arg).ln()
    if value.op == "exp":
        return decimal_real(value.arg).exp()
    if value.op == "neg":
        return -decimal_real(value.arg)
    if value.op == "add":
        return sum((decimal_real(a) for a in value.args), Decimal(0))
    if value.op == "mul":
        result = Decimal(1)
        for a in value.args:
            result *= decimal_real(a)
        return result
    if value.op == "div":
        return decimal_real(value.numerator) / decimal_real(value.denominator)
    raise AssertionError("unknown public ExactReal operator: " + value.op)


def assert_quantity(value, expected):
    assert value.status == "finite" and value.exact is not None
    assert abs(decimal_real(value.exact) - expected) < Decimal("1e-35")


@pytest.mark.parametrize("continuation", (False, True), ids=("none", "reuse_candidates"))
def test_continuation_uses_adopted_joint_in_math_input_and_information(make_rig, continuation):
    """Paper:3477-3478,3498,3500; F-a M-09/M-17. Bug: reuse model.initial; choice can stay the same."""
    rig = make_rig(continuation=continuation)
    first_claim(rig)
    old_eq = rig.requests("evaluation_prepare")[0]
    old_artifact = rig.workers.prepared_by_request[old_eq.cid]
    old_eval = next(iter(rig.workers.evaluated_by_request.values()))
    assert isinstance(old_eval.value, f.Selected)
    before = {point: rig.read_stored(point) for point, _ in rig.entry_store.load()}
    w1, a1 = rig.adopt(1)
    assert_update(rig, w1, a1, FIRST)
    rig.settle_steps()
    if not continuation:
        assert [eq.cid for eq in rig.requests("evaluation_prepare")] == [old_eq.cid]
        assert rig.workers.prepared_by_request[old_eq.cid] is old_artifact
        return
    mathematical_checks = []
    for number, adopted, p in ((1, a1, F(4, 5)), (2, None, F(8, 9))):
        if number == 2:
            rig.claim(2)
            rig.drive(lambda: len(rig.requests("belief_update")) == 2)
            w2, adopted = rig.adopt(2)
            assert_update(rig, w2, adopted, SECOND, a1.cid)
        rig.drive(lambda: len(rig.requests("evaluation_prepare")) == number + 1)
        eq = rig.requests("evaluation_prepare")[-1]
        desc = eq.value["desc"]
        assert desc["args"]["compiler"] == plain(fc.PREPARE_FACTS)
        assert {t["point"] for t in desc["trigger"]} == {adopted.cid}
        x = closure(rig, desc["numerical_view"]["boundary"])
        assert {adopted.cid, adopted.value["result"], adopted.value["acquisition"]} <= x
        # K12 (00:5x): the adopted chain's Predictions must be explicit roots;
        # causal ancestors alone cannot make law/reading/R* visible to Ep.
        predictions = {rig.one(c.FINITE_JOINT_COUNT_LAW).cid}
        current = adopted
        while current is not None:
            predictions.add(current.value["result"])
            update = rig.by_cid(c.WORK_REQUESTED, current.value["request"])
            predictions.update(o["reading"] for o in update.value["desc"]["args"]["observations"])
            current = (rig.by_cid(c.BELIEF_ADOPTED, current.value["previous"])
                       if current.value["previous"] else None)
        assert predictions <= set(desc["numerical_view"]["boundary"])
        fixed = closure(rig, desc["args"]["input"]["fixed_parents"])
        assert adopted.cid in fixed
        assert desc["args"]["input"]["candidates"] == rig.one(CG).cid
        assert desc["work_id"] != old_eq.value["desc"]["work_id"]
        assert desc["stage_slot"] != old_eq.value["desc"]["stage_slot"]
        ep = rig.run_stage("evaluation_prepare")
        prepared = rig.workers.prepared_by_request[eq.cid]
        assert isinstance(prepared.value, f.FProblem)
        saved_math = json.loads(prepared.canonical_bytes)
        assert saved_math["compiler"] == plain(fc.PREPARE_FACTS)
        assert saved_math["input"]["value"]["fixed_parents"] == desc["args"]["input"]["fixed_parents"]
        assert prepared.value.world_manifest.compiler == fc.PREPARE_FACTS
        assert prepared.value.K.belief == rig.read_stored(adopted.value["result"])[2].id
        rig.run_stage("selection_draw")
        ee = rig.run_stage("evaluation")
        result = rig.workers.evaluated_by_request[ee.request].value
        assert isinstance(result, f.Selected)
        evaluation = result.evaluation
        assert evaluation.root.problem_key == prepared.value.problem_key
        assert evaluation.root.world_manifest.compiler == fc.PREPARE_FACTS
        assert evaluation.root.K.belief == rig.read_stored(adopted.value["result"])[2].id
        assert evaluation.candidates == ("Q", "M")
        # Perfect measurement of the two CE1 carriers yields H(p); silence Q
        # yields zero. Old initial would yield ln(2) and q(M)=2/3.
        mathematical_checks.append((evaluation, p))
        assert ep.desc.args.compiler == fc.PREPARE_FACTS
    assert len(rig.facts(CG)) == 1
    assert len({eq.value["desc"]["work_id"] for eq in rig.requests("evaluation_prepare")}) == 3
    draws = rig.facts(c.DRAW_REQUESTED)
    assert len({d.value["desc"]["args"]["stream_id"] for d in draws}) == 1
    assert len({(d.value["desc"]["args"]["request"]["context_key"],
                 d.value["desc"]["args"]["request"]["ordinal"]) for d in draws}) == 3
    assert all(rig.read_stored(point) == stored for point, stored in before.items())
    # Reach the second continuation before comparing either information value.
    # A wrong first evaluation must not hide work-id/ordinal/history problems.
    for evaluation, p in mathematical_checks:
        with localcontext() as context:
            context.prec = 60
            probability = Decimal(p.numerator) / Decimal(p.denominator)
            entropy = -(probability * probability.ln()
                        + (1 - probability) * (1 - probability).ln())
            assert abs(entropy - Decimal(2).ln()) > Decimal("0.1")
            assert_quantity(evaluation.information[0].additional, Decimal(0))
            assert_quantity(evaluation.information[1].additional, entropy)
            assert_quantity(evaluation.G[1], -entropy)
            assert_quantity(evaluation.q_star[1], entropy.exp() / (1 + entropy.exp()))


@pytest.mark.parametrize("change", ("legal", "missing", "other_origin", "other_content", "late", "unused"))
def test_u_requires_the_actual_origin_content_acquisition_before_use(make_rig, change):
    """Paper:3302,3332-3336,3479,3493,2869-2879.

    Bug: input_points/G existence substitutes for EA/EW. Wrong origin and
    late acquisition retain every content in each EA entry: a missing
    unrelated content cannot mask those independent comparisons.
    """
    rig = make_rig()
    first_claim(rig)
    q = rig.requests("belief_update")[0]
    b = rig.by_cid(c.SEGMENT_BINDING, q.value["desc"]["args"]["observations"][0]["binding"])
    raw = b.value["report"]
    if change == "unused":
        rig.workers.omit_use.add(raw)
    elif change != "legal":
        def alter(work, evidence):
            acquisitions = []
            for item in evidence.acquisitions:
                if raw not in item.contents:
                    acquisitions.append(item)
                    continue
                if change == "other_origin":
                    acquisitions.append(replace(item, origin=rig.model_point))
                elif change == "other_content":
                    acquisitions.append(replace(item, contents=item.contents - {raw}))
                    acquisitions.append(replace(item, contents=frozenset({rig.model_point})))
                elif change == "late":
                    last_use = max(e.used_ns for e in evidence.uses if e.point == raw)
                    acquisitions.append(replace(item, acquired_ns=last_use + 1))
                else:
                    acquisitions.append(replace(item, contents=item.contents - {raw}))
            changed = replace(evidence, acquisitions=tuple(acquisitions))
            if change in ("other_origin", "late"):
                assert [e.contents for e in changed.acquisitions] == [e.contents for e in evidence.acquisitions]
                assert changed.uses == evidence.uses and changed.executions == evidence.executions
                for before, after in zip(evidence.acquisitions, changed.acquisitions):
                    if change == "other_origin":
                        assert after.acquired_ns == before.acquired_ns
                    else:
                        assert after.origin == before.origin
            return changed
        rig.workers.evidence_change = alter
    work = rig.run_stage("belief_update")
    ret = rig.workers.returns[work.request]
    if change == "legal":
        rig.drive(lambda: bool(rig.facts(c.BELIEF_ADOPTED)))
        assert_update(rig, work, rig.one(c.BELIEF_ADOPTED), FIRST)
    else:
        assert isinstance(ret, (u.Rejected, u.Insufficient)) and ret.issues
        assert any(issue.fields or getattr(issue, "missing", ()) for issue in ret.issues)
        assert_no_adoption(rig, work.request)
        assert rig.by_cid(c.SEGMENT_REPORT, raw).value["item"]["value"]["kind"] == "no_arrival"


@pytest.mark.parametrize("mode", ("legal", "missing_issue", "forged_issue", "other_q", "wrong_joint", "wrong_mass"))
def test_result_requires_factory_issue_for_this_q_and_the_whole_response(make_rig, mode):
    """Paper:3306,3335,3495-3496. Bug: any issued object or matching joint alone authorizes R*/A*."""
    rig = make_rig()
    first_claim(rig)
    old_issue = None
    if mode == "other_q":
        old_work, _ = rig.adopt(1)
        old_issue = rig.workers.returns[old_work.request]
        rig.claim(2)
        rig.drive(lambda: len(rig.requests("belief_update")) == 2)
    def reply(work, ctx):
        ret = rig.workers.compute(work, ctx)
        assert isinstance(ret, u.IssuedUpdate)
        response, issued = u.update_response(ret), ret
        if mode == "missing_issue":
            issued = None
        elif mode == "forged_issue":
            # Same public type and all public fields, without using any private
            # token/attribute. A type/field comparison alone must not issue it.
            issued = object.__new__(u.IssuedUpdate)
            for field in ("request", "result", "application_digest", "numerical_view", "registry_key"):
                object.__setattr__(issued, field, getattr(ret, field))
        elif mode == "other_q":
            issued = old_issue
        elif mode in ("wrong_joint", "wrong_mass"):
            result = plain(ret.result)
            result["joint" if mode == "wrong_joint" else "evidence_mass"] = (
                [[1, 2], [1, 2]] if mode == "wrong_joint" else [1, 1])
            response = f.ContractValue(contract=c.UPDATE_RESPONSE, value={"kind": "issued", "value": result})
        rig.workers.post(ctx, rig.workers.finished(work, fb.WorkOutputs(outputs=response)), issued)
    rig.workers.overrides["belief_update"] = reply
    work = rig.run_stage("belief_update")
    if mode == "legal":
        rig.drive(lambda: bool(rig.facts(c.BELIEF_ADOPTED)))
        assert_update(rig, work, rig.one(c.BELIEF_ADOPTED), FIRST)
    else:
        assert_no_adoption(rig, work.request)
        pending = rig.host.window.status().pending
        waiting = rig.facts(c.WAITING)
        reasons = [p.reason for p in pending]
        reasons += [missing["reason"] for fact in waiting for missing in fact.value["missing"]]
        assert any(reason == "update:issued" or reason.startswith("update:issued:") for reason in reasons), {
            "pending": reasons, "waiting": [w.value for w in waiting]}
    assert not rig.workers.errors


@pytest.mark.parametrize("branch", ("legal", "rejected", "insufficient", "failure", "unknown"))
def test_non_successful_update_never_creates_result_or_adoption(make_rig, branch):
    """Paper:1927-1928,3308,3323,3431,3475,3482,3495.

    Bugs: treat every WorkOutputs as issued, or treat an ordinary definitive
    Rejected/Insufficient as a missing-issue failure. No R*/A* alone cannot
    distinguish the latter: meaning 3 must carry the declared response and
    meaning 4 must not invent update:issued. The nearest issued case adopts
    CE1 and must not acquire a rejected/insufficient response.
    """
    rig = make_rig()
    first_claim(rig)
    def reply(work, ctx):
        if branch == "legal":
            event, issue = rig.workers.normal(work, ctx)
        else:
            issue = None
            if branch == "rejected":
                ret = u.Rejected(request=work.request, issues=(u.RejectedIssue(code="missing_contract",
                    fields=("/observations/0/reading",), evidence=frozenset(), message="test meaning missing"),))
                outcome = fb.WorkOutputs(outputs=u.update_response(ret))
            elif branch == "insufficient":
                ret = u.Insufficient(request=work.request, issues=(u.InsufficientIssue(
                    code="budget_exhausted", fields=(), evidence=frozenset(), message="test budget",
                    missing=(u.VerificationNeed(kind="budget", value={"phase": "computation"}),)),))
                outcome = fb.WorkOutputs(outputs=u.update_response(ret))
            elif branch == "failure":
                outcome = fb.WorkFailure(failure=fb.FailureInfo(failure_kind="test-device",
                    content={"reason": "failed"}, readings=(), basis=()))
            else:
                outcome = fb.WorkUnknown(unknown=fb.UnknownInfo(reason="test result unknown", basis=()))
            event = rig.workers.finished(work, outcome)
        rig.workers.post(ctx, event, issue)
    rig.workers.overrides["belief_update"] = reply
    work = rig.run_stage("belief_update")
    terminal = [t for t in rig.facts(c.WORK_TERMINAL) if t.value["request"] == work.request]
    assert len(terminal) == 1
    assert terminal[0].value["terminal_kind"] == {"failure": "failure", "unknown": "unknown"}.get(branch, "outputs")

    def assert_definitive_response():
        status = rig.host.window.status()
        # A definitive non-adoption is attached to Q*. A successful result
        # has its own reading: identify it by the independently saved A*,
        # without requiring a redundant Q* status row after adoption.
        readings = [r for r in status.readings if r.reader == work.desc.reader and (
            r.adopted == rig.one(c.BELIEF_ADOPTED).cid if branch == "legal"
            else r.target == work.request)]
        assert readings, "meaning 3 must identify this reader's definitive response/adoption"
        if branch in ("rejected", "insufficient"):
            assert {r.response for r in readings} == {branch}
            reasons = [p.reason for p in status.pending]
            reasons += [missing["reason"] for fact in rig.facts(c.WAITING)
                        for missing in fact.value["missing"]]
            assert not any(reason == "update:issued" or reason.startswith("update:issued:")
                           for reason in reasons), reasons
        elif branch == "legal":
            assert {r.response for r in readings} == {"none"}
            assert all(r.reached == "adopted" for r in readings)

    if branch == "legal":
        rig.drive(lambda: bool(rig.facts(c.BELIEF_ADOPTED)))
        assert_update(rig, work, rig.one(c.BELIEF_ADOPTED), FIRST)
        assert_definitive_response()
    else:
        assert_no_adoption(rig, work.request)
        if branch in ("rejected", "insufficient"):
            assert_definitive_response()
        assert len(rig.requests("belief_update")) == 1
        request_before = rig.read_stored(work.request)
        rig.host.rebuild_window()
        rig.settle_steps()
        assert rig.read_stored(work.request) == request_before
        assert_no_adoption(rig, work.request)
        if branch in ("rejected", "insufficient"):
            assert_definitive_response()
        assert len(rig.requests("belief_update")) == 1


@pytest.mark.parametrize("stopped", (False, True), ids=("running", "stopped_before_settle"))
def test_monitor_span_requires_measurement_run_still_active_when_host_settles(make_rig, stopped):
    """Paper:1926-1928,3492 (K4),3494. Bug: entry alone permits a monitor span.

    Both cases enter at M=0 and post the same complete Claim (0,2] at M=2.
    In the negative case the command posts the Claim, releases the worker,
    and the test joins the deferred launcher before any host pump/settle.
    Thus actual run return precedes even the Claim's acceptance, not merely
    an Ended report. The live case differs only in keeping that run active
    and must produce the real span and the exact first CE1 adoption.
    """
    rig = make_rig()
    rig.initial_evaluation()
    segment = rig.start_measurement()
    measure = next(w for w in rig.workers.entries if w.desc.purpose == "measure_segment")
    assert measure.request == segment.cid and rig.thread.is_alive()
    assert not rig.facts(c.MONITOR_SPAN)
    rig.clock.set(2)
    interval = f.MeasurementInterval(clock=rig.clock.run, start_ns=0, end_ns=2,
                                     closure="(start,end]")
    reports = []
    before = rig.storage_snapshot()

    def emit_then_optionally_return(work, ctx):
        report = fb.SegmentReport(segment=work.request, item_slot="claim-1",
            item=f.CoverageClaim(route_epoch="route-A", interval=interval,
                                 kind="no_arrival", contract=c.NO_ARRIVAL, evidence=()))
        reports.append(report)
        rig.workers.post(ctx, report)
        if stopped:
            rig.workers.release.set()

    rig.command(emit_then_optionally_return)
    if stopped:
        rig.thread.join(2)
        assert not rig.thread.is_alive(), "incomplete observation: measurement run has not returned"
        assert measure.desc.work_id in rig.workers.stops
    else:
        assert rig.thread.is_alive() and measure.desc.work_id not in rig.workers.stops
    # post() only queued the Claim; no host acceptance or storage happened
    # while waiting for actual run return. This is the scheduling witness.
    assert rig.storage_snapshot() == before
    rig.drive(lambda: any(r.value == wire(reports[0]) for r in rig.facts(c.SEGMENT_REPORT)))
    rig.settle_steps()
    raw = [r for r in rig.facts(c.SEGMENT_REPORT) if r.value == wire(reports[0])]
    assert len(raw) == 1 and raw[0].value["item"]["value"]["interval"] == wire(interval)
    if stopped:
        assert not rig.facts(c.MONITOR_SPAN)
        assert not rig.requests("belief_update")
        assert not rig.facts(c.UPDATE_RESULT) and not rig.facts(c.BELIEF_ADOPTED)
        assert not rig.workers.update_calls
        pending = rig.host.window.status().pending
        assert any(p.kind == "awaiting_evidence" and p.reason == "monitor:stopped"
                   for p in pending), [(p.kind, p.reason) for p in pending]
    else:
        rig.drive(lambda: bool(rig.requests("belief_update")))
        work, adoption = rig.adopt()
        assert_update(rig, work, adoption, FIRST)
        span = rig.one(c.MONITOR_SPAN)
        assert span.value["segment"] == segment.cid and span.value["work"] == measure.desc.work_id
        assert (span.value["entered_ns"], span.value["observed_ns"]) == (0, 2)
        assert rig.thread.is_alive() and measure.desc.work_id not in rig.workers.stops
    assert not rig.workers.errors


@pytest.mark.parametrize("partial", (False, True), ids=("whole_window", "partial_window"))
def test_support_comes_from_actual_monitor_span_without_truncating_claim(make_rig, partial):
    """Paper:3492,2839-2847,744-766; user's third-turn clarification of B.

    Bug: accept a whole-window Claim made before actual entry, or trim it.
    Entry at 1 for Claim (0,2] is rejected by B with claim:window. This public
    path cannot reach U's Insufficient(support) guard; it is not a ContractGap.
    The nearest legal case enters at 0 and reaches the exact CE1 result.
    """
    rig = make_rig(partial=partial)
    rig.initial_evaluation()
    rig.start_measurement()
    original = rig.claim(1, monitored=True)
    raw = [r for r in rig.facts(c.SEGMENT_REPORT) if r.value == wire(original)]
    assert len(raw) == 1 and raw[0].value["item"]["value"]["interval"]["start_ns"] == 0
    if partial:
        rig.drive(lambda: any(p.target == raw[0].cid and p.kind == "conflict"
                              and p.reason == "claim:window" for p in rig.host.window.status().pending))
        rig.settle_steps()
        assert not rig.facts(c.SEGMENT_BINDING)
        assert not rig.requests("belief_update")
        assert not rig.facts(c.UPDATE_RESULT) and not rig.facts(c.BELIEF_ADOPTED)
        assert not rig.workers.update_calls and not rig.workers.returns
        assert not any(s.value["entered_ns"] == 0 for s in rig.facts(c.MONITOR_SPAN))
        assert rig.by_cid(c.SEGMENT_REPORT, raw[0].cid).value == wire(original)
    else:
        rig.drive(lambda: bool(rig.requests("belief_update")))
        work = rig.run_stage("belief_update")
        ret = rig.workers.returns[work.request]
        assert isinstance(ret, u.IssuedUpdate)
        rig.drive(lambda: bool(rig.facts(c.BELIEF_ADOPTED)))
        assert_update(rig, work, rig.one(c.BELIEF_ADOPTED), FIRST)
    assert rig.thread.is_alive()


@pytest.mark.parametrize("entered", (False, True), ids=("without_ticket", "with_ticket"))
def test_read_and_monitored_require_the_start_ticket(make_rig, entered):
    """Paper:3479,3499; fb.py:624-630. Bug: unused context adds EW/EI before enter()."""
    rig = make_rig()
    checked = []
    def probe(work, ctx):
        if work.desc.purpose != "measure_segment":
            return
        before = ctx.evidence()
        interval = f.MeasurementInterval(clock=rig.clock.run, start_ns=0, end_ns=0,
                                         closure="[start,end]")
        if entered:
            assert ctx.enter()
            ctx.read(work.request)
            ctx.monitored(interval)
            after = ctx.evidence()
            assert any(x.work_id == work.desc.work_id and x.point == work.request for x in after.uses)
            assert any(x.work_id == work.desc.work_id and x.interval == interval for x in after.intervals)
        else:
            with pytest.raises(RuntimeError):
                ctx.read(work.request)
            with pytest.raises(RuntimeError):
                ctx.monitored(interval)
            after = ctx.evidence()
            assert after.uses == before.uses and after.intervals == before.intervals
        checked.append(work.request)
    rig.workers.before_enter = probe
    _fact, callback = rig.callback("measure_segment")
    # For the positive probe enter() consumes the ticket, so the normal worker
    # run subsequently observes False and does not become an unjoined monitor.
    if entered:
        callback()
    else:
        rig.start_measurement()
    assert len(checked) == 1
    assert not rig.workers.errors


@pytest.mark.parametrize("uncertain", (False, True), ids=("confirmed_adoption", "lost_adoption_ack"))
def test_k13_serializes_update_requests_until_previous_adoption_is_confirmed(make_rig, uncertain):
    """Paper:3307,3321,3476,3497,3501 (K13, user's adopted decision).

    Bug: publish Q2 while Q1/A1 is pending, treat a lost acknowledgement as
    no previous adoption, or freeze Q2.prior before confirmation. Two early
    Claims must eventually give FIRST then SECOND, without Stale or lost E2.
    The public delta serializes this series, so it cannot independently
    discriminate removing C9's predecessor comparison; that guard is not
    claimed verified by this test. Other receiving/measuring work stays live.
    """
    rig = make_rig()
    first_claim(rig)
    q1 = rig.requests("belief_update")[0]
    second_claim = rig.claim(2)
    rig.drive(lambda: len(rig.facts(c.SEGMENT_BINDING)) == 2)
    second_raw = [r for r in rig.facts(c.SEGMENT_REPORT) if r.value == wire(second_claim)]
    assert len(second_raw) == 1
    second_bytes = rig.read_stored(second_raw[0].cid)

    def assert_only_first_request():
        assert [q.cid for q in rig.requests("belief_update")] == [q1.cid]
        prepared = [p.cid for p in rig.ledger.preparations
                    if p.record.body.contract == c.WORK_REQUESTED
                    and p.record.body.content.as_json()["desc"]["purpose"] == "belief_update"]
        assert prepared == [q1.cid], "K13: do not freeze a second Q* before confirmation"

    rig.settle_steps()
    assert_only_first_request()
    assert not rig.facts(c.BELIEF_ADOPTED)
    assert q1.value["desc"]["args"]["prior"] is None
    rig.ledger.hold_adoption_confirmation = uncertain
    w1 = rig.run_stage("belief_update", 0)
    rig.drive(lambda: bool(rig.facts(c.BELIEF_ADOPTED)))
    a1 = rig.one(c.BELIEF_ADOPTED)
    assert_update(rig, w1, a1, FIRST)
    if uncertain:
        assert rig.ledger.uncertain is not None
        held = rig.ledger.uncertain
        assert held.cid == a1.cid and rig.contents.blocked
    if uncertain:
        rig.settle_steps()
        assert [a.cid for a in rig.facts(c.BELIEF_ADOPTED)] == [a1.cid]
        assert_only_first_request()
        assert not rig.facts(c.STALE)
        before = len(rig.facts(c.RECEIVED))
        payload = b"still receiving during unconfirmed adoption"
        rig.host.post(received(payload))
        rig.drive(lambda: len(rig.facts(c.RECEIVED)) == before + 1)
        assert rig.facts(c.RECEIVED)[-1].value["data"] == list(payload)
        assert_only_first_request()
        snapshot = rig.read_stored(a1.cid)
        storage = rig.storage_snapshot()
        rig.host.rebuild_window()
        assert rig.storage_snapshot() == storage
        rig.settle_steps()
        assert rig.read_stored(a1.cid) == snapshot
        assert_only_first_request()
        assert not rig.facts(c.STALE)
        rig.contents.blocked.clear()
        rig.ledger.hold_adoption_confirmation = False
    rig.drive(lambda: len(rig.requests("belief_update")) == 2)
    q2 = rig.requests("belief_update")[1]
    assert q2.value["desc"]["args"]["prior"] == a1.cid
    assert q2.value["desc"]["work_id"] != q1.value["desc"]["work_id"]
    positions = {p.cid: i for i, p in enumerate(rig.ledger.preparations)}
    assert positions[a1.cid] < positions[q2.cid]
    assert second_raw[0].cid in closure(rig, q2.value["desc"]["numerical_view"]["boundary"])
    w2 = rig.run_stage("belief_update", 1)
    rig.drive(lambda: len(rig.facts(c.BELIEF_ADOPTED)) == 2)
    a2 = rig.facts(c.BELIEF_ADOPTED)[1]
    assert_update(rig, w2, a2, SECOND, a1.cid)
    assert not rig.facts(c.STALE), "K13: this public path cannot produce Stale"
    assert not rig.facts(c.CONFLICT)
    assert result_for(rig, q1.cid).value["result"] == FIRST
    assert result_for(rig, q2.cid).value["result"] == SECOND
    assert result_for(rig, q2.cid).value["result"] not in (FIRST, DOUBLE)
    assert rig.read_stored(second_raw[0].cid) == second_bytes
    assert rig.thread.is_alive()
    assert Counter(r for r, _budget in rig.workers.update_calls) == Counter({q1.cid: 1, q2.cid: 1})
    if uncertain:
        attempts = [p for p in rig.ledger.writes if p.cid == held.cid]
        assert attempts and all(p == held for p in attempts)
        assert len([p for p in rig.ledger.preparations if p.cid == held.cid]) == 1
        assert rig.read_stored(held.cid) == (held.header, held.salt, held.record)


@pytest.mark.parametrize("moment", ("before_entry", "before_reply", "after_result"))
@pytest.mark.parametrize("conflict", (False, True), ids=("same_redelivery", "late_conflicting_claim"))
def test_saved_late_clash_blocks_use_of_an_old_numerical_result(make_rig, conflict, moment):
    """Paper:2853-2865,3082-3092,3417,3485; 354,358 (Xuse).

    Bug: use only Xnum, only entry-time conflicts, or stop checking after R*.
    A negative observation is made only after the Wu reply's actual envelope
    has been accepted and its raw report saved, then settle has run. Holding
    confirmation of an already-written R* puts the third delivery before the
    adoption decision, rather than after an A* plan has already been made.
    A pre-entry clash can revoke the start ticket: in that case no legitimate
    Wu response is reachable, so verify that earlier public guard explicitly.
    """
    rig = make_rig()
    first_claim(rig)
    saved = rig.requests("belief_update")[0]
    original = rig.one(c.SEGMENT_BINDING).value["report"]
    original_bytes = rig.read_stored(original)
    _q, callback = rig.callback("belief_update")
    ready, release = Event(), Event()
    replies = []

    def reply(work, ctx):
        ret = rig.workers.compute(work, ctx)
        assert isinstance(ret, u.IssuedUpdate) and plain(ret.result) == FIRST
        ready.set()
        assert release.wait(10), "incomplete observation: test did not release Wu"
        event = rig.workers.finished(work, fb.WorkOutputs(outputs=u.update_response(ret)))
        replies.append(event)
        rig.workers.post(ctx, event, ret)

    def redeliver(*, accept_without_settle=False):
        report = fb.SegmentReport(segment=rig.one(c.SEGMENT_REQUESTED).cid, item_slot="claim-1",
            item=f.CoverageClaim(route_epoch="route-A",
                interval=f.MeasurementInterval(clock=rig.clock.run, start_ns=0, end_ns=2,
                                               closure="(start,end]"),
                kind="count_exactly_one" if conflict else "no_arrival",
                contract=c.COUNT_EXACTLY_ONE if conflict else c.NO_ARRIVAL, evidence=()))
        def emit(_work, ctx):
            if accept_without_settle:
                accept_posted(rig, report, lambda: rig.workers.post(ctx, report))
            else:
                rig.workers.post(ctx, report)
        rig.command(emit)
        if not accept_without_settle:
            rig.drive(lambda: any(r.value == wire(report) and r.cid != original
                                  for r in rig.facts(c.SEGMENT_REPORT)))
        return report

    rig.workers.overrides["belief_update"] = reply
    if moment == "before_entry":
        redeliver()
        release.set()
        callback()
        if not ready.is_set():
            assert conflict
            assert (saved.value["desc"]["work_id"], False) in rig.workers.entry_attempts
            assert not rig.workers.update_calls and not rig.workers.errors
            assert not rig.facts(c.UPDATE_RESULT) and not rig.facts(c.BELIEF_ADOPTED)
            assert rig.read_stored(original) == original_bytes
            assert any(p.kind == "conflict" and p.reason == "report:identity" and p.target == original
                       for p in rig.host.window.status().pending)
            return
    elif moment == "before_reply":
        worker_thread = Thread(target=callback, daemon=True)
        rig.workers.threads.append(worker_thread)
        worker_thread.start()
        assert ready.wait(3), "incomplete observation: Wu did not enter/compute"
        redeliver()
        release.set()
        worker_thread.join(3)
        assert not worker_thread.is_alive()
    else:
        rig.ledger.hold_result_confirmation = True
        release.set()
        callback()
        rig.drive(lambda: bool(rig.facts(c.UPDATE_RESULT)))
        assert rig.ledger.uncertain_result is not None
        assert not rig.facts(c.BELIEF_ADOPTED)
        redeliver(accept_without_settle=True)
        rig.contents.blocked.clear()
    assert not rig.workers.errors
    assert ready.is_set() and len(replies) == 1
    rig.drive(lambda: any(r.value == wire(replies[0]) for r in rig.facts(c.WORK_REPORT)))
    rig.settle_steps(12)
    work = next(w for w in rig.workers.entries if w.desc.purpose == "belief_update")
    if conflict:
        assert not rig.facts(c.BELIEF_ADOPTED)
        assert any(p.kind == "conflict" and p.reason == "report:identity" and p.target == original
                   for p in rig.host.window.status().pending)
    else:
        rig.drive(lambda: bool(rig.facts(c.BELIEF_ADOPTED)))
        adopted = rig.one(c.BELIEF_ADOPTED)
        assert_update(rig, work, adopted, FIRST)
        assert not rig.facts(c.CONFLICT)
    assert rig.read_stored(original) == original_bytes
    assert rig.read_stored(saved.cid)[2].body.content.as_json() == saved.value


@pytest.mark.parametrize("conflict", (False, True), ids=("equal_delivery", "conflicting_delivery"))
def test_accepted_unconfirmed_claim_already_blocks_update_use(make_rig, conflict):
    """Paper:354,358,2853,3082,3505 (R01).

    Bug: inspect only saved/confirmed reports. Accept the actual second
    delivery without settle, then attempt entry before its raw record even
    exists. This attempt precedes even the injected write fault: storage
    waiting cannot mask a missing accepted-delivery conflict check at entry.
    Hold the Claim before commit, verify no R*/A* while unconfirmed, then
    confirm and check again. The equal-content control enters and issues
    before the write fault, and reaches A* after storage is released. This
    fault also delays its reply saving; no liveness during that fault is
    assumed, nor a separate claim about an already-entered Wu's R* guard.
    """
    rig = make_rig()
    first_claim(rig)
    q, callback = rig.callback("belief_update")
    original = rig.one(c.SEGMENT_BINDING).value["report"]
    replies = []

    def reply(work, ctx):
        ret = rig.workers.compute(work, ctx)
        assert isinstance(ret, u.IssuedUpdate) and plain(ret.result) == FIRST
        event = rig.workers.finished(work, fb.WorkOutputs(outputs=u.update_response(ret)))
        accept_posted(rig, event, lambda: rig.workers.post(ctx, event, ret))
        replies.append(event)

    rig.workers.overrides["belief_update"] = reply
    report = fb.SegmentReport(segment=rig.one(c.SEGMENT_REQUESTED).cid, item_slot="claim-1",
        item=f.CoverageClaim(route_epoch="route-A",
            interval=f.MeasurementInterval(clock=rig.clock.run, start_ns=0, end_ns=2,
                                           closure="(start,end]"),
            kind="count_exactly_one" if conflict else "no_arrival",
            contract=c.COUNT_EXACTLY_ONE if conflict else c.NO_ARRIVAL, evidence=()))
    envelopes = []
    def deliver(_work, ctx):
        envelopes.append(accept_posted(rig, report, lambda: rig.workers.post(ctx, report)))
    rig.ledger.hold_claim_confirmation = True
    rig.command(deliver)
    assert not [r for r in rig.facts(c.SEGMENT_REPORT) if r.cid != original and r.value == wire(report)]
    receipt = next(r for r in rig.host.window.status().receipts if r.envelope == envelopes[0])
    assert receipt.state == "accepted" and any(slot.state != "saved" for slot in receipt.slots)
    callback()
    assert (q.value["desc"]["work_id"], not conflict) in rig.workers.entry_attempts
    assert not rig.workers.errors
    if conflict:
        assert not rig.workers.update_calls and not replies
    else:
        assert len(replies) == 1
    rig.drive(lambda: rig.ledger.uncertain_claim is not None)
    held = rig.ledger.uncertain_claim
    assert held.record.body.content.as_json() == wire(report)
    assert held.cid not in dict(rig.entry_store.load())
    receipt = next(r for r in rig.host.window.status().receipts if r.envelope == envelopes[0])
    assert any(slot.state != "saved" for slot in receipt.slots)
    rig.settle_steps()
    assert not rig.facts(c.UPDATE_RESULT) and not rig.facts(c.BELIEF_ADOPTED)
    rig.ledger.hold_claim_confirmation = False
    rig.drive(lambda: any(r.envelope == envelopes[0] and all(s.state == "saved" for s in r.slots)
                         for r in rig.host.window.status().receipts))
    rig.settle_steps()
    if conflict:
        assert not rig.facts(c.UPDATE_RESULT) and not rig.facts(c.BELIEF_ADOPTED)
        assert any(p.kind == "conflict" and p.reason in ("report:identity", "update:conflict")
                   for p in rig.host.window.status().pending)
    else:
        rig.drive(lambda: any(r.value == wire(replies[0]) for r in rig.facts(c.WORK_REPORT)))
        rig.drive(lambda: bool(rig.facts(c.BELIEF_ADOPTED)))
        work = next(w for w in rig.workers.entries if w.request == q.cid)
        assert_update(rig, work, rig.one(c.BELIEF_ADOPTED), FIRST)
    assert rig.read_stored(held.cid) == (held.header, held.salt, held.record)
    attempts = rig.ledger.held_claim_attempts + [p for p in rig.ledger.writes if p.cid == held.cid]
    assert attempts and all(p == held for p in attempts)


@pytest.mark.parametrize("missing", (None, "binding", "claim", "law", "reading", "monitor"))
def test_u_cannot_borrow_required_inputs_outside_its_fixed_roots(make_rig, missing):
    """Paper:2781-2793,3303,3332-3335,3473,3494.

    Bug: a wide reader silently repairs a deficient Xnum. The reader keeps
    every real body; the saved request has the same args and declared inputs.
    Its independently keyed root closure actually excludes the selected input.
    The nearest legal copy with the complete roots must issue CE1.
    """
    rig = make_rig()
    work, _adoption, evidence = direct_first(rig)
    binding = rig.one(c.SEGMENT_BINDING)
    points = {"binding": binding.cid, "claim": binding.value["report"],
        "law": rig.one(c.FINITE_JOINT_COUNT_LAW).cid,
        "reading": work.desc.args.observations[0].reading,
        "monitor": rig.one(c.MONITOR_SPAN).cid}
    boundary = work.desc.numerical_view.boundary
    if missing is not None:
        target = points[missing]
        boundary = frozenset(p for p in boundary if target not in closure(rig, (p,)))
        assert target not in closure(rig, boundary)
        assert PublicReader(rig.ledger).record(target) == rig.read_stored(target)[2]
    desc = replace(work.desc, numerical_view=fixed_view(rig, boundary))
    q = save_request(rig, work, desc=desc)
    qbody = rig.read_stored(q)[2].body
    assert qbody.inputs == rig.read_stored(work.request)[2].body.inputs
    assert qbody.content.as_json()["desc"]["args"] == wire(work.desc.args)
    try:
        ret = direct_update(rig, q, evidence)
    except f.FReplayUnavailable as error:
        # A logical absence from the required fixed image is also a typed
        # unavailable-input outcome at this public boundary (U docstring).
        assert missing is not None and "missing_input" in str(error)
        assert PublicReader(rig.ledger).record(target) == rig.read_stored(target)[2]
        return
    if missing is None:
        assert isinstance(ret, u.IssuedUpdate) and plain(ret.result) == FIRST
    else:
        assert isinstance(ret, (u.Rejected, u.Insufficient)) and ret.issues


@pytest.mark.parametrize("missing", (None, "segment", "route"))
def test_u_derives_mandatory_closure_independently_of_decided_inputs(make_rig, missing):
    """Paper:2781-2793,3333,3475. Bug: trust Desc.input_points as a closure certificate.

    Only Decided.inputs loses one required Ref; Xnum, all args, input_points,
    bodies and real evidence remain complete. Complete outer inputs issue.
    """
    rig = make_rig()
    work, _adoption, evidence = direct_first(rig)
    b = rig.one(c.SEGMENT_BINDING)
    required = {"segment": b.value["segment"], "route": b.value["route"]}
    old = rig.read_stored(work.request)[2].body
    inputs = old.inputs
    if missing is not None:
        ref = rig.read_stored(required[missing])[2].id
        assert ref in inputs
        inputs = tuple(r for r in inputs if r != ref)
        assert len(inputs) == len(old.inputs) - 1
    q = save_request(rig, work, inputs=inputs)
    ret = direct_update(rig, q, evidence)
    if missing is None:
        assert isinstance(ret, u.IssuedUpdate) and plain(ret.result) == FIRST
    else:
        assert isinstance(ret, (u.Rejected, u.Insufficient)) and ret.issues


@pytest.mark.parametrize("ref", (c.FINITE_UPDATE_COMPUTE, c.FINITE_SEGMENT_PROJECTION),
                         ids=("update_compute", "segment_projection"))
@pytest.mark.parametrize("omit", (None, "declaration", "implementation"))
def test_u_requires_declared_and_implemented_stage3_capabilities(make_rig, ref, omit):
    """Paper:3333,3478; F-a:114,459,470. Bug: hard-coded U bypasses its registry.

    Rekey the saved Q* to the actual reduced registry, so an unrelated key
    mismatch cannot mask missing meaning (Rejected) versus ability (Insufficient).
    """
    rig = make_rig()
    work, _adoption, evidence = direct_first(rig)
    selected = [d for d in rig.registry.declarations if d.ref == ref]
    assert len(selected) == 1
    key = (selected[0].kind, ref)
    reduced = f.make_f_registry(
        declarations=tuple(d for d in rig.registry.declarations
                           if omit != "declaration" or (d.kind, d.ref) != key),
        implementations=tuple(i for i in rig.registry.implementations
            if omit is None or (i.kind, i.ref) != key))
    desc = replace(work.desc, numerical_view=fixed_view(rig, work.desc.numerical_view.boundary,
                                                     registry=reduced))
    q = save_request(rig, work, desc=desc)
    ret = direct_update(rig, q, evidence, registry=reduced)
    if omit is None:
        assert isinstance(ret, u.IssuedUpdate) and plain(ret.result) == FIRST
    else:
        expected = u.Rejected if omit == "declaration" else u.Insufficient
        assert isinstance(ret, expected) and ret.issues
        assert any(i.code == ("missing_contract" if omit == "declaration" else "algorithm_unavailable")
                   for i in ret.issues)


@pytest.mark.parametrize("change", (None, "no_executions", "claim_not_in_worker_reports"))
def test_u_requires_independent_execution_and_that_workers_original_report(make_rig, change):
    """Paper:2833-2847,3332,3336 (G6). Bug: B/Started and uses/acquisitions stand in for EW.

    Remove only executions, or just this Claim from the measuring work's
    reports. All saved facts, uses and acquisitions remain the legal CE1 ones.
    """
    rig = make_rig()
    work, _adoption, original = direct_first(rig)
    binding = rig.one(c.SEGMENT_BINDING)
    raw = binding.value["report"]
    measure = next(w for w in rig.workers.entries if w.desc.purpose == "measure_segment")
    measured = [e for e in original.executions if e.work_id == measure.desc.work_id]
    assert len(measured) == 1 and any(r.point == raw for r in measured[0].reports)
    evidence = original
    if change == "no_executions":
        evidence = replace(original, executions=())
    elif change is not None:
        evidence = replace(original, executions=tuple(replace(e,
            reports=tuple(r for r in e.reports if r.point != raw))
            if e.work_id == measure.desc.work_id else e for e in original.executions))
    assert evidence.uses == original.uses and evidence.acquisitions == original.acquisitions
    assert evidence.intervals == original.intervals
    ret = direct_update(rig, work.request, evidence)
    if change is None:
        assert isinstance(ret, u.IssuedUpdate) and plain(ret.result) == FIRST
    else:
        assert isinstance(ret, u.Insufficient) and ret.issues


def test_context_read_and_monitored_are_revoked_after_actual_run_return(make_rig):
    """Paper:3479 (expired context),3499. Bug: enter-once permits use after stop forever.

    The same retained public ctx succeeds during run; after actual launcher
    return both operations raise RuntimeError and change no TargetEvidence.
    """
    rig = make_rig()
    rig.initial_evaluation()
    segment = rig.start_measurement()
    interval = f.MeasurementInterval(clock=rig.clock.run, start_ns=0, end_ns=0,
                                     closure="[start,end]")
    seen = []
    def use(work, ctx):
        before = ctx.evidence()
        assert isinstance(ctx.read(segment.cid), bytes)
        ctx.monitored(interval)
        after = ctx.evidence()
        assert len(after.uses) == len(before.uses) + 1
        assert len(after.intervals) == len(before.intervals) + 1
        assert after.uses[-1].work_id == work.desc.work_id and after.uses[-1].point == segment.cid
        assert after.intervals[-1].interval == interval
        seen.append(ctx)
    rig.command(use)
    assert rig.thread.is_alive() and len(seen) == 1
    rig.workers.release.set()
    rig.thread.join(2)
    assert not rig.thread.is_alive()
    ctx = seen[0]
    before = ctx.evidence()
    with pytest.raises(RuntimeError):
        ctx.read(segment.cid)
    assert ctx.evidence() == before
    with pytest.raises(RuntimeError):
        ctx.monitored(interval)
    assert ctx.evidence() == before


def test_u_non_update_request_raises_typed_input_error(make_rig):
    """Paper:3323,3482; public compute_finite_update docstring:215.

    Bug: malformed request takes an undefined-name path. A saved Qgen has
    real header/body, but cannot be interpreted as belief_update; use a real
    successful CE1 call as the closest correctly typed request.
    """
    rig = make_rig()
    _work, _adoption, evidence = direct_first(rig)
    qgen = rig.one(c.CANDIDATE_REQUEST)
    with pytest.raises(f.FInputError):
        direct_update(rig, qgen.cid, evidence)


def test_implied_claim_keeps_numerical_result_and_semantic_application_digest(make_rig):
    """Paper:2763-2769,3304 (C6). Bug: hash delivery partitions/Claim history instead of meaning.

    Distinct slot N((0,1])=0 is implied by adopted N((0,2])=0. Both actual
    R* records must keep joint, evidence mass and digest, despite distinct Q/B.
    """
    rig = make_rig()
    first_claim(rig)
    w1, a1 = rig.adopt()
    r1 = assert_update(rig, w1, a1, FIRST)
    interval = f.MeasurementInterval(clock=rig.clock.run, start_ns=0, end_ns=1,
                                     closure="(start,end]")
    rig.claim(1, slot="implied-subwindow", interval=interval)
    rig.drive(lambda: len(rig.requests("belief_update")) == 2)
    w2, a2 = rig.adopt(2)
    r2 = assert_update(rig, w2, a2, FIRST, a1.cid)
    assert w2.desc.args.observations != w1.desc.args.observations
    assert r2.value["result"] == r1.value["result"] == FIRST
    assert r2.value["application_digest"] == r1.value["application_digest"]


@pytest.mark.parametrize("ambiguous", (False, True), ids=("one_channel", "same_quantity_two_ids"))
def test_count_channel_mapping_is_unique_not_just_a_channel_id(make_rig, ambiguous):
    """Paper:2698,2763,2920-2927 (FB23-R04). Bug: arbitrarily pick u from two matching channels.

    The negative Boot declares the paper's four-row u/v law with identical
    route/domain; the positive removes v and marginalizes that same table.
    The latter's expected posterior is (3/4,1/4), mass 1/2.
    """
    args = delta_args()
    domain = {"start_ns": 0, "end_ns": 1, "closure": "(start,end]"}
    args["law"]["channels"] = [{"id": name, "route_slots": ["route"], "domain": domain}
                                for name in (("u", "v") if ambiguous else ("u",))]
    args["claims"][0]["channel"] = "u"
    if ambiguous:
        rows = [((0, 0), F(9, 16), F(1, 16)), ((0, 1), F(3, 16), F(3, 16)),
                ((1, 0), F(3, 16), F(3, 16)), ((1, 1), F(1, 16), F(9, 16))]
        args["law"]["rows"] = [{"marks": [{"channel": ch, "time_ns": 1, "count": n}
            for ch, n in zip(("u", "v"), counts) if n], "mass": [plain(a), plain(b)]}
            for counts, a, b in rows]
    else:
        args["law"]["rows"] = [{"marks": [], "mass": [[3, 4], [1, 4]]},
            {"marks": [{"channel": "u", "time_ns": 1, "count": 1}],
             "mass": [[1, 4], [3, 4]]}]
    rig = make_rig(derivation_args=args)
    rig.initial_evaluation()
    rig.start_measurement()
    rig.claim(1, interval=f.MeasurementInterval(clock=rig.clock.run, start_ns=0, end_ns=1,
                                               closure="(start,end]"))
    rig.drive(lambda: bool(rig.requests("belief_update")))
    work = rig.run_stage("belief_update")
    ret = rig.workers.returns[work.request]
    if ambiguous:
        assert isinstance(ret, u.Rejected) and any(i.code == "shape" for i in ret.issues)
        assert_no_adoption(rig, work.request)
    else:
        expected = {"joint": [[3, 4], [1, 4]], "evidence_mass": [1, 2]}
        assert isinstance(ret, u.IssuedUpdate) and plain(ret.result) == expected
        rig.drive(lambda: bool(rig.facts(c.BELIEF_ADOPTED)))
        assert result_for(rig, work.request).value["result"] == expected


def test_unreferenced_missing_prediction_body_preserves_old_prepare_except_reader_key(make_rig):
    """Paper:3337,3500 (K12); F-a:454-458,470; user's sixth-turn correction.

    No A* exists. Keep identical original inputs and add one unreferenced
    Prediction entry whose body is absent only in the wider public reader.
    Its absent body must not become missing_input while looking for A*.
    The response kind and every artifact JSON field except the environment's
    reader_view_key stay equal. That key must include the added header and
    its absent-body marker, rather than keeping the old captured image's key.
    """
    rig = make_rig()
    rig.initial_evaluation()
    ep = next(w for w in rig.workers.entries if w.desc.purpose == "evaluation_prepare")
    kwargs = prepare_kwargs(ep)
    points = {e.cid for e in rig.workers.prepares[0][1].entries()}
    old_reader = PublicReader(rig.ledger, points=points)
    before = u.prepare_fb_from_facts(old_reader, registry=rig.registry,
                                   evidence=current_evidence(rig), **kwargs)
    assert isinstance(before.value, f.FProblem) and not rig.facts(c.BELIEF_ADOPTED)
    extra_record = rig.record(Prediction(target="unreferenced", about=(), basis=(),
        contract=contract("test.fb3.unreferenced"), content=Payload.json({"unused": 17})),
        RefKind.PREDICTION, Role.MODEL)
    extra = rig.ledger.append(extra_record, ()).cid
    reader = PublicReader(rig.ledger, points=points | {extra}, missing={extra})
    assert extra in {e.cid for e in reader.entries()} and extra not in points
    with pytest.raises(KeyError):
        reader.record(extra)
    after = u.prepare_fb_from_facts(reader, registry=rig.registry,
                                  evidence=current_evidence(rig), **kwargs)
    assert isinstance(after.value, type(before.value))
    rows = []
    headers = dict(rig.entry_store.load())
    for entry in sorted(reader.entries(), key=lambda item: item.cid):
        row = {"point": entry.cid, "header_hex": headers[entry.cid].hex(),
            "body_present": entry.cid != extra, "salt_hex": None,
            "payload_media_type": None, "payload_hex": None, "record_hex": None}
        if entry.cid != extra:
            _header, salt, record = rig.read_stored(entry.cid)
            value = wire(record)
            value["body"] = {"type": type(record.body).__name__, "value": wire(record.body)}
            row.update(salt_hex=salt.hex(), payload_media_type=record.body.content.media_type,
                       payload_hex=record.body.content.data.hex(), record_hex=canonical(value).hex())
        rows.append(row)
    expected_key = "sha256:" + sha256(canonical({"domain": "sui.f.reader_view/1", "entries": rows})).hexdigest()
    before_json, after_json = json.loads(before.canonical_bytes), json.loads(after.canonical_bytes)
    before_key = before_json["environment"].pop("reader_view_key")
    after_key = after_json["environment"].pop("reader_view_key")
    assert before_key == captured_reader_key(rig, old_reader)
    assert after_key == expected_key and after_key != before_key
    assert after_json == before_json


def copied_prior_chain(rig, first, adoption, second, change):
    """Rebind references identically in control and negative; corrupt one value."""
    old_r = result_for(rig, first.request)
    rvalue = json.loads(json.dumps(old_r.value))
    if change in ("application_digest", "registry_key"):
        rvalue[change] = "sha256:" + "0" * 64
        assert rvalue[change] != old_r.value[change]
    elif change == "numerical_view":
        rvalue["numerical_view"]["environment"]["reader_view_key"] = "sha256:" + "0" * 64
    elif change == "result_joint":
        rvalue["result"]["joint"] = [[1, 2], [1, 2]]
    elif change == "result_mass":
        rvalue["result"]["evidence_mass"] = [1, 1]
    rfield = ("result" if change in ("result_joint", "result_mass") else
              change if change in ("application_digest", "registry_key", "numerical_view") else None)
    assert {k for k in old_r.value if old_r.value[k] != rvalue[k]} == ({rfield} if rfield else set())
    new_r = save_copy(rig, old_r.cid, value=rvalue)
    old_g = rig.by_cid(ACQUIRED, adoption.value["acquisition"])
    old_clock = old_g.value["clock"]
    now = rig.clock.mono_ns()
    clock_value = rig.read_stored(old_clock)[2].body.content.as_json()
    clock_value["reading"]["time_ns"] = now
    new_clock = save_copy(rig, old_clock, value=clock_value, received_ns=now,
        parents=front(rig, events_for(rig, {new_r, clock_value["source"]})))
    gvalue = dict(old_g.value, contents=[new_r], clock=new_clock)
    legal_gvalue = dict(gvalue)
    extra_points = set()
    if change == "acquisition_origin":
        other_origin = save_copy(rig, rig.one(ORIGIN).cid)
        extra_points.add(other_origin)
        gvalue["origin"] = other_origin
    elif change == "acquisition_contents":
        gvalue["contents"] = [rig.model_point]
    gfield = {"acquisition_origin": "origin", "acquisition_contents": "contents"}.get(change)
    assert {k for k in gvalue if gvalue[k] != legal_gvalue[k]} == ({gfield} if gfield else set())
    new_g = save_copy(rig, old_g.cid, value=gvalue, received_ns=now,
        parents=front(rig, {new_clock if p == old_clock else p for p in old_g.parents} | extra_points))
    acquisition = new_g
    assert rig.read_stored(acquisition)[2].body.contract == ACQUIRED
    avalue = dict(adoption.value, result=new_r, acquisition=acquisition)
    replace_refs = {old_r.record_id: rig.read_stored(new_r)[2].id,
                    old_g.record_id: rig.read_stored(acquisition)[2].id}
    ainputs = tuple(replace_refs.get(r, r) for r in rig.read_stored(adoption.cid)[2].body.inputs)
    new_a = save_copy(rig, adoption.cid, value=avalue, inputs=ainputs,
                     parents=front(rig, events_for(rig, {new_r, new_g})))
    mapping = {old_r.cid: new_r, old_g.cid: new_g, old_clock: new_clock, adoption.cid: new_a}
    desc = second.desc
    boundary = frozenset(mapping.get(p, p) for p in desc.numerical_view.boundary) | extra_points
    assert new_a in closure(rig, boundary) and adoption.cid not in closure(rig, boundary)
    changed_desc = replace(desc, args=replace(desc.args, prior=new_a),
        input_points=frozenset(mapping.get(p, p) for p in desc.input_points) | extra_points,
        numerical_view=fixed_view(rig, boundary))
    references = {rig.read_stored(old)[2].id: rig.read_stored(new)[2].id
                  for old, new in mapping.items()}
    old_q = rig.by_cid(c.WORK_REQUESTED, second.request)
    qinputs = tuple({references.get(r, r) for r in rig.read_stored(second.request)[2].body.inputs}
                    | {rig.read_stored(p)[2].id for p in extra_points})
    new_q = save_request(rig, second, desc=changed_desc, inputs=qinputs,
        parents=front(rig, {mapping.get(p, p) for p in old_q.parents}))
    assert rig.by_cid(c.UPDATE_RESULT, new_r).value == rvalue
    return new_q, new_a, new_r, mapping


def current_evidence(rig):
    """Z8: retained public ctx, never host state; evidence() is also valid after run."""
    ctx = rig.workers.contexts.get("measure_segment", rig.workers.contexts["evaluation_prepare"])
    return ctx.evidence()


_CURRENT_EVIDENCE = object()


def adoption_prepare_inputs(rig, new_a, new_r, *, sole_adoption=False, additional_roots=()):
    """Fresh valid context, complete history roots, and exactly one visible head."""
    initial_ep = next(w for w in rig.workers.entries if w.desc.purpose == "evaluation_prepare")
    roots = set(initial_ep.desc.args.input.fixed_parents) | set(additional_roots)
    head = rig.read_stored(new_a)[2].body.content.as_json()
    head_q = rig.read_stored(head["request"])[2].body.content.as_json()["desc"]
    roots |= {new_a, new_r} | set(head_q["numerical_view"]["boundary"])
    # The original Ep's observation/judgment precede every adoption. A fresh
    # public context must observe the copied A*, otherwise chronology alone
    # rejects every chain and masks the four intended replay comparisons.
    old_context = rig.read_stored(initial_ep.desc.args.input.context)[2].body.content.as_json()
    now = rig.clock.mono_ns()
    readings = []
    for name in ("observation_reading", "judgment_reading"):
        old_clock = old_context[name]
        clock_value = rig.read_stored(old_clock)[2].body.content.as_json()
        clock_value["reading"]["time_ns"] = now
        readings.append(save_copy(rig, old_clock, value=clock_value, received_ns=now,
            parents=front(rig, events_for(rig, {new_a, clock_value["source"]}))))
    context_value = dict(old_context, observation_reading=readings[0], judgment_reading=readings[1])
    context = save_copy(rig, initial_ep.desc.args.input.context, value=context_value, received_ns=now,
                        parents=front(rig, events_for(rig, {new_a, *readings})))
    roots.add(context)
    visible_history = closure(rig, roots)
    adoptions = [a for a in rig.facts(c.BELIEF_ADOPTED) if a.cid in visible_history]
    heads = {a.cid for a in adoptions} - {a.value["previous"] for a in adoptions}
    assert heads == {new_a}, "a second head must not mask the intended chain check"
    kwargs = prepare_kwargs(initial_ep, fixed_parents=tuple(sorted(roots)))
    kwargs["context_ref"] = context
    visible = closure(rig, roots) | {e.cid for e in rig.workers.prepares[0][1].entries()}
    if sole_adoption:
        all_adoptions = {a.cid for a in rig.facts(c.BELIEF_ADOPTED)}
        assert visible_history & all_adoptions == {new_a}, "fixed roots must contain just the copied A*"
        assert visible & all_adoptions == {new_a}, "the whole FReader must contain just the copied A*"
        assert closure(rig, visible) <= visible, "an excluded A* must not hide behind an entry's parent"
    kwargs["registry"] = rig.registry
    return PublicReader(rig.ledger, points=visible), kwargs


def prepare_adoption(rig, new_a, new_r, *, sole_adoption=False, additional_roots=(),
                     evidence=_CURRENT_EVIDENCE):
    reader, kwargs = adoption_prepare_inputs(rig, new_a, new_r,
        sole_adoption=sole_adoption, additional_roots=additional_roots)
    return u.prepare_fb_from_facts(reader,
        evidence=current_evidence(rig) if evidence is _CURRENT_EVIDENCE else evidence, **kwargs)


@pytest.mark.parametrize("change", (None, "application_digest", "registry_key", "numerical_view",
    "result_joint", "result_mass", "acquisition_origin", "acquisition_contents"))
def test_previous_adoption_is_fully_checked_by_u_and_evaluation_prepare(make_rig, change):
    """Paper:2799-2809,3082-3092,3335,3500,3508,3651 (R04); C7:3305.

    Bug: skip one R* result/metadata field, or accept any acquired-content
    record regardless of its origin/contents. Each negative changes exactly
    one R* field or one G field; G always has the correct saved contract.
    Control copies use the same reference rebinding and must succeed in U
    and in preparation, excluding missing refs, old clocks and a second head.
    """
    rig = make_rig()
    first, a1, _evidence = direct_first(rig)
    rig.claim(2)
    rig.drive(lambda: len(rig.requests("belief_update")) == 2)
    second, a2 = rig.adopt(2)
    assert_update(rig, second, a2, SECOND, a1.cid)
    evidence = rig.workers.update_evidence[second.request]
    q, new_a, new_r, mapping = copied_prior_chain(rig, first, a1, second, change)
    evidence = replace_evidence_points(evidence, mapping)
    ret = direct_update(rig, q, evidence)
    try:
        prepared = prepare_adoption(rig, new_a, new_r,
            evidence=replace_evidence_points(current_evidence(rig), mapping))
    except (f.FInputError, f.FReplayMismatch, f.FReplayUnavailable, f.FIncomplete,
            f.FSpecificationMissing):
        if change is None:
            raise
        prepared = None
    if change is None:
        assert isinstance(ret, u.IssuedUpdate) and plain(ret.result) == SECOND
        assert prepared is not None and isinstance(prepared.value, f.FProblem)
        assert prepared.value.K.belief == rig.read_stored(new_r)[2].id
    else:
        assert isinstance(ret, (u.Rejected, u.Insufficient)) and ret.issues
        assert prepared is None or isinstance(prepared.value, f.NoDecision)


@pytest.mark.parametrize("mismatch", (False, True), ids=("matching_prior", "head_previous_differs"))
def test_prepare_checks_unique_head_previous_against_its_requests_prior(make_rig, mismatch):
    """Paper:2799-2807,3082-3088,3500,3508,3651 (K12/R04).

    Bug: trust a unique A* head without comparing previous to its Q*.prior.
    Keep A*.previous=A1, hence exactly one head. Build Q* with prior=None
    only in the negative and actually issue its correct one-observation
    result, with matching R* fields, report, G and time. Thus a bad R*, an
    invalid acquisition or two competing heads cannot reject it first.
    """
    rig = make_rig()
    first, a1, _evidence = direct_first(rig)
    rig.claim(2)
    rig.drive(lambda: len(rig.requests("belief_update")) == 2)
    second, a2 = rig.adopt(2)
    evidence = rig.workers.update_evidence[second.request]
    desc = replace(second.desc, args=replace(second.desc.args, prior=None if mismatch else a1.cid))
    q = save_request(rig, second, desc=desc)
    issued = direct_update(rig, q, evidence)
    expected = FIRST if mismatch else SECOND
    assert isinstance(issued, u.IssuedUpdate) and plain(issued.result) == expected
    old_r = result_for(rig, second.request)
    terminal = next(t for t in rig.facts(c.WORK_TERMINAL) if t.value["request"] == second.request)
    old_report = rig.by_cid(c.WORK_REPORT, terminal.value["first_receipt"])
    report_value = json.loads(json.dumps(old_report.value))
    report_value["outcome"] = {"kind": "outputs", "value": wire(u.update_response(issued))}
    raw = save_copy(rig, old_report.cid, value=report_value,
        parents=front(rig, {q if p == second.request else p for p in old_report.parents}))
    rvalue = {"request": q, "result": plain(issued.result),
        "application_digest": issued.application_digest, "numerical_view": wire(desc.numerical_view),
        "registry_key": issued.registry_key}
    rbody = replace(rig.read_stored(old_r.cid)[2].body, content=Payload.json(rvalue),
        about=(rig.read_stored(q)[2].id,), basis=(rig.read_stored(q)[2].id, rig.read_stored(raw)[2].id))
    rrecord = rig.record(rbody, RefKind.PREDICTION, Role.MODEL)
    r = rig.ledger.write(rig.ledger.prepare(rrecord, front(rig, {q, raw}))).cid
    old_g = rig.by_cid(ACQUIRED, a2.value["acquisition"])
    now = rig.clock.mono_ns()
    clock_value = rig.read_stored(old_g.value["clock"])[2].body.content.as_json()
    clock_value["reading"]["time_ns"] = now
    clock = save_copy(rig, old_g.value["clock"], value=clock_value, received_ns=now,
        parents=front(rig, events_for(rig, {clock_value["source"], r})))
    g = save_copy(rig, old_g.cid, value=dict(old_g.value, clock=clock, contents=[r]), received_ns=now,
                  parents=(clock,))
    avalue = dict(a2.value, request=q, result=r, acquisition=g, previous=a1.cid)
    ainputs = tuple(rig.read_stored(p)[2].id for p in
                    {second.desc.reader, rig.model_point, a1.cid, q, r, g})
    head = save_copy(rig, a2.cid, value=avalue, inputs=ainputs,
                     parents=front(rig, events_for(rig, {r, g, a1.cid})))
    assert (avalue["previous"] != desc.args.prior) == mismatch
    # U has already independently validated this Q* and its numerical answer;
    # the preparation must now discriminate only the A*/Q* link.
    mapping = {second.request: q, old_report.cid: raw, old_r.cid: r, old_g.cid: g,
               old_g.value["clock"]: clock, a2.cid: head}
    try:
        prepared = prepare_adoption(rig, head, r,
            evidence=replace_evidence_points(current_evidence(rig), mapping))
    except (f.FInputError, f.FReplayMismatch, f.FReplayUnavailable, f.FIncomplete,
            f.FSpecificationMissing):
        if not mismatch:
            raise
        prepared = None
    if mismatch:
        assert prepared is None or isinstance(prepared.value, f.NoDecision)
    else:
        assert prepared is not None and isinstance(prepared.value, f.FProblem)
        assert prepared.value.K.belief == rig.read_stored(r)[2].id


@pytest.mark.parametrize("change", (None, "reader_view_key", "registry_key"))
def test_u_checks_each_fixed_view_key_with_the_complete_correct_boundary(make_rig, change):
    """Paper:3303,3333,3506 (R02); F-a:454-470.

    Bug: use correct inputs but ignore the declared view/registry key. Keep
    the complete boundary, args, outer inputs, registry and real evidence;
    only one key differs. An identical legal copy issues the first CE1 value.
    """
    rig = make_rig()
    work, _adoption, evidence = direct_first(rig)
    original = work.desc.numerical_view
    view = original if change is None else replace(original, **{change: "sha256:" + "0" * 64})
    assert view.boundary == original.boundary
    assert {name for name in ("reader_view_key", "registry_key")
            if getattr(view, name) != getattr(original, name)} == ({change} if change else set())
    q = save_request(rig, work, desc=replace(work.desc, numerical_view=view))
    assert rig.read_stored(q)[2].body.inputs == rig.read_stored(work.request)[2].body.inputs
    ret = direct_update(rig, q, evidence)
    if change is None:
        assert isinstance(ret, u.IssuedUpdate) and plain(ret.result) == FIRST
    else:
        assert isinstance(ret, (u.Rejected, u.Insufficient)) and ret.issues


def budget_request(rig, work, budget):
    return save_request(rig, work, desc=replace(work.desc, args=replace(work.desc.args, budget=budget)))


def assert_budget_shortage(ret, *, phase=None):
    assert isinstance(ret, u.Insufficient) and ret.issues
    needs = [need for issue in ret.issues if issue.code == "budget_exhausted" for need in issue.missing]
    assert any(n.kind == "budget" and (phase is None or plain(n.value)["phase"] == phase)
               for n in needs), [(n.kind, plain(n.value)) for n in needs]


def test_reader_snapshot_budget_returns_insufficient_instead_of_raising(make_rig):
    """Paper:3323,3475 (J4),3482. Bug: FIncomplete from reader capture escapes U.

    max_cells=1 cannot even represent the known multiple-entry reader. The
    exact same facts/evidence with the ordinary budget issue the CE1 value.
    """
    rig = make_rig()
    work, _a, evidence = direct_first(rig)
    assert len(PublicReader(rig.ledger).entries()) > 1
    budget = cells(UPDATE_BUDGET, 1)
    q = budget_request(rig, work, budget)
    ret = direct_update(rig, q, evidence, budget=budget)
    assert_budget_shortage(ret, phase="reader")


def test_term_budget_is_shared_with_previous_update_replay(make_rig):
    """Paper:2805-2811,3475 (one-call budget),3482,3511 (R07).

    Bug: reset max_terms between replay and the new observation. BOTH the
    first observation and the second observation alone must issue with the
    selected budget. Otherwise second-call Insufficient might just be the
    second projection being individually too expensive. Every successful
    trial equals CE1; ordinary full replay must still give SECOND.
    """
    rig = make_rig()
    first, a1, first_evidence = direct_first(rig)
    rig.claim(2)
    rig.drive(lambda: len(rig.requests("belief_update")) == 2)
    second, a2 = rig.adopt(2)
    assert_update(rig, second, a2, SECOND, a1.cid)
    evidence = rig.workers.update_evidence[second.request]
    alone_desc = replace(second.desc, args=replace(second.desc.args, prior=None))
    alone = replace(second, request=save_request(rig, second, desc=alone_desc), desc=alone_desc)
    ordinary_alone = direct_update(rig, alone.request, evidence)
    assert isinstance(ordinary_alone, u.IssuedUpdate) and plain(ordinary_alone.result) == FIRST
    shared_budget = None
    for terms in range(1, 129):
        budget = logical(UPDATE_BUDGET, terms)
        q1 = budget_request(rig, first, budget)
        q_alone = budget_request(rig, alone, budget)
        controls = (direct_update(rig, q1, first_evidence, budget=budget),
                    direct_update(rig, q_alone, evidence, budget=budget))
        for ret in controls:
            if isinstance(ret, u.IssuedUpdate):
                assert plain(ret.result) == FIRST
            else:
                assert_budget_shortage(ret)
        if all(isinstance(ret, u.IssuedUpdate) for ret in controls):
            shared_budget = budget
            break
    assert shared_budget is not None, "no budget admits both separate computations in the bounded range"
    q2 = budget_request(rig, second, shared_budget)
    ret = direct_update(rig, q2, evidence, budget=shared_budget)
    assert_budget_shortage(ret)
    assert any(need.kind == "budget" and plain(need.value)["phase"] in
               ("projection", "replay", "computation") for issue in ret.issues for need in issue.missing)
    ordinary = direct_update(rig, second.request, evidence)
    assert isinstance(ordinary, u.IssuedUpdate) and plain(ordinary.result) == SECOND


@pytest.mark.parametrize("contradiction", (False, True), ids=("model_zero", "three_way_contradiction"))
def test_integer_compatibility_search_exhaustion_is_not_a_logical_verdict(make_rig, contradiction):
    """Paper:2857-2861 (three-way conjunction),3475,3481,3511 (J9-b/R07).

    Bug: omit the integer search-size bound while retaining the scalar term
    counter. Twelve involved point/open cells each have upper=1, hence a
    2**12 box even though the table is only two/three rows and two carriers. Scalar
    single-observation controls fit max_terms=1024 and reader capture fits
    max_cells. For suffix windows one mark at time 12 explicitly witnesses
    logical compatibility, independently of the implementation's search order.
    High budget must distinguish model mass zero from the impossible triple
    N((0,6])=N((6,12])=N((0,12])=1, rather than treating either as shortage.
    """
    args = delta_args()
    args["law"]["channels"][0]["domain"]["end_ns"] = 12
    paths = [(5,), (11,), (5, 11)] if contradiction else [(9,), (1, 11)]
    args["law"]["rows"] = [{"marks": [{"channel": "arrivals", "time_ns": time, "count": 1}
        for time in path], "mass": [plain(F(1, len(paths))), plain(F(1, len(paths)))]} for path in paths]
    args["claims"] = [{"meaning": plain(c.COUNT_EXACTLY_ONE), "channel": "arrivals"}]
    rig = make_rig(derivation_args=args)
    rig.initial_evaluation()
    rig.start_measurement()
    windows = ([(0, 6), (2, 6), (4, 6), (6, 12), (8, 12), (10, 12), (0, 12)]
               if contradiction else [(start, 12) for start in range(0, 12, 2)])
    works = []
    needed = set()
    for index, (start, end) in enumerate(windows):
        interval = f.MeasurementInterval(clock=rig.clock.run, start_ns=start, end_ns=end,
                                         closure="(start,end]")
        rig.claim(1, slot=f"search-{index}", kind="count_exactly_one", meaning=c.COUNT_EXACTLY_ONE,
                  interval=interval, now=12)
        rig.drive(lambda: len(rig.requests("belief_update")) == index + 1)
        needed |= set(rig.requests("belief_update")[-1].value["desc"]["input_points"])
        if index == len(windows) - 1:
            def read_all_before_normal(work, ctx):
                for point in sorted(needed):
                    ctx.read(point)
                event, issued = rig.workers.normal(work, ctx)
                rig.workers.post(ctx, event, issued)
            rig.workers.overrides["belief_update"] = read_all_before_normal
        work = rig.run_stage("belief_update")
        works.append(work)
        normal = rig.workers.returns[work.request]
        matching = [path for path in paths if all(sum(a < t <= b for t in path) == 1
                                                for a, b in windows[:index + 1])]
        if index < len(windows) - 1:
            assert matching, "each proper prefix must retain positive model mass"
            expected = {"joint": [[1, 2], [1, 2]], "evidence_mass": plain(F(len(matching), len(paths)))}
            assert isinstance(normal, u.IssuedUpdate) and plain(normal.result) == expected
            rig.drive(lambda: len(rig.facts(c.BELIEF_ADOPTED)) == index + 1)
        else:
            assert not matching and isinstance(normal, u.Rejected)
    cuts = sorted({edge for window in windows for edge in window})
    # Every endpoint except 0, and every intervening open cell, is involved.
    cells = [(F(point), F(point)) for point in cuts if point != 0]
    cells += [(F(a), F(b)) for a, b in zip(cuts, cuts[1:])]
    assert len(cells) == 12
    upper = [min(1 for start, end in windows if start < (a + b) / 2 <= end) for a, b in cells]
    search_size = 1
    for limit in upper:
        search_size *= limit + 1
    assert search_size == 4096
    # 予算 C (紙 F-b Z34 (a)): 上限は実際の仕事 (logical_work/1 の出来事) で数える。low は「単独の観測がどれも収まる最小の
    # 論理の上限」を公開の入口で実測した値 (試験の閾値。仕事の数え方の主張ではない)。探索は 4096 の候補を各 12 座標で
    # 拡張するので、その上限を大きく超える
    singles, need = [], 0
    for work, (start, end) in zip(works, windows):
        evidence = rig.workers.update_evidence[work.request]
        alone = replace(work, desc=replace(work.desc, args=replace(work.desc.args, prior=None)))
        # 単独の観測どうしは仕事がほぼ同じ: 今の閾値で発行されれば探さない (二分探索の回数を減らす)
        if need == 0 or not isinstance(direct_update(rig, budget_request(rig, alone, logical(UPDATE_BUDGET, need)),
                                                     evidence, budget=logical(UPDATE_BUDGET, need)), u.IssuedUpdate):
            need = minimal_logical_limit(rig, alone, evidence, low=need)
        singles.append((work, start, end, evidence))
    low = logical(UPDATE_BUDGET, need)
    high = logical(UPDATE_BUDGET, 10**6)
    assert len(PublicReader(rig.ledger).entries()) < low.numerical.max_cells
    assert low.logical_limit < 12 * search_size < high.logical_limit
    # These real single observations have the same row/state arithmetic;
    # each one must finish with the smaller logical budget, not fail first.
    for work, start, end, evidence in singles:
        single_desc = replace(work.desc, args=replace(work.desc.args, prior=None, budget=low))
        single_q = save_request(rig, work, desc=single_desc)
        ret = direct_update(rig, single_q, evidence, budget=low)
        mass = F(sum(sum(start < time <= end for time in path) == 1 for path in paths), len(paths))
        assert mass > 0 and isinstance(ret, u.IssuedUpdate)
        assert plain(ret.result) == {"joint": [[1, 2], [1, 2]], "evidence_mass": plain(mass)}
    last = works[-1]
    observations = tuple(o for work in works for o in work.desc.args.observations)
    boundary = frozenset(p for work in works for p in work.desc.numerical_view.boundary)
    inputs = frozenset(p for work in works for p in work.desc.input_points)
    trigger = frozenset(t for work in works for t in work.desc.trigger)
    desc = replace(last.desc, trigger=trigger, input_points=inputs,
        numerical_view=fixed_view(rig, boundary),
        args=replace(last.desc.args, prior=None, observations=observations, budget=high))
    refs = {r for work in works for r in rig.read_stored(work.request)[2].body.inputs}
    parents = front(rig, set().union(*(set(rig.by_cid(c.WORK_REQUESTED, w.request).parents) for w in works)))
    q = save_request(rig, last, desc=desc, inputs=tuple(refs), parents=parents)
    evidence = rig.workers.update_evidence[last.request]
    normal = direct_update(rig, q, evidence, budget=high)
    expected_code = "measurement_conflict" if contradiction else "model_falsified"
    assert isinstance(normal, u.Rejected) and any(i.code == expected_code for i in normal.issues)
    small_desc = replace(desc, args=replace(desc.args, budget=low))
    small_q = save_request(rig, last, desc=small_desc, inputs=tuple(refs), parents=parents)
    ret = direct_update(rig, small_q, evidence, budget=low)
    assert_budget_shortage(ret, phase="computation")
    assert_no_adoption(rig, last.request)
    if contradiction:
        # 矛盾は全 4096 候補を各 12 座標で拡張し切って初めて言える = 拡張の出来事だけで 12 × 4096 を超える。探索を数えない
        # 誤実装なら、この上限で矛盾の判定まで届いてしまう
        bound = logical(UPDATE_BUDGET, 12 * search_size)
        bound_q = save_request(rig, last, desc=replace(desc, args=replace(desc.args, budget=bound)),
                               inputs=tuple(refs), parents=parents)
        assert_budget_shortage(direct_update(rig, bound_q, evidence, budget=bound), phase="computation")


@pytest.mark.parametrize("rebuild", (False, True), ids=("redelivery", "rebuild_same_binding"))
def test_delta_identity_is_original_claim_not_delivery_binding_or_previous_adoption(make_rig, rebuild):
    """Paper:3359,3472,2761-2767,3409. Bug: hash B/view/prior into O-03 and issue Q* again."""
    rig = make_rig()
    first_claim(rig)
    work, adopted = rig.adopt()
    assert_update(rig, work, adopted, FIRST)
    original_q = rig.requests("belief_update")[0]
    original_b = rig.one(c.SEGMENT_BINDING)
    raw_count = len(rig.facts(c.SEGMENT_REPORT))
    if rebuild:
        rig.host.post(received(b"a newer saved view, same original claim"))
        rig.drive(lambda: bool(rig.facts(c.RECEIVED)))
        rig.host.rebuild_window()
    rig.claim(1, slot="claim-1")
    rig.drive(lambda: len(rig.facts(c.SEGMENT_REPORT)) == raw_count + 1)
    rig.settle_steps()
    assert [q.cid for q in rig.requests("belief_update")] == [original_q.cid]
    assert [a.cid for a in rig.facts(c.BELIEF_ADOPTED)] == [adopted.cid]
    assert rig.by_cid(c.SEGMENT_BINDING, original_b.cid).value == original_b.value
    deliveries = [r for r in rig.facts(c.SEGMENT_REPORT) if r.value["item_slot"] == "claim-1"]
    assert len(deliveries) == 2 and deliveries[0].value == deliveries[1].value
    assert [b.cid for b in rig.facts(c.SEGMENT_BINDING)] == [original_b.cid]


def test_distinct_binding_remake_is_unreachable_from_this_public_contract():
    """Paper:3409 (B2); user's third-turn clarification of this public version.

    With original Claim, reading, route, evidence, Started and clock fixed,
    the logical key identifies the same B. Rebuild/redelivery rechecks it;
    no declared public operation produces a distinct legal B with that key.
    This guard is not_run, not a ContractGap or verified mutation kill.
    """
    pytest.skip("not_run: distinct B with all logical-key inputs fixed is unreachable in this public version")


@pytest.mark.parametrize("kind", ("no_arrival", "undeclared-kind"))
def test_undeclared_claim_kind_is_saved_without_becoming_no_arrival(make_rig, kind):
    """Paper:3301,2661-2666,2773,3472. Bug: map an unknown kind to no_arrival by default."""
    rig = make_rig()
    rig.initial_evaluation()
    rig.start_measurement()
    report = rig.claim(kind=kind)
    saved = [r for r in rig.facts(c.SEGMENT_REPORT) if r.value == wire(report)]
    assert len(saved) == 1 and saved[0].value["item"]["value"]["kind"] == kind
    if kind == "no_arrival":
        work, adopted = rig.adopt()
        assert_update(rig, work, adopted, FIRST)
    else:
        # δ may report the missing meaning before constructing Q*. If it does
        # construct Q*, U must explicitly reject it, rather than infer a kind.
        if rig.requests("belief_update"):
            work = rig.run_stage("belief_update")
            ret = rig.workers.returns[work.request]
            assert isinstance(ret, u.Rejected)
            assert any(i.code == "missing_contract" for i in ret.issues)
        else:
            assert any(p.kind == "missing_contract" for p in rig.host.window.status().pending)
        assert not rig.facts(c.BELIEF_ADOPTED) and not rig.facts(c.UPDATE_RESULT)


def test_unhandled_frame_is_retained_with_explicit_missing_meaning(make_rig):
    """Paper:3299-3301,3472,3474. Bug: throw away an unsupported branch or guess a claim projection."""
    rig = make_rig()
    rig.initial_evaluation()
    rig.start_measurement()
    rig.clock.set(2)
    posted = []
    def emit(work, ctx):
        base = segment_items()["frame"]
        item = replace(base, route_epoch="route-A", sample_seq=0,
            measurement_id=replace(base.measurement_id, route_epoch="route-A", sample_seq=0),
            measurement_interval=f.MeasurementInterval(clock=rig.clock.run,
                start_ns=0, end_ns=2, closure="(start,end]"),
            actual_time=f.ClockReading(run=rig.clock.run, time_ns=2))
        event = fb.SegmentReport(segment=work.request, item_slot="frame", item=item)
        posted.append(event)
        rig.workers.post(ctx, event)
    rig.command(emit)
    rig.drive(lambda: any(r.value == wire(posted[0]) for r in rig.facts(c.SEGMENT_REPORT)))
    rig.settle_steps()
    assert not rig.requests("belief_update")
    assert any(p.kind == "missing_contract" for p in rig.host.window.status().pending)
    assert not rig.facts(c.BELIEF_ADOPTED)
    # Nearest supported branch on the same live segment still has a working path.
    rig.claim(1)
    work, adopted = rig.adopt()
    assert_update(rig, work, adopted, FIRST)
    assert any(r.value == wire(posted[0]) for r in rig.facts(c.SEGMENT_REPORT))


def test_hung_update_does_not_stop_received_or_finite_segment_report_storage(make_rig):
    """Paper:3245-3246,3483,3485; Z33:3717.

    Bug: execute U under the window lock or dedicate all seats to updates.
    While the explicit worker gate is closed, Received and Claim2 must really
    be saved. After release, a computation exceeding the old three-second
    watchdog is allowed to finish; its fixed-image result must still be FIRST.
    The finite harness watchdog is not a latency requirement or a success.
    """
    rig = make_rig()
    first_claim(rig)
    gate = Event()
    rig.workers.gates["belief_update"] = gate
    q, callback = rig.callback("belief_update")
    thread = Thread(target=callback, daemon=True)
    rig.workers.threads.append(thread)
    thread.start()
    assert rig.workers.entered.setdefault("belief_update", Event()).wait(2)
    before = len(rig.facts(c.RECEIVED))
    rig.host.post(received(b"arrived while Wu is blocked", {"fixture": "stage3-reception"}))
    rig.claim(2)
    rig.drive(lambda: len(rig.facts(c.RECEIVED)) == before + 1)
    assert rig.facts(c.RECEIVED)[-1].value["data"] == list(b"arrived while Wu is blocked")
    assert any(r.value["item_slot"] == "claim-2" for r in rig.facts(c.SEGMENT_REPORT))
    assert not rig.facts(c.BELIEF_ADOPTED)
    assert q.cid not in rig.workers.returns
    first_x = closure(rig, q.value["desc"]["numerical_view"]["boundary"])
    later = [r.cid for r in rig.facts(c.SEGMENT_REPORT) if r.value["item_slot"] == "claim-2"]
    assert later and not (set(later) & first_x)
    assert thread.is_alive() and rig.thread.is_alive()
    gate.set()
    thread.join(OBSERVATION_TIMEOUT)
    assert not thread.is_alive()
    rig.drive(lambda: any(a.value["request"] == q.cid for a in rig.facts(c.BELIEF_ADOPTED)))
    assert result_for(rig, q.cid).value["result"] == FIRST


FAULT_TARGETS = (
    ("law", c.FINITE_JOINT_COUNT_LAW), ("reading", c.OBSERVATION_PLAN_2),
    ("monitor_span", c.MONITOR_SPAN), ("input_acquisition", ACQUIRED),
    ("Q", c.WORK_REQUESTED), ("R", c.UPDATE_RESULT),
    ("result_acquisition", ACQUIRED), ("A", c.BELIEF_ADOPTED),
)


@pytest.mark.parametrize("label,target", FAULT_TARGETS, ids=[row[0] for row in FAULT_TARGETS])
@pytest.mark.parametrize("side,rebuild", tuple(product(("before", "after"), (False, True))),
                         ids=("before", "before_rebuild", "after", "after_rebuild"))
def test_stage3_storage_retry_reuses_preparation_without_recompute_or_redraw(make_rig, label, target, side, rebuild):
    """Paper:3258,2062-2077,3491-3498. Bug: new r/salt/CID, rerun U, or consume another draw on retry."""
    rig = make_rig(continuation=True, cut=(target, side), rebuild=rebuild,
                   acquisition_phase="result" if label == "result_acquisition" else "input")
    first_claim(rig)
    w1, a1 = rig.adopt(1)
    assert_update(rig, w1, a1, FIRST)
    rig.run_stage("evaluation_prepare")
    rig.run_stage("selection_draw")
    rig.run_stage("evaluation")
    assert len(rig.ledger.hit) == 1 and rig.ledger.cut is None
    assert rig.rebuilt == rebuild
    _, actual_side, prepared = rig.ledger.hit[0]
    assert actual_side == side
    attempts = [p for p in rig.ledger.writes if p.cid == prepared.cid]
    assert attempts and all(p == prepared for p in attempts)
    assert len([p for p in rig.ledger.preparations if p.cid == prepared.cid]) == 1
    header, salt, record = rig.read_stored(prepared.cid)
    assert (header, salt, record) == (prepared.header, prepared.salt, prepared.record)
    assert len([cid for cid, _header in rig.entry_store.load() if cid == prepared.cid]) == 1
    assert rig.workers.update_calls == [(w1.request, UPDATE_BUDGET)]
    assert Counter(w.desc.work_id for w in rig.workers.entries).most_common(1)[0][1] == 1
    draws = [w for w in rig.workers.entries if w.desc.purpose == "selection_draw"]
    assert len(draws) == 2 and len({w.desc.work_id for w in draws}) == 2
    assert len(rig.facts(c.DRAW_REPORT)) == 2
    assert len(rig.facts(c.SELECTION)) == 2
    assert [r.value["result"] for r in rig.facts(c.UPDATE_RESULT)] == [FIRST]
    assert [a.value["result"] for a in rig.facts(c.BELIEF_ADOPTED)] == [result_for(rig, w1.request).cid]


def test_boundary_without_adoption_keeps_the_stage2_fa_prepare_compiler():
    """Paper:3246,3337,3500. Bug: always dispatch Ep through the new F-b compiler."""
    rig = Stage2Rig()
    try:
        rig.through("evaluation")
        rig.drive(lambda: bool(rig.facts(c.SELECTION)))
        assert not rig.facts(c.BELIEF_ADOPTED)
        eq = rig.one(c.EVALUATION_REQUESTED)
        assert eq.value["desc"]["args"]["compiler"] == plain(fc.PREPARE_FACTS)
        prepared = rig.workers.issued["evaluation_prepare"]
        assert json.loads(prepared.canonical_bytes)["compiler"] == plain(fc.PREPARE_FACTS)
        assert prepared.value.world_manifest.compiler == fc.PREPARE_FACTS
        evaluated = rig.workers.issued["evaluation"]
        assert isinstance(evaluated.value, f.Selected)
        with localcontext() as context:
            context.prec = 60
            assert_quantity(evaluated.value.evaluation.information[1].additional, Decimal(2).ln())
            assert_quantity(evaluated.value.evaluation.q_star[1], Decimal(2) / 3)
        assert rig.one(c.SELECTION).value["evaluated"] == rig.one(c.EVALUATED).cid
    finally:
        rig.close()


def deliver_first_claim_again(rig, *, conflict, accept_only=False):
    """The original measurement mouth, same (segment, item_slot), same window."""
    report = fb.SegmentReport(segment=rig.one(c.SEGMENT_REQUESTED).cid, item_slot="claim-1",
        item=f.CoverageClaim(route_epoch="route-A",
            interval=f.MeasurementInterval(clock=rig.clock.run, start_ns=0, end_ns=2,
                                           closure="(start,end]"),
            kind="count_exactly_one" if conflict else "no_arrival",
            contract=c.COUNT_EXACTLY_ONE if conflict else c.NO_ARRIVAL, evidence=()))
    def post(_work, ctx):
        if accept_only:
            accept_posted(rig, report, lambda: rig.workers.post(ctx, report))
        else:
            rig.workers.post(ctx, report)
    rig.command(post)
    return report


@pytest.mark.parametrize("conflict", (False, True), ids=("same_finish", "incompatible_finish"))
def test_late_wu_terminal_clash_blocks_uncreated_acquisition_and_adoption(make_rig, conflict):
    """Paper:2853-2865,3082-3092,3520 (R01-R2, all Wu terminal deliveries).

    Bug: inspect only the first terminal, or skip the use guard after a save
    retry. Genuine issued is accepted and R* is committed with confirmation
    held; neither G nor A* exists. The still-running same entered Wu mouth
    posts its second finish, which is accepted before R* confirmation resumes.
    A same-content finish with the same genuine issue is the legal control.
    Z33:3717 does not bound computation latency: the harness waits for the
    actual result/second Post, not a three-second assumption. Ignoring the
    second terminal still fails the no-G/no-A assertions after confirmation.
    """
    rig = make_rig()
    first_claim(rig)
    rig.ledger.hold_result_confirmation = True
    again, posted, release = Event(), Event(), Event()
    rig.workers.gates["cleanup-late-terminal"] = release
    rig.workers.gates["cleanup-second-terminal"] = again
    replies = []
    def worker(work, ctx):
        issue = rig.workers.compute(work, ctx)
        assert isinstance(issue, u.IssuedUpdate) and plain(issue.result) == FIRST
        first = rig.workers.finished(work, fb.WorkOutputs(outputs=u.update_response(issue)))
        late = (replace(first, outcome=fb.WorkFailure(failure=fb.FailureInfo(
            failure_kind="test-late-failure", content={"reason": "incompatible terminal"},
            readings=(), basis=()))) if conflict else first)
        replies.extend((first, late))
        rig.workers.post(ctx, first, issue)
        assert again.wait(OBSERVATION_TIMEOUT)
        rig.workers.post(ctx, late, None if conflict else issue)
        posted.set()
        assert release.wait(OBSERVATION_TIMEOUT)
    rig.workers.overrides["belief_update"] = worker
    q, callback = rig.callback("belief_update")
    thread = Thread(target=callback, daemon=True)
    rig.workers.threads.append(thread)
    thread.start()
    rig.drive(lambda: bool(rig.facts(c.UPDATE_RESULT)))
    result = rig.one(c.UPDATE_RESULT)
    assert result.value["request"] == q.cid and result.value["result"] == FIRST
    assert rig.ledger.uncertain_result is not None
    assert not rig.facts(c.BELIEF_ADOPTED)
    assert not any(result.cid in g.value["contents"] for g in rig.facts(ACQUIRED))
    assert not any(p.record.body.contract == ACQUIRED
                   and result.cid in p.record.body.content.as_json()["contents"]
                   for p in rig.ledger.preparations)
    def second_post():
        again.set()
        assert posted.wait(OBSERVATION_TIMEOUT), "incomplete observation: second Wu finish not posted"
    accept_posted(rig, replies[1], second_post)
    rig.contents.blocked.clear()
    release.set()
    thread.join(OBSERVATION_TIMEOUT)
    assert not thread.is_alive() and not rig.workers.errors
    rig.drive(lambda: len([r for r in rig.facts(c.WORK_REPORT)
                           if r.value["work"] == q.value["desc"]["work_id"]]) == 2)
    rig.settle_steps(12)
    assert len(rig.facts(c.UPDATE_RESULT)) == 1  # already saved R* is retained
    if conflict:
        assert not rig.facts(c.BELIEF_ADOPTED)
        assert not any(result.cid in g.value["contents"] for g in rig.facts(ACQUIRED))
        assert not any(p.record.body.contract == ACQUIRED
                       and result.cid in p.record.body.content.as_json()["contents"]
                       for p in rig.ledger.preparations)
    else:
        rig.drive(lambda: bool(rig.facts(c.BELIEF_ADOPTED)))
        work = next(w for w in rig.workers.entries if w.request == q.cid)
        assert_update(rig, work, rig.one(c.BELIEF_ADOPTED), FIRST)


@pytest.mark.parametrize("conflict", (False, True), ids=("same_previous_claim", "clashing_previous_claim"))
def test_second_update_depends_on_all_previous_claim_deliveries(make_rig, conflict):
    """Paper:2853-2865,3082-3092,3520 (R01-R2, transitive UseDeps).

    Bug: check Claim2 only and miss a later clash with Claim1 after Q2 fixed.
    Claim2 is untouched and Q2 has the valid adopted prior. Redelivery uses
    Claim1's original measurement mouth/key; the equal control adopts SECOND.
    """
    rig = make_rig()
    first, a1, _ = direct_first(rig)
    rig.claim(2)
    q, callback = rig.callback("belief_update")
    assert q.value["desc"]["args"]["prior"] == a1.cid
    original = next(
        b.value["report"] for b in rig.facts(c.SEGMENT_BINDING)
        if rig.read_stored(b.value["report"])[2].body.content.as_json()["item_slot"] == "claim-1")
    old_bytes = rig.read_stored(original)
    report = deliver_first_claim_again(rig, conflict=conflict, accept_only=True)
    callback()
    rig.drive(lambda: len([r for r in rig.facts(c.SEGMENT_REPORT) if r.value == wire(report)])
              == (1 if conflict else 2))
    rig.settle_steps(12)
    assert rig.read_stored(original) == old_bytes
    assert len(rig.requests("belief_update")) == 2
    if conflict:
        assert (q.value["desc"]["work_id"], False) in rig.workers.entry_attempts
        assert not any(w.request == q.cid for w in rig.workers.entries)
        assert_no_adoption(rig, q.cid)
        assert [a.cid for a in rig.facts(c.BELIEF_ADOPTED)] == [a1.cid]
    else:
        rig.drive(lambda: len(rig.facts(c.BELIEF_ADOPTED)) == 2)
        second = next(w for w in rig.workers.entries if w.request == q.cid)
        assert_update(rig, second, rig.facts(c.BELIEF_ADOPTED)[1], SECOND, a1.cid)


@pytest.mark.parametrize("conflict", (False, True), ids=("same_claim_after_T_fault", "clash_after_T_fault"))
def test_terminal_save_retry_rechecks_claim_before_creating_result(make_rig, conflict):
    """Paper:2853-2865,3082-3092,3520 (R01-R2, uncreated successors on resume).

    Bug: a cached successor action after T's save failure bypasses the new
    Claim conflict. Stop the public host pump at the one-shot pre-write T
    error, accept the next delivery before any settle/retry, then resume.
    Prepared T may finish saving; an as-yet unprepared R* may not be created.
    Equal redelivery traverses the same save fault and must reach adoption.
    """
    rig = make_rig()
    first_claim(rig)
    q, callback = rig.callback("belief_update")
    rig.ledger.cut = (c.WORK_TERMINAL, "before")
    callback()
    with pytest.raises(OSError, match="stage2 before write"):
        rig.host.run_until(lambda _status: False, timeout=.5)
    assert len(rig.ledger.hit) == 1 and rig.ledger.hit[0][0] == c.WORK_TERMINAL
    terminal = rig.ledger.hit[0][2]
    assert terminal.record.body.content.as_json()["request"] == q.cid
    assert terminal.cid not in {e.cid for e in PublicReader(rig.ledger).entries()}
    assert not rig.facts(c.UPDATE_RESULT) and not rig.facts(c.BELIEF_ADOPTED)
    assert not any(p.record.body.contract == c.UPDATE_RESULT for p in rig.ledger.preparations)
    report = deliver_first_claim_again(rig, conflict=conflict, accept_only=True)
    rig.drive(lambda: terminal.cid in {e.cid for e in PublicReader(rig.ledger).entries()}
              and any(r.value == wire(report) for r in rig.facts(c.SEGMENT_REPORT)))
    rig.settle_steps(12)
    assert rig.read_stored(terminal.cid)[2] == terminal.record
    if conflict:
        assert_no_adoption(rig, q.cid)
        assert not any(p.record.body.contract == c.UPDATE_RESULT for p in rig.ledger.preparations)
    else:
        rig.drive(lambda: bool(rig.facts(c.BELIEF_ADOPTED)))
        work = next(w for w in rig.workers.entries if w.request == q.cid)
        assert_update(rig, work, rig.one(c.BELIEF_ADOPTED), FIRST)


def replace_evidence_points(evidence, mapping):
    """Keep every witness, origin and M value; rebind only copied record identities."""
    return replace(evidence,
        uses=tuple(replace(x, point=mapping.get(x.point, x.point)) for x in evidence.uses),
        acquisitions=tuple(replace(x, contents=frozenset(mapping.get(p, p) for p in x.contents))
                           for x in evidence.acquisitions),
        executions=tuple(replace(x, reports=tuple(
            replace(r, point=mapping.get(r.point, r.point)) for r in x.reports))
            for x in evidence.executions))


def rebind_request_inputs(rig, work, mapping, *, prior=None, extra=()):
    """A fresh, independently keyed Q*, with all typed references rebound alike."""
    desc = work.desc
    references = {rig.read_stored(a)[2].id: rig.read_stored(b)[2].id for a, b in mapping.items()}
    body = rig.read_stored(work.request)[2].body
    inputs = {references.get(r, r) for r in body.inputs} | {rig.read_stored(p)[2].id for p in extra}
    boundary = {mapping.get(p, p) for p in desc.numerical_view.boundary} | set(extra)
    observations = tuple(replace(o, binding=mapping.get(o.binding, o.binding),
                                 reading=mapping.get(o.reading, o.reading)) for o in desc.args.observations)
    changed = replace(desc, args=replace(desc.args, observations=observations,
        prior=desc.args.prior if prior is None else prior),
        input_points=frozenset(mapping.get(p, p) for p in desc.input_points) | frozenset(extra),
        numerical_view=fixed_view(rig, boundary))
    old_q = rig.by_cid(c.WORK_REQUESTED, work.request)
    return save_request(rig, work, desc=changed, inputs=tuple(inputs),
        parents=front(rig, {mapping.get(p, p) for p in old_q.parents} | events_for(rig, extra)))


def copied_chain_with_previous_request(rig, first, adoption, second, change,
        *, first_extra_view=(), first_extra_inputs=(), second_extra=(), first_budget=None):
    """Rebind Q1/R1/G1/A1, so bad Q1 authentication is the only bad fact."""
    view = first.desc.numerical_view
    if first_extra_view:
        view = fixed_view(rig, set(view.boundary) | set(first_extra_view))
    if change in ("reader_view_key", "registry_key"):
        view = replace(view, **{change: "sha256:" + "0" * 64})
    qbody = rig.read_stored(first.request)[2].body
    inputs = tuple(qbody.inputs) + tuple(rig.read_stored(p)[2].id for p in first_extra_inputs)
    if change == "boot_input":
        boot_ref = rig.read_stored(first.desc.process.declaration)[2].id
        assert boot_ref in inputs
        inputs = tuple(r for r in inputs if r != boot_ref)
        assert len(inputs) == len(qbody.inputs) - 1
    desc = replace(first.desc, numerical_view=view)
    if change == "method":
        desc = replace(desc, method=replace(desc.method, version="999"))
    elif change == "purpose":
        desc = replace(desc, purpose="candidate_generation")
    elif change == "output_contract":
        desc = replace(desc, output_contract=contract("test.fb3.wrong_update_response"))
    elif change == "saved_budget":
        desc = replace(desc, args=replace(desc.args, budget=cells(desc.args.budget, 1)))
    if first_budget is not None:
        desc = replace(desc, args=replace(desc.args, budget=first_budget))
    q1 = save_request(rig, first, desc=desc, inputs=inputs)
    old_r = result_for(rig, first.request)
    terminal = next(t for t in rig.facts(c.WORK_TERMINAL) if t.value["request"] == first.request)
    old_raw = rig.by_cid(c.WORK_REPORT, terminal.value["first_receipt"])
    raw = save_copy(rig, old_raw.cid,
        parents=front(rig, {q1 if p == first.request else p for p in old_raw.parents}))
    rvalue = dict(old_r.value, request=q1, numerical_view=wire(view))
    # Every numerical value and semantic digest stays exactly the original.
    assert rvalue["result"] == FIRST and rvalue["application_digest"] == old_r.value["application_digest"]
    r1 = save_copy(rig, old_r.cid, value=rvalue,
        about=(rig.read_stored(q1)[2].id,), basis=(rig.read_stored(q1)[2].id, rig.read_stored(raw)[2].id),
        parents=front(rig, {q1, raw}))
    old_g = rig.by_cid(ACQUIRED, adoption.value["acquisition"])
    now = rig.clock.mono_ns()
    clock_value = rig.read_stored(old_g.value["clock"])[2].body.content.as_json()
    clock_value["reading"]["time_ns"] = now
    clock = save_copy(rig, old_g.value["clock"], value=clock_value, received_ns=now,
        parents=front(rig, events_for(rig, {r1, clock_value["source"]})))
    g1 = save_copy(rig, old_g.cid, value=dict(old_g.value, contents=[r1], clock=clock),
                   received_ns=now, parents=(clock,))
    avalue = dict(adoption.value, request=q1, result=r1, acquisition=g1)
    ainputs = tuple(rig.read_stored(p)[2].id for p in {first.desc.reader, first.desc.args.model, q1, r1, g1})
    a1 = save_copy(rig, adoption.cid, value=avalue, inputs=ainputs,
                   parents=front(rig, events_for(rig, {r1, g1})))
    mapping = {first.request: q1, old_raw.cid: raw, old_r.cid: r1, old_g.cid: g1,
               old_g.value["clock"]: clock, adoption.cid: a1}
    q2 = rebind_request_inputs(rig, second, mapping, prior=a1, extra=second_extra)
    assert a1 in closure(rig, rig.read_stored(q2)[2].body.content.as_json()["desc"]["numerical_view"]["boundary"])
    return q2, a1, r1, mapping


@pytest.mark.parametrize("change", (None, "reader_view_key", "registry_key", "boot_input"))
def test_each_previous_request_is_authenticated_by_u_and_prepare(make_rig, change):
    """Paper:2781-2809,3082-3092,3521,3651 (R04-R2 / R02-R2).

    Bug: authenticate only the current Q*, then trust the previous Q* during
    replay. R1's request/view agree with copied Q1, and all numeric metadata,
    acquisition, A1 and Q2 references are valid. The identical correct-key
    rebinding must succeed in both U and the ordinary F-a preparation.
    """
    rig = make_rig()
    first, a1, _ = direct_first(rig)
    rig.claim(2)
    second, a2 = rig.adopt(2)
    assert_update(rig, second, a2, SECOND, a1.cid)
    q, head, result, mapping = copied_chain_with_previous_request(rig, first, a1, second, change)
    evidence = replace_evidence_points(rig.workers.update_evidence[second.request], mapping)
    ret = direct_update(rig, q, evidence)
    if change == "registry_key":
        prepared = prepare_adoption(rig, head, result,
            evidence=replace_evidence_points(current_evidence(rig), mapping))
        assert_incomplete_preparation(prepared, "algorithm_unavailable")
    else:
        try:
            prepared = prepare_adoption(rig, head, result,
                evidence=replace_evidence_points(current_evidence(rig), mapping))
        except (f.FInputError, f.FReplayMismatch, f.FReplayUnavailable, f.FIncomplete, f.FSpecificationMissing):
            if change is None:
                raise
            prepared = None
    if change is None:
        assert isinstance(ret, u.IssuedUpdate) and plain(ret.result) == SECOND
        assert prepared is not None and isinstance(prepared.value, f.FProblem)
        assert prepared.value.K.belief == rig.read_stored(result)[2].id
    else:
        assert isinstance(ret, (u.Rejected, u.Insufficient)) and ret.issues
        assert prepared is None or isinstance(prepared.value, f.NoDecision)


@pytest.mark.parametrize("change", (None, "missing_boot", "unsaved_input"))
def test_declared_inputs_include_boot_and_resolve_every_extra_ref(make_rig, change):
    """Paper:2781-2793,3521 (R02-R2a). Bug: omit Boot from C or ignore excess I.

    A real, unused prediction is in the fixed image in every case. The legal
    extra Ref issues identical numbers. Only the Boot Ref is removed, or the
    extra Ref is replaced by a valid-shaped but absent Ref; no root is lost.
    """
    rig = make_rig()
    work, _a, evidence = direct_first(rig)
    extra = save_copy(rig, rig.model_point)
    desc = replace(work.desc, numerical_view=fixed_view(rig, set(work.desc.numerical_view.boundary) | {extra}))
    old = rig.read_stored(work.request)[2].body
    extra_ref = rig.read_stored(extra)[2].id
    inputs = tuple(old.inputs) + (extra_ref,)
    if change == "missing_boot":
        boot_ref = rig.read_stored(desc.process.declaration)[2].id
        assert boot_ref in inputs
        inputs = tuple(r for r in inputs if r != boot_ref)
    elif change == "unsaved_input":
        absent = replace(extra_ref, value="fb3-valid-but-never-saved")
        assert all(rig.read_stored(e.cid)[2].id != absent for e in PublicReader(rig.ledger).entries())
        inputs = tuple(r if r != extra_ref else absent for r in inputs)
    q = save_request(rig, work, desc=desc, inputs=inputs)
    ret = direct_update(rig, q, evidence)
    if change is None:
        assert isinstance(ret, u.IssuedUpdate) and plain(ret.result) == FIRST
    else:
        assert isinstance(ret, (u.Rejected, u.Insufficient)) and ret.issues


@pytest.mark.parametrize("kind,meaning", (("no_arrival", c.NO_ARRIVAL),
                                         ("count_exactly_one", c.COUNT_EXACTLY_ONE)))
@pytest.mark.parametrize("omit", (None, "declaration", "implementation"))
def test_claim_projection_needs_its_own_declared_and_implemented_meaning(make_rig, kind, meaning, omit):
    """Paper:2660-2664,3333,3521 (R02-R2b). Bug: hard-code the Claim's meaning.

    Remove only its projection capability and rekey Q* to that registry.
    Otherwise a registry-key mismatch could mask the absent declaration or
    algorithm. The full registry must issue the independent CE1 count sum.
    """
    args = delta_args()
    args["claims"] = [{"meaning": plain(meaning), "channel": "arrivals"}]
    rig = make_rig(derivation_args=args)
    rig.initial_evaluation()
    rig.start_measurement()
    rig.claim(kind=kind, meaning=meaning)
    work, _ = rig.adopt()
    evidence = rig.workers.update_evidence[work.request]
    expected_count = 0 if kind == "no_arrival" else 1
    weights = [sum(row[s + 1] for row in CE1_ROWS if sum(row[0][:2]) == expected_count) / 2
               for s in range(2)]
    mass = sum(weights)
    expected = {"joint": [plain(w / mass) for w in weights], "evidence_mass": plain(mass)}
    selected = [d for d in rig.registry.declarations if d.ref == meaning and d.kind == "projection"]
    assert len(selected) == 1
    key = (selected[0].kind, selected[0].ref)
    reduced = f.make_f_registry(
        declarations=tuple(d for d in rig.registry.declarations
                           if omit != "declaration" or (d.kind, d.ref) != key),
        implementations=tuple(i for i in rig.registry.implementations
                              if omit is None or (i.kind, i.ref) != key))
    desc = replace(work.desc, numerical_view=fixed_view(rig, work.desc.numerical_view.boundary, registry=reduced))
    q = save_request(rig, work, desc=desc)
    ret = direct_update(rig, q, evidence, registry=reduced)
    if omit is None:
        assert isinstance(ret, u.IssuedUpdate) and plain(ret.result) == expected
    else:
        assert isinstance(ret, u.Rejected if omit == "declaration" else u.Insufficient)
        assert any(i.code == ("missing_contract" if omit == "declaration" else "algorithm_unavailable")
                   for i in ret.issues)


@pytest.mark.parametrize("mismatch", (False, True), ids=("same_model", "other_real_model"))
def test_head_adoptions_model_must_match_its_requests_model(make_rig, mismatch):
    """Paper:2799-2809,3082-3092,3500,3521 (R04-R3 / K12).

    Bug: select an A* by origin and forget model correspondence. Only model
    and its typed Ref change; Q1/R1/G/origin/previous are preserved. The other
    model is a real, sealed model source in the image, not an unavailable CID.
    Preparation uses a separate first-adoption rig: A2 does not exist, and
    neither the fixed-root closure nor any FReader entry contains original A1.
    Both model variants must present exactly the copied head. A competing-head
    failure therefore cannot mask the model comparison (review 2026-10-21).
    The other model is an explicit fixed root in both variants, so its body
    and typed Ref are available even when it is the mismatching head's model.
    """
    rig = make_rig()
    first, a1, _ = direct_first(rig)
    rig.claim(2)
    second, _ = rig.adopt(2)
    other = save_copy(rig, rig.model_point)
    value = dict(a1.value, model=other if mismatch else rig.model_point)
    inputs = rig.read_stored(a1.cid)[2].body.inputs
    if mismatch:
        old_ref, new_ref = rig.read_stored(rig.model_point)[2].id, rig.read_stored(other)[2].id
        assert old_ref in inputs
        inputs = tuple(new_ref if r == old_ref else r for r in inputs)
    head = save_copy(rig, a1.cid, value=value, inputs=inputs,
                     parents=front(rig, set(a1.parents) | events_for(rig, {other})))
    q = rebind_request_inputs(rig, second, {a1.cid: head}, prior=head, extra=(other,))
    ret = direct_update(rig, q, rig.workers.update_evidence[second.request])
    if mismatch:
        assert isinstance(ret, (u.Rejected, u.Insufficient)) and ret.issues
    else:
        assert isinstance(ret, u.IssuedUpdate) and plain(ret.result) == SECOND

    prepare_rig = make_rig()
    prepare_work, original_a, _ = direct_first(prepare_rig)
    assert len(prepare_rig.requests("belief_update")) == 1
    assert [a.cid for a in prepare_rig.facts(c.BELIEF_ADOPTED)] == [original_a.cid]
    other_model = save_copy(prepare_rig, prepare_rig.model_point)
    head_value = dict(original_a.value,
                      model=other_model if mismatch else prepare_rig.model_point)
    assert {key for key in head_value if head_value[key] != original_a.value[key]} == (
        {"model"} if mismatch else set())
    original_inputs = prepare_rig.read_stored(original_a.cid)[2].body.inputs
    old_ref = prepare_rig.read_stored(prepare_rig.model_point)[2].id
    new_ref = prepare_rig.read_stored(head_value["model"])[2].id
    assert old_ref in original_inputs
    head_inputs = tuple(new_ref if r == old_ref else r for r in original_inputs)
    copied_head = save_copy(prepare_rig, original_a.cid, value=head_value, inputs=head_inputs,
        parents=front(prepare_rig, set(original_a.parents) | events_for(prepare_rig, {other_model})))
    result = result_for(prepare_rig, prepare_work.request)
    assert head_value["result"] == result.cid and result.value["result"] == FIRST
    assert original_a.cid not in closure(prepare_rig, {copied_head})
    try:
        prepared = prepare_adoption(prepare_rig, copied_head, result.cid,
                                    sole_adoption=True, additional_roots=(other_model,))
    except (f.FInputError, f.FReplayMismatch, f.FReplayUnavailable, f.FIncomplete,
            f.FSpecificationMissing) as error:
        if not mismatch:
            raise
        assert "competing" not in str(error).lower(), "a different head must not reject this input first"
        prepared = None
    if mismatch:
        assert prepared is None or isinstance(prepared.value, f.NoDecision)
        if prepared is not None:
            assert "competing" not in prepared.canonical_bytes.decode("utf-8").lower()
    else:
        assert prepared is not None and isinstance(prepared.value, f.FProblem)
        assert prepared.value.K.belief == result.record_id


def test_callers_larger_budget_cannot_override_the_requests_saved_budget(make_rig):
    """Paper:3475,3482,3521 (R07-R2). Bug: use the caller's budget instead of Q*.

    Establish Insufficient(reader budget) with the exact stored budget first.
    An unchanged Q* and a larger call argument must not turn into an issue;
    the ordinary Q* with that larger stored budget is the successful control.
    """
    rig = make_rig()
    work, _a, evidence = direct_first(rig)
    small = cells(UPDATE_BUDGET, 1)
    q = budget_request(rig, work, small)
    assert_budget_shortage(direct_update(rig, q, evidence, budget=small), phase="reader")
    ret = direct_update(rig, q, evidence, budget=UPDATE_BUDGET)
    assert isinstance(ret, (u.Rejected, u.Insufficient)) and ret.issues
    legal = direct_update(rig, work.request, evidence, budget=UPDATE_BUDGET)
    assert isinstance(legal, u.IssuedUpdate) and plain(legal.result) == FIRST


@pytest.mark.parametrize("partial", (False, True), ids=("whole_support", "late_monitor_entry"))
def test_direct_u_requires_whole_window_support_without_clipping_claim(make_rig, partial):
    """Paper:2830-2840, Z33:3717; fb_rules.md:17123,40758-40810.

    Bug: ignore or clip partial Support. Start the real measuring execution
    at M=0/1, keeping its factory monitor publication, handle and EW intact.
    A seed Claim (1,2] supplies a legal B; the same mouth then really reports
    the target Claim (0,2]. Rebind B/Q and ordinary EA/uses to that report,
    without inventing a host monitor or copying its publication. Stage 1
    correctly cannot bind the partial target, so this is a direct-U fixture.
    The complete witness issues FIRST; late entry is Insufficient(support).
    """
    rig = make_rig(partial=partial)
    rig.initial_evaluation()
    rig.start_measurement()
    rig.claim(1, slot="support-seed", interval=f.MeasurementInterval(
        clock=rig.clock.run, start_ns=1, end_ns=2, closure="(start,end]"))
    work, _a = rig.adopt()
    binding = rig.by_cid(c.SEGMENT_BINDING, work.desc.args.observations[0].binding)
    seed = binding.value["report"]
    original_view = closure(rig, work.desc.numerical_view.boundary)
    spans = [s for s in rig.facts(c.MONITOR_SPAN) if s.cid in original_view
             and s.value["segment"] == binding.value["segment"]]
    assert len(spans) == 1
    span = spans[0]
    saved_span = rig.read_stored(span.cid)
    target = rig.claim(1, slot="support-target")
    raw = next(r.cid for r in rig.facts(c.SEGMENT_REPORT) if r.value == wire(target))
    before = rig.read_stored(raw)
    bvalue = dict(binding.value, report=raw, view=wire(fixed_view(rig,
        {raw if p == seed else p for p in binding.value["view"]["boundary"]})))
    copied_b = save_copy(rig, binding.cid, value=bvalue, parents=front(rig,
        {raw if p == seed else p for p in binding.parents}))
    mapping = {seed: raw, binding.cid: copied_b}
    rebound_work = replace(work, desc=replace(work.desc, trigger=tuple(
        replace(t, point=mapping.get(t.point, t.point)) for t in work.desc.trigger)))
    q = rebind_request_inputs(rig, rebound_work, mapping)
    actual = current_evidence(rig)
    evidence = replace(replace_evidence_points(actual, mapping), executions=actual.executions)
    monitors = [m for m in evidence.host_monitors if m.publication == span.cid]
    assert len(monitors) == 1 and evidence.host_monitors == actual.host_monitors
    ew = next(x for x in evidence.executions
              if x.execution_occurrence == monitors[0].execution_occurrence)
    assert ew.entered_ns[monitors[0].entry_index] == span.value["entered_ns"] == int(partial)
    assert any(r.point == raw for r in ew.reports), "target must actually come from this mouth"
    ret = direct_update(rig, q, evidence)
    assert rig.read_stored(span.cid) == saved_span
    assert rig.read_stored(raw) == before
    assert before[2].body.content.as_json()["item"]["value"]["interval"]["start_ns"] == 0
    if partial:
        assert isinstance(ret, u.Insufficient)
        # Whole-window generation also consumes SUPPORT_CHECKS. Its typed
        # shortage may name authentication rather than the old need-purpose
        # string "support"; require the actual Support rule, not any shortage.
        assert ret.issues and all(i.code == "prerequisite_unavailable"
            and any(rule in i.message for rule in ("SUPPORT-COVERED", "SUPPORT-START", "A1-SUPPORT"))
            and i.missing for i in ret.issues), [(i.code, i.message) for i in ret.issues]
    else:
        assert isinstance(ret, u.IssuedUpdate) and plain(ret.result) == FIRST


def test_context_read_crossing_worker_return_cannot_add_use_after_observed_stop(make_rig):
    """Paper:3479,3499,3514,3522 (J8/K11/R10-R2).

    Bug: check the ticket, release ownership, then add a use after stop. Gate
    only the reader thread's public content-store get; the entered worker's
    body really returns while that read is in flight. If the launch callback
    completes first, snapshot the confirmed stop before releasing the read:
    no later use may appear. If the atomic read delays stop, release the read
    and verify its one use precedes the stopped snapshot. The bounded join
    selects an observed schedule, never treats a timeout as stop evidence.
    The active read and the same read after confirmed stop are the controls.
    """
    rig = make_rig()
    returned, reached, release_read = Event(), Event(), Event()
    rig.workers.gates["cleanup-inflight-read"] = release_read
    def measurement(work, ctx):
        rig.workers.normal(work, ctx)
        returned.set()
    rig.workers.overrides["measure_segment"] = measurement
    rig.initial_evaluation()
    rig.start_measurement()
    ctx = rig.workers.contexts["measure_segment"]
    work = next(w for w in rig.workers.entries if w.desc.purpose == "measure_segment")
    point = rig.model_point
    # read returns the sealed record's bytes, not the model payload.
    active_bytes = ctx.read(point)
    assert isinstance(active_bytes, bytes) and active_bytes
    before = ctx.evidence()
    seal_value = entry_from_header(point, rig.read_stored(point)[0]).seal
    original_get = rig.contents.get
    identities, outcomes = [], []
    def gated_get(value_seal):
        if identities and get_ident() == identities[0] and value_seal == seal_value:
            reached.set()
            assert release_read.wait(10), "incomplete observation: read gate not released"
        return original_get(value_seal)
    rig.contents.get = gated_get
    def read():
        identities.append(get_ident())
        try:
            outcomes.append(ctx.read(point))
        except BaseException as error:
            outcomes.append(error)
    reader_thread = Thread(target=read, daemon=True)
    rig.workers.threads.append(reader_thread)
    reader_thread.start()
    assert reached.wait(3), "incomplete observation: public body read was not reached"
    rig.workers.release.set()
    assert returned.wait(3), "incomplete observation: worker body has not returned"
    rig.thread.join(.2)
    stop_first = not rig.thread.is_alive()
    stopped_before_read = ctx.evidence() if stop_first else None
    if stop_first:
        assert any(x.work_id == work.desc.work_id and x.stopped for x in stopped_before_read.executions)
    release_read.set()
    reader_thread.join(3)
    rig.thread.join(3)
    rig.contents.get = original_get
    assert not reader_thread.is_alive() and not rig.thread.is_alive()
    assert not rig.workers.errors and len(outcomes) == 1
    after = ctx.evidence()
    assert any(x.work_id == work.desc.work_id and x.stopped for x in after.executions)
    if stop_first:
        assert after.uses == stopped_before_read.uses
    else:
        assert outcomes == [active_bytes]
        assert len(after.uses) == len(before.uses) + 1
        assert after.uses[-1].work_id == work.desc.work_id and after.uses[-1].point == point
    with pytest.raises(RuntimeError):
        ctx.read(point)
    assert ctx.evidence() == after


def assert_incomplete_preparation(artifact, reason):
    """A4/Z8: assert the public mathematical diagnostic, not a caught exception."""
    assert isinstance(artifact.value, f.NoDecision), type(artifact.value).__name__
    assert artifact.value.reason == reason
    assert plain(artifact.value)["outcome"] == "incomplete"


def copy_adoption_for_request(rig, work, adoption, q, *, previous=None, result_value=None):
    """A coherent R/G/A around a copied Q; all clocks and basis are real records."""
    old_r = result_for(rig, work.request)
    terminal = next(t for t in rig.facts(c.WORK_TERMINAL) if t.value["request"] == work.request)
    old_raw = rig.by_cid(c.WORK_REPORT, terminal.value["first_receipt"])
    report_value = json.loads(json.dumps(old_raw.value))
    result_value = old_r.value["result"] if result_value is None else result_value
    response = report_value["outcome"]["value"]
    assert report_value["outcome"]["kind"] == "outputs" and response["contract"] == plain(c.UPDATE_RESPONSE)
    assert response["value"]["kind"] == "issued" and response["value"]["value"] == old_r.value["result"]
    response["value"]["value"] = json.loads(json.dumps(result_value))
    raw = save_copy(rig, old_raw.cid, value=report_value, parents=())
    desc = rig.read_stored(q)[2].body.content.as_json()["desc"]
    rvalue = dict(old_r.value, request=q, numerical_view=desc["numerical_view"], result=result_value)
    r = save_copy(rig, old_r.cid, value=rvalue, about=(rig.read_stored(q)[2].id,),
        basis=(rig.read_stored(q)[2].id, rig.read_stored(raw)[2].id), parents=front(rig, {q, raw}))
    old_g = rig.by_cid(ACQUIRED, adoption.value["acquisition"])
    now = rig.clock.mono_ns()
    clock_value = rig.read_stored(old_g.value["clock"])[2].body.content.as_json()
    clock_value["reading"]["time_ns"] = now
    clock = save_copy(rig, old_g.value["clock"], value=clock_value, received_ns=now,
        parents=front(rig, events_for(rig, {r, clock_value["source"]})))
    g = save_copy(rig, old_g.cid, value=dict(old_g.value, contents=[r], clock=clock),
                  received_ns=now, parents=(clock,))
    points = {work.desc.reader, work.desc.args.model, q, r, g}
    if previous is not None:
        points.add(previous)
    a = save_copy(rig, adoption.cid,
        value=dict(adoption.value, request=q, result=r, acquisition=g, previous=previous),
        inputs=tuple(rig.read_stored(p)[2].id for p in points),
        parents=front(rig, events_for(rig, {r, g} | ({previous} if previous else set()))))
    return a, r, {work.request: q, old_raw.cid: raw, old_r.cid: r,
                   old_g.cid: g, old_g.value["clock"]: clock, adoption.cid: a}


def post_previous_terminal(rig, work, ctx, mode):
    """The retained, actually entered Wu mouth; no foreign host.post substitution."""
    original = next(event for event, _issue in rig.workers.sent
        if isinstance(event, fb.WorkFinished) and event.work == work.desc.work_id
        and isinstance(event.outcome, fb.WorkOutputs))
    if mode == "failure":
        event = replace(original, outcome=fb.WorkFailure(failure=fb.FailureInfo(
            failure_kind="late-certain-failure", content={"device": "failed"}, readings=(), basis=())))
    elif mode == "unknown":
        event = replace(original, outcome=fb.WorkUnknown(unknown=fb.UnknownInfo(
            reason="late uncertainty, not a different known value", basis=())))
    else:
        assert mode == "equal"
        event = original
    issue = rig.workers.returns[work.request] if mode == "equal" else None
    accept_posted(rig, event, lambda: rig.workers.post(ctx, event, issue))
    return event


@pytest.mark.parametrize("depth", (2, 3), ids=("Q2", "Q3"))
@pytest.mark.parametrize("mode", ("equal", "unknown", "failure"))
def test_previous_wu_terminal_conflict_reaches_every_later_update(make_rig, depth, mode):
    """Paper:3534,3551-3591,3627-3628 (R01-R3a/G3-G6/Z2).

    Bug: inspect only this Wu or only the immediately previous Wu. Late Wu1
    failure must stop Q2 and Q3, while equal success and Unknown+success pass.
    """
    rig = make_rig()
    first, a1, _ = direct_first(rig)
    first_ctx = rig.workers.contexts["belief_update"]
    saved_a1 = rig.read_stored(a1.cid)
    rig.claim(2)
    previous = a1
    if depth == 3:
        _second, previous = rig.adopt(2)
        rig.claim(3, slot="claim-3", now=3, interval=f.MeasurementInterval(
            clock=rig.clock.run, start_ns=0, end_ns=3, closure="(start,end]"))
    q, callback = rig.callback("belief_update")
    assert q.value["desc"]["args"]["prior"] == previous.cid
    event = post_previous_terminal(rig, first, first_ctx, mode)
    callback()  # after accept, before requiring the late report to have a CID
    rig.drive(lambda: any(r.value == wire(event) and r.value["work"] == first.desc.work_id
                         for r in rig.facts(c.WORK_REPORT)))
    rig.settle_steps(12)
    assert rig.read_stored(a1.cid) == saved_a1
    assert not rig.workers.errors
    if mode == "failure":
        assert (q.value["desc"]["work_id"], False) in rig.workers.entry_attempts
        assert not any(w.request == q.cid for w in rig.workers.entries)
        assert_no_adoption(rig, q.cid)
        assert len(rig.facts(c.BELIEF_ADOPTED)) == depth - 1
        assert any(p.reason == "update:conflict" for p in rig.host.window.status().pending)
    else:
        rig.drive(lambda: len(rig.facts(c.BELIEF_ADOPTED)) == depth)
        work = next(w for w in rig.workers.entries if w.request == q.cid)
        assert_update(rig, work, rig.facts(c.BELIEF_ADOPTED)[-1], SECOND, previous.cid)


@pytest.mark.parametrize("conflict", (False, True), ids=("same_claim", "conflicting_claim"))
def test_blocked_saved_adoption_cannot_open_continuation_or_new_root_belief(make_rig, conflict):
    """Paper:3535,3579-3591,3616-3617,3628-3629,3633 (R01-R3b/G5/Z8).

    Bug: open continuation from blocked A*, or authenticate only its old Xnum.
    The already prepared A* still saves; old roots remain usable, new roots
    with the incompatible original delivery yield NoDecision(use_conflict).
    """
    rig = make_rig(continuation=True)
    first_claim(rig)
    initial_eqs = {q.cid for q in rig.requests("evaluation_prepare")}
    rig.ledger.hold_adoption_confirmation = True
    work = rig.run_stage("belief_update")
    rig.drive(lambda: bool(rig.facts(c.BELIEF_ADOPTED)))
    a = rig.one(c.BELIEF_ADOPTED)
    held = rig.ledger.uncertain
    assert held is not None and held.cid == a.cid
    assert {q.cid for q in rig.requests("evaluation_prepare")} == initial_eqs
    before = {r.cid for r in rig.facts(c.SEGMENT_REPORT)}
    event = deliver_first_claim_again(rig, conflict=conflict, accept_only=True)
    rig.contents.blocked.clear()
    rig.drive(lambda: any(r.cid not in before and r.value == wire(event) for r in rig.facts(c.SEGMENT_REPORT)))
    raw = next(r for r in rig.facts(c.SEGMENT_REPORT) if r.cid not in before and r.value == wire(event))
    rig.settle_steps(12)
    assert rig.read_stored(a.cid) == (held.header, held.salt, held.record)
    assert len([p for p in rig.ledger.preparations if p.cid == a.cid]) == 1
    if conflict:
        assert {q.cid for q in rig.requests("evaluation_prepare")} == initial_eqs
        assert {p.cid for p in rig.ledger.preparations
                if p.record.body.contract == c.EVALUATION_REQUESTED} == initial_eqs
    else:
        rig.drive(lambda: len(rig.requests("evaluation_prepare")) == 2)
    result = result_for(rig, work.request)
    old = prepare_adoption(rig, a.cid, result.cid, sole_adoption=True)
    assert isinstance(old.value, f.FProblem) and old.value.K.belief == result.record_id
    current = prepare_adoption(rig, a.cid, result.cid, sole_adoption=True, additional_roots=(raw.cid,))
    if conflict:
        assert_incomplete_preparation(current, "use_conflict")
    else:
        assert isinstance(current.value, f.FProblem) and current.value.K.belief == result.record_id


@pytest.mark.parametrize("which", ("reader", "previous_claim"))
@pytest.mark.parametrize("omit", (False, True), ids=("complete_I", "one_required_ref_missing"))
def test_recursive_required_refs_are_not_just_this_requests_observations(make_rig, which, omit):
    """Paper:2783-2793,3536,3614,3631 (R02-R3a/A2).

    Bug: reset C at recursion, or forget Desc.reader. Remove exactly one Ref,
    leaving all fixed roots, previous inputs, numerical data and witnesses.
    """
    rig = make_rig()
    first, a1, evidence = direct_first(rig)
    work, expected = first, FIRST
    target = first.desc.reader
    if which == "previous_claim":
        target = rig.one(c.SEGMENT_BINDING).value["report"]
        rig.claim(2)
        work, a2 = rig.adopt(2)
        assert_update(rig, work, a2, SECOND, a1.cid)
        evidence = rig.workers.update_evidence[work.request]
        expected = SECOND
    old = rig.read_stored(work.request)[2].body.inputs
    ref = rig.read_stored(target)[2].id
    assert ref in old
    inputs = tuple(r for r in old if r != ref) if omit else old
    assert len(inputs) == len(old) - int(omit)
    q = save_request(rig, work, inputs=inputs)
    ret = direct_update(rig, q, evidence)
    if omit:
        assert isinstance(ret, u.Rejected) and any(i.code == "unresolved_reference" for i in ret.issues)
    else:
        assert isinstance(ret, u.IssuedUpdate) and plain(ret.result) == expected


@pytest.mark.parametrize("inherit", (False, True), ids=("missing_previous_extra_I", "inherited_extra_I"))
def test_previous_extra_declared_input_is_inherited_without_new_observation(make_rig, inherit):
    """Paper:2787-2789,3536,3558,3614,3631 (R02-R3a/A2).

    Bug: propagate only previously read numerical inputs and drop surplus I.
    A real unused Prediction in Q1.I must be authenticated and inherited in Q2.
    X is absent from Q2.input_points in both variants, so Local(Q2) cannot
    reject first and hide the missing recursive inheritance check. Both
    variants contain X in the correctly keyed fixed image; only Q2.I differs.
    """
    rig = make_rig()
    first, a1, _ = direct_first(rig)
    rig.claim(2)
    second, _ = rig.adopt(2)
    x = save_copy(rig, rig.model_point)
    q, _a, _r, mapping = copied_chain_with_previous_request(rig, first, a1, second, None,
        first_extra_view=(x,), first_extra_inputs=(x,))
    value = rig.read_stored(q)[2].body.content.as_json()
    assert x not in value["desc"]["input_points"]
    ref = rig.read_stored(x)[2].id
    inputs = rig.read_stored(q)[2].body.inputs
    assert ref not in inputs
    value["desc"]["numerical_view"] = wire(fixed_view(rig,
        set(value["desc"]["numerical_view"]["boundary"]) | {x}))
    q = save_copy(rig, q, value=value, inputs=tuple(inputs) + ((ref,) if inherit else ()))
    assert x in closure(rig, value["desc"]["numerical_view"]["boundary"])
    ret = direct_update(rig, q, replace_evidence_points(current_evidence(rig), mapping))
    if inherit:
        assert isinstance(ret, u.IssuedUpdate) and plain(ret.result) == SECOND
    else:
        assert isinstance(ret, u.Rejected) and any(i.code == "unresolved_reference" for i in ret.issues)


@pytest.mark.parametrize("include_x", (False, True), ids=("Q1_only_X", "Q2_also_contains_X"))
def test_previous_subimage_must_be_taken_from_its_immediate_parent_image(make_rig, include_x):
    """Paper:3537,3592-3604,3630 (R02-R3b/A1).

    Bug: reconstruct Q1's subimage from the wide base instead of Q2's image.
    X is only an unused Q1 boundary entry, not a missing inherited I item.
    Both a wide reader and exactly Q2's closed image must give the same verdict.
    """
    rig = make_rig()
    first, a1, _ = direct_first(rig)
    rig.claim(2)
    second, _ = rig.adopt(2)
    x = save_copy(rig, rig.model_point)
    q, head, _r, mapping = copied_chain_with_previous_request(rig, first, a1, second, None,
        first_extra_view=(x,), second_extra=(x,) if include_x else ())
    q1 = rig.read_stored(head)[2].body.content.as_json()["request"]
    first_view = rig.read_stored(q1)[2].body.content.as_json()["desc"]["numerical_view"]
    assert x in first_view["boundary"]
    assert rig.read_stored(x)[2].id not in rig.read_stored(q1)[2].body.inputs
    desc = rig.read_stored(q)[2].body.content.as_json()["desc"]
    points = closure(rig, desc["numerical_view"]["boundary"]) | {q}
    assert (x in points) == include_x
    evidence = replace_evidence_points(current_evidence(rig), mapping)
    wide = direct_update(rig, q, evidence)
    narrow = u.compute_finite_update(q, reader=PublicReader(rig.ledger, points=points),
        registry=rig.registry, evidence=evidence, budget=UPDATE_BUDGET)
    assert type(wide) is type(narrow)
    if include_x:
        assert isinstance(wide, u.IssuedUpdate)
        assert plain(wide.result) == plain(narrow.result) == SECOND
        assert wide.application_digest == narrow.application_digest
    else:
        assert isinstance(wide, (u.Rejected, u.Insufficient)) and wide.issues
        assert plain(wide) == plain(narrow)


@pytest.mark.parametrize("location", ("current", "previous", "head"))
@pytest.mark.parametrize("change", (None, "method", "purpose", "output_contract", "saved_budget"))
def test_request_authentication_applies_in_all_three_public_paths(make_rig, location, change):
    """Paper:3538,3592-3616,3630-3633 (AUTH-R3/A1/A3/A4).

    Bug: check purpose/method/output/saved budget only on the outer U call.
    Rebind the same one-field change through R/G/A, with correct numerical data.
    """
    rig = make_rig()
    first, a1, _ = direct_first(rig)
    rig.claim(2)
    second, _ = rig.adopt(2)
    q2, head, result, mapping = copied_chain_with_previous_request(rig, first, a1, second, change)
    q1 = rig.read_stored(head)[2].body.content.as_json()["request"]
    evidence = replace_evidence_points(current_evidence(rig), mapping)
    if change == "saved_budget":
        # Establish the saved frame's insufficiency independently of replay.
        assert_budget_shortage(direct_update(rig, q1, evidence,
            budget=cells(UPDATE_BUDGET, 1)), phase="reader")
    if location == "head":
        if change is None:
            prepared = prepare_adoption(rig, head, result, evidence=evidence)
            assert isinstance(prepared.value, f.FProblem)
            assert prepared.value.K.belief == rig.read_stored(result)[2].id
        elif change == "saved_budget":
            assert_incomplete_preparation(prepare_adoption(rig, head, result, evidence=evidence),
                                          "budget_exhausted")
        else:
            try:
                prepared = prepare_adoption(rig, head, result, evidence=evidence)
            except (f.FInputError, f.FSpecificationMissing) as error:
                assert error.reason in ("shape", "missing_contract")
            else:
                assert isinstance(prepared.value, f.NoDecision)
                assert prepared.value.reason in ("algorithm_unavailable", "prerequisite_unavailable")
        return
    q = q1 if location == "current" else q2
    budget = cells(UPDATE_BUDGET, 1) if change == "saved_budget" and location == "current" else UPDATE_BUDGET
    try:
        ret = direct_update(rig, q, evidence, budget=budget)
    except f.FInputError as error:
        assert change in ("purpose", "method", "output_contract") and error.reason in ("shape", "missing_contract")
        return
    if change is None:
        assert isinstance(ret, u.IssuedUpdate) and plain(ret.result) == (FIRST if location == "current" else SECOND)
    elif change == "saved_budget":
        assert_budget_shortage(ret)
    else:
        assert isinstance(ret, (u.Rejected, u.Insufficient)) and ret.issues


@pytest.mark.parametrize("prior", (False, True), ids=("head_Q", "previous_Q"))
@pytest.mark.parametrize("bad_key", (False, True), ids=("known_registry", "unknown_registry"))
def test_prepare_keeps_registry_shortage_as_incomplete_not_bad_proof(make_rig, prior, bad_key):
    """Paper:3539,3616,3633 (DIAG-R3/A4/Z8).

    Bug: translate any replay Insufficient into FInputError(proof_mismatch).
    No exception is accepted for the unknown registry, at head or in its prior.
    """
    rig = make_rig()
    first, a1, _ = direct_first(rig)
    rig.claim(2)
    second, a2 = rig.adopt(2)
    q, head, result, mapping = copied_chain_with_previous_request(rig, first, a1, second,
        "registry_key" if bad_key else None)
    if prior:
        head, result, rest = copy_adoption_for_request(rig, second, a2, q, previous=head)
        mapping.update(rest)
    prepared = prepare_adoption(rig, head, result,
        evidence=replace_evidence_points(current_evidence(rig), mapping))
    if bad_key:
        assert_incomplete_preparation(prepared, "algorithm_unavailable")
    else:
        assert isinstance(prepared.value, f.FProblem)
        assert prepared.value.K.belief == rig.read_stored(result)[2].id


@pytest.mark.parametrize("duplicate", (False, True), ids=("distinct_extra_ref", "duplicated_ref"))
def test_declared_inputs_are_checked_before_converting_to_a_set(make_rig, duplicate):
    """Paper:2789,3540,3606 (INPUTS-R3).

    Bug: silently deduplicate I. Only the appended Ref changes; Desc, view and
    evidence are identical. An unused real extra Ref is the successful control.
    """
    rig = make_rig()
    work, _a, evidence = direct_first(rig)
    x = save_copy(rig, rig.model_point)
    desc = replace(work.desc, numerical_view=fixed_view(rig, set(work.desc.numerical_view.boundary) | {x}))
    old = rig.read_stored(work.request)[2].body.inputs
    ref = old[0] if duplicate else rig.read_stored(x)[2].id
    q = save_request(rig, work, desc=desc, inputs=tuple(old) + (ref,))
    assert rig.read_stored(q)[2].body.inputs.count(ref) == (2 if duplicate else 1)
    ret = direct_update(rig, q, evidence)
    if duplicate:
        assert isinstance(ret, u.Rejected) and any(i.code == "shape" for i in ret.issues)
    else:
        assert isinstance(ret, u.IssuedUpdate) and plain(ret.result) == FIRST


def test_prepare_entries_with_adoption_require_independent_host_evidence(make_rig):
    """Paper:3617,3633 (Z8). Bug: infer execution ownership from saved bytes.

    Both public entries receive exactly the same reader, fixed roots and inputs.
    Only the F-b entry receives independent observations from the public ctx.
    """
    rig = make_rig()
    work, a, _ = direct_first(rig)
    r = result_for(rig, work.request)
    reader, kwargs = adoption_prepare_inputs(rig, a.cid, r.cid)
    evidence = current_evidence(rig)
    without_observations = ff.prepare_f_from_facts(reader, **fa_kwargs(kwargs))
    with_observations = u.prepare_fb_from_facts(reader, evidence=evidence, **kwargs)
    assert_incomplete_preparation(without_observations, "prerequisite_unavailable")
    assert isinstance(with_observations.value, f.FProblem)
    assert with_observations.value.K.belief == r.record_id


@pytest.mark.parametrize("evidence", (None, (), {}), ids=("none", "tuple", "mapping"))
def test_fb_prepare_requires_target_evidence_type(make_rig, evidence):
    """Paper:3633 (Z8); public F-b entry, twelfth request (TargetEvidence required).

    Bug: accept None or duck-typed observations instead of rejecting their shape.
    The same complete adopted series succeeds with the actual TargetEvidence.
    """
    rig = make_rig()
    work, a, _ = direct_first(rig)
    r = result_for(rig, work.request)
    reader, kwargs = adoption_prepare_inputs(rig, a.cid, r.cid)
    valid = u.prepare_fb_from_facts(reader, evidence=current_evidence(rig), **kwargs)
    assert isinstance(valid.value, f.FProblem) and valid.value.K.belief == r.record_id
    with pytest.raises(f.FInputError) as exc:
        u.prepare_fb_from_facts(reader, evidence=evidence, **kwargs)
    assert exc.value.reason == "shape"


def test_prepare_entries_without_adoption_have_identical_artifact_bytes(make_rig):
    """Paper:3633 (Z8/K12). Bug: require F-b evidence on the old F-a path.

    F-a without observations and F-b with a well-typed empty TargetEvidence
    must produce identical original artifact bytes when no A* is present.
    """
    rig = make_rig()
    rig.initial_evaluation()
    work = next(w for w in rig.workers.entries if w.desc.purpose == "evaluation_prepare")
    reader = rig.workers.prepares[0][1]
    kwargs = prepare_kwargs(work)
    absent = ff.prepare_f_from_facts(reader, registry=rig.registry, **fa_kwargs(kwargs))
    empty = u.prepare_fb_from_facts(reader, registry=rig.registry,
        evidence=u.TargetEvidence(executions=(), uses=(), intervals=(), acquisitions=(),
                                  route_applications=(), host_monitors=()), **kwargs)
    assert isinstance(absent.value, f.FProblem) and not rig.facts(c.BELIEF_ADOPTED)
    assert absent.canonical_bytes == empty.canonical_bytes


@pytest.mark.parametrize("conflict", (False, True), ids=("same_terminal", "clashing_terminal"))
def test_diagnostic_terminal_is_created_even_when_its_evidence_is_in_conflict(make_rig, conflict):
    """Paper:1080-1082,3546,3556-3566,3591 (REF-3/G2/G3/G6).

    Bug: follow diagnostic E as U and forbid T itself. Accept both ends before
    any host settle, so T is newly created after the clash, not a retry.
    """
    rig = make_rig()
    first_claim(rig)
    events = []
    def reply(work, ctx):
        ret = rig.workers.compute(work, ctx)
        assert isinstance(ret, u.IssuedUpdate)
        first = rig.workers.finished(work, fb.WorkOutputs(outputs=u.update_response(ret)))
        late = (replace(first, outcome=fb.WorkFailure(failure=fb.FailureInfo(
            failure_kind="diagnostic-only", content={"certainty": True}, readings=(), basis=())))
            if conflict else first)
        events.extend((first, late))
        accept_posted(rig, first, lambda: rig.workers.post(ctx, first, ret))
        accept_posted(rig, late, lambda: rig.workers.post(ctx, late, None if conflict else ret))
        assert not rig.facts(c.WORK_TERMINAL) or not any(
            t.value["request"] == work.request for t in rig.facts(c.WORK_TERMINAL))
    rig.workers.overrides["belief_update"] = reply
    q, callback = rig.callback("belief_update")
    callback()
    rig.drive(lambda: any(t.value["request"] == q.cid for t in rig.facts(c.WORK_TERMINAL))
        and len([r for r in rig.facts(c.WORK_REPORT) if r.value["work"] == events[0].work]) == 2)
    t = next(t for t in rig.facts(c.WORK_TERMINAL) if t.value["request"] == q.cid)
    assert t.value["terminal_kind"] == "outputs"
    assert rig.by_cid(c.WORK_REPORT, t.value["first_receipt"]).value == wire(events[0])
    if conflict:
        assert_no_adoption(rig, q.cid)
    else:
        rig.drive(lambda: bool(rig.facts(c.BELIEF_ADOPTED)))
        assert rig.one(c.BELIEF_ADOPTED).value["result"] == result_for(rig, q.cid).cid


@pytest.mark.parametrize("conflict", (False, True), ids=("equal_E_and_U", "clashing_E_and_U"))
def test_evidence_visit_does_not_suppress_the_same_points_use_dependency(make_rig, conflict):
    """Paper:1080-1081,3546,3562-3566,3631 (REF-2/REF-3/G3).

    Bug: mark a Point visited through Claim.evidence (E), then omit its U
    expansion through Q2.prior and B. The same Claim1 point has both paths.
    """
    rig = make_rig()
    first, a1, _ = direct_first(rig)
    raw = rig.one(c.SEGMENT_BINDING).value["report"]
    ref = rig.read_stored(raw)[2].id
    rig.claim(2, evidence=(ref,))
    q, callback = rig.callback("belief_update")
    assert q.value["desc"]["args"]["prior"] == a1.cid
    b2 = next(b for b in rig.facts(c.SEGMENT_BINDING) if b.value["report"] != raw)
    claim2 = rig.read_stored(b2.value["report"])[2].body.content.as_json()
    assert claim2["item"]["value"]["evidence"] == [str(ref)]
    event = deliver_first_claim_again(rig, conflict=conflict, accept_only=True)
    callback()
    rig.drive(lambda: any(r.value == wire(event) for r in rig.facts(c.SEGMENT_REPORT)))
    rig.settle_steps(12)
    if conflict:
        assert (q.value["desc"]["work_id"], False) in rig.workers.entry_attempts
        assert_no_adoption(rig, q.cid)
    else:
        rig.drive(lambda: len(rig.facts(c.BELIEF_ADOPTED)) == 2)
        second = next(w for w in rig.workers.entries if w.request == q.cid)
        assert_update(rig, second, rig.facts(c.BELIEF_ADOPTED)[1], SECOND, a1.cid)


@pytest.mark.parametrize("family", ("item_branch", "started_life"))
@pytest.mark.parametrize("conflict", (False, True), ids=("same_value", "exclusive_value"))
def test_item_branches_and_lifecycle_keys_are_compared_without_erasing_exclusions(make_rig, family, conflict):
    """Paper:3546,3567-3578,3627 (G4/Z2; Frame intentionally outside this version).

    Bug: namespace Claim/Gap by branch or only compare Started by item_slot.
    The legal duplicate has the same semantic value; the negative uses the
    same item family or k/life key despite a different branch/Started slot.
    """
    rig = make_rig()
    first_claim(rig)
    q, callback = rig.callback("belief_update")
    if family == "started_life":
        original = next(e for e, _issue in rig.workers.sent if isinstance(e, fb.SegmentReport)
                        and isinstance(e.item, fb.SegmentBoundary) and e.item.kind == "started")
        item = replace(original.item, reading=rig.actual_reading()) if conflict else original.item
        event = replace(original, item_slot="another-started-slot", item=item)
    else:
        original = next(e for e, _issue in rig.workers.sent if isinstance(e, fb.SegmentReport)
                        and e.item_slot == "claim-1")
        item = (f.Gap(route_epoch="route-A", sequence_range=(0, 1), interval=original.item.interval,
                      reason="missing frames", evidence=()) if conflict else original.item)
        event = replace(original, item=item)
    rig.command(lambda _work, ctx: accept_posted(rig, event, lambda: rig.workers.post(ctx, event)))
    callback()
    rig.drive(lambda: any(r.value == wire(event) for r in rig.facts(c.SEGMENT_REPORT)))
    rig.settle_steps(12)
    if conflict:
        assert (q.value["desc"]["work_id"], False) in rig.workers.entry_attempts
        assert_no_adoption(rig, q.cid)
    else:
        rig.drive(lambda: bool(rig.facts(c.BELIEF_ADOPTED)))
        work = next(w for w in rig.workers.entries if w.request == q.cid)
        assert_update(rig, work, rig.one(c.BELIEF_ADOPTED), FIRST)


@pytest.mark.parametrize("change", (None, "joint", "evidence_mass"))
def test_replay_recomputes_result_even_when_issued_report_and_result_agree(make_rig, change):
    """Paper:2801-2809,3307,3610,3634 (19-3/C7/A1).

    Bug: compare R* only with its issued-report basis and skip primary replay.
    The copied report and R* have exactly the same schema-valid forged result;
    metadata, primary inputs and acquisition stay correct in all variants.
    Round 16: result_mismatch remains the paper expectation. The earlier
    observation_binding_mismatch exit is unconfirmed; retain the red case
    without accepting that different reason or inspecting its implementation.
    """
    rig = make_rig()
    first, a1, _ = direct_first(rig)
    rig.claim(2)
    second, _ = rig.adopt(2)
    q1 = save_request(rig, first)
    correct = direct_update(rig, q1, current_evidence(rig))
    assert isinstance(correct, u.IssuedUpdate) and plain(correct.result) == FIRST
    value = json.loads(json.dumps(FIRST))
    if change == "joint":
        value["joint"] = [[1, 2], [1, 2]]
    elif change == "evidence_mass":
        value["evidence_mass"] = [1, 1]
    head, r, mapping = copy_adoption_for_request(rig, first, a1, q1, result_value=value)
    result = rig.by_cid(c.UPDATE_RESULT, r)
    report_point = next(p for p in result.parents if rig.read_stored(p)[2].body.contract == c.WORK_REPORT)
    report = rig.read_stored(report_point)[2].body.content.as_json()
    assert report["outcome"]["value"]["value"] == {"kind": "issued", "value": value}
    assert result.value["result"] == value
    old_r = result_for(rig, first.request)
    for field in ("application_digest", "registry_key", "numerical_view"):
        assert result.value[field] == old_r.value[field]
    q2 = rebind_request_inputs(rig, second, mapping, prior=head)
    evidence = replace_evidence_points(current_evidence(rig), mapping)
    ret = direct_update(rig, q2, evidence)
    if change is None:
        assert isinstance(ret, u.IssuedUpdate) and plain(ret.result) == SECOND
        prepared = prepare_adoption(rig, head, r, evidence=evidence)
        assert isinstance(prepared.value, f.FProblem) and prepared.value.K.belief == result.record_id
    else:
        assert isinstance(ret, u.Rejected) and any(i.code == "result_mismatch" for i in ret.issues)
        with pytest.raises(f.FInputError) as error:
            prepare_adoption(rig, head, r, evidence=evidence)
        assert error.value.reason == "result_mismatch"


@pytest.mark.parametrize("offset", (-1, 0, 1), ids=("smaller", "equal", "larger"))
def test_call_budget_must_equal_saved_budget_even_when_both_can_compute(make_rig, offset):
    """Paper:3615,3630,3632 (A3/R07-R2).

    Bug: omit equality and use either the caller's or saved sufficient budget.
    A matching saved/call control first proves this call budget computes CE1;
    thus a smaller-call rejection cannot be a budget-exhaustion false positive.
    """
    rig = make_rig()
    work, _a, evidence = direct_first(rig)
    call_budget = logical(UPDATE_BUDGET, UPDATE_BUDGET.logical_limit + offset)
    control_q = budget_request(rig, work, call_budget)
    control = direct_update(rig, control_q, evidence, budget=call_budget)
    assert isinstance(control, u.IssuedUpdate) and plain(control.result) == FIRST
    ret = direct_update(rig, work.request, evidence, budget=call_budget)
    if offset == 0:
        assert isinstance(ret, u.IssuedUpdate) and plain(ret.result) == FIRST
    else:
        assert isinstance(ret, u.Rejected) and ret.issues


@pytest.mark.parametrize("field", ("process", "permissions"))
@pytest.mark.parametrize("bad", (False, True), ids=("matching_boot", "mismatching_boot"))
def test_update_boot_slots_must_match_initial_declaration_not_merely_exist(make_rig, field, bad):
    """Paper:3598-3600,3630 (A1 declarations).

    Bug: resolve an existing Boot slot but never compare its declared role.
    Wrong process uses the real sensing slot; wrong permissions retains one
    real permission. Boot Ref, image, mathematical args and evidence stay put.
    """
    rig = make_rig()
    work, _a, evidence = direct_first(rig)
    initial = rig.boot_input.declaration.initial.value
    expected = frozenset({fb.BootSlot(declaration=work.desc.process.declaration,
        slot=initial.derivation.slot), fb.BootSlot(declaration=work.desc.process.declaration,
        slot=initial.allocation.slot)})
    assert work.desc.permissions == expected and work.desc.process.slot == initial.process_slot
    desc = work.desc
    if bad and field == "process":
        slot = rig.boot_input.declaration.routes[0].value.process_slot
        assert slot != initial.process_slot
        desc = replace(desc, process=replace(desc.process, slot=slot))
    elif bad:
        desc = replace(desc, permissions=frozenset({desc.allocation}))
        assert desc.permissions < expected
    q = save_request(rig, work, desc=desc)
    assert rig.read_stored(q)[2].body.inputs == rig.read_stored(work.request)[2].body.inputs
    ret = direct_update(rig, q, evidence)
    if bad:
        assert isinstance(ret, u.Rejected) and ret.issues
    else:
        assert isinstance(ret, u.IssuedUpdate) and plain(ret.result) == FIRST


@pytest.mark.parametrize("bad", (False, True), ids=("same_origin_model", "other_origin_model"))
def test_reader_origin_model_is_checked_after_coherent_reader_rebinding(make_rig, bad):
    """Paper Z33:3717; fb_rules.md:40662-40691 (ledger_origin_binding).

    Bug: accept a reader with another model because EA agrees with Q.reader,
    instead of deriving the unique Origin from Boot and the fixed ledger.
    Both images retain the sole eligible original Origin and an ineligible
    other-model Origin; only Q.reader and the matching EA origins differ.
    A copied matching-model Origin would make the legal pair ambiguous.
    The old model-equality guard alone is redundant with this association's
    requested/model rules, so this does not claim to isolate that guard.
    Unverified: omitting only that guard is publicly indistinguishable here;
    A1-DECLARATION-PERMISSION (fb_rules.md:49207) rejects the wrong reader's
    requested rights first (proof_mismatch). The legal pair must still issue.
    """
    rig = make_rig()
    work, _a, _ = direct_first(rig)
    original = rig.by_cid(ORIGIN, work.desc.reader)
    other_model = save_copy(rig, rig.model_point)
    value = dict(original.value, model=other_model)
    alternate = save_copy(rig, original.cid, value=value)
    reader = alternate if bad else original.cid
    boundary = set(work.desc.numerical_view.boundary) | {alternate, other_model, original.cid}
    desc = replace(work.desc, reader=reader,
        input_points=work.desc.input_points | {alternate, other_model, original.cid},
        numerical_view=fixed_view(rig, boundary))
    inputs = set(rig.read_stored(work.request)[2].body.inputs)
    inputs |= {rig.read_stored(p)[2].id for p in (alternate, other_model, original.cid)}
    q = save_request(rig, work, desc=desc, inputs=inputs,
        parents=front(rig, set(rig.by_cid(c.WORK_REQUESTED, work.request).parents)
                      | events_for(rig, {alternate, other_model, original.cid})))
    evidence = current_evidence(rig)
    evidence = replace(evidence, acquisitions=tuple(replace(a, origin=reader)
        if a.origin == original.cid else a for a in evidence.acquisitions))
    eligible = [x.cid for x in rig.facts(ORIGIN) if x.cid in closure(rig, boundary)
                and x.value["model"] == rig.boot_input.declaration.initial.value.model]
    assert eligible == [original.cid], "do not let ambiguity or no candidate mask reader/model mismatch"
    assert all(a.origin == reader for a in evidence.acquisitions)
    ret = direct_update(rig, q, evidence)
    if bad:
        assert isinstance(ret, u.Rejected) and any(i.code == "proof_mismatch"
            and "A1-DECLARATION-PERMISSION" in i.message for i in ret.issues), [
            (i.code, i.message[:160]) for i in ret.issues]
    else:
        assert isinstance(ret, u.IssuedUpdate) and plain(ret.result) == FIRST


@pytest.mark.parametrize("omit", (False, True), ids=("all_channel_refs", "unused_channel_route_missing"))
def test_local_closure_includes_route_of_an_unobserved_channel(make_rig, omit):
    """Paper:2684-2706,2783-2793,3600,3614,3631 (A2 Local).

    Bug: collect route_config refs only from the channel used by this Claim.
    Two genuinely distinct Boot routes keep channel matching unique. Remove
    the unused route from input_points in BOTH controls, so only law's typed
    reference can require its I entry; all bodies remain in the fixed image.
    """
    args = delta_args()
    args["law"]["channels"].append({"id": "unused", "route_slots": ["unused-route"],
        "domain": dict(args["law"]["channels"][0]["domain"])})
    rig = make_rig(second_route=True, derivation_args=args)
    rig.initial_evaluation()
    expected_config = wire(rig.boot_input.declaration.routes[0].value.config)
    matching = [r for r in rig.facts(ROUTE) if r.value["config"] == expected_config]
    assert len(matching) == 1, [r.value for r in rig.facts(ROUTE)]
    route = matching[0]
    index = next(i for i, q in enumerate(rig.requests("measure_segment"))
                 if q.value["desc"]["args"]["route"] == route.cid)
    rig.start_measurement(index)
    rig.claim()
    work, _a = rig.adopt()
    assert isinstance(rig.workers.returns[work.request], u.IssuedUpdate)
    assert plain(rig.workers.returns[work.request].result) == FIRST
    law = rig.one(c.FINITE_JOINT_COUNT_LAW)
    assert len(law.value["channels"]) == 2
    used = next(ch for ch in law.value["channels"] if ch["id"] == "arrivals")
    unused = next(ch for ch in law.value["channels"] if ch["id"] == "unused")
    assert used["route_configs"] == [route.cid] and len(unused["route_configs"]) == 1
    target = unused["route_configs"][0]
    assert target != route.cid and target in closure(rig, work.desc.numerical_view.boundary)
    ref = rig.read_stored(target)[2].id
    inputs = rig.read_stored(work.request)[2].body.inputs
    assert ref in inputs
    desc = replace(work.desc, input_points=work.desc.input_points - {target})
    q = save_request(rig, work, desc=desc,
        inputs=tuple(r for r in inputs if r != ref) if omit else inputs)
    ret = direct_update(rig, q, rig.workers.update_evidence[work.request])
    if omit:
        assert isinstance(ret, u.Rejected) and any(i.code == "unresolved_reference" for i in ret.issues)
    else:
        assert isinstance(ret, u.IssuedUpdate) and plain(ret.result) == FIRST


def minimal_logical_limit(rig, work, evidence, low=0, high=1 << 14):
    """公開の入口 U で、この要求 (work の desc) が発行される最小の論理の上限を二分探索で実測する (試験の閾値)。
    (low, high] の中で探す。上限より小さい値はどれも budget_exhausted の不足であること (別の拒否・不足でない) も確かめる。"""
    def issued(limit):
        budget = logical(UPDATE_BUDGET, limit)
        q = budget_request(rig, work, budget)
        ret = direct_update(rig, q, evidence, budget=budget)
        if isinstance(ret, u.IssuedUpdate):
            return True
        assert_budget_shortage(ret)
        return False
    assert issued(high), "the request must issue with the high logical limit"
    while low + 1 < high:
        mid = (low + high) // 2
        if issued(mid):
            high = mid
        else:
            low = mid
    return high


def non_reader_term_shortage(rig, work, evidence):
    """Empirical fixture threshold, not an assertion about the unspecified term unit."""
    for terms in range(1, 129):
        budget = logical(UPDATE_BUDGET, terms)
        q = budget_request(rig, work, budget)
        ret = direct_update(rig, q, evidence, budget=budget)
        if isinstance(ret, u.Insufficient):
            assert_budget_shortage(ret)
            phases = {plain(n.value)["phase"] for issue in ret.issues for n in issue.missing if n.kind == "budget"}
            if phases & {"projection", "replay", "computation"}:
                return budget
        else:
            assert isinstance(ret, u.IssuedUpdate) and plain(ret.result) == FIRST
    raise ContractGap("CG-FB3-TERM-FRAME-FIXTURE: no non-reader max_terms shortage in 1..128; paper:3615,3632")


@pytest.mark.parametrize("path", ("next_U", "head_Q1", "head_Q2"))
@pytest.mark.parametrize("small", (False, True), ids=("sufficient_saved_terms", "insufficient_saved_terms"))
def test_replay_enforces_each_saved_term_budget_below_the_outer_budget(make_rig, path, small):
    """Paper:3615,3632 (A3 saved frame, separate from reader max_cells).

    Bug: accumulate only into the outer budget and omit the Q1 saved frame.
    Q1 directly proves a non-reader term shortage with unchanged max_cells;
    R1 and its issued report remain numerically correct and mutually equal.
    """
    rig = make_rig()
    first, a1, first_evidence = direct_first(rig)
    budget = non_reader_term_shortage(rig, first, first_evidence) if small else UPDATE_BUDGET
    assert budget.numerical == UPDATE_BUDGET.numerical
    rig.claim(2)
    second, a2 = rig.adopt(2)
    q2, head, r, mapping = copied_chain_with_previous_request(rig, first, a1, second, None,
        first_budget=budget)
    q1 = rig.read_stored(head)[2].body.content.as_json()["request"]
    evidence = replace_evidence_points(current_evidence(rig), mapping)
    direct = direct_update(rig, q1, evidence, budget=budget)
    if small:
        assert_budget_shortage(direct)
        assert any(n.kind == "budget" and plain(n.value)["phase"] != "reader"
                   for issue in direct.issues for n in issue.missing)
    else:
        assert isinstance(direct, u.IssuedUpdate) and plain(direct.result) == FIRST
    if path == "next_U":
        ret = direct_update(rig, q2, evidence, budget=UPDATE_BUDGET)
        if small:
            assert_budget_shortage(ret)
        else:
            assert isinstance(ret, u.IssuedUpdate) and plain(ret.result) == SECOND
    else:
        if path == "head_Q2":
            head, r, rest = copy_adoption_for_request(rig, second, a2, q2, previous=head)
            mapping.update(rest)
            evidence = replace_evidence_points(current_evidence(rig), mapping)
        prepared = prepare_adoption(rig, head, r, evidence=evidence)
        if small:
            assert_incomplete_preparation(prepared, "budget_exhausted")
        else:
            assert isinstance(prepared.value, f.FProblem)
            assert prepared.value.K.belief == rig.read_stored(r)[2].id


@pytest.mark.parametrize("missing", (False, True), ids=("full_observations", "Wu1_execution_missing"))
def test_prepare_does_not_treat_lost_update_origin_observation_as_irrelevant(make_rig, missing):
    """Paper:3579,3617,3633 (G5/Z8).

    Bug: treat a missing Wu1 ExecutionObservation as no related terminal.
    Only that row is removed; measurement execution, uses, EA and EI remain.
    """
    rig = make_rig()
    work, a, _ = direct_first(rig)
    evidence = current_evidence(rig)
    rows = tuple(x for x in evidence.executions if x.work_id == work.desc.work_id)
    assert len(rows) == 1 and rows[0].entered == 1 and rows[0].reports
    changed = replace(evidence, executions=tuple(x for x in evidence.executions
        if not missing or x.work_id != work.desc.work_id))
    assert changed.uses == evidence.uses and changed.acquisitions == evidence.acquisitions
    assert changed.intervals == evidence.intervals
    measuring = rig.workers.contexts["measure_segment"]
    assert measuring is not None and len(changed.executions) == len(evidence.executions) - int(missing)
    r = result_for(rig, work.request)
    prepared = prepare_adoption(rig, a.cid, r.cid, evidence=changed)
    if missing:
        assert_incomplete_preparation(prepared, "prerequisite_unavailable")
    else:
        assert isinstance(prepared.value, f.FProblem) and prepared.value.K.belief == r.record_id


@pytest.mark.parametrize("moment", ("before_open", "after_open"))
@pytest.mark.parametrize("conflict", (False, True), ids=("same_delivery", "clashing_delivery"))
def test_continuation_gate_and_conflict_display_do_not_depend_on_opening_time(make_rig, moment, conflict):
    """Paper:3628-3629 (Z3/Z4; the continuation opener itself is not a second gate).

    Bug: guard only the opener, or display update:conflict only from there.
    After-open is witnessed by a prepared continuation context, held at the
    public pre-write boundary after o/j exist and before any new EQ is prepared.
    Prepared context may finish saving; EQ and every downstream publication
    must stop. Same delivery traverses the identical cut and finishes selection.
    """
    rig = make_rig(continuation=True)
    first_claim(rig)
    downstream = {c.EVALUATION_REQUESTED, c.PREPARED, c.DRAW_REQUESTED,
                  c.DRAW_REPORT, c.EVALUATED, c.SELECTION, MATH}
    def publications():
        return {p.cid for p in rig.ledger.preparations if p.record.body.contract in downstream
                or (p.record.body.contract == c.WORK_REQUESTED
                    and p.record.body.content.as_json()["desc"]["purpose"] == "evaluation")}
    previous_publications = publications()
    previous_bytes = {p: rig.read_stored(p) for p in previous_publications}
    rig.ledger.hold_adoption_confirmation = moment == "before_open"
    rig.ledger.hold_context_before_write = moment == "after_open"
    work = rig.run_stage("belief_update")
    rig.drive(lambda: bool(rig.facts(c.BELIEF_ADOPTED)))
    a = rig.one(c.BELIEF_ADOPTED)
    held = rig.ledger.held_context
    if moment == "after_open":
        assert held is not None
        assert held.cid not in {e.cid for e in PublicReader(rig.ledger).entries()}
        assert a.cid in closure(rig, held.parents)
        context = held.record.body.content.as_json()
        for field in ("observation_reading", "judgment_reading"):
            assert rig.read_stored(context[field])[2].body.contract == CLOCK
        assert not rig.contents.blocked
    else:
        assert rig.ledger.uncertain is not None and held is None
    assert publications() == previous_publications
    old_raw = {r.cid for r in rig.facts(c.SEGMENT_REPORT)}
    event = deliver_first_claim_again(rig, conflict=conflict, accept_only=True)
    rig.settle_steps(3)
    rig.contents.blocked.clear()
    rig.ledger.hold_context_before_write = False
    rig.drive(lambda: any(r.cid not in old_raw and r.value == wire(event)
                         for r in rig.facts(c.SEGMENT_REPORT)))
    rig.settle_steps(12)
    assert [x.cid for x in rig.facts(c.BELIEF_ADOPTED)] == [a.cid]
    if held is not None:
        assert rig.read_stored(held.cid)[2] == held.record
        assert all(p == held for p in rig.ledger.held_context_attempts)
        assert len([p for p in rig.ledger.preparations if p.cid == held.cid]) == 1
    pending = rig.host.window.status().pending
    if conflict:
        assert any(p.reason == "update:conflict" for p in pending), [(p.kind, p.reason) for p in pending]
        assert publications() == previous_publications
        assert all(rig.read_stored(p) == record for p, record in previous_bytes.items())
    else:
        assert not any(p.reason == "update:conflict" for p in pending)
        rig.drive(lambda: len(rig.requests("evaluation_prepare")) == 2)
        ep = rig.run_stage("evaluation_prepare")
        rig.run_stage("selection_draw")
        ee = rig.run_stage("evaluation")
        rig.drive(lambda: len(rig.facts(c.SELECTION)) == 2)
        prepared = rig.workers.prepared_by_request[ep.request]
        assert isinstance(prepared.value, f.FProblem)
        assert prepared.value.K.belief == result_for(rig, work.request).record_id
        assert isinstance(rig.workers.evaluated_by_request[ee.request].value, f.Selected)


def paper_required_input_points(rig, request):
    """Paper:2784-2794,3601,3615,3657; typed Local/History, never host I as oracle."""
    required = {}
    by_ref = {rig.read_stored(e.cid)[2].id: e.cid for e in PublicReader(rig.ledger).entries()}

    def add(label, point):
        if point is not None:
            required.setdefault(point, set()).add(label)

    def law_refs(point, prefix):
        add(prefix, point)
        law = rig.read_stored(point)[2].body.content.as_json()
        add(prefix + ".model", law["model"])
        if law["extends"] is not None:
            law_refs(law["extends"], prefix + ".extends")
        for i, channel in enumerate(law["channels"]):
            add(f"{prefix}.channel[{i}].process.declaration", channel["process"]["declaration"])
            for j, route in enumerate(channel["route_configs"]):
                add(f"{prefix}.channel[{i}].route_configs[{j}]", route)
            sources = [s for s in rig.facts(CLOCK_SOURCE)
                       if s.value["run"] == channel["domain"]["clock"]]
            assert len(sources) == 1
            add(f"{prefix}.channel[{i}].domain.clock", sources[0].cid)

    def visit(q, prefix):
        desc = rig.read_stored(q)[2].body.content.as_json()["desc"]
        add(prefix + ".reader", desc["reader"])
        add(prefix + ".args.model", desc["args"]["model"])
        for i, trigger in enumerate(desc["trigger"]):
            add(f"{prefix}.trigger[{i}]", trigger["point"])
        for i, point in enumerate(desc["input_points"]):
            add(f"{prefix}.input_points[{i}]", point)
        for name, slot in (("process", desc["process"]), ("allocation", desc["allocation"])):
            add(prefix + "." + name + ".declaration", slot["declaration"])
        for i, slot in enumerate(desc["permissions"]):
            add(f"{prefix}.permissions[{i}].declaration", slot["declaration"])
        for i, observation in enumerate(desc["args"]["observations"]):
            name = f"{prefix}.observations[{i}]"
            add(name + ".binding", observation["binding"])
            add(name + ".reading", observation["reading"])
            binding = rig.read_stored(observation["binding"])[2].body.content.as_json()
            for field in ("report", "segment", "route"):
                add(name + ".B." + field, binding[field])
            for field in ("evidence", "clock"):
                for j, point in enumerate(binding[field]):
                    add(f"{name}.B.{field}[{j}]", point)
            for field, point in binding["generation"].items():
                add(name + ".B.generation." + field, point)
            reading = rig.read_stored(observation["reading"])[2].body.content.as_json()
            add(name + ".reading.model", reading["model"])
            for j, claim in enumerate(reading["projection"]["args"]["claims"]):
                law_refs(claim["law"], f"{name}.reading.claims[{j}].law")
            visible = closure(rig, desc["numerical_view"]["boundary"])
            spans = [s for s in rig.facts(c.MONITOR_SPAN)
                     if s.cid in visible and s.value["segment"] == binding["segment"]]
            assert spans
            for j, span in enumerate(spans):
                add(f"{name}.support[{j}]", span.cid)
                for field in ("segment", "route", "clock"):
                    add(f"{name}.support[{j}].{field}", span.value[field])
        prior = desc["args"]["prior"]
        if prior is not None:
            add(prefix + ".prior.A", prior)
            a = rig.read_stored(prior)[2].body.content.as_json()
            for field in ("request", "result", "acquisition", "origin", "model", "previous"):
                add(prefix + ".prior." + field, a[field])
            result = rig.read_stored(a["result"])[2].body
            for i, ref in enumerate(result.basis):
                add(f"{prefix}.prior.R.basis[{i}]", by_ref[ref])
            g = rig.read_stored(a["acquisition"])[2].body.content.as_json()
            add(prefix + ".prior.G.clock", g["clock"])
            clock = rig.read_stored(g["clock"])[2].body.content.as_json()
            add(prefix + ".prior.G.clock.source", clock["source"])
            previous = rig.read_stored(a["request"])[2].body
            for i, ref in enumerate(previous.inputs):
                add(f"{prefix}.Resolve(I(p))[{i}]", by_ref[ref])
            visit(a["request"], prefix + ".C(p)")

    visit(request, "q")
    return required


@pytest.mark.parametrize("prior", (False, True), ids=("initial_Q", "Q_with_prior"))
def test_paper_k1_host_declares_the_whole_paper_closure(make_rig, prior):
    """Paper:2784-2794,3615,3657 (K1, constructing C as well as checking it).

    Bug: the producer omits a typed dependency which its own U also overlooks.
    The expected set comes from paper fields, without copying declared I.
    """
    rig = make_rig()
    work, _a, _ = direct_first(rig)
    if prior:
        rig.claim(2)
        work, _a = rig.adopt(2)
    required = paper_required_input_points(rig, work.request)
    declared = set(rig.read_stored(work.request)[2].body.inputs)
    missing = [(sorted(labels), point) for point, labels in required.items()
               if rig.read_stored(point)[2].id not in declared]
    assert not missing, missing


@pytest.mark.parametrize("prior", (False, True), ids=("initial_Q", "Q_with_prior"))
def test_paper_k1_every_required_input_is_individually_required(make_rig, prior):
    """Paper:2784-2794,3601,3615,3657 (K1).

    Bug: omit any one typed Local/History/previous-I dependency from closure.
    The paper-derived table includes every field even when several resolve to
    one Point; each distinct required Ref is removed alone, with bytes/view/EW
    untouched. Fill paper-required I refs missing from the producer before
    making the legal control; a separate test checks that producer itself.
    Test both public U and the evaluation head, rebinding independent witnesses.
    """
    rig = make_rig()
    first, adopted, _ = direct_first(rig)
    first_adoption = adopted
    work = first
    if prior:
        rig.claim(2)
        work, adopted = rig.adopt(2)
    evidence = current_evidence(rig)
    request = work.request
    if prior:
        # Make the *previous* Q legal too, before testing just one missing Ref
        # in this Q. Otherwise a prior producer omission could reject first.
        first_required = paper_required_input_points(rig, first.request)
        first_i = set(rig.read_stored(first.request)[2].body.inputs)
        first_extra = tuple(p for p in first_required if rig.read_stored(p)[2].id not in first_i)
        request, _head, _result, mapping = copied_chain_with_previous_request(
            rig, first, first_adoption, work, None, first_extra_inputs=first_extra)
        evidence = replace_evidence_points(evidence, mapping)
    required = paper_required_input_points(rig, request)
    original = tuple(rig.read_stored(request)[2].body.inputs)
    previous = rig.read_stored(request)[2].body.content.as_json()["desc"]["args"]["prior"]
    missing_refs = {rig.read_stored(p)[2].id for p in required} - set(original)
    original += tuple(sorted(missing_refs, key=str))
    complete = save_copy(rig, request, inputs=original)
    baseline = direct_update(rig, complete, evidence)
    assert isinstance(baseline, u.IssuedUpdate) and plain(baseline.result) == (SECOND if prior else FIRST)
    head, result, mapping = copy_adoption_for_request(rig, work, adopted, complete,
                                                    previous=previous)
    prepared = prepare_adoption(rig, head, result,
        evidence=replace_evidence_points(evidence, mapping))
    assert isinstance(prepared.value, f.FProblem)
    assert prepared.value.K.belief == rig.read_stored(result)[2].id
    failures = []
    for point, labels in sorted(required.items()):
        ref = rig.read_stored(point)[2].id
        assert original.count(ref) == 1, (sorted(labels), point, "legal I must include paper C")
        inputs = tuple(r for r in original if r != ref)
        assert len(inputs) == len(original) - 1 and set(original) - set(inputs) == {ref}
        q = save_copy(rig, request, inputs=inputs)
        ret = direct_update(rig, q, evidence)
        if not (isinstance(ret, u.Rejected) and any(i.code == "unresolved_reference" for i in ret.issues)):
            failures.append(("U", sorted(labels), point, type(ret).__name__))
        head, result, mapping = copy_adoption_for_request(rig, work, adopted, q,
                                                        previous=previous)
        try:
            prepared = prepare_adoption(rig, head, result,
                evidence=replace_evidence_points(evidence, mapping))
        except f.FInputError as error:
            if error.reason != "unresolved_reference":
                failures.append(("prepare", sorted(labels), point, error.reason))
        else:
            failures.append(("prepare", sorted(labels), point, type(prepared.value).__name__))
    assert not failures, {"required_points": len(required), "paths": ("U", "prepare"),
                          "failures": failures}


@pytest.mark.parametrize("declared", (False, True), ids=("X_not_in_I", "X_in_I"))
def test_paper_k1_extra_input_point_needs_its_own_declared_ref(make_rig, declared):
    """Paper:3601,3615,3643,3657 (K1/R02-R4).

    Bug: ignore Desc.input_points because X has no numerical meaning.
    A real Prediction is in the keyed image and input_points in both cases;
    only its otherwise valid I reference is absent in the negative.
    """
    rig = make_rig()
    work, _a, evidence = direct_first(rig)
    x = save_copy(rig, rig.model_point)
    desc = replace(work.desc, input_points=work.desc.input_points | {x},
        numerical_view=fixed_view(rig, set(work.desc.numerical_view.boundary) | {x}))
    original = rig.read_stored(work.request)[2].body.inputs
    ref = rig.read_stored(x)[2].id
    assert ref not in original
    q = save_request(rig, work, desc=desc, inputs=tuple(original) + ((ref,) if declared else ()))
    ret = direct_update(rig, q, evidence)
    if declared:
        assert isinstance(ret, u.IssuedUpdate) and plain(ret.result) == FIRST
    else:
        assert isinstance(ret, u.Rejected) and any(i.code == "unresolved_reference" for i in ret.issues)


@pytest.mark.parametrize("mode", ("equal", "unknown", "failure"))
def test_paper_k2_continuation_draw_entry_checks_posted_unaccepted_cg_terminal(make_rig, mode):
    """Paper:3580-3592,3641,3658 (K2/R01-R4a).

    Bug: check only accepted Wg reports when continuation D enters. The real
    launched D callback calls ctx.enter after Post, with no Accept or settle
    between them; equal success and Unknown still consume exactly one draw.
    """
    rig = make_rig(continuation=True)
    first_claim(rig)
    work, a = rig.adopt()
    rig.run_stage("evaluation_prepare")
    d, callback = rig.callback("selection_draw")
    assert len(rig.requests("selection_draw")) == 2
    assert d.value["desc"]["work_id"] not in {w.desc.work_id for w in rig.workers.entries}
    wg = next(w for w in rig.workers.entries if w.desc.purpose == "candidate_generation")
    ctx = rig.workers.contexts["candidate_generation"]
    original = next(event for event, _ in rig.workers.sent
                    if isinstance(event, fb.WorkFinished) and event.work == wg.desc.work_id
                    and isinstance(event.outcome, fb.WorkOutputs))
    if mode == "failure":
        event = replace(original, outcome=fb.WorkFailure(failure=fb.FailureInfo(
            failure_kind="candidate-generation-failed", content={"certain": True}, readings=(), basis=())))
    elif mode == "unknown":
        event = replace(original, outcome=fb.WorkUnknown(unknown=fb.UnknownInfo(reason="unknown", basis=())))
    else:
        event = original
    consumed = []
    def draw(draw_work, draw_ctx):
        consumed.append(draw_work.desc.work_id)
        reply, issued = rig.workers.normal(draw_work, draw_ctx)
        rig.workers.post(draw_ctx, reply, issued)
    rig.workers.overrides["selection_draw"] = draw
    before = {r.envelope for r in rig.host.window.status().receipts}
    rig.workers.post(ctx, event)
    posted = [r for r in rig.host.window.status().receipts if r.envelope not in before]
    assert len(posted) == 1 and posted[0].state == "received", "must still be before Accept"
    callback()
    expected_entry = mode != "failure"
    assert (d.value["desc"]["work_id"], expected_entry) in rig.workers.entry_attempts
    assert consumed == ([d.value["desc"]["work_id"]] if expected_entry else [])
    if expected_entry:
        rig.drive(lambda: len(rig.facts(c.DRAW_REPORT)) == 2)
        rig.run_stage("evaluation")
        rig.drive(lambda: len(rig.facts(c.SELECTION)) == 2)
        assert rig.workers.prepared_by_request[rig.requests("evaluation_prepare")[-1].cid].value.K.belief == result_for(rig, work.request).record_id
    else:
        rig.drive(lambda: any(r.value == wire(event) for r in rig.facts(c.WORK_REPORT)))
        rig.settle_steps(12)
        assert len(rig.facts(c.DRAW_REPORT)) == len(rig.facts(c.SELECTION)) == 1
        assert len([w for w in rig.workers.entries if w.desc.purpose == "evaluation"]) == 1
    assert [x.cid for x in rig.facts(c.BELIEF_ADOPTED)] == [a.cid]


@pytest.mark.parametrize("change", ("legal", "execution", "entered", "report", "acquisition", "late_acquisition"))
def test_paper_k3_previous_result_requires_each_independent_observation(make_rig, change):
    """Paper:2094-2103,2874-2880,3610-3611,3651,3659 (K3).

    Bug: trust saved Q/R/G/A for a prior result when one EW/EH/EA witness is
    missing or late. Only the selected independent observation changes; all
    saved bytes remain identical. The complete witness succeeds at both U
    and the evaluation's head A2 before each negative is tried.
    Classification (fb_rules.md:1696,1701-1702; paper:2094,3617): a present EW
    row with entered=0 is a confirmed non-entry, hence
    rejected (proof_mismatch) at U and a typed FInputError at the head; only a
    missing observation is insufficient. A late EA is also a confirmed mismatch;
    this older case breaks both before-use and before-adoption order, so it
    does not isolate ORDER's code. rule15's early_use changes only the use time.
    """
    rig = make_rig()
    first, a1, _ = direct_first(rig)
    rig.claim(2)
    second, a2 = rig.adopt(2)
    r1, r2 = result_for(rig, first.request), result_for(rig, second.request)
    reader, kwargs = adoption_prepare_inputs(rig, a2.cid, r2.cid)
    evidence = current_evidence(rig)
    assert isinstance(direct_update(rig, second.request, evidence), u.IssuedUpdate)
    control = u.prepare_fb_from_facts(reader, evidence=evidence, **kwargs)
    assert isinstance(control.value, f.FProblem) and control.value.K.belief == r2.record_id
    before = rig.storage_snapshot()
    row = next(x for x in evidence.executions if x.work_id == first.desc.work_id)
    raw = next(ref for ref in rig.read_stored(r1.cid)[2].body.basis if ref != rig.read_stored(first.request)[2].id)
    raw_point = next(e.cid for e in reader.entries() if rig.read_stored(e.cid)[2].id == raw)
    assert any(r.point == raw_point for r in row.reports) and row.entered == 1
    g = rig.by_cid(ACQUIRED, a1.value["acquisition"])
    acquired_ns = rig.read_stored(g.value["clock"])[2].body.content.as_json()["reading"]["time_ns"]
    acquired = [x for x in evidence.acquisitions if x.origin == a1.value["origin"]
                and r1.cid in x.contents and x.acquired_ns == acquired_ns]
    assert len(acquired) == 1
    used_ns = min(x.used_ns for x in evidence.uses if x.work_id == second.desc.work_id and x.point == r1.cid)
    changed = evidence
    if change == "execution":
        changed = replace(evidence, executions=tuple(x for x in evidence.executions if x != row))
    elif change in ("entered", "report"):
        new_row = (replace(row, entered=0) if change == "entered" else
                   replace(row, reports=tuple(r for r in row.reports if r.point != raw_point)))
        changed = replace(evidence, executions=tuple(new_row if x == row else x for x in evidence.executions))
    elif change in ("acquisition", "late_acquisition"):
        changed = replace(evidence, acquisitions=tuple(
            replace(x, acquired_ns=used_ns + 1) if x == acquired[0] and change == "late_acquisition" else x
            for x in evidence.acquisitions if change != "acquisition" or x != acquired[0]))
    assert changed.uses == evidence.uses and changed.intervals == evidence.intervals
    if change in ("execution", "entered", "report"):
        assert changed.acquisitions == evidence.acquisitions
    else:
        assert changed.executions == evidence.executions
    ret = direct_update(rig, second.request, changed)
    if change in ("entered", "late_acquisition"):
        # A4: known non-entry/inversion is mismatch, not MISSING. Late EA also
        # violates ADOPTION_TIMES; don't assert ORDER was the first failure.
        assert isinstance(ret, u.Rejected) and ret.issues
        if change == "entered":
            assert any(i.code == "proof_mismatch" for i in ret.issues)
        with pytest.raises(f.FInputError, match="proof_mismatch" if change == "entered" else None):
            u.prepare_fb_from_facts(reader, evidence=changed, **kwargs)
        assert rig.storage_snapshot() == before
        return
    prepared = u.prepare_fb_from_facts(reader, evidence=changed, **kwargs)
    assert rig.storage_snapshot() == before
    if change == "legal":
        assert isinstance(ret, u.IssuedUpdate) and plain(ret.result) == SECOND
        assert isinstance(prepared.value, f.FProblem) and prepared.value.K.belief == r2.record_id
    else:
        assert isinstance(ret, u.Insufficient) and any(i.code == "prerequisite_unavailable" for i in ret.issues)
        assert_incomplete_preparation(prepared, "prerequisite_unavailable")


def test_paper_k4_outside_event_does_not_change_adopted_preparation_value(make_rig):
    """Paper:1082,3580,3645,3660 (K4/SCOPE-R5); F-a A-02/A-03/E-06.

    Bug: resolve scoped Refs by scanning outside the fixed roots. Add exactly
    one unrelated Received to the reader, keeping roots/target/evidence fixed;
    the claim stays equal (the whole-reader environment key may change).
    """
    rig = make_rig()
    work, a, _ = direct_first(rig)
    r = result_for(rig, work.request)
    reader, kwargs = adoption_prepare_inputs(rig, a.cid, r.cid)
    evidence = current_evidence(rig)
    old = u.prepare_fb_from_facts(reader, evidence=evidence, **kwargs)
    old_received = {x.cid for x in rig.facts(c.RECEIVED)}
    rig.host.post(received())
    rig.drive(lambda: len(rig.facts(c.RECEIVED)) == len(old_received) + 1)
    extra = next(x.cid for x in rig.facts(c.RECEIVED) if x.cid not in old_received)
    points = {e.cid for e in reader.entries()}
    assert extra not in closure(rig, kwargs["fixed_parents"]) and extra not in points
    wider = PublicReader(rig.ledger, points=points | {extra})
    new = u.prepare_fb_from_facts(wider, evidence=evidence, **kwargs)
    assert isinstance(old.value, f.FProblem) and isinstance(new.value, f.FProblem)
    assert old.value.K.belief == new.value.K.belief == r.record_id
    assert plain(old.value) == plain(new.value)
    before_json, after_json = json.loads(old.canonical_bytes), json.loads(new.canonical_bytes)
    before_json["environment"].pop("reader_view_key")
    after_json["environment"].pop("reader_view_key")
    assert before_json == after_json


@pytest.mark.parametrize("observed", (False, True), ids=("saved_without_EH", "actual_mouth_EH"))
@pytest.mark.parametrize("conflict", (False, True), ids=("same_content", "different_content"))
def test_paper_k5_related_saved_report_needs_independent_provenance(make_rig, observed, conflict):
    """Paper:3580,3618,3642,3661 (K5/R01-R4b).

    Bug: build candidate deliveries only from EH and silently ignore a relevant
    saved report whose provenance is unknown. Equal and different unknown
    reports are both shortages; EH distinguishes equality from use_conflict.
    """
    rig = make_rig()
    work, a, _ = direct_first(rig)
    r = result_for(rig, work.request)
    baseline = prepare_adoption(rig, a.cid, r.cid)
    assert isinstance(baseline.value, f.FProblem) and baseline.value.K.belief == r.record_id
    old = {x.cid for x in rig.facts(c.SEGMENT_REPORT)}
    evidence = current_evidence(rig)
    if observed:
        event = deliver_first_claim_again(rig, conflict=conflict)
        rig.drive(lambda: any(x.cid not in old and x.value == wire(event) for x in rig.facts(c.SEGMENT_REPORT)))
        extra = next(x.cid for x in rig.facts(c.SEGMENT_REPORT) if x.cid not in old and x.value == wire(event))
        evidence = current_evidence(rig)
    else:
        b = rig.by_cid(c.SEGMENT_BINDING, work.desc.args.observations[0].binding)
        raw = rig.by_cid(c.SEGMENT_REPORT, b.value["report"])
        value = json.loads(json.dumps(raw.value))
        if conflict:
            value["item"]["value"]["kind"] = "count_exactly_one"
            value["item"]["value"]["contract"] = plain(c.COUNT_EXACTLY_ONE)
        extra = save_copy(rig, raw.cid, value=value, parents=())
    assert any(r.point == extra for x in evidence.executions for r in x.reports) == observed
    prepared = prepare_adoption(rig, a.cid, r.cid, additional_roots=(extra,), evidence=evidence)
    if not observed:
        assert_incomplete_preparation(prepared, "prerequisite_unavailable")
    elif conflict:
        assert_incomplete_preparation(prepared, "use_conflict")
    else:
        assert isinstance(prepared.value, f.FProblem) and prepared.value.K.belief == r.record_id


@pytest.mark.parametrize("api", (ff.restore_f_math_result, ff.verify_f_math_result),
                         ids=("restore", "verify"))
def test_paper_k6_replaying_valid_adopted_artifact_is_unavailable_not_mismatch(make_rig, api):
    """Paper:3617,3635,3646,3662 (K6/A4/DIAG-R5).

    Bug: classify loss of non-serialized independent observations as a false
    numerical proof. Valid A*-free bytes replay; equally valid adopted bytes
    with the same reader/registry/budget fail specifically as unavailable.
    """
    rig = make_rig()
    work, a, _ = direct_first(rig)
    initial = rig.workers.prepares[0][0]
    old_reader = rig.workers.prepares[0][1]
    old = rig.workers.prepared_by_request[initial.request]
    assert isinstance(old.value, f.FProblem)
    assert api(old.canonical_bytes, reader=old_reader, registry=rig.registry,
               budget=initial.desc.args.budget) is not None
    r = result_for(rig, work.request)
    reader, kwargs = adoption_prepare_inputs(rig, a.cid, r.cid)
    prepared = u.prepare_fb_from_facts(reader, evidence=current_evidence(rig), **kwargs)
    assert isinstance(prepared.value, f.FProblem) and prepared.value.K.belief == r.record_id
    with pytest.raises(f.FReplayUnavailable) as error:
        api(prepared.canonical_bytes, reader=reader, registry=rig.registry, budget=kwargs["budget"])
    assert error.value.reason == "prerequisite_unavailable"


def table_post(rig, ctx, event, issued=None):
    """Actual retained public mouth, accepted and saved before returning its Point."""
    ref = c.SEGMENT_REPORT if isinstance(event, fb.SegmentReport) else c.WORK_REPORT
    if isinstance(event, fb.DrawReturned):
        ref = c.DRAW_REPORT
    before = {r.cid for r in rig.facts(ref)}
    accept_posted(rig, event, lambda: rig.workers.post(ctx, event, issued))
    rig.drive(lambda: any(r.cid not in before and r.value == wire(event) for r in rig.facts(ref)))
    return next(r.cid for r in rig.facts(ref) if r.cid not in before and r.value == wire(event))


def table_two_mouths(rig):
    """Two real Boot routes and entered measurement mouths; no synthetic EW."""
    contexts = {}
    def measure(work, ctx):
        contexts[work.request] = ctx
        rig.workers.normal(work, ctx)
    rig.workers.overrides["measure_segment"] = measure
    rig.initial_evaluation()
    route = next(r.cid for r in rig.facts(ROUTE) if r.value["config"]["route_epoch"] == "route-A")
    qs = rig.requests("measure_segment")
    first_index = next(i for i, q in enumerate(qs) if q.value["desc"]["args"]["route"] == route)
    first_k = rig.start_measurement(first_index)
    rig.drive(lambda: first_k.cid in contexts)
    rig.claim()
    work, a = rig.adopt()
    rig.workers.threads.append(rig.thread)
    second_k = rig.start_measurement(1 - first_index)
    rig.drive(lambda: second_k.cid in contexts and any(r.value["segment"] == second_k.cid
        and r.value["item"]["kind"] == "started" for r in rig.facts(c.SEGMENT_REPORT)))
    assert first_k.cid != second_k.cid
    return work, a, first_k, second_k, contexts


def table_assert_rejected(call, reason=None):
    """Public U: a typed input exception or Rejected is a definitive mismatch."""
    try:
        ret = call()
    except f.FInputError as error:
        assert error.reason == reason if reason else bool(error.reason)
        return
    assert isinstance(ret, u.Rejected), (type(ret).__name__, getattr(ret, "issues", ()))
    assert ret.issues and (reason is None or any(i.code == reason for i in ret.issues))


@pytest.mark.parametrize("path", ("current", "previous", "head"))
@pytest.mark.parametrize("field", ("applied", "started", "ended"))
@pytest.mark.parametrize("bad", (False, True), ids=("legal", "other_target"))
def test_v032_generation_reference_is_the_right_event_not_just_an_existing_point(make_rig, path, field, bad):
    """T-A1 A1-GENERATION-APPLIED:4475, A1-GENERATION-STARTED:4476, A1-GENERATION-ENDED:4477;
    T-REF REF-B-APPLIED:3913, REF-B-STARTED:3914, REF-B-ENDED:3915;
    T-A2 A2-B-APPLIED:4312, A2-B-STARTED:4313, A2-B-ENDED:4314.
    期待: 合法 / 不適合（今のU・前のQ・評価の頭）。
    Bug: authenticate existence/contract but not the reference's actual target.
    Ended's legal branch is null (bootstrap does not require it); the negative
    is a real Ended from a different entered k, present in EH and in the image.
    """
    if field == "ended":
        rig = make_rig(second_route=True)
        first, a1, first_k, other_k, contexts = table_two_mouths(rig)
        other_work = next(w for w in rig.workers.entries if w.request == other_k.cid)
        event = fb.SegmentReport(segment=other_k.cid, item_slot="other-ended",
            item=fb.SegmentBoundary(kind="ended", work=other_work.desc.work_id,
                reading=rig.actual_reading(), reason="other actual mouth", evidence=()))
        target = table_post(rig, contexts[other_k.cid], event)
        measure_ctx = contexts[first_k.cid]
    else:
        rig = make_rig()
        first, a1, _ = direct_first(rig)
        measure_ctx = rig.workers.contexts["measure_segment"]
        b = rig.by_cid(c.SEGMENT_BINDING, first.desc.args.observations[0].binding)
        target = save_copy(rig, b.value["route"]) if field == "applied" else b.value["report"]
    binding = rig.by_cid(c.SEGMENT_BINDING, first.desc.args.observations[0].binding)
    value = json.loads(json.dumps(binding.value))
    assert field != "ended" or value["generation"][field] is None
    if bad:
        value["generation"][field] = target
    assert {k for k in value if value[k] != binding.value[k]} == ({"generation"} if bad else set())
    bcopy = save_copy(rig, binding.cid, value=value,
        parents=front(rig, set(binding.parents) | events_for(rig, {target})))
    mapping = {binding.cid: bcopy}
    q1 = rebind_request_inputs(rig, first, mapping, extra=(target,))
    if path == "current":
        call = lambda: direct_update(rig, q1, replace_evidence_points(current_evidence(rig), mapping))
        if bad:
            table_assert_rejected(call)
        else:
            ret = call()
            assert isinstance(ret, u.IssuedUpdate) and plain(ret.result) == FIRST
        return
    head, result, rest = copy_adoption_for_request(rig, first, a1, q1)
    mapping.update(rest)
    if path == "head":
        evidence = replace_evidence_points(current_evidence(rig), mapping)
        if bad:
            with pytest.raises(f.FInputError):
                prepare_adoption(rig, head, result, evidence=evidence)
        else:
            prepared = prepare_adoption(rig, head, result, evidence=evidence)
            assert isinstance(prepared.value, f.FProblem)
            assert prepared.value.K.belief == rig.read_stored(result)[2].id
        return
    rig.clock.set(3)
    event = fb.SegmentReport(segment=rig.read_stored(binding.cid)[2].body.content.as_json()["segment"],
        item_slot="claim-2", item=f.CoverageClaim(route_epoch="route-A", interval=f.MeasurementInterval(
            clock=rig.clock.run, start_ns=1, end_ns=3, closure="(start,end]"),
            kind="no_arrival", contract=c.NO_ARRIVAL, evidence=()))
    table_post(rig, measure_ctx, event)
    second, _ = rig.adopt(2)
    q2 = rebind_request_inputs(rig, second, mapping, prior=head, extra=(target,))
    evidence = replace_evidence_points(current_evidence(rig), mapping)
    if bad:
        table_assert_rejected(lambda: direct_update(rig, q2, evidence))
    else:
        ret = direct_update(rig, q2, evidence)
        assert isinstance(ret, u.IssuedUpdate) and plain(ret.result) == SECOND


@pytest.mark.parametrize("source", ("related", "unrelated", "unknown"))
def test_v032_provenance_excludes_a_confirmed_other_mouth_but_not_an_unknown_one(make_rig, source):
    """T-G6 G6-PROV-SEGMENT-RELATED:4444, G6-PROV-SEGMENT-UNRELATED:4445,
    G6-PROV-SEGMENT-UNKNOWN:4446; T-G4 G4-ITEM-CLAIM:4367;
    T-A1 A1-PROVENANCE-MISSING:4510. 期待: 使用の禁止 / 合法 / 不足。
    Bug: treat confirmed unrelated EH as missing, or treat unknown as unrelated.
    All three roots contain the identical conflicting Claim for the same key;
    only the independently observed mouth differs. Both mouths really entered.
    """
    rig = make_rig(second_route=True)
    work, a, k, other_k, contexts = table_two_mouths(rig)
    r = result_for(rig, work.request)
    event = fb.SegmentReport(segment=k.cid, item_slot="claim-1",
        item=f.CoverageClaim(route_epoch="route-A", interval=f.MeasurementInterval(
            clock=rig.clock.run, start_ns=0, end_ns=2, closure="(start,end]"),
            kind="count_exactly_one", contract=c.COUNT_EXACTLY_ONE, evidence=()))
    before = prepare_adoption(rig, a.cid, r.cid)
    assert isinstance(before.value, f.FProblem) and before.value.K.belief == r.record_id
    evidence = current_evidence(rig)
    if source == "unknown":
        b = rig.by_cid(c.SEGMENT_BINDING, work.desc.args.observations[0].binding)
        point = save_copy(rig, b.value["report"], value=wire(event), parents=())
    else:
        point = table_post(rig, contexts[k.cid if source == "related" else other_k.cid], event)
        evidence = current_evidence(rig)
        owner = next(w.desc.work_id for w in rig.workers.entries
                     if w.request == (k.cid if source == "related" else other_k.cid))
        assert any(x.work_id == owner and any(report.point == point for report in x.reports)
                   for x in evidence.executions)
    prepared = prepare_adoption(rig, a.cid, r.cid, additional_roots=(point,), evidence=evidence)
    if source == "unrelated":
        assert isinstance(prepared.value, f.FProblem) and prepared.value.K.belief == r.record_id
    else:
        assert_incomplete_preparation(prepared, "use_conflict" if source == "related" else "prerequisite_unavailable")


@pytest.mark.parametrize("branch", ("started_equal", "started", "ended", "route_applied"))
def test_v032_life_branch_is_part_of_the_key_but_slot_is_not(make_rig, branch):
    """T-G4 G4-LIFE-STARTED:4371, G4-LIFE-ENDED:4372, G4-LIFE-ROUTE-APPLIED:4373;
    T-REF REF-SEG-BOUNDARY-STARTED-SUBJECT:3948, REF-SEG-BOUNDARY-ENDED-SUBJECT:3955,
    REF-SEG-BOUNDARY-ROUTE-APPLIED-SUBJECT:3962. 期待: 異内容Startedは使用の禁止、他は合法。
    Bug: use one common LIFE key for all branches, or include item_slot in it.
    Q uses the original Started; a different Ended/Applied must not clash with
    it, while an altered Started in a different slot must prevent entry.
    """
    rig = make_rig()
    first_claim(rig)
    q, callback = rig.callback("belief_update")
    ctx = rig.workers.contexts["measure_segment"]
    mw = next(w for w in rig.workers.entries if w.desc.purpose == "measure_segment")
    if branch == "started_equal":
        item = next(e.item for e, _ in rig.workers.sent if isinstance(e, fb.SegmentReport)
            and isinstance(e.item, fb.SegmentBoundary) and e.item.kind == "started")
    elif branch == "route_applied":
        started = next(e for e, _ in rig.workers.sent if isinstance(e, fb.SegmentReport)
            and isinstance(e.item, fb.SegmentBoundary) and e.item.kind == "started")
        item = fb.RouteAppliedItem(config=mw.desc.args.route, reading=started.item.reading,
                                   reason="actual application report", evidence=())
    else:
        item = fb.SegmentBoundary(kind=branch, work=mw.desc.work_id, reading=rig.actual_reading(),
                                  reason="later lifecycle report", evidence=())
    event = fb.SegmentReport(segment=mw.request, item_slot="different-life-slot", item=item)
    table_post(rig, ctx, event)
    callback()
    assert (q.value["desc"]["work_id"], branch != "started") in rig.workers.entry_attempts, (
        branch, rig.workers.entry_attempts[-1],
        [(p.kind, p.reason) for p in rig.host.window.status().pending])
    rig.drive(lambda: any(r.value == wire(event) for r in rig.facts(c.SEGMENT_REPORT)))
    if branch == "started":
        rig.settle_steps(8)
        assert_no_adoption(rig, q.cid)
    else:
        rig.drive(lambda: bool(rig.facts(c.BELIEF_ADOPTED)))
        assert result_for(rig, q.cid).value["result"] == FIRST


@pytest.mark.parametrize("branch", ("claim", "gap", "measurement_unavailable", "coverage_unproved"))
def test_v032_all_item_branches_share_the_same_family_before_settle(make_rig, branch):
    """T-G4 G4-ITEM-CLAIM:4367, G4-ITEM-GAP:4368,
    G4-ITEM-MEASUREMENT-UNAVAILABLE:4369, G4-ITEM-COVERAGE-UNPROVED:4370;
    T-REF REF-SEG-CLAIM-CLAIM/GAP/MEASUREMENT-UNAVAILABLE/COVERAGE-UNPROVED-*:3926-3943.
    期待: 同内容Claimは合法、兄弟枝はsettle前から使用の禁止。
    Bug: namespace item keys by branch. Accept and invoke entry immediately,
    so later binding reconstruction cannot be the guard that rejects first.
    """
    rig = make_rig()
    first_claim(rig)
    q, callback = rig.callback("belief_update")
    original = next(e for e, _ in rig.workers.sent if isinstance(e, fb.SegmentReport) and e.item_slot == "claim-1")
    interval = original.item.interval
    item = {"claim": original.item,
        "gap": f.Gap(route_epoch="route-A", sequence_range=(0, 1), interval=interval, reason="lost", evidence=()),
        "measurement_unavailable": f.MeasurementUnavailable(route_epoch="route-A", requested_interval=interval,
                                                           reason="unavailable", evidence=()),
        "coverage_unproved": f.CoverageUnproved(route_epoch="route-A", interval=interval,
                                               missing_contracts=(c.BOOTSTRAP_GENERATION,), evidence=())}[branch]
    event = replace(original, item=item)
    ctx = rig.workers.contexts["measure_segment"]
    accept_posted(rig, event, lambda: rig.workers.post(ctx, event))
    callback()
    assert (q.value["desc"]["work_id"], branch == "claim") in rig.workers.entry_attempts
    rig.drive(lambda: any(r.value == wire(event) for r in rig.facts(c.SEGMENT_REPORT)))
    if branch == "claim":
        rig.drive(lambda: bool(rig.facts(c.BELIEF_ADOPTED)))
        assert result_for(rig, q.cid).value["result"] == FIRST
    else:
        rig.settle_steps(8)
        assert_no_adoption(rig, q.cid)


@pytest.mark.parametrize("path", ("current", "previous", "head"))
@pytest.mark.parametrize("field", ("stage_slot", "trigger", "permissions", "observations"))
@pytest.mark.parametrize("bad", (False, True), ids=("legal", "wrong_type"))
def test_v032_desc_shape_is_checked_at_every_authentication_stage(make_rig, path, field, bad):
    """T-A1 A1-SHAPE:4456, A1-CLASS-MISMATCH:4507.
    期待: 合法 / 不適合(shape)（今のU・前のQ・評価の頭）。
    Bug: authenticate the current typed DTO, but trust a saved untyped field
    when recursively reading a prior request or the evaluation's head.
    """
    rig = make_rig()
    work, adopted, _ = direct_first(rig)
    value = {"desc": wire(work.desc)}
    if bad:
        if field == "observations":
            value["desc"]["args"][field] = {}
        else:
            value["desc"][field] = 37 if field == "stage_slot" else {"wrong": "container"}
    q = save_copy(rig, work.request, value=value)
    if path == "current":
        call = lambda: direct_update(rig, q, current_evidence(rig))
        if bad:
            table_assert_rejected(call, "shape")
        else:
            ret = call()
            assert isinstance(ret, u.IssuedUpdate) and plain(ret.result) == FIRST
        return
    head, result, mapping = copy_adoption_for_request(rig, work, adopted, q)
    if path == "head":
        evidence = replace_evidence_points(current_evidence(rig), mapping)
        if bad:
            with pytest.raises(f.FInputError) as error:
                prepare_adoption(rig, head, result, evidence=evidence)
            assert error.value.reason == "shape"
        else:
            prepared = prepare_adoption(rig, head, result, evidence=evidence)
            assert isinstance(prepared.value, f.FProblem)
            assert prepared.value.K.belief == rig.read_stored(result)[2].id
        return
    rig.claim(2)
    second, _ = rig.adopt(2)
    q2 = rebind_request_inputs(rig, second, mapping, prior=head)
    evidence = replace_evidence_points(current_evidence(rig), mapping)
    if bad:
        table_assert_rejected(lambda: direct_update(rig, q2, evidence), "shape")
    else:
        ret = direct_update(rig, q2, evidence)
        assert isinstance(ret, u.IssuedUpdate) and plain(ret.result) == SECOND


@pytest.mark.parametrize("depth", (2, 3))
@pytest.mark.parametrize("path", ("next_U", "head"))
@pytest.mark.parametrize("timing", ("legal", "after_adoption", "before_generation"))
def test_v032_history_acquisition_is_bounded_by_its_own_adoption_not_only_later_use(make_rig, depth, path, timing):
    """T-A1 A1-HISTORY-ACQUIRE-BEFORE-ADOPT:4494, A1-HISTORY-ACQUIRE-BEFORE-USE:4495;
    A1-HISTORY-ACQUIRE-MISSING:4493, A1-CLASS-INSUFFICIENT:4506, A1-CLASS-MISMATCH:4507.
    v0.35 正本 fb_rules.md:1701 GENERATED/ACQUIRED: Gと同じorigin/contents
    のEAは存在し、既知の時刻逆転は不適合。観測欠落の不足とは分ける。
    期待: 合法 / 不適合 / 不適合。
    Bug: accept any R1 acquisition before Wu2 use, even after A1 itself, or
    classify an observed acquisition before generation as mere missing proof.
    The saved Q/R/G/A bytes, origins, contents and use times do not change.
    Round 16: after_adoption remains a mismatch expectation. The handoff
    described a handwritten path treating it as missing proof pending row
    migration; that reported status does not change the oracle.
    """
    rig = make_rig()
    first, a1, _ = direct_first(rig)
    r1 = result_for(rig, first.request)
    rig.claim(2)
    second, last_a = rig.adopt(2)
    if depth == 3:
        rig.claim(3, interval=f.MeasurementInterval(clock=rig.clock.run,
            start_ns=0, end_ns=1, closure="(start,end]"), now=3)
        second, last_a = rig.adopt(3)
    evidence = current_evidence(rig)
    selected = [x for x in evidence.acquisitions if x.origin == first.desc.reader and r1.cid in x.contents]
    assert selected and min(x.acquired_ns for x in selected) == 2
    consumer_use = min(x.used_ns for x in evidence.uses
                      if x.work_id == second.desc.work_id and x.point == r1.cid)
    assert a1.at_ns == 2 < consumer_use
    acquired_ns = 2 if timing == "legal" else (consumer_use if timing == "after_adoption" else 1)
    changed = replace(evidence, acquisitions=tuple(
        replace(x, acquired_ns=acquired_ns) if x in selected else x for x in evidence.acquisitions))
    assert changed.executions == evidence.executions and changed.uses == evidence.uses
    assert [x.contents for x in changed.acquisitions] == [x.contents for x in evidence.acquisitions]
    if path == "next_U":
        if timing != "legal":
            table_assert_rejected(lambda: direct_update(rig, second.request, changed))
        else:
            ret = direct_update(rig, second.request, changed)
            assert isinstance(ret, u.IssuedUpdate) and plain(ret.result) == SECOND
    elif timing != "legal":
        with pytest.raises(f.FInputError):
            prepare_adoption(rig, last_a.cid, last_a.value["result"], evidence=changed)
    else:
        prepared = prepare_adoption(rig, last_a.cid, last_a.value["result"], evidence=changed)
        assert isinstance(prepared.value, f.FProblem)
        assert prepared.value.K.belief == result_for(rig, second.request).record_id


@pytest.mark.parametrize("bad", (False, True), ids=("null_extends", "unsupported_extends"))
def test_v032_saved_extends_is_unsupported_rather_than_silently_ignored(make_rig, bad):
    """T-REF REF-LAW-EXTENDS:4031, REF-LAW-EXTENDS-NULL:4032; T-A2 A2-LAW-EXTENDS:4328.
    期待: 合法 / 不適合(missing_contract)、保存済みの記録は保持。
    Bug: drop the unsupported non-null branch instead of refusing its use.
    The parent law exists and has the same valid law contract; no missing-body
    or malformed-law guard can substitute for the unsupported reference rule.
    """
    rig = make_rig()
    work, _a, evidence = direct_first(rig)
    law = rig.one(c.FINITE_JOINT_COUNT_LAW)
    reading = rig.by_cid(c.OBSERVATION_PLAN_2, work.desc.args.observations[0].reading)
    lv = dict(law.value, extends=law.cid if bad else None)
    new_law = save_copy(rig, law.cid, value=lv)
    rv = json.loads(json.dumps(reading.value))
    rv["projection"]["args"]["claims"][0]["law"] = new_law
    new_reading = save_copy(rig, reading.cid, value=rv,
        basis=tuple(rig.read_stored(new_law)[2].id if x == law.record_id else x
                    for x in rig.read_stored(reading.cid)[2].body.basis))
    mapping = {reading.cid: new_reading}
    q = rebind_request_inputs(rig, work, mapping, extra=(new_law,))
    snapshot = rig.storage_snapshot()
    call = lambda: direct_update(rig, q, replace_evidence_points(evidence, {**mapping, law.cid: new_law}))
    if bad:
        table_assert_rejected(call, "missing_contract")
    else:
        ret = call()
        assert isinstance(ret, u.IssuedUpdate) and plain(ret.result) == FIRST
    assert rig.storage_snapshot() == snapshot


@pytest.mark.parametrize("operation", ("EQ_entry", "D_entry", "Ee_entry"))
@pytest.mark.parametrize("conflict", (False, True), ids=("same_terminal", "different_terminal"))
def test_v032_each_continuation_entry_starts_from_its_own_used_records(make_rig, operation, conflict):
    """T-G6 G6-EP-ENTER:4418, G6-D-ENTER:4421, G6-EE-ENTER:4424;
    T-REF REF-PR-REPORT:4122, REF-EE-DRAW:3901; T-G4 G4-DRAW-REPORT:4395.
    期待: 合法 / 入場前から使用の禁止。両例ともPost済み・未Accept。
    Bug: gate A*/CG alone and omit EQ/PR/DF's own terminal dependencies.
    """
    rig = make_rig(continuation=True)
    first_claim(rig)
    first, a = rig.adopt()
    if operation == "EQ_entry":
        stage = "evaluation_prepare"
        owner = next(w for w in rig.workers.entries if w.desc.purpose == "candidate_generation")
        ctx = rig.workers.contexts["candidate_generation"]
    else:
        ep = rig.run_stage("evaluation_prepare")
        if operation == "D_entry":
            stage, owner, ctx = "selection_draw", ep, rig.workers.contexts["evaluation_prepare"]
        else:
            draw = rig.run_stage("selection_draw")
            stage, owner, ctx = "evaluation", draw, rig.workers.contexts["selection_draw"]
    q, callback = rig.callback(stage)
    original = next(event for event, _issue in rig.workers.sent
                    if isinstance(event, (fb.WorkFinished, fb.DrawReturned))
                    and event.work == owner.desc.work_id)
    if conflict and isinstance(original, fb.DrawReturned):
        event = replace(original, outcome=fb.DrawValue(value={"u": [3, 4]}))
    elif conflict:
        event = replace(original, outcome=fb.WorkFailure(failure=fb.FailureInfo(
            failure_kind="definitive-late-failure", content={"certain": True}, readings=(), basis=())))
    else:
        event = original
    issued = (rig.workers.issued.get("evaluation_prepare")
              if operation == "D_entry" and not conflict else None)
    before = {r.envelope for r in rig.host.window.status().receipts}
    rig.workers.post(ctx, event, issued)
    pending = [r for r in rig.host.window.status().receipts if r.envelope not in before]
    assert len(pending) == 1 and pending[0].state == "received"
    callback()
    assert (q.value["desc"]["work_id"], not conflict) in rig.workers.entry_attempts
    if conflict:
        rig.settle_steps(10)
        assert not any(w.request == q.cid for w in rig.workers.entries)
        assert len(rig.facts(c.SELECTION)) == 1
    else:
        raw = c.DRAW_REPORT if stage == "selection_draw" else c.WORK_REPORT
        rig.drive(lambda: any(r.value["work"] == q.value["desc"]["work_id"] for r in rig.facts(raw)))
        if stage == "evaluation_prepare":
            rig.run_stage("selection_draw")
        if stage != "evaluation":
            rig.run_stage("evaluation")
        rig.drive(lambda: len(rig.facts(c.SELECTION)) == 2)
        assert rig.facts(c.BELIEF_ADOPTED)[0].cid == a.cid
        eq = rig.requests("evaluation_prepare")[-1]
        assert rig.workers.prepared_by_request[eq.cid].value.K.belief == result_for(rig, first.request).record_id


@pytest.mark.parametrize("index", (0, 1), ids=("first_binding", "second_binding"))
@pytest.mark.parametrize("missing", (False, True), ids=("complete_I", "one_missing_ref"))
def test_v032_each_observation_array_element_requires_its_own_binding(make_rig, index, missing):
    """T-A2 A2-OBSERVATION-BINDING:4307; T-REF REF-Q-BINDING:3769;
    T-A1 A1-C:4471. 期待: 合法 / 不適合(unresolved_reference)。
    Bug: expand only the first or last element of observations. Put both CE1
    Claims in one Q with prior=null and remove B from input_points in BOTH
    variants: only observations[index].binding can require that Ref in I.
    Head/predecessor paths for the two-element array remain unverified here.
    """
    rig = make_rig()
    first, _a, _ = direct_first(rig)
    rig.claim(2)
    second, _ = rig.adopt(2)
    observations = (first.desc.args.observations[0], second.desc.args.observations[0])
    bindings = {o.binding for o in observations}
    desc = replace(second.desc, args=replace(second.desc.args, prior=None, observations=observations),
                   input_points=second.desc.input_points - bindings)
    ref = rig.read_stored(observations[index].binding)[2].id
    inputs = rig.read_stored(second.request)[2].body.inputs
    assert inputs.count(ref) == 1
    q = save_request(rig, second, desc=desc,
        inputs=tuple(r for r in inputs if not missing or r != ref))
    ret = direct_update(rig, q, current_evidence(rig))
    if missing:
        assert isinstance(ret, u.Rejected) and any(i.code == "unresolved_reference" for i in ret.issues)
    else:
        assert isinstance(ret, u.IssuedUpdate) and plain(ret.result) == SECOND


@pytest.mark.parametrize("conflict", (False, True), ids=("same_draw", "different_draw"))
def test_v032_evaluation_request_creation_checks_the_draw_fact_it_uses(make_rig, conflict):
    """T-G6 G6-EE-CREATE:4423, G6-DF-CREATE:4422; T-REF REF-EE-DRAW:3901;
    T-G4 G4-DRAW-FACT:4394, G4-DRAW-REPORT:4395. 期待: 合法 / 新しいEeの使用の禁止。
    Bug: use only A*/CG when creating Ee, ignoring DF's actual draw report.
    DF is saved before the new delivery; hold its confirmation at the public
    content store so that Ee has not yet been prepared when the clash arrives.
    """
    rig = make_rig(continuation=True)
    first_claim(rig)
    rig.adopt()
    rig.run_stage("evaluation_prepare")
    old_ee = {q.cid for q in rig.requests("evaluation")}
    held = []
    original_write = rig.ledger.write
    draw_fact = contract("sui.f.draw_fact")
    def write(prepared):
        ret = original_write(prepared)
        if prepared.record.body.contract == draw_fact and not held:
            held.append(prepared)
            rig.ledger.hit.append((draw_fact, "confirmation", prepared))
            rig.contents.blocked.add(entry_from_header(prepared.cid, prepared.header).seal)
            raise OSError("test: saved DF confirmation held before Ee")
        return ret
    rig.ledger.write = write
    draw = rig.run_stage("selection_draw")
    assert len(held) == 1 and {q.cid for q in rig.requests("evaluation")} == old_ee
    original = next(event for event, _ in rig.workers.sent
                    if isinstance(event, fb.DrawReturned) and event.work == draw.desc.work_id)
    event = replace(original, outcome=fb.DrawValue(value={"u": [3, 4]})) if conflict else original
    ctx = rig.workers.contexts["selection_draw"]
    accept_posted(rig, event, lambda: rig.workers.post(ctx, event))
    rig.contents.blocked.clear()
    rig.settle_steps(10)
    assert rig.read_stored(held[0].cid)[2] == held[0].record
    if conflict:
        assert {q.cid for q in rig.requests("evaluation")} == old_ee
        assert len(rig.facts(c.SELECTION)) == 1
    else:
        rig.drive(lambda: len(rig.requests("evaluation")) == 2)
        rig.run_stage("evaluation")
        rig.drive(lambda: len(rig.facts(c.SELECTION)) == 2)


def table_body_read_race(rig, points, action, post, *, before_post=None, when=None):
    """Only public sealed-content get is synchronized; no implementation hooks."""
    seals = {entry_from_header(point, rig.read_stored(point)[0]).seal for point in points}
    reached, release, posted, sender_started = Event(), Event(), Event(), Event()
    rig.workers.gates["table-body-read-cleanup"] = release
    identities, errors = [], []
    original_get = rig.contents.get
    def get(value_seal):
        if (identities and get_ident() == identities[0] and value_seal in seals and not reached.is_set()
                and (when is None or when())):
            reached.set()
            assert release.wait(10), "unverified schedule: dependency read was not released"
        return original_get(value_seal)
    def run():
        identities.append(get_ident())
        try:
            action()
        except BaseException as error:
            errors.append(error)
    def deliver():
        try:
            sender_started.set()
            post()
            posted.set()
        except BaseException as error:
            errors.append(error)
    rig.contents.get = get
    worker, sender = Thread(target=run, daemon=True), Thread(target=deliver, daemon=True)
    rig.workers.threads.extend((worker, sender))
    worker.start()
    try:
        assert reached.wait(3), "unverified schedule: no public dependency read in this operation"
        if before_post is not None:
            before_post()
        sender.start()
        assert sender_started.wait(2), "unverified schedule: sender thread did not start"
        completed_while_paused = posted.wait(2)
    finally:
        release.set()
        worker.join(5)
        if sender.ident is not None:
            sender.join(5)
        else:
            # Rig.close joins all registered threads, including failed probes.
            rig.workers.threads.remove(sender)
        rig.contents.get = original_get
    assert not worker.is_alive() and not sender.is_alive(), "public operation did not return"
    assert not errors, [(type(e).__name__, str(e)) for e in errors]
    assert completed_while_paused, "Post did not finish while dependency-body reading was paused"


@pytest.mark.parametrize("phase", (
    pytest.param("settle", marks=pytest.mark.xfail(strict=False, reason=(
        "判定待ち (Claude 2026-10-22 01:5x → レビュー 7 通目の問い 1): settle の中の歩の build の本文の読みも"
        "ロックの外であるべきか。紙 G6 の最後の行がロックの外に出すのは閉包・再生・比較で、build の読みは段 2 からロックの中"))),
    "entry"))
@pytest.mark.parametrize("conflict", (False, True), ids=("same_claim", "different_claim"))
def test_v032_post_completes_during_public_dependency_read_and_old_permission_is_not_used(make_rig, phase, conflict):
    """T-G6 G6-VERSION-RECHECK:4447, G6-EQ-CREATE:4417, G6-EP-ENTER:4418; Z22:3703 (LOCK-R6).
    期待: 依存読取りが待つ間もPostが完了。合法なら同settleで公開・入場、矛盾なら使用の禁止。
    Expect Post progress while the dependency read waits; legal same-settle
    publication/entry after an equal delivery, forbidden use after a clash.
    Bug: hold the Post lock while reading dependencies, keep an old permit, or
    defer an equal-version refresh to the next settle. No private function is
    intercepted. Entry's checkpoint must precede ctx.enter's observed return.
    Unverified: lock placement of computations which perform no public read.
    """
    rig = make_rig(continuation=True)
    first_claim(rig)
    if phase == "settle":
        rig.ledger.hold_context_before_write = True
    work, a = rig.adopt()
    ctx = rig.workers.contexts["measure_segment"]
    original = next(event for event, _ in rig.workers.sent
                    if isinstance(event, fb.SegmentReport) and event.item_slot == "claim-1")
    event = replace(original, item=replace(original.item,
        kind="count_exactly_one", contract=c.COUNT_EXACTLY_ONE)) if conflict else original
    if phase == "settle":
        assert rig.ledger.held_context is not None
        assert len(rig.requests("evaluation_prepare")) == 1
        rig.ledger.hold_context_before_write = False
        action = rig.host.window.settle
        checkpoint = None
        # Exclude direct A*/CG reads while constructing the context. Pause a
        # deeper model dependency after the context is actually saved.
        context_point = rig.ledger.held_context.cid
        when = lambda: context_point in dict(rig.entry_store.load())
        points = {rig.model_point}
    else:
        q, action = rig.callback("evaluation_prepare")
        def checkpoint():
            assert not any(w == q.value["desc"]["work_id"] for w, _ in rig.workers.entry_attempts), (
                "unverified schedule: body read occurred after entry, not inside ctx.enter")
        points = {q.cid, a.cid, rig.one(CG).cid, rig.model_point}
        when = None
    table_body_read_race(rig, points, action, lambda: rig.workers.post(ctx, event),
                         before_post=checkpoint, when=when)
    if phase == "settle":
        # Read C/E now: no additional settle may supply a missing same-call retry.
        assert len(rig.requests("evaluation_prepare")) == (1 if conflict else 2)
        if conflict:
            assert len([p for p in rig.ledger.preparations
                        if p.record.body.contract == c.EVALUATION_REQUESTED]) == 1
    else:
        assert (q.value["desc"]["work_id"], not conflict) in rig.workers.entry_attempts
        if not conflict:
            prepared = rig.workers.prepared_by_request[q.cid]
            assert isinstance(prepared.value, f.FProblem)
            assert prepared.value.K.belief == result_for(rig, work.request).record_id


@pytest.mark.parametrize("frame", (False, True), ids=("claim", "unsupported_frame"))
def test_v032_binding_report_selects_the_declared_item_kind_branch(make_rig, frame):
    """T-REF REF-B-REPORT:3904, REF-B-REPORT-FRAME:3905, REF-SEG-CLAIM-FRAME:3944.
    期待: 合法 / 不適合(missing_contract)、保存済みの記録は保持。
    Bug: apply the Claim row unconditionally to B.report or erase Frame as an
    empty dependency set. Rebind references, image keys and witness Points;
    a schema-valid Frame is the only different branch of the original report.
    """
    rig = make_rig()
    work, _a, evidence = direct_first(rig)
    b = rig.by_cid(c.SEGMENT_BINDING, work.desc.args.observations[0].binding)
    raw = rig.by_cid(c.SEGMENT_REPORT, b.value["report"])
    value = json.loads(json.dumps(raw.value))
    if frame:
        item = segment_items()["frame"]
        item = replace(item, measurement_interval=f.MeasurementInterval(clock=rig.clock.run,
            start_ns=0, end_ns=2, closure="(start,end]"),
            actual_time=f.ClockReading(run=rig.clock.run, time_ns=2),
            measurement_id=replace(item.measurement_id, origin=rig.read_stored(work.desc.reader)[2].id))
        value["item"] = {"kind": "frame", "value": wire(item)}
    new_raw = save_copy(rig, raw.cid, value=value, parents=())
    bvalue = dict(b.value, report=new_raw, view=wire(fixed_view(rig,
        {new_raw if p == raw.cid else p for p in b.value["view"]["boundary"]})))
    new_b = save_copy(rig, b.cid, value=bvalue,
        parents=front(rig, {new_raw if p == raw.cid else p for p in b.parents}))
    mapping = {raw.cid: new_raw, b.cid: new_b}
    copied_work = replace(work, desc=replace(work.desc, trigger=tuple(
        replace(t, point=new_raw) if t.point == raw.cid else t for t in work.desc.trigger)))
    q = rebind_request_inputs(rig, copied_work, mapping)
    snapshot = rig.storage_snapshot()
    if frame:
        table_assert_rejected(lambda: direct_update(rig, q, replace_evidence_points(evidence, mapping)),
                              "missing_contract")
    else:
        ret = direct_update(rig, q, replace_evidence_points(evidence, mapping))
        assert isinstance(ret, u.IssuedUpdate) and plain(ret.result) == FIRST
    assert rig.storage_snapshot() == snapshot


def v032_unverified_combinations():
    """Unverified combinations, not passing tests or new skips.

    REF-MATH-PREPARE-DRAW:4264 / REF-MATH-EVALUATE-DRAW:4287: a modified
    bind_draw call cannot be substituted for a factory-issued PR/EV through
    the current Boot worker protocol without an earlier issue check. F-a's
    standalone verifier would test replay, not the T-REF interpreter; that is
    not claimed as coverage of the element guard here.
    The formerly pending REF-DF-LOGICAL-LINK, REF-MODEL-SOURCE-TYPED-DEPS,
    G4-CANDIDATE-RESULT and A1-BUDGET-UNIT now have rules (v0.35 Z26:3707;
    fb_rules.md:39-43). Their individual discriminating fixtures remain
    unverified here; they are no longer undecided rules.
    G4-DRAW-REPORT:4395 via authenticated_request across distinct WorkIds
    sharing one draw key is not isolated from the terminal-key guard here;
    the retained D mouth in the new gate tests has just one WorkId.
    The separate unsupported guards along Frame's Q.trigger and B.report
    paths are not individually discriminated by the shared Frame negative.
    If settle's paused-read Post-progress check fails, its subsequent
    same-settle conflict/version/publication checks have not been reached.
    The exact internal location of the public read is not established here.
    Non-null preferences/reading-frame branches and all simultaneous continuation
    subjects under forged Boot declarations, and a finite ended-required
    generation contract, are not added as independent fixtures this round.
    """


def rule15_tables():
    """Read the allowed rule data, never the implementation or peer tests.

    fb_rules.md:26-38,48: denominator precedes execution. The generated tuple
    supplies G6 row IDs/locations; expected effects below come from the paper,
    not from an interpreter's returned marks or a window status.
    """
    root = Path(__file__).resolve().parents[1]
    lines = (root / "src/sui/fb_rules.md").read_text(encoding="utf8").splitlines()
    atoms = {}
    for number, line in enumerate(lines, 1):
        if line.startswith("| A1-"):
            cells = [cell.strip() for cell in line.strip("| ").split("|")]
            for atom in json.loads(cells[4]):
                atoms[atom["id"]] = dict(atom, paper_line=number, row=cells[0])
    # _fb_rules.py is explicitly authorized *table data*. Do not import any
    # private implementation, or execute the generated module to read a tuple.
    tree = ast.parse((root / "src/sui/_fb_rules.py").read_text(encoding="utf8"))
    g6 = next(ast.literal_eval(node.value) for node in tree.body
              if isinstance(node, ast.Assign)
              and any(isinstance(t, ast.Name) and t.id == "T_G6" for t in node.targets))
    return atoms, {row["id"]: row for row in g6}


RULE15_ATOMS, RULE15_G6 = rule15_tables()


def rule15_expect(call, classification, code=None, *, entry="U", malformed_request=False):
    """Paper A4:3617, fb_rules.md:28-30; preserve the public failure category."""
    if classification == "不適合":
        # A physically/structurally invalid entry is a typed input exception;
        # a constructed update's authentication failure is Rejected. Both are
        # specified public mismatch exits; no NameError/broad exception escape.
        try:
            result = call()
        except f.FInputError as error:
            assert entry == "prepare" or malformed_request, (
                "U must return Rejected for a constructed request's confirmed mismatch", str(error))
            if code is not None:
                assert code in str(error), str(error)
            return
        assert isinstance(result, u.Rejected), (type(result).__name__, plain(result))
        assert result.issues
        if code is not None:
            assert code in {issue.code for issue in result.issues}
    else:
        result = call()
        if entry == "U":
            assert isinstance(result, u.Insufficient), (type(result).__name__, plain(result))
            assert code in {issue.code for issue in result.issues}
        else:
            assert_incomplete_preparation(result, code)


def rule15_two_updates(rig):
    first, a1, _ = direct_first(rig)
    rig.claim(2)
    second, a2 = rig.adopt(2)
    r1, r2 = result_for(rig, first.request), result_for(rig, second.request)
    evidence = current_evidence(rig)
    reader, kwargs = adoption_prepare_inputs(rig, a2.cid, r2.cid)
    return first, a1, second, a2, r1, r2, evidence, reader, kwargs


def rule15_control(rig, first, second, result, evidence, reader, kwargs, *, entry):
    """The identical complete witness succeeds, before trying its one mutation."""
    if entry == "U":
        a = direct_update(rig, first.request, evidence)
        b = direct_update(rig, second.request, evidence)
        assert isinstance(a, u.IssuedUpdate) and plain(a.result) == FIRST
        assert isinstance(b, u.IssuedUpdate) and plain(b.result) == SECOND
    else:
        p = u.prepare_fb_from_facts(reader, evidence=evidence, **kwargs)
        assert isinstance(p.value, f.FProblem) and p.value.K.belief == result.record_id


@pytest.mark.parametrize("entry", ("U", "prepare"))
@pytest.mark.parametrize("witness,change,atom", (
    ("started", "early", "A1-CLOCK-ORDER"),
    ("started", "run", "A1-CLOCK-RUN"),
    ("started", "missing_run", "A1-CLOCK-RUN-RIGHT-PRESENT"),
    ("claim", "early", "A1-CLOCK-ORDER"),
    ("claim", "run", "A1-CLOCK-RUN"),
    ("claim", "missing_run", "A1-CLOCK-RUN-RIGHT-PRESENT"),
    ("entry", "missing_time", "A1-CLOCK-ORDER-LEFT-PRESENT"),
    ("entry", "missing_run", "A1-CLOCK-RUN-LEFT-PRESENT"),
), ids=lambda value: value)
def test_rule15_clock_atoms_use_independent_run_and_actual_receipt(make_rig, witness, change, atom, entry):
    """fb_rules.md:26-38,50, CLOCK_PAIRS:292-299, T-A1:1688-1689.

    A1-CLOCK ORDER/RUN/present; A1-CLOCK-MISSING-ALIGNMENT. 期待: 逆転は
    不適合(shape)、異runは不適合(clock_unaligned)、欠落は不足。
    Bug: replace EH's receipt/run or EW's actual entry M with saved readings.
    Controls preserve every saved byte; one selected host observation changes.
    U(current Q1), U(previous Q1 inside Q2), and head A2 all see the same pair.
    The missing operands also block the row's dependent comparisons; no claim
    is made that identical present guards in other rows are distinguishable.
    """
    rig = make_rig()
    first, _a1, second, _a2, _r1, r2, evidence, reader, kwargs = rule15_two_updates(rig)
    rule15_control(rig, first, second, r2, evidence, reader, kwargs, entry=entry)
    binding = rig.read_stored(first.desc.args.observations[0].binding)[2].body.content.as_json()
    point = binding["generation"]["started"] if witness == "started" else binding["report"]
    k = rig.read_stored(binding["segment"])[2].body.content.as_json()["desc"]["work_id"]
    row = next(x for x in evidence.executions if x.work_id == k)
    assert row.entered == 1 and row.entered_ns and row.run == rig.clock.run
    if witness == "entry":
        replacement = replace(row, **({"entered_ns": ()} if change == "missing_time" else {"run": None}))
    else:
        report = next(x for x in row.reports if x.point == point)
        assert report.run == rig.clock.run
        at = (rig.read_stored(point)[2].body.content.as_json()["item"]["value"]["reading"]["value"]["reading"]["time_ns"]
              if witness == "started" else 2)
        altered = (replace(report, received_ns=at - 1) if change == "early" else
                   replace(report, run="test:another-host-run" if change == "run" else None))
        replacement = replace(row, reports=tuple(altered if x == report else x for x in row.reports))
    changed = replace(evidence, executions=tuple(replacement if x == row else x for x in evidence.executions))
    assert changed.uses == evidence.uses and changed.acquisitions == evidence.acquisitions
    assert changed.intervals == evidence.intervals
    snapshot = rig.storage_snapshot()
    relation = RULE15_ATOMS[atom]
    classification = relation["on_fail"]
    code = relation.get("code") if classification == "不適合" else "prerequisite_unavailable"
    calls = ((lambda: direct_update(rig, first.request, changed), lambda: direct_update(rig, second.request, changed))
             if entry == "U" else (lambda: u.prepare_fb_from_facts(reader, evidence=changed, **kwargs),))
    for call in calls:
        rule15_expect(call, classification, code, entry=entry)
    assert rig.storage_snapshot() == snapshot


@pytest.mark.parametrize("entry", ("U", "prepare"))
@pytest.mark.parametrize("change,atom", (
    ("missing_execution", "A1-HISTORY-ENTER-OBSERVATION"),
    ("not_entered", "A1-HISTORY-ENTER-MISMATCH-COUNT"),
    ("missing_report", "A1-HISTORY-RETURN-MISSING-OBSERVATION"),
    ("missing_acquisition", "A1-HISTORY-ACQUIRE-MISSING-OBSERVATION"),
    ("missing_acquired_run", "A1-HISTORY-ACQUIRE-BEFORE-USE-RUN-LEFT-PRESENT"),
    ("missing_used_run", "A1-HISTORY-ACQUIRE-BEFORE-USE-RUN-RIGHT-PRESENT"),
    ("different_used_run", "A1-HISTORY-ACQUIRE-BEFORE-USE-RUN"),
    ("early_use", "A1-HISTORY-ACQUIRE-BEFORE-USE-ORDER"),
))
def test_rule15_history_atoms_have_separate_missing_and_mismatch_exits(make_rig, change, atom, entry):
    """fb_rules.md:32-38, T-A1:1695-1702; Paper A1/A4:3610-3617.

    期待: present EW entered=0 / 異run / 既知の逆転は不適合、喪失は不足。
    Bug: trust the stored history, infer a missing host/run from saved bytes,
    conflate an absent EW with an observed non-entry, or reverse acquisition.
    The acquired time is preserved for early_use: only R1's subsequent *use*
    moves, so ADOPTION_TIMES still passes and cannot mask the ORDER check.
    Each complete control succeeds at Q2 U and the evaluation head A2.
    """
    rig = make_rig()
    first, a1, second, _a2, r1, r2, evidence, reader, kwargs = rule15_two_updates(rig)
    rule15_control(rig, first, second, r2, evidence, reader, kwargs, entry=entry)
    row = next(x for x in evidence.executions if x.work_id == first.desc.work_id)
    basis = set(rig.read_stored(r1.cid)[2].body.basis) - {rig.read_stored(first.request)[2].id}
    report = next(x for x in row.reports if x.point is not None and rig.read_stored(x.point)[2].id in basis)
    g = rig.by_cid(ACQUIRED, a1.value["acquisition"])
    acq = next(x for x in evidence.acquisitions
               if x.origin == g.value["origin"] and x.contents == frozenset(g.value["contents"]))
    assert row.entered == 1 and report.run == acq.run == rig.clock.run
    uses = [x for x in evidence.uses if x.point == r1.cid and x.work_id == second.desc.work_id]
    assert uses and all(x.run == rig.clock.run and x.used_ns >= acq.acquired_ns for x in uses)
    changed = evidence
    if change in ("missing_execution", "not_entered", "missing_report"):
        new_row = replace(row, entered=0) if change == "not_entered" else replace(
            row, reports=tuple(x for x in row.reports if x != report))
        changed = replace(evidence, executions=tuple(new_row if x == row else x
            for x in evidence.executions if change != "missing_execution" or x != row))
    elif change in ("missing_acquisition", "missing_acquired_run"):
        changed = replace(evidence, acquisitions=tuple(replace(x, run=None) if x == acq else x
            for x in evidence.acquisitions if change != "missing_acquisition" or x != acq))
    else:
        def alter_use(x):
            if x not in uses:
                return x
            if change == "early_use":
                return replace(x, used_ns=acq.acquired_ns - 1)
            return replace(x, run=None if change == "missing_used_run" else "test:other-use-run")
        changed = replace(evidence, uses=tuple(alter_use(x) for x in evidence.uses))
    snapshot = rig.storage_snapshot()
    relation = RULE15_ATOMS[atom]
    classification = relation["on_fail"]
    code = relation.get("code") if classification == "不適合" else "prerequisite_unavailable"
    call = (lambda: direct_update(rig, second.request, changed)) if entry == "U" else (
        lambda: u.prepare_fb_from_facts(reader, evidence=changed, **kwargs))
    rule15_expect(call, classification, code, entry=entry)
    assert rig.storage_snapshot() == snapshot


@pytest.mark.parametrize("entry", ("U", "prepare"))
@pytest.mark.parametrize("target", ("claim", "binding", "monitor", "law", "reading"))
@pytest.mark.parametrize("source", ("acquisition", "use"))
def test_rule15_all_five_required_input_kinds_need_independent_acquisition_and_use(make_rig, target, source, entry):
    """fb_rules.md: INPUT_ACQUISITIONS:370-382, input_use_obligations:689;
    A1-ACQUIRE/A1-ACQUIRE-MISSING:1690-1691; Paper K5:3497/A1:3610.
    期待: 5種のうち1種だけのEA/EWを失えば不足(prerequisite_unavailable)。
    Bug: retain the obsolete three-kind list and omit law or reading. Remove
    the selected point from EA.contents (all other contents survive), or only
    that Wu1's use. No stored record is changed and the complete pair succeeds
    at current Q1, previous Q1 inside Q2, and evaluation head A2.
    Round 16: monitor-only EA/use omissions retain the insufficient oracle.
    The reported gap is between B.evidence=[] and the table's REF-B-SUPPORT
    source for monitor obligations; no table decision is assumed here.
    """
    rig = make_rig()
    first, _a1, second, _a2, _r1, r2, evidence, reader, kwargs = rule15_two_updates(rig)
    rule15_control(rig, first, second, r2, evidence, reader, kwargs, entry=entry)
    observation = first.desc.args.observations[0]
    b = rig.read_stored(observation.binding)[2].body.content.as_json()
    reading = rig.read_stored(observation.reading)[2].body.content.as_json()
    law = reading["projection"]["args"]["claims"][0]["law"]
    visible = closure(rig, first.desc.numerical_view.boundary)
    spans = [s for s in rig.facts(c.MONITOR_SPAN)
             if s.cid in visible and s.value["segment"] == b["segment"]]
    assert len(spans) == 1
    points = dict(claim=b["report"], binding=observation.binding,
                  monitor=spans[0].cid, law=law, reading=observation.reading)
    point = points[target]
    assert any(point in x.contents and x.origin == first.desc.reader for x in evidence.acquisitions)
    assert any(x.point == point and x.work_id == first.desc.work_id for x in evidence.uses)
    if source == "acquisition":
        changed = replace(evidence, acquisitions=tuple(replace(x, contents=x.contents - {point})
            if x.origin == first.desc.reader and point in x.contents else x for x in evidence.acquisitions))
        assert changed.uses == evidence.uses and changed.executions == evidence.executions
    else:
        changed = replace(evidence, uses=tuple(x for x in evidence.uses
            if not (x.point == point and x.work_id == first.desc.work_id)))
        assert changed.acquisitions == evidence.acquisitions and changed.executions == evidence.executions
    calls = ((lambda: direct_update(rig, first.request, changed), lambda: direct_update(rig, second.request, changed))
             if entry == "U" else (lambda: u.prepare_fb_from_facts(reader, evidence=changed, **kwargs),))
    for call in calls:
        rule15_expect(call, "不足", "prerequisite_unavailable", entry=entry)


@pytest.mark.parametrize("entry", ("U", "prepare"))
@pytest.mark.parametrize("change,atom", (
    ("purpose", "A1-REQUEST-PURPOSE"),
    ("method", "A1-REQUEST-METHOD"),
    ("output_contract", "A1-REQUEST-OUTPUT"),
    ("registry_key", "A1-REGISTRY-AVAILABLE"),
))
def test_rule15_request_atoms_apply_to_current_previous_and_head(make_rig, change, atom, entry):
    """fb_rules.md: A1-REQUEST:1665, A1-REGISTRY:1673; Paper A1/A4:3599-3617.
    期待: 要求の用途/方式/返答契約の不一致は不適合(shape)、未知registryは不足。
    Bug: authenticate only current Q; use a copied prior/head's opaque label.
    Every control is copied and its independent EH/EA is rebound in the same
    way. The negative changes one Desc field; R's saved view follows Q's view.
    Paper section 6-3: current-Q method/output mismatches cannot construct U's
    request and raise FInputError(shape); previous-Q mismatches return
    Rejected(shape), mapped to FInputError(shape) at the evaluation head.
    """
    rig = make_rig()
    first, a1, _ = direct_first(rig)
    # Copy before advancing M, so the copies and their independent witnesses
    # keep the same actual generation/acquisition/adoption times.
    saved = []
    for bad in (False, True):
        desc = first.desc
        if bad:
            if change == "purpose":
                desc = replace(desc, purpose="candidate_generation")
            elif change == "method":
                desc = replace(desc, method=contract("sui.f.finite_evaluation"))
            elif change == "output_contract":
                desc = replace(desc, output_contract=c.WORK_REQUESTED)
            else:
                desc = replace(desc, numerical_view=replace(desc.numerical_view,
                    registry_key="sha256:" + "0" * 64))
        q1 = save_request(rig, first, desc=desc)
        head, r, mapping = copy_adoption_for_request(rig, first, a1, q1)
        saved.append((bad, q1, head, r, mapping))
    rig.claim(2)
    second, _a2 = rig.adopt(2)
    original = current_evidence(rig)
    relation = RULE15_ATOMS[atom]
    for bad, q1, head, result, mapping in saved:
        evidence = replace_evidence_points(original, mapping)
        q2 = rebind_request_inputs(rig, second, mapping, prior=head)
        reader, kwargs = adoption_prepare_inputs(rig, head, result, sole_adoption=True)
        calls = (lambda: direct_update(rig, q1, evidence), lambda: direct_update(rig, q2, evidence),
                 lambda: u.prepare_fb_from_facts(reader, evidence=evidence, **kwargs))
        for index, call in enumerate(calls):
            if (index == 2) != (entry == "prepare"):
                continue
            if bad and index == 0 and change in ("method", "output_contract"):
                with pytest.raises(f.FInputError) as error:
                    call()
                assert error.value.reason == "shape"
            elif bad:
                rule15_expect(call, relation["on_fail"],
                    relation.get("code") if relation["on_fail"] == "不適合" else "algorithm_unavailable",
                    entry="prepare" if index == 2 else "U", malformed_request=change == "purpose" and index == 0)
            else:
                ret = call()
                if index < 2:
                    assert isinstance(ret, u.IssuedUpdate) and plain(ret.result) == (FIRST if index == 0 else SECOND)
                else:
                    assert isinstance(ret.value, f.FProblem) and ret.value.K.belief == rig.read_stored(result)[2].id


@pytest.mark.parametrize("entry", ("U", "prepare"))
@pytest.mark.parametrize("field,atom", (
    ("origin", "A1-HISTORY-ACQUIRE-ORIGIN"),
    ("contents", "A1-HISTORY-ACQUIRE-RESULT"),
))
def test_rule15_history_acquisition_matches_adoption_even_when_ea_matches_g(make_rig, field, atom, entry):
    """fb_rules.md:1699 A1-HISTORY-ACQUIRE ORIGIN/RESULT; Paper A1:3611/A4:3617.
    期待: Gに合う独立EAが有っても、Aのorigin/resultと違うGは不適合(proof_mismatch)。
    Bug: accept any G/EA pair, without comparing its origin and contents with A.
    Rebind EA with the copied G's exact origin/contents, retaining its real
    run and time, so absence of a matching EA cannot explain rejection.
    The same copied G/A with original fields is the legal control.
    """
    rig = make_rig()
    first, a1, _ = direct_first(rig)
    r1 = result_for(rig, first.request)
    g1 = rig.by_cid(ACQUIRED, a1.value["acquisition"])
    alternate_origin = save_copy(rig, first.desc.reader)
    cases = []
    for bad in (False, True):
        value = dict(g1.value)
        if bad:
            # F-a:60 / F-b:2334 declare contents:[Point], with no non-empty
            # constraint. Empty contents avoid introducing a second target's
            # generation/unsupported-use checks before the membership atom.
            value[field] = alternate_origin if field == "origin" else []
        g = save_copy(rig, g1.cid, value=value,
            parents=front(rig, set(g1.parents) | ({alternate_origin} if bad and field == "origin" else set())))
        refs = {rig.read_stored(g1.cid)[2].id: rig.read_stored(g)[2].id}
        a = save_copy(rig, a1.cid, value=dict(a1.value, acquisition=g),
            inputs=tuple(refs.get(x, x) for x in rig.read_stored(a1.cid)[2].body.inputs),
            parents=front(rig, events_for(rig, {g, r1.cid})))
        cases.append((bad, a, g, value))
    rig.claim(2)
    second, _ = rig.adopt(2)
    actual = current_evidence(rig)
    ea = next(x for x in actual.acquisitions
              if x.origin == g1.value["origin"] and x.contents == frozenset(g1.value["contents"]))
    for bad, a, g, value in cases:
        mapping = {g1.cid: g, a1.cid: a}
        q2 = rebind_request_inputs(rig, second, mapping, prior=a,
            extra=(alternate_origin,) if bad and field == "origin" else ())
        evidence = replace(actual, acquisitions=tuple(
            replace(x, origin=value["origin"], contents=frozenset(value["contents"])) if x == ea else x
            for x in actual.acquisitions))
        assert any(x.origin == value["origin"] and x.contents == frozenset(value["contents"])
                   and x.acquired_ns == ea.acquired_ns and x.run == ea.run for x in evidence.acquisitions)
        reader, kwargs = adoption_prepare_inputs(rig, a, r1.cid, sole_adoption=True)
        if bad:
            relation = RULE15_ATOMS[atom]
            call = (lambda: direct_update(rig, q2, evidence)) if entry == "U" else (
                lambda: u.prepare_fb_from_facts(reader, evidence=evidence, **kwargs))
            rule15_expect(call, relation["on_fail"], relation["code"], entry=entry)
        else:
            if entry == "U":
                ret = direct_update(rig, q2, evidence)
                assert isinstance(ret, u.IssuedUpdate) and plain(ret.result) == SECOND
            else:
                prepared = u.prepare_fb_from_facts(reader, evidence=evidence, **kwargs)
                assert isinstance(prepared.value, f.FProblem) and prepared.value.K.belief == r1.record_id


RULE15_GATE_FIXTURES = {
    # The predecessor is a *different* public operation. Post occurs after its
    # write returns, before the tested operation has even been prepared.
    "G6-Q-CREATE": ("before_first_Q", "input_G", "belief_update"),
    "G6-WU-ENTER": ("entry", "belief_update", "belief_update"),
    "G6-RESULT-CREATE": ("write", "update_T", "result"),
    "G6-RESULT-ACQUIRE": ("write", "result", "result_EA"),
    "G6-G-CREATE": ("write", "result_clock", "result_G"),
    "G6-ADOPTION-CREATE": ("write", "result_G", "adoption"),
    "G6-CONTINUE-A": ("write", "adoption", "evaluation_prepare"),
    "G6-CONTINUE-CG": ("write", "adoption", "evaluation_prepare"),
    "G6-CONTINUE-DECL": ("write", "adoption", "evaluation_prepare"),
    "G6-EQ-CREATE": ("write", "context", "evaluation_prepare"),
    "G6-EP-ENTER": ("entry", "evaluation_prepare", "evaluation_prepare"),
    "G6-PR-CREATE": ("reply", "evaluation_prepare", "prepared"),
    "G6-D-CREATE": ("write", "prepared", "selection_draw"),
    "G6-D-ENTER": ("entry", "selection_draw", "selection_draw"),
    "G6-DF-CREATE": ("write", "draw_T", "draw_fact"),
    "G6-EE-CREATE": ("write", "draw_fact", "evaluation"),
    "G6-EE-ENTER": ("entry", "evaluation", "evaluation"),
    "G6-EV-CREATE": ("reply", "evaluation", "evaluated"),
    "G6-SELECTION-CREATE": ("write", "evaluated", "selection"),
    "G6-START-Q": ("before_first_Q", "belief_update", "start_belief_update"),
    "G6-START-EQ": ("write", "evaluation_prepare", "start_evaluation_prepare"),
    "G6-START-D": ("write", "selection_draw", "start_selection_draw"),
    "G6-START-EE": ("write", "evaluation", "start_evaluation"),
}


def rule15_claim_delivery(rig, conflict):
    original = next(e for e, _ in rig.workers.sent
                    if isinstance(e, fb.SegmentReport) and e.item_slot == "claim-1")
    return (replace(original, item=replace(original.item,
        kind="count_exactly_one", contract=c.COUNT_EXACTLY_ONE)) if conflict else original)


def rule15_gate_count(rig, target):
    if target.startswith("start_"):
        stage = target.removeprefix("start_")
        ids = {x.value["desc"]["work_id"] for x in rig.requests(stage)}
        return sum(key in ids for key, _ in rig.launcher.attempts)
    if target in REQUEST_CONTRACT:
        return len(rig.requests(target))
    refs = {"result": c.UPDATE_RESULT, "result_G": ACQUIRED,
            "adoption": c.BELIEF_ADOPTED, "prepared": c.PREPARED,
            "draw_fact": contract("sui.f.draw_fact"), "evaluated": c.EVALUATED,
            "selection": c.SELECTION}
    results = {r.cid for r in rig.facts(c.UPDATE_RESULT)}
    if target == "result_EA":
        return sum(bool(results & x.contents) for x in current_evidence(rig).acquisitions)
    facts = rig.facts(refs[target])
    if target == "result_G":
        facts = [x for x in facts if results & set(x.value["contents"])]
    return len(facts)


def rule15_predecessor_matches(rig, prepared, name):
    ref = prepared.record.body.contract
    value = prepared.record.body.content.as_json()
    if name in REQUEST_CONTRACT:
        return ref == REQUEST_CONTRACT[name] and value["desc"]["purpose"] == name
    if name in ("update_T", "draw_T"):
        stage = "belief_update" if name == "update_T" else "selection_draw"
        return ref == c.WORK_TERMINAL and value["request"] == rig.requests(stage)[-1].cid
    if name == "input_G":
        claims = {x.cid for x in rig.facts(c.SEGMENT_REPORT) if x.value["item"]["kind"] == "claim"}
        return ref == ACQUIRED and bool(claims & set(value["contents"]))
    results = {x.cid for x in rig.facts(c.UPDATE_RESULT)}
    if name == "result_G":
        return ref == ACQUIRED and bool(results & set(value["contents"]))
    if name == "result_clock":
        # R* is a Prediction: the acquisition clock has R*'s *event* basis as
        # parents, not R* itself. Observe order, without promoting R* to E.
        return ref == CLOCK and bool(results) and not rule15_gate_count(rig, "result_G")
    return ref == {"result": c.UPDATE_RESULT, "adoption": c.BELIEF_ADOPTED,
                   "context": contract("sui.f.context_observed"), "prepared": c.PREPARED,
                   "draw_fact": contract("sui.f.draw_fact"), "evaluated": c.EVALUATED}[name]


def rule15_check_legal_gate_content(rig, target):
    """K6/K8-K10:3498-3502: compare content and links as well as cardinality."""
    if target.startswith("start_"):
        target = target.removeprefix("start_")
    if target in REQUEST_CONTRACT:
        request = rig.requests(target)[-1]
        desc, args = request.value["desc"], request.value["desc"]["args"]
        assert desc["purpose"] == target and desc["reader"] == rig.one(ORIGIN).cid
        assert request.contract == REQUEST_CONTRACT[target]
        if target == "belief_update":
            assert args["model"] == rig.model_point and args["prior"] is None
            assert args["budget"] == plain(UPDATE_BUDGET) and len(args["observations"]) == 1
            b = rig.read_stored(args["observations"][0]["binding"])[2].body.content.as_json()
            assert rig.read_stored(b["report"])[2].body.content.as_json() == wire(rule15_claim_delivery(rig, False))
        elif target == "evaluation_prepare":
            assert args["compiler"] == plain(fc.PREPARE_FACTS)
            assert args["input"]["model"] == rig.model_point
            assert args["input"]["candidates"] == rig.one(CG).cid
            assert rig.one(c.BELIEF_ADOPTED).cid in closure(rig, args["input"]["fixed_parents"])
        elif target in ("selection_draw", "evaluation"):
            assert args["prepared"] == rig.facts(c.PREPARED)[-1].cid
            if target == "evaluation":
                assert args["draw"] == rig.facts(contract("sui.f.draw_fact"))[-1].cid
    for result in rig.facts(c.UPDATE_RESULT):
        assert result.value["result"] == FIRST
        assert result.value["request"] == rig.requests("belief_update")[0].cid
        assert result.value["registry_key"] == public_registry_key(rig.registry)
    for adoption in rig.facts(c.BELIEF_ADOPTED):
        result = rig.by_cid(c.UPDATE_RESULT, adoption.value["result"])
        assert adoption.value["previous"] is None and adoption.value["origin"] == rig.one(ORIGIN).cid
        assert adoption.value["model"] == rig.model_point
        assert adoption.value["request"] == result.value["request"]
        g = rig.by_cid(ACQUIRED, adoption.value["acquisition"])
        assert g.value["contents"] == [result.cid] and g.value["origin"] == adoption.value["origin"]
    if target in ("prepared", "evaluated", "selection"):
        pr = rig.facts(c.PREPARED)[-1]
        prepared = rig.workers.prepared_by_request[pr.value["request"]]
        assert isinstance(prepared.value, f.FProblem)
        assert prepared.value.K.belief == rig.one(c.UPDATE_RESULT).record_id
        assert rig.read_stored(pr.value["artifact"])[2].body.content.as_json() == json.loads(prepared.canonical_bytes)
    if target == "draw_fact":
        assert rig.facts(contract("sui.f.draw_fact"))[-1].value["value"] == {"u": [1, 4]}
    if target == "selection":
        selection, ev = rig.facts(c.SELECTION)[-1], rig.facts(c.EVALUATED)[-1]
        assert selection.value["evaluated"] == ev.cid


@pytest.mark.parametrize("row", [r for key, r in RULE15_G6.items() if key in RULE15_GATE_FIXTURES],
                         ids=lambda row: row["id"])
@pytest.mark.parametrize("conflict", (False, True), ids=("equal_Post", "clashing_Post"))
def test_rule15_k12_operation_gate_from_table_row(make_rig, row, conflict):
    """fb_rules.md T-G6:1615-1644; Paper G6:3580-3593/Z25:3706/Z28:3709.
    行IDが分母。期待: 同内容なら合法、依存Claimの異内容は使用の禁止とpending conflict。
    Bug: check a gate only when opening continuation, or use a stale permit
    after a predecessor commits. Inject a real admitted mouth's Post *without
    Accept* at the public predecessor's write return / worker's reply / entry.
    Count actual C/E, launcher calls, entry witnesses, and independent EA.
    G6-CONTINUE-* are simultaneous: this tests their combined operation with
    A*'s Claim key; it does not claim to isolate CG/DECL's separate subjects.
    All paths preserve prepared-record retry: injection precedes the target's
    prepare, rather than pretending a cut at its own write revokes preparation.
    G6-EV-CREATE (fb_rules.md:1633) needs the continued D's draw before Ee's
    reply. Otherwise callback(evaluation) can select the completed initial Ee,
    and the fixture fails before either delivery reaches the target gate.
    """
    mode, predecessor, target = RULE15_GATE_FIXTURES[row["id"]]
    rig = make_rig(continuation=True)
    fired, before = [], []

    def inject():
        assert not fired
        before.append(rule15_gate_count(rig, target))
        event = rule15_claim_delivery(rig, conflict)
        raw_count = len(rig.facts(c.SEGMENT_REPORT))
        rig.workers.post(rig.workers.contexts["measure_segment"], event)
        assert len(rig.facts(c.SEGMENT_REPORT)) == raw_count, "Post must precede saving/Accept"
        fired.append(event)

    def arm_write():
        original = rig.ledger.write
        def write(prepared):
            result = original(prepared)
            if not fired and rule15_predecessor_matches(rig, prepared, predecessor):
                inject()
            return result
        rig.ledger.write = write

    if mode == "before_first_Q":
        rig.initial_evaluation()
        rig.start_measurement()
        arm_write()
        rig.claim()
    else:
        first_claim(rig)
        # Only the gates around initial Wu/R/G/A are tested on that first
        # update. The others use the actual continued evaluation with A1.
        early = (predecessor in {"belief_update", "update_T", "result", "result_clock", "result_G", "adoption", "context"}
                 or row["id"] == "G6-START-EQ")
        if mode == "entry" and predecessor == "belief_update":
            q, callback = rig.callback(predecessor)
            inject()
            callback()
        elif early:
            arm_write()
            rig.run_stage("belief_update")
        else:
            rig.adopt()
            if (predecessor in {"draw_T", "draw_fact", "evaluation", "evaluated"}
                    or (mode == "entry" and predecessor == "selection_draw")):
                rig.run_stage("evaluation_prepare")
            if predecessor == "evaluated" or (mode in ("entry", "reply") and predecessor == "evaluation"):
                rig.run_stage("selection_draw")
            if mode == "entry":
                q, callback = rig.callback(predecessor)
                inject()
                callback()
            elif mode == "reply":
                def reply(work, ctx):
                    event, issued = rig.workers.normal(work, ctx)
                    rig.workers.post(ctx, event, issued)
                    inject()
                rig.workers.overrides[predecessor] = reply
                rig.run_stage(predecessor)
            else:
                arm_write()
                stage = ("evaluation_prepare" if predecessor in {"prepared", "selection_draw"}
                         else "selection_draw" if predecessor in {"draw_T", "draw_fact", "evaluation"}
                         else "evaluation")
                rig.run_stage(stage)
    assert len(fired) == 1, (row["id"], "unverified: public predecessor was not reached")
    rig.settle_steps(8)
    if target.startswith("start_"):
        # FWindow exposes only drain(), not the host's start-claim operation.
        # The host pump may Accept the queued Post before attempting launch.
        # Start rows therefore verify the nearest public schedule, not a
        # guaranteed pre-Accept claim; entry rows above are truly pre-Accept.
        rig.host.run_until(lambda _status: False, timeout=.03)
    pending = rig.host.window.status().pending
    if mode == "entry":
        attempts = [allowed for key, allowed in rig.workers.entry_attempts if key == q.value["desc"]["work_id"]]
        assert attempts == [not conflict], (row["id"], attempts)
    else:
        count = rule15_gate_count(rig, target)
        assert count == before[0] + (0 if conflict else 1), (row["id"], before, count)
    if conflict:
        assert any("conflict" in p.reason for p in pending), [(p.kind, p.reason) for p in pending]
    elif mode == "entry":
        assert any(w.request == q.cid for w in rig.workers.entries)
    # The queued raw delivery is eventually accepted/saved even when use is
    # forbidden. New derived records must remain forbidden after that as well.
    n = 2 if not conflict else 1
    rig.drive(lambda: sum(r.value == wire(fired[0]) for r in rig.facts(c.SEGMENT_REPORT)) == n)
    rig.settle_steps(4)
    if conflict and mode != "entry":
        assert rule15_gate_count(rig, target) == before[0]
    if not conflict:
        rule15_check_legal_gate_content(rig, target)


@pytest.mark.parametrize("row_id,stage", (
    ("G6-EQ-CREATE", "candidate_generation"),
    ("G6-EP-ENTER", "evaluation_prepare"),
    ("G6-PR-CREATE", "evaluation_prepare"),
    ("G6-D-CREATE", "evaluation_prepare"),
    ("G6-D-ENTER", "selection_draw"),
))
@pytest.mark.parametrize("conflict", (False, True), ids=("equal_unrelated_Post", "clashing_unrelated_Post"))
def test_rule15_k12_initial_thinking_has_no_claim_use_key(make_rig, row_id, stage, conflict):
    """fb_rules.md:1612-1628, REF-EQ/PR/D; Paper REF-3:1082/G6:3580-3593.
    期待: 初回のCG/EQ/PR/Dはまだ原Claimの使用を持たないので、異内容でも進む。
    Bug: block all work because a received Claim clashes anywhere in the host.
    Produce an admitted measuring mouth's real Claim before the initial
    thinking work runs; no A* or adopted belief is part of those requests.
    """
    assert row_id in RULE15_G6
    rig = make_rig()
    rig.start_measurement()
    rig.claim()
    if stage != "candidate_generation":
        rig.run_stage("candidate_generation")
        # Both Wu and Ep use the thinking allocation. Let the independently
        # launched Wu finish with a legitimate failure, so this control does
        # not mistake occupied capacity for a Claim-use gate. It adopts no A*.
        def finish_without_adoption(work, ctx):
            rig.workers.post(ctx, rig.workers.finished(work, fb.WorkFailure(
                failure=fb.FailureInfo(failure_kind="test-unavailable", content="no update result",
                                       readings=(), basis=()))))
        rig.workers.overrides["belief_update"] = finish_without_adoption
        rig.run_stage("belief_update")
        assert not rig.facts(c.BELIEF_ADOPTED)
    if stage == "selection_draw":
        rig.run_stage("evaluation_prepare")
    event = rule15_claim_delivery(rig, conflict)
    rig.workers.post(rig.workers.contexts["measure_segment"], event)
    q, callback = rig.callback(stage)
    before = len(rig.workers.entries)
    callback()
    assert (q.value["desc"]["work_id"], True) in rig.workers.entry_attempts
    assert len(rig.workers.entries) == before + 1
    raw = c.DRAW_REPORT if stage == "selection_draw" else c.WORK_REPORT
    rig.drive(lambda: any(r.value["work"] == q.value["desc"]["work_id"] for r in rig.facts(raw)))
    rig.settle_steps(8)
    target = {"G6-EQ-CREATE": "evaluation_prepare", "G6-EP-ENTER": "prepared",
              "G6-PR-CREATE": "prepared", "G6-D-CREATE": "selection_draw", "G6-D-ENTER": "draw_fact"}[row_id]
    assert rule15_gate_count(rig, target) == 1


RULE15_REQUESTED_A1_ROWS = frozenset({
    "A1-BUDGET-UNIT", "A1-REQUEST", "A1-REGISTRY", "A1-ORIGIN-MODEL",
    "A1-CLOCK", "A1-CLOCK-MISSING", "A1-HISTORY-ENTER", "A1-HISTORY-ENTER-MISMATCH",
    "A1-HISTORY-RETURN-MISSING", "A1-HISTORY-ACQUIRE", "A1-HISTORY-ACQUIRE-MISSING",
    "A1-HISTORY-ACQUIRE-BEFORE-USE",
})
RULE15_BOUNDARY_CASE_ATOMS = frozenset({
    "A1-REQUEST-PURPOSE", "A1-REQUEST-METHOD", "A1-REQUEST-OUTPUT", "A1-REGISTRY-AVAILABLE",
    "A1-CLOCK-ORDER", "A1-CLOCK-RUN", "A1-CLOCK-RUN-RIGHT-PRESENT",
    "A1-CLOCK-ORDER-LEFT-PRESENT", "A1-CLOCK-RUN-LEFT-PRESENT",
    "A1-HISTORY-ENTER-OBSERVATION", "A1-HISTORY-ENTER-MISMATCH-COUNT",
    "A1-HISTORY-RETURN-MISSING-OBSERVATION", "A1-HISTORY-ACQUIRE-MISSING-OBSERVATION",
    "A1-HISTORY-ACQUIRE-BEFORE-USE-RUN-LEFT-PRESENT",
    "A1-HISTORY-ACQUIRE-BEFORE-USE-RUN-RIGHT-PRESENT",
    "A1-HISTORY-ACQUIRE-BEFORE-USE-RUN", "A1-HISTORY-ACQUIRE-BEFORE-USE-ORDER",
    "A1-HISTORY-ACQUIRE-ORIGIN", "A1-HISTORY-ACQUIRE-RESULT",
})
# This is a denominator/remainder, not a fabricated passing test for a missing
# fixture. A paired public exit does not prove that no other guard can stop it.
RULE15_WITHOUT_PAIRED_ATOM_CASE = tuple(sorted(
    key for key, atom in RULE15_ATOMS.items()
    if atom["row"] in RULE15_REQUESTED_A1_ROWS and key not in RULE15_BOUNDARY_CASE_ATOMS))
RULE15_WITHOUT_K12_GATE_CASE = tuple(sorted(set(RULE15_G6) - set(RULE15_GATE_FIXTURES)))


def rule15_unverified_atoms_and_gates():
    """Unverified, never skip/pass substitutes (fb_rules.md:26-50; Paper Z25-28).

    A1-BUDGET-UNIT (1712): all six atoms read an actual instrumented effect or
    its derived expected value. Saved RateBudget has no unit/counter field.
    Changing budget only tests limits, not corrupting an actual unit/charge.
    Round 16 confirms there is no public effect-injection interface. These
    six atoms remain unverified here; structural seam tests are separate.
    A1-REGISTRY-KEY[-LEFT-PRESENT]: actual registry identity is the digest of
    the supplied immutable registry. An unknown saved key first fails
    AVAILABLE. No independent public setter corrupts just the actual effect.
    A1-REQUEST METHOD/OUTPUT-RIGHT-PRESENT: the required ContractRef literal
    is fixed; corrupting registry declarations exercises capabilities, not
    this operand. ARGS overlaps the DTO shape guard; not isolated here.
    For current-Q METHOD/OUTPUT, the public entry's construction guard raises
    FInputError(shape) before the atomic check (Paper section 6-3). This is the
    correct entrance exception, not evidence of isolating these atoms; prior
    and head authentication retain the table's mismatch classification.
    A1-ORIGIN-MODEL-READER/CHAIN: MODEL-ORIGIN repeats the reader/model equality;
    a change to that pair cannot make just one of those two atoms false.
    Their present guards and history EA-origin/contents guards likewise share
    operands with their necessary premises. Existing field-negative cases
    are not counted as proof of independent atom discrimination.
    A1-CLOCK equality pairs, non-null Ended pairs, changed entry-vs-Started M,
    and every individual present guard are not all isolated by this fixture.
    The explicitly absent observation correctly blocks dependent comparisons;
    public failure cannot identify which of redundant guards enforced it.
    G6-NEXT-CONCLUSION has no public consumer callback in this version.
    G6-INPUT-ACQUIRE[-B/-MONITOR/-LAW/-READING] has no independently exposed
    pre-EA callback. Public contents.get is also used for authentication and
    building B; pausing it is not proof of pausing the actual acquisition gate.
    G6-EVALUATION-HEAD: the pure prepare entry cannot resolve the body/key of
    an unaccepted Post from ReportObservation(point=None). Accepted fixed-root
    clashes are covered by earlier tests; the exact Post-only schedule is not.
    G6-START-* uses the host pump, which can Accept before claiming a start;
    its nearest public schedule is tested, not claimed as pre-Accept coverage.
    The three simultaneous continuation rows share A*'s key in K12; separate
    CG/declaration-only counterexamples are not discriminated by that pair.
    The provenance/common/save-exception G6 rows are distinct families and
    remain covered only by earlier named tests, not K12's Claim generator.
    """


class RedClassification:
    """Report exception classes without displaying prohibited function bodies."""

    def __init__(self):
        self.outcomes = {}

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_makereport(self, item, call):
        outcome = yield
        report = outcome.get_result()
        if not item.nodeid.startswith("tests/test_fb_stage3.py"):
            return
        if report.failed:
            error = call.excinfo.value if call.excinfo is not None else None
            category = ("ContractGap" if isinstance(error, ContractGap) else
                        "NotImplementedError" if isinstance(error, NotImplementedError) else "other")
            frames, trace = [], getattr(error, "__traceback__", None)
            while trace is not None:
                code = trace.tb_frame.f_code
                if code.co_filename.replace("\\", "/").endswith("/test_fb_stage3.py"):
                    frames.append(f"{code.co_name}:{trace.tb_lineno}")
                trace = trace.tb_next
            location = " -> ".join(frames[-3:])
            self.outcomes[item.nodeid] = (category, type(error).__name__, str(error) + " [test " + location + "]")
            # xdist forwards this safe string to its controller. Even with
            # --tb=short it cannot display prohibited implementation bodies.
            report.longrepr = (f"FB3 red {item.nodeid}: {category}/{type(error).__name__}: "
                               f"{str(error)[:1800]} [test {location}]")
        elif report.when == "call" and report.passed:
            self.outcomes[item.nodeid] = ("passed", "", "")
        elif report.skipped:
            self.outcomes[item.nodeid] = ("skipped", "", "")

    def pytest_terminal_summary(self, terminalreporter):
        counts = Counter(row[0] for row in self.outcomes.values())
        terminalreporter.write_line("FB3 five metrics: total={} passed={} NotImplementedError={} ContractGap={} other={}".format(
            len(self.outcomes), counts["passed"], counts["NotImplementedError"], counts["ContractGap"], counts["other"]))
        terminalreporter.write_line(f"FB3 not_run: skipped={counts['skipped']} (documented public unreachability)")
        groups = {}
        for category, kind, message in self.outcomes.values():
            if category in ("passed", "skipped"):
                continue
            _prefix, _tag, location = message.rpartition(" [test ")
            key = (category, kind, location)
            count, first = groups.get(key, (0, message))
            groups[key] = count + 1, first
        for (category, kind, location), (count, message) in groups.items():
            excerpt = message.partition(" [test ")[0].replace("\n", " ")
            terminalreporter.write_line(f"FB3 red {count} {category}/{kind}: {excerpt[:1500]} [test {location}")


@pytest.fixture(scope="session", autouse=True)
def red_classification(request):
    reporter = RedClassification()
    request.config.pluginmanager.register(reporter, "fb-stage3-red-classification")
    return reporter



