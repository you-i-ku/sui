"""K28/K28-a/K28-b, paper v1.05 :3543-3545. No implementation bodies.

K28-a(a-c,f) fixes pairs-only bootstrap, updates/status, U-entry failure fields
and the MethodCall-shaped time_projection. K28-a(d-e) deliberately adds no
second reading version or forged Stale adoption: the ordered acquisition path
cannot reach that branch. Z55/Z56 are identified by name, not old line numbers.

Missing public contracts fail PER CASE before use, never at collection. SourceMeasurer
and FiniteUpdater are production workers; a test source releases operations with
Events. No test script calls acquire(). Computing workers remain TEST workers.
"""

from copy import deepcopy
from dataclasses import fields, replace
from fractions import Fraction as Q
from itertools import product
from threading import Event
from types import SimpleNamespace
from typing import get_args, get_type_hints

from test_fb_loop import assert_admitted_evaluation_root, wait_evaluation_activity_end

import pytest

from sui import f, fb, fb_contracts as c, f_update2 as u
from sui.ids import Ref, RefKind
from sui.records import Decided, Payload, Prediction, Role
from gate_f_facts_cases import finite_world, plain
from test_fb_skeleton import boot, contract, desc, point, reading, segment_items, slot, source
from test_fb_stage1 import RealRig, wire
from test_fb_stage1 import (rig as stage1_rig, RAW_FIELD_PROBES, RAW_EXAMPLES,
    malformed_raw_example, closed_raw_field_probe, RAW_BRANCH_PROBES,
    closed_raw_branch_probe, closed_raw_event, accept_and_save)
from test_fb_stage2 import LaunchCut, ORDER, PREPARE_BUDGET, EVALUATE_BUDGET
from test_fb_loop import LoopRig, Workers, registry, assert_update, closure
from test_fb_measure import (AcquireRig, AcquireWorkers, AcquirePort, acquire1_api,
    acquire1_quiet, acquire1_item, acquire1_expected_frame, make_acquire_rig, RAW, ROUTE)
from test_fb_read import read1_model, T, E, U, M, CONTROL, MODEL


DELTA = contract("sui.fb.saved_acquisition_update")
CORRESPONDENCE = contract("sui.fb.state_correspondence")
PROJECTION = contract("sui.fb.acquisition_sequence_projection")
GENERATION = contract("sui.fb.acquisition_generation")
REPEAT_ID = "sui.fb.acquisition_repeat_when_done/1"
RULER = {T: ((Q(0), Q(1, 4)), (Q(3, 4), Q(0))),
         E: ((Q(1, 4), Q(0)), (Q(0), Q(3, 4)))}
EXPECTED = (
    {"joint": [[1, 4], [3, 4]], "evidence_mass": [1, 2]},
    {"joint": [[1, 10], [9, 10]], "evidence_mass": [5, 16]},
    {"joint": [[3, 4], [1, 4]], "evidence_mass": [3, 32]},
)
STATUS_FIELDS = {"model", "origin", "route_epoch", "sample_seq", "obligation", "request",
    "outcome", "reading", "reasons", "fields", "published_through", "saved_through", "adopted_through"}
WAITING_OUTCOMES = {"waiting_storage", "waiting_binding", "waiting_predecessor",
    "waiting_confirmation", "requested", "recording", "ready"}
FINAL_OUTCOMES = {"adopted", "stale", "rejected", "insufficient", "failure",
    "unknown", "stopped", "conflicted", "issued:shape"}


def belief1_api(*, status=False):
    """Require paper's contract refs, without inventing exported constant names.

    K28-a(b) fixes the public status names and fields.
    The public registry, never a private implementation table, is inspected.
    """
    required = {("method", DELTA), ("projection", PROJECTION), ("generation", GENERATION)}
    declared = {(declaration.kind, declaration.ref) for declaration in u.fb_registry_v1().declarations}
    absent = sorted(f"{kind}:{ref.name}/{ref.version}" for kind, ref in required-declared)
    if status:
        if "updates" not in {x.name for x in fields(fb.FStatus)}: absent.append("FStatus.updates")
        if not hasattr(fb, "BeliefUpdateStatus"): absent.append("BeliefUpdateStatus")
    assert not absent, "K28 public API missing: " + ", ".join(absent)
    if status:
        assert STATUS_FIELDS == {x.name for x in fields(fb.BeliefUpdateStatus)}
        assert get_type_hints(fb.FStatus)["updates"] == tuple[fb.BeliefUpdateStatus, ...]
        hints = get_type_hints(fb.BeliefUpdateStatus)
        for tail in ("published_through", "saved_through", "adopted_through"):
            assert type(None) in get_args(hints[tail])


def belief1_enumerate(matrices, symbols, prior=(Q(1, 2), Q(1, 2))):
    """Enumerate every state path; retain the terminal state, do not reset it."""
    terminal = [Q(0), Q(0)]
    likelihood = [Q(0), Q(0)]
    for start in range(2):
        for path in product(range(2), repeat=len(symbols)):
            weight, previous = Q(1), start
            for symbol, arrival in zip(symbols, path):
                weight *= matrices[symbol][arrival][previous]
                previous = arrival
            likelihood[start] += weight
            terminal[previous] += prior[start] * weight
    mass = sum(terminal, Q(0))
    return tuple(x / mass for x in terminal) if mass else None, mass, tuple(likelihood)


class BeliefSource:
    def __init__(self, rig, symbols):
        self.rig, self.symbols, self.calls = rig, tuple(symbols), []
        self.mode = "present"  # FSource is installed, including empty/error outcomes.
        self.ready = [Event() for _ in symbols]
        self.release = [Event() for _ in symbols]
        self.release_read = Event()
    def read(self, cursor):
        i = len(self.calls)
        self.calls.append(cursor)
        if i >= len(self.symbols):
            raise SystemExit("test source exhausted: measurer accepted a round after stop")
        self.ready[i].set()
        assert self.release[i].wait(30), "test did not release source operation"
        self.rig.clock.set(self.rig.clock.peek() + 10)
        self.rig.clock.phase = "commit"
        if self.symbols[i] == U: raise OSError("test source failure")
        if self.symbols[i] == T:
            return self.rig.api.SourceItem(media_type="text/plain", data=RAW, claims={})
        assert self.symbols[i] == E
        return None


class BeliefPort(AcquirePort):
    def reader(self):
        reader = self.delegate.reader()
        return BeliefFailureReader(reader, self.rig.read_error) if self.rig.read_error is not None else reader

    """Production updater output boundary; faults replace only public notifications."""
    def post(self, event, issued=None):
        rig = self.rig
        rig.returned[self.work.request] = (self, event, issued)
        if isinstance(issued, u.IssuedUpdate): rig.workers.updates[self.work.request] = issued
        mode = rig.update_modes.get(rig.update_order.index(self.work.request), "normal")
        if mode == "stopped": return  # Delayed delivery is retained for K15(4).
        if mode in ("failure", "unknown"):
            outcome = (fb.WorkFailure(failure=fb.FailureInfo(failure_kind="test_failure",
                content={"type": "MemoryError"}, readings=(), basis=())) if mode == "failure" else
                fb.WorkUnknown(unknown=fb.UnknownInfo(reason="test outcome unknown", basis=())))
            event, issued = replace(event, outcome=outcome), None
        elif mode in ("rejected", "insufficient"):
            returned = (u.Rejected(request=self.work.request, issues=(u.RejectedIssue(
                code="missing_contract", fields=("/test",), evidence=frozenset(), message="test"),))
                if mode == "rejected" else u.Insufficient(request=self.work.request, issues=(u.InsufficientIssue(
                code="prerequisite_unavailable", fields=("/test",), missing=(u.VerificationNeed(kind="prerequisite", value={}),),
                evidence=frozenset(), message="test"),)))
            event, issued = replace(event, outcome=fb.WorkOutputs(outputs=u.update_response(returned))), None
        elif mode == "issued:shape":
            event = replace(event, outcome=fb.WorkOutputs(outputs=f.ContractValue(
                contract=c.UPDATE_RESPONSE, value={"kind": "issued", "value": {}})))
        elif mode == "drop-issued": issued = None
        elif mode == "foreign-issued": issued = rig.foreign_issued
        return super().post(event, issued=issued)


class BeliefWorkers(Workers):
    def run(self, work, ctx):
        if work.desc.purpose == "measure_segment":
            return AcquireWorkers.run(self, work, ctx)
        if work.desc.purpose != "belief_update": return super().run(work, ctx)
        port = BeliefPort(self.rig, work, ctx)
        self.rig.update_order.append(work.request)
        self.contexts["belief_update"] = ctx
        self.rig.update_ports[work.request] = port
        try:
            self.rig.updater.run(work, port)
        except BaseException as error:
            self.errors.append(error)
            raise
        finally:
            self.stops.append(work.desc.work_id)


class BeliefRig(AcquireRig):
    """K28-a(a) bootstrap; source timing and launch timing are test-owned."""
    def __init__(self, *, symbols=(T, E, T), matrices=None, prior=(Q(1, 2), Q(1, 2)),
                 pairs=(("A", "A"), ("B", "B")), targets=("box", "box"),
                 continuation=False, mutate=None, update_modes=None, delta=DELTA, asymmetric=False,
                 worker_type=BeliefWorkers, updater_type=None, repeat=None, outcome_groups=None,
                  extra_models=(), before_host=None, defer_boot=False):
        belief1_api()
        super().__init__(acquire1_api(), tick=0, advance=0)
        self.committed_points = []
        add_entry = self.entry_store.add
        def observe_commit(cid, header):
            result = add_entry(cid, header)
            self.committed_points.append(cid)
            return result
        self.entry_store.add = observe_commit
        self.gate_production_return = False
        self.source = BeliefSource(self, symbols)
        self.workers = worker_type(self)
        self.update_ports, self.returned, self.update_modes = {}, {}, update_modes or {}
        self.update_order, self.read_error = [], None
        self.foreign_issued, self.measure_key = None, None
        self.document, _ = finite_world("FA01")
        self.document["states"] = [{"id": "A", "target": targets[0]}, {"id": "B", "target": targets[1]}]
        self.document["targets"] = list(dict.fromkeys(targets))
        self.document["initial"] = wire(prior)
        if asymmetric:
            from gate_f_facts_cases import diagonal, outcome
            measurement, = (kernel for kernel in self.document["kernels"] if kernel["id"] == "measure")
            measurement["outcomes"] = [outcome("y0", diagonal((Q(1, 2), 1)), value=0),
                                       outcome("y1", diagonal((Q(1, 2), 0)), value=1)]
        model = self.record(Prediction(target="belief1.model", about=(), basis=(),
            content=Payload.json({"document": self.document}), contract=contract("sui.f.model_source")),
            RefKind.PREDICTION, Role.MODEL)
        self.model_point = self.ledger.write(self.ledger.prepare(model, ())).cid
        observation = read1_model({REPEAT_ID: matrices or RULER}, states=("A", "B"),
            groups=outcome_groups or {x: (x,) for x in (matrices or RULER)}, schedule=(REPEAT_ID,))
        observation.declaration = replace(observation.declaration,
            control_rule=fb.MethodCall(contract=CONTROL, args={"first": [REPEAT_ID],
                "after": {x: [REPEAT_ID] for x in (T, E, U, M)}}))
        args = {"route": "route", "observation_model": "observation",
                "correspondence": {"pairs": wire(pairs)}}
        if mutate is not None: observation.declaration, args = mutate(observation.declaration, args)
        event = boot(True)
        event = replace(event, declaration=replace(event.declaration, perception=replace(
            event.declaration.perception, value=replace(event.declaration.perception.value,
                model=self.model_point, derivation=fb.SlottedMethod(slot='delta', method=fb.MethodCall(contract=delta, args=args))))))
        initial = replace(event.declaration.initial.value, generator=fb.MethodCall(contract=c.MODEL_OPERATIONS, args={}), method=fb.MethodCall(contract=contract('sui.f.finite_evaluation'), args={}), draw=fb.MethodCall(contract=contract('stage2.scripted_draw'), args={}), prepare_budget=PREPARE_BUDGET, evaluate_budget=EVALUATE_BUDGET, continuation=fb.MethodCall(contract=c.REUSE_CANDIDATES, args={}) if continuation else None)
        initial = replace(initial, allocation=replace(initial.allocation, value=replace(initial.allocation.value,
            amount=fb.QuantityValue(contract=c.SEATS, value=2))))
        per = event.declaration.perception
        event = replace(event, declaration=replace(event.declaration, perception=replace(per,
            value=replace(per.value, allocation=replace(per.value.allocation, value=replace(
                per.value.allocation.value, amount=fb.QuantityValue(contract=c.SEATS, value=2)))))))
        route, = event.declaration.routes
        route = replace(route, value=replace(route.value, reading_contract=PROJECTION,
            config=replace(route.value.config, sampling_contract=c.ACQUISITION_RESULT_SAMPLING,
                           clock_contract=contract("sui.f.simulated_clock"))))
        if repeat is not None: route = replace(route, value=replace(route.value, repeat=repeat))
        self.boot_input = replace(event, declaration=replace(event.declaration,
            capacity=fb.QuantityValue(contract=c.SEATS, value=3), initial=replace(event.declaration.initial, value=initial),
            routes=(route,), observation_models=(slot("observation", MODEL, observation.declaration),
                *(slot(f"alternative-{i}", MODEL, model) for i, model in enumerate(extra_models)))))
        if before_host is not None:
            before_host(self)
        self.updater = (updater_type or fb.FiniteUpdater)(registry=self.registry)
        self.clock_declaration = replace(source(), run=self.clock.run, measurement=contract("sui.f.simulated_clock"))
        self.host = fb.FThreadHost(ledger=self.ledger, clock=self.clock, workers=self.workers,
            registry=self.registry, launcher=self.launcher, sources={ROUTE: self.source})
        self.host.post(fb.ClockDeclared(declaration=self.clock_declaration))
        self.host.post(self.boot_input)
        if not defer_boot:
            self.until(lambda: len(self.facts(MODEL)) == 1+len(extra_models))
    def begin(self):
        self.measure_key = self.launch("measure_segment")
        assert self.source.ready[0].wait(10)
    def publish(self, index, *, last=False):
        assert self.source.ready[index].wait(10)
        if last: self.measurers[self.measure_key].stop()
        self.source.release[index].set()
        self.wait_returns(index + 1)
        return self.saved_pair(self.calls[index])
    def update(self):
        before = len(self.facts(c.BELIEF_ADOPTED))
        work = self.run_stage("belief_update")
        self.until(lambda: len(self.facts(c.BELIEF_ADOPTED)) == before + 1)
        return work, self.facts(c.BELIEF_ADOPTED)[-1]
    def close(self):
        for measurer in self.measurers.values(): measurer.stop()
        for release in self.source.release: release.set()
        super().close()


@pytest.fixture
def make_belief1():
    rigs = []
    def make(**kwargs):
        rig = BeliefRig(**kwargs)
        rigs.append(rig)
        return rig
    yield make
    for rig in reversed(rigs): rig.close()


def belief1_status(rig, seq):
    belief1_api(status=True)
    rows = [row for row in rig.host.window.status().updates if row.model == rig.model_point and row.sample_seq == seq]
    assert len(rows) == 1
    row, = rows
    assert row.route_epoch == ROUTE and row.origin is not None
    assert isinstance(row.outcome, str)
    assert row.outcome in WAITING_OUTCOMES | FINAL_OUTCOMES or (
        row.outcome.startswith("update:issued:") and bool(row.outcome.removeprefix("update:issued:"))), row.outcome
    if row.request is not None:
        q = rig.one(c.WORK_REQUESTED, cid=row.request)
        use, = q.value["desc"]["args"]["observations"]
        assert row.obligation == use["binding"], "K28-b(a): obligation names this Frame's B"
    return row


def belief1_chain(rig, expected=EXPECTED):
    adoptions = rig.facts(c.BELIEF_ADOPTED)
    assert len(adoptions) == len(expected)
    previous = None
    for adopted, answer in zip(adoptions, expected):
        assert adopted.value["previous"] == previous
        result = rig.one(c.UPDATE_RESULT, cid=adopted.value["result"])
        assert result.value["result"] == answer
        q = rig.one(c.WORK_REQUESTED, cid=adopted.value["request"])
        assert q.value["desc"]["args"]["prior"] == previous
        assert q.value["desc"]["reader"] == adopted.value["origin"]
        previous = adopted.cid
    assert len({a.value["previous"] for a in adoptions}) == len(adoptions)
    assert not rig.facts(c.STALE), "K28-a(e): no acquisition request may be issued against an older head"


def test_belief1_ruler_independent_terminal_path_enumeration():
    """K28 :4324: distinguish final-state joint from initial-state posterior and from double application."""
    for symbols, answer in zip(((T,), (T, E), (T, E, T)), EXPECTED):
        joint, mass, likelihood = belief1_enumerate(RULER, symbols)
        assert wire(joint) == answer["joint"] and wire(mass) == answer["evidence_mass"]
        assert mass == sum(likelihood, Q(0)) / 2
    assert belief1_enumerate(RULER, (T, E))[2] == (Q(9, 16), Q(1, 16))
    assert EXPECTED[1]["joint"] != [[9, 10], [1, 10]]


@pytest.mark.parametrize("batch", [False, True], ids=["sequential", "three-saved-before-Wu-entry"])
def test_belief1_production_TET_adopts_in_order_and_matches_enumeration_and_K26(make_belief1, batch):
    """K28(a): production workers; skipping, batching or multiplying prefix L by current q fails each prefix."""
    rig = make_belief1()
    rig.begin()
    if batch:
        for i in range(3): rig.publish(i, last=i == 2)
        assert len(rig.reports("frame")) == 3
        assert not [work for work in rig.workers.entries if work.desc.purpose == "belief_update"]
    previous = None
    for i, answer in enumerate(EXPECTED):
        if not batch: rig.publish(i, last=i == 2)
        work, adopted = rig.update()
        assert_update(rig, work, adopted, answer, previous)
        previous = adopted.cid
        assert len(work.desc.args.observations) == 1
        use, = work.desc.args.observations
        binding = rig.one(c.SEGMENT_BINDING, cid=use.binding)
        frame = rig.one(c.SEGMENT_REPORT, cid=binding.value["report"])
        assert frame.value["item"]["kind"] == "frame" and frame.value["item"]["value"]["sample_seq"] == i
        reading = rig.one(c.OBSERVATION_PLAN_2, cid=use.reading)
        assert reading.value["projection"]["contract"] == wire(PROJECTION)
        assert reading.value["generation"]["contract"] == wire(GENERATION)
        assert reading.value["model"] == rig.model_point
        assert reading.value["projection"]["args"]["observation_model"] == rig.one(MODEL).cid
        assert reading.value["projection"]["args"]["correspondence"] == rig.one(CORRESPONDENCE).cid
        assert reading.value["projection"]["args"]["time_projection"] == {
            "contract": wire(contract("sui.f.value_only")), "args": {}}
        assert binding.value["reading_contract"] == wire(PROJECTION)
        assert binding.value["segment"] == frame.value["segment"]
        correspondence = rig.read_stored(rig.one(CORRESPONDENCE).cid)[2]
        assert correspondence.writer == Role.MODEL and isinstance(correspondence.body, Prediction)
        assert wire(rig.boot_input.declaration.perception.value.derivation.method.args) == {
            "route": "route", "observation_model": "observation",
            "correspondence": {"pairs": [["A", "A"], ["B", "B"]]}}
        assert correspondence.body.content.as_json() == {
            "model": rig.model_point, "observation_model": rig.one(MODEL).cid,
            "pairs": [["A", "A"], ["B", "B"]]}
        assert rig.committed_points.index(rig.one(CORRESPONDENCE).cid) < rig.committed_points.index(reading.cid)
        required = {rig.one(c.BOOT_DECLARATION).cid, rig.model_point, rig.one(MODEL).cid,
            rig.one(CORRESPONDENCE).cid, reading.cid, binding.value["segment"], binding.value["route"], adopted.value["origin"]}
        for call in rig.calls[:i+1]:
            raw, (_, saved_frame) = rig.saved_pair(call)
            required.add(saved_frame.cid)
            required.update(b.cid for b in rig.facts(c.SEGMENT_BINDING) if b.value["report"] == saved_frame.cid)
            if raw: required.add(raw[1].cid)
        for previous_adoption in rig.facts(c.BELIEF_ADOPTED)[:i]:
            required.update((previous_adoption.cid, previous_adoption.value["request"],
                previous_adoption.value["result"], previous_adoption.value["acquisition"]))
        assert required <= closure(rig, work.desc.input_points)
        model, = rig.facts(MODEL)
        read = fb.read_acquisition_sequence(rig.records(), model=model.cid, run=rig.clock.run, route_epoch=ROUTE, through_seq=i)
        assert sum(read.likelihood, Q(0)) / 2 == Q(*answer["evidence_mass"])
    belief1_chain(rig)
    assert len(rig.source.calls) == len(rig.calls) == 3
    assert rig.workers.contexts["measure_segment"].evidence().intervals == ()


def test_belief1_observation_cell_sums_all_compatible_outcome_matrices(make_belief1):
    """K28(a): split T into two equal compatible outcomes; selecting only one halves each T mass."""
    half = tuple(tuple(Q(x)/2 for x in row) for row in RULER[T])
    rig = make_belief1(matrices={"T-left": half, "T-right": half, E: RULER[E]},
        outcome_groups={T: ("T-left", "T-right"), E: (E,)})
    rig.begin()
    for i in range(3): rig.publish(i, last=i == 2); rig.update()
    belief1_chain(rig)


@pytest.mark.parametrize("swap", [False, True])
def test_belief1_explicit_correspondence_reorders_state_coordinates(make_belief1, swap):
    """K28 correspondence: swapping only the declared map reverses state coordinates, not evidence mass."""
    pairs = (("A", "B"), ("B", "A")) if swap else (("A", "A"), ("B", "B"))
    rig = make_belief1(pairs=pairs)
    rig.begin()
    answers = []
    for i, original in enumerate(EXPECTED):
        rig.publish(i, last=i == 2)
        work, adopted = rig.update()
        answer = {**original, "joint": list(reversed(original["joint"])) if swap else original["joint"]}
        assert plain(rig.workers.updates[work.request].result) == answer
        answers.append(answer)
    belief1_chain(rig, answers)
    correspondence, = rig.facts(CORRESPONDENCE)
    assert correspondence.value == {"model": rig.model_point, "observation_model": rig.one(MODEL).cid, "pairs": wire(pairs)}


@pytest.mark.parametrize("kind", ["diagonal", "uninformative", "state-swap"])
def test_belief1_equal_likelihood_is_not_automatically_a_numerical_noop(make_belief1, kind):
    """K28 decision 8: new MID changes mass even when q stays; equal-rate swap changes q."""
    prior = (Q(2, 3), Q(1, 3))
    if kind == "diagonal":
        matrices = {T: ((Q(3, 4), 0), (0, Q(1, 4))), E: ((Q(1, 4), 0), (0, Q(3, 4)))}
        joint, mass = (Q(6, 7), Q(1, 7)), Q(7, 12)
    else:
        matrices = {T: (((0, Q(1, 2)), (Q(1, 2), 0)) if kind == "state-swap"
                        else ((Q(1, 2), 0), (0, Q(1, 2)))), E: ((Q(1, 2), 0), (0, Q(1, 2)))}
        joint, mass = ((Q(1, 3), Q(2, 3)) if kind == "state-swap" else prior), Q(1, 2)
    rig = make_belief1(symbols=(T,), matrices=matrices, prior=prior)
    rig.begin(); rig.publish(0, last=True)
    rig.update()
    belief1_chain(rig, ({"joint": wire(joint), "evidence_mass": wire(mass)},))


def test_belief1_distinct_equal_result_MIDs_are_new_evidence_and_time_alone_is_not(make_belief1):
    """K28(a)(c): TT has two real MIDs; after last operation elapsed M is not another kernel application."""
    rig = make_belief1(symbols=(T, T))
    rig.begin()
    answers = []
    for i in range(2):
        rig.publish(i, last=i == 1); rig.update()
        joint, mass, _ = belief1_enumerate(RULER, (T,) * (i+1))
        answers.append({"joint": wire(joint), "evidence_mass": wire(mass)})
    belief1_chain(rig, answers)
    mids = [r.value["item"]["value"]["measurement_id"] for r in rig.reports("frame")]
    assert mids[0] != mids[1]
    before = tuple(rig.facts(c.BELIEF_ADOPTED))
    rig.clock.set(rig.clock.peek() + 8 * 60 * 60 * 10**9)
    for _ in range(3): rig.round()
    assert tuple(rig.facts(c.BELIEF_ADOPTED)) == before


@pytest.mark.parametrize("kind", ["frame", "claim", "gap", "measurement_unavailable"])
@pytest.mark.parametrize("mouth", ["worker", "host"])
def test_belief1_producer_cannot_publish_frame_or_interval_evidence(make_acquire_rig, kind, mouth):
    """K28 decision 4: a well-typed producer report cannot masquerade as host acquisition."""
    rig = make_acquire_rig(acquire1_api(), script=acquire1_quiet)
    key = rig.launch("measure_segment")
    assert rig.started.setdefault(key, Event()).wait(30)
    port = rig.ports[key]
    event = fb.SegmentReport(segment=rig.work_by_id[key].request, item_slot="forbidden", item=segment_items()[kind])
    post = port.post if mouth == "worker" else rig.host.post
    before = (tuple(rig.receipts()), port.evidence().sources,
              tuple((e.work_id, e.reports) for e in port.evidence().executions))
    with pytest.raises(TypeError): post(event)
    after = (tuple(rig.receipts()), port.evidence().sources,
             tuple((e.work_id, e.reports) for e in port.evidence().executions))
    assert after == before
    for _ in range(3): rig.round()
    assert not any(r.value.get("item_slot") == "forbidden" for r in rig.reports(kind))
    assert not rig.calls


@pytest.mark.parametrize("kind", ["frame", "claim", "gap", "measurement_unavailable"])
def test_belief1_accept_rejects_envelopes_outside_acquire(kind):
    """K28 decision 4: outer shape alone never authenticates a source-acquisition Frame."""
    rig = RealRig()
    try:
        event = fb.SegmentReport(segment=point("unknown-segment"), item_slot="forged", item=segment_items()[kind])
        before = rig.storage_snapshot()
        with pytest.raises(fb.FbInputError): rig.host.window.accept(rig.envelope(1, event, 0))
        assert rig.storage_snapshot() == before
        assert not rig.host.window.status().receipts
        assert not rig.prepare_observations
    finally: rig.close()


def test_belief1_original_acquire_envelope_retry_is_idempotent_after_save(make_acquire_rig):
    """K28 :4254: accept an original envelope even after it has left the receive queue."""
    api = acquire1_api()
    rig = make_acquire_rig(api, items=(acquire1_item(api),))
    key = rig.launch("measure_segment")
    rig.wait_returns()
    call, = rig.calls
    raw, (report, frame) = rig.saved_pair(call)
    event = fb.SegmentReport(segment=call.work.request, item_slot="frame:0",
        item=acquire1_expected_frame(rig, call, raw[1]))
    assert wire(event) == frame.value
    envelope = fb.Envelope(number=report.envelope, received_ns=report.received_ns, event=event)
    before = rig.storage_snapshot()
    rig.host.window.accept(envelope)
    for _ in range(2): rig.host.window.settle()
    assert rig.storage_snapshot() == before
    assert len(rig.reports("frame")) == 1
    assert rig.source_for(call).frame == frame.cid
    assert rig.ports[key].evidence().sources == call.port.evidence().sources


@pytest.mark.parametrize("change", ["number", "bytes", "interval-end"])
def test_belief1_acquire_envelope_requires_both_original_number_and_bytes(make_acquire_rig, change):
    """K28 :4254: authentic Frame content alone, or an authentic number alone, is insufficient."""
    api = acquire1_api()
    rig = make_acquire_rig(api, items=(acquire1_item(api),))
    rig.launch("measure_segment"); rig.wait_returns()
    call, = rig.calls
    raw, (report, frame) = rig.saved_pair(call)
    event = fb.SegmentReport(segment=call.work.request, item_slot="frame:0",
        item=acquire1_expected_frame(rig, call, raw[1]))
    assert wire(event) == frame.value
    envelope = fb.Envelope(number=report.envelope, received_ns=report.received_ns, event=event)
    if change == "number": envelope = replace(envelope, number=report.envelope+100)
    elif change == "bytes": envelope = replace(envelope, event=replace(event, item_slot="changed-envelope-bytes"))
    else:
        item = replace(event.item, measurement_interval=replace(event.item.measurement_interval,
            end_ns=report.received_ns + 1))
        envelope = replace(envelope, event=replace(event, item=item))
    before = rig.storage_snapshot()
    with pytest.raises(fb.FbInputError): rig.host.window.accept(envelope)
    assert rig.storage_snapshot() == before
    assert rig.one(c.SEGMENT_REPORT, cid=frame.cid).value == wire(event)


@pytest.mark.parametrize("kind", ["started", "ended", "coverage_unproved"])
def test_belief1_boundary_and_unproved_reports_remain_accepted(make_acquire_rig, kind):
    """K28 Z56: closing evidence ingress must not close the three remaining report branches."""
    rig = make_acquire_rig(acquire1_api(), script=acquire1_quiet)
    key = rig.launch("measure_segment")
    assert rig.started.setdefault(key, Event()).wait(30)
    event = fb.SegmentReport(segment=rig.work_by_id[key].request, item_slot="allowed:"+kind,
        item=segment_items()[kind])
    rig.ports[key].post(event)
    rig.until(lambda: any(r.value == wire(event) for r in rig.reports(kind)))
    assert rig.host.halted is None


@pytest.mark.parametrize("mode", ["rejected", "insufficient", "failure", "unknown", "stopped",
                                  "issued:shape", "drop-issued"])
def test_belief1_nonadoption_keeps_later_obligations_waiting_with_distinct_status(make_belief1, mode):
    """K28 decisions 5/11: a nonadopted prefix blocks later numbers; stopped is not success or failure."""
    belief1_api(status=True)
    rig = make_belief1(update_modes={0: mode})
    rig.begin()
    for i in range(3): rig.publish(i, last=i == 2)
    if mode == "stopped":
        # No readable WorkFinished is posted; the public launch callback returns.
        fact, body = rig.callback("belief_update")
        rig.executed.add(fact.value["desc"]["work_id"])
        body()
    else: rig.run_stage("belief_update")
    expected = "update:issued:missing" if mode == "drop-issued" else mode
    rig.until(lambda: belief1_status(rig, 0).outcome == expected)
    for _ in range(4): rig.round()
    row = belief1_status(rig, 0)
    assert row.request == rig.requests("belief_update")[0].cid
    assert row.obligation is not None and row.origin is not None
    if mode in ("rejected", "insufficient"):
        assert row.reasons == (("missing_contract",) if mode == "rejected" else ("prerequisite_unavailable",))
        assert row.fields == ("/test",)
    assert len(rig.requests("belief_update")) == 1
    assert not rig.facts(c.UPDATE_RESULT) and not rig.facts(c.BELIEF_ADOPTED)
    waiting = belief1_status(rig, 1)
    assert waiting.outcome == "waiting_predecessor" and waiting.adopted_through is None
    assert rig.host.halted is None


def test_belief1_stopped_late_terminal_adopts_then_unblocks_next_number(make_belief1):
    """K28 :4260: a permanent stopped flag, retry, or skipping to E fails the T->E chain."""
    belief1_api(status=True)
    rig = make_belief1(symbols=(T, E), update_modes={0: "stopped"})
    rig.begin(); rig.publish(0); rig.publish(1, last=True)
    fact, body = rig.callback("belief_update")
    rig.executed.add(fact.value["desc"]["work_id"]); body()
    rig.until(lambda: belief1_status(rig, 0).outcome == "stopped")
    assert len(rig.requests("belief_update")) == 1
    port, terminal, issued = rig.returned[fact.cid]
    port.delegate.post(terminal, issued=issued)
    rig.until(lambda: len(rig.facts(c.BELIEF_ADOPTED)) == 1)
    assert belief1_status(rig, 0).outcome == "adopted"
    rig.update()
    belief1_chain(rig, EXPECTED[:2])
    assert sum(w.request == fact.cid for w in rig.workers.entries) == 1
    assert sum(key == fact.value["desc"]["work_id"] for key, _ in rig.launcher.attempts) == 1


def test_belief1_wrong_issued_handle_is_not_U_rejection_and_never_skips_number(make_belief1):
    """K28 B1: transport of an issued handle for a different Q is not U rejected."""
    belief1_api(status=True)
    rig = make_belief1(update_modes={1: "foreign-issued"})
    rig.begin(); rig.publish(0)
    first, _ = rig.update()
    rig.foreign_issued = rig.workers.updates[first.request]
    rig.publish(1); rig.publish(2, last=True)
    rig.run_stage("belief_update")
    rig.until(lambda: belief1_status(rig, 1).outcome.startswith("update:issued:"))
    assert len(rig.facts(c.BELIEF_ADOPTED)) == 1
    assert len(rig.requests("belief_update")) == 2
    assert belief1_status(rig, 2).outcome == "waiting_predecessor"


@pytest.mark.parametrize("blocked", ["raw", "frame"])
@pytest.mark.parametrize("with_prior", [False, True], ids=["no-saved-or-adopted-tail", "after-first-adoption"])
def test_belief1_published_but_unsaved_tail_is_waiting_not_read_or_noop(make_belief1, blocked, with_prior):
    """K28 :4261: r<h is visible; neither a missing raw nor a missing Frame permits Q1."""
    belief1_api(status=True)
    rig = make_belief1(symbols=(T, T))
    rig.begin()
    if with_prior: rig.publish(0); rig.update()
    index = int(with_prior)
    write = rig.ledger.write
    fired = []
    def cut(prepared):
        body = prepared.record.body
        value = plain(body.content.as_json())
        if ((blocked == "raw" and body.contract == c.RECEIVED) or
            (blocked == "frame" and body.contract == c.SEGMENT_REPORT and value["item"]["kind"] == "frame")):
            fired.append(prepared)
            raise OSError("test blocked one tail member")
        return write(prepared)
    rig.ledger.write = cut
    assert rig.source.ready[index].wait(30)
    rig.measurers[rig.measure_key].stop()
    rig.source.release[index].set(); rig.wait_returns(index+1)
    rig.until(lambda: bool(fired))
    row = belief1_status(rig, index)
    assert row.outcome == "waiting_storage"
    tail = 0 if with_prior else None
    assert (row.published_through, row.saved_through, row.adopted_through) == (index, tail, tail)
    assert len(rig.requests("belief_update")) == len(rig.facts(c.BELIEF_ADOPTED)) == index
    rig.ledger.write = write
    rig.saved_pair(rig.calls[index]); rig.update()
    joint, mass, _ = belief1_enumerate(RULER, (T, T))
    answers = (EXPECTED[0], {"joint": wire(joint), "evidence_mass": wire(mass)}) if with_prior else (EXPECTED[0],)
    belief1_chain(rig, answers)
    assert all(p.cid == fired[0].cid and p.record == fired[0].record for p in fired)
    assert len(rig.calls) == index+1


@pytest.mark.parametrize("stage", ["all-initial-states-zero", "prior-support-only-zero"])
def test_belief1_zero_mass_retains_read_and_update_stage_without_epsilon(make_belief1, stage):
    """K28 decision 8: read model_zero implies U model_falsified; converse fails for p=(1,0)."""
    belief1_api(status=True)
    matrices = {T: ((0, 0), (0, 0 if stage == "all-initial-states-zero" else 1)),
                E: ((1, 0), (0, 1 if stage == "all-initial-states-zero" else 0))}
    rig = make_belief1(symbols=(T,), matrices=matrices, prior=(Q(1), Q(0)))
    rig.begin(); rig.publish(0, last=True); rig.run_stage("belief_update")
    row = belief1_status(rig, 0)
    assert row.outcome == "rejected" and row.reasons == ("model_falsified",)
    assert row.reading == ("model_zero" if stage == "all-initial-states-zero" else "read")
    assert not rig.facts(c.BELIEF_ADOPTED) and not rig.facts(c.UPDATE_RESULT)
    assert rig.host.halted is None


@pytest.mark.parametrize("defect", ["correspondence-absent", "correspondence-duplicate", "correspondence-missing",
    "target-crossing", "repeat-contract", "repeat-args", "control-id", "first", "after", "weight",
    "emission-kind", "emission-contract", "emission-value", "cell-value"])
def test_belief1_invalid_declarations_are_not_valid_updates_or_numerical_noops(make_belief1, defect):
    """K28 decisions 3/9 + K39-c: name invalid content without epsilon/noop.

    Correspondence content is checked by the shared candidate resolution at
    boot. Delta still holds malformed argument shapes at delta:* below.
    """
    belief1_api(status=True)
    def mutate(model, args):
        if defect == "correspondence-absent": args.pop("correspondence")
        elif defect == "correspondence-duplicate": args["correspondence"]["pairs"] = [["A", "A"], ["B", "A"]]
        elif defect == "correspondence-missing": args["correspondence"]["pairs"] = [["A", "A"]]
        elif defect in ("first", "after"):
            rule = deepcopy(model.control_rule.args)
            if defect == "first": rule["first"] = ["unrelated-u"]
            else: rule["after"][E] = ["unrelated-u"]
            model = replace(model, control_rule=replace(model.control_rule, args=rule))
        elif defect == "weight":
            model = replace(model, independence=replace(model.independence, args={"weights_by_initial_state": [[[1,2]], [[1,2]]]}))
        elif defect == "control-id":
            control, = model.controls
            model = replace(model, controls=(replace(control, id="unrelated-u"),))
        elif defect.startswith("emission-"):
            control, = model.controls
            out, *rest = control.kernel.outcomes
            emission = out.evidence
            if defect == "emission-kind": emission = replace(emission, kind="coverage")
            elif defect == "emission-contract": emission = replace(emission, measurement_contract=contract("test.other_sampling"))
            else: emission = replace(emission, value={"result": "empty", "source_called": True})
            model = replace(model, controls=(replace(control, kernel=replace(control.kernel,
                outcomes=(replace(out, evidence=emission), *rest))),))
        elif defect == "cell-value":
            control, = model.controls
            cell, *rest = control.cells
            model = replace(model, controls=(replace(control, cells=(replace(cell,
                observation=f.ObservationValue(kind="measurement", value={"result": "empty", "source_called": True})), *rest)),))
        return model, args
    repeat = None
    if defect in ("repeat-contract", "repeat-args"):
        repeat = fb.MethodCall(contract=(contract("test.other_repeat") if defect == "repeat-contract" else c.ACQUISITION_REPEAT_WHEN_DONE),
            args={} if defect == "repeat-contract" else {"unexpected": True})
    def before_host(rig):
        if defect == "repeat-contract":
            # K27-a(b): pass Boot's measurement-declaration check so this
            # mismatching repeat actually reaches delta's K28-b(d) check.
            declaration, = (d for d in rig.registry.declarations if d.kind == "measurement"
                             and d.ref == c.ACQUISITION_REPEAT_WHEN_DONE)
            rig.registry = f.make_f_registry(declarations=rig.registry.declarations + (
                replace(declaration, ref=repeat.contract),), implementations=rig.registry.implementations)
    rig = make_belief1(symbols=(T,), mutate=mutate, repeat=repeat,
        targets=("left", "right") if defect == "target-crossing" else ("box", "box"), before_host=before_host)
    if defect in ("correspondence-duplicate", "correspondence-missing"):
        candidate = rig.boot_input.declaration.perception.slot
        reason = "perception:candidate:correspondence:" + candidate
        rig.until(lambda: any(p.reason == reason for p in rig.host.window.status().pending))
        boot_point = rig.one(c.BOOT_DECLARATION).cid
        status = rig.host.window.status()
        assert any(p.reason == reason and p.target == boot_point for p in status.pending)
        assert not any(p.reason.startswith("delta:") and p.target == boot_point for p in status.pending)
        assert not rig.requests("belief_update")
        assert not rig.facts(c.BELIEF_ADOPTED) and not rig.facts(c.UPDATE_RESULT)
        assert rig.host.halted is None
        return
    if repeat is not None:
        for _ in range(5): rig.round()
    else:
        rig.begin(); rig.publish(0, last=True)
        for _ in range(5): rig.round()
        if defect != "correspondence-absent":
            # Remaining observation-content checks belong to U. K39-c moves
            # correspondence content to the shared candidate resolution above.
            rig.until(lambda: len(rig.requests("belief_update")) == 1)
            rig.run_stage("belief_update")
    assert not rig.facts(c.BELIEF_ADOPTED)
    status = rig.host.window.status()
    rows = [r for r in status.updates if r.model == rig.model_point]
    assert rows or status.pending
    assert any(r.reasons for r in rows) or any(p.reason for p in status.pending)
    if defect == "correspondence-absent":
        assert not rig.requests("belief_update")
        assert any(p.reason in {"delta:args", "delta:correspondence"} for p in status.pending)
    elif repeat is not None:
        assert not rig.requests("belief_update")
        assert any(p.reason == "delta:repeat" for p in status.pending)
    elif repeat is None:
        row = belief1_status(rig, 0)
        assert row.outcome == "rejected" and row.reasons
        assert "model_falsified" not in row.reasons
    assert rig.host.halted is None


class BeliefFailureReader(f.FReader):
    """Inject only at the public reader operation used by the actual production updater."""
    def __init__(self, reader, error): self.delegate, self.error = reader, error
    def record(self, point): raise self.error
    def entry(self, point): return self.delegate.entry(point)
    def entries(self): return self.delegate.entries()
    def ancestors(self, frontier): return self.delegate.ancestors(frontier)
    def sealed_content(self, point): return self.delegate.sealed_content(point)


class BeliefEntryFailureReader(f.FReader):
    """A public reader: missing/malformed Q, or an exception from the lower component.

    It never tags an exception as raised by U. Positive cases let the real U
    entrance construct its own FInputError; identical lower-component words
    must not be treated as proof of that origin (K28-a(c)).
    """
    def __init__(self, request, record=None, error=None):
        self.request, self.value, self.error, self.calls = request, record, error, []
    def record(self, cid):
        self.calls.append(cid)
        assert cid == self.request, "the malformed entry must fail before numerical dependencies"
        if self.error is not None: raise self.error
        if self.value is None: raise KeyError(cid)
        return self.value


class BeliefEntryFailurePort(fb.FWorkContext):
    """K24 worker-unit port, not a host execution or a synthetic adoption."""
    def __init__(self, reader):
        self.value, self.posts, self.readings, self.entries = reader, [], [], 0
    def enter(self):
        self.entries += 1
        return True
    def now(self):
        value = reading()
        value = replace(value, reading=replace(value.reading, time_ns=20+len(self.readings)))
        self.readings.append(value)
        return value
    def reader(self): return self.value
    def evidence(self): return u.TargetEvidence(executions=(), uses=(), intervals=(), acquisitions=(), sources=())
    def post(self, event, issued=None): self.posts.append((event, issued))


@pytest.mark.parametrize("case", [
    "U-missing-request", "U-malformed-desc",
    "lower-unresolved-request", "lower-unresolved-desc", "lower-shape-request", "lower-shape-desc",
    "unknown-code", "unknown-field", "external-error",
])
def test_belief1_updater_failure_keeps_only_closed_reason_and_field_not_free_text(case):
    """K28-a(c): preserve only U-entrance reason/field; lower exceptions with the SAME words keep type only.

    Retaining a lower-component reason, filtering by class/words alone, leaking
    free text, or discarding a genuine U-entrance reason fails a separate case.
    """
    assert hasattr(fb, "FiniteUpdater"), "K24 public API missing: FiniteUpdater"
    request = point("belief1-entry-failure-Q")
    work = fb.Compute(request=request, desc=replace(desc("belief_update"),
        method=c.FINITE_UPDATE_COMPUTE, output_contract=c.UPDATE_RESPONSE))
    rig = RealRig(connect=False)
    try:
        expected = {"error_type": "FInputError"}
        if case.startswith("U-"):
            bad_record = (None if case == "U-missing-request" else
                rig.record(Decided(inputs=(), content=Payload.json({"desc": []}), contract=c.WORK_REQUESTED),
                    RefKind.DECISION, Role.MODEL))
            reader = BeliefEntryFailureReader(request, record=bad_record)
            reason, field = (("unresolved_reference", "/request") if case == "U-missing-request"
                             else ("shape", "/request/desc"))
            # Setup witness against the PUBLIC U: these words are paper's
            # expected result, not copied from an implementation traceback.
            with pytest.raises(f.FInputError) as caught:
                u.compute_finite_update(request, reader=reader, registry=registry(),
                    evidence=u.TargetEvidence(executions=(), uses=(), intervals=(), acquisitions=(), sources=()))
            assert (caught.value.reason, caught.value.field) == (reason, field)
            assert type(caught.value) is not f.FInputError, "K28-b(f): U entrance uses a dedicated subtype"
            # K28-b(f) does not publish the dedicated subclass's spelling.
            # The paper still requires the name of the actual thrown type.
            expected.update(error_type=type(caught.value).__name__, reason=reason, field=field)
        else:
            reason = "unresolved_reference" if "unresolved" in case else "shape"
            field = "/request/desc" if case.endswith("desc") else "/request"
            if case == "unknown-code": reason = "external-secret-code"
            if case == "unknown-field": field = "external-secret-field"
            error = (RuntimeError("secret free text") if case == "external-error" else
                     f.FInputError(reason, "secret free text", field))
            reader = BeliefEntryFailureReader(request, error=error)
            expected = {"error_type": type(error).__name__}
        port = BeliefEntryFailurePort(reader)
        fb.FiniteUpdater(registry=registry()).run(work, port)
        assert port.entries == 1 and reader.calls
        event_and_issue, = port.posts
        event, issued = event_and_issue
        assert issued is None and isinstance(event, fb.WorkFinished) and isinstance(event.outcome, fb.WorkFailure)
        assert event.work == work.desc.work_id and event.outcome.failure.failure_kind == "execution_error"
        assert plain(event.outcome.failure.content) == expected
        assert event.outcome.failure.readings == tuple(port.readings)
        assert "secret" not in str(wire(event))
    finally: rig.close()


class BeliefSnapshotReader:
    """Test-owned record view for U-only contrasts; no host ingress is simulated."""
    def __init__(self, records): self.records = dict(records)
    def record(self, point): return self.records[point]


def belief1_clone(rig, fact, value, *, parents=None):
    """Declare a new public record in the TEST ledger, never inject it through Post."""
    original = rig.read_stored(fact.cid)[2]
    record = replace(original, id=rig.ids.new(original.id.kind),
        body=replace(original.body, content=Payload.json(value)))
    entry = rig.ledger.write(rig.ledger.prepare(record, tuple(fact.parents if parents is None else parents)))
    return entry.cid


def belief1_direct(rig, q, *, value=None, records=None):
    records = rig.records() if records is None else dict(records)
    if value is not None:
        cid = belief1_clone(rig, q, value)
        records[cid] = rig.read_stored(cid)[2]
    else: cid = q.cid
    return u.compute_finite_update(cid, reader=BeliefSnapshotReader(records), registry=rig.registry, evidence=None)


def belief1_reader_scope_copy(rig, records, *, pinned, run, epoch):
    """U-only namespace copy of a production prefix, NOT a host delivery.

    Rename every copied record/record-id reference together, plus the run/epoch
    in clocks, routes, raws and Frames. The child model and origin stay pinned.
    No prior adoption is copied: the snapshot is taken before the first update.
    K26 must independently read the copied prefix before the negative U call.
    """
    points = {cid: point(f"K28-52:{run}:{epoch}:{cid}") for cid in records if cid not in pinned}
    ids = {record.id: Ref(kind=record.id.kind, value=f"k28-52-copy-{index}")
           for index, (cid, record) in enumerate(records.items()) if cid not in pinned}
    names = {**points, **{str(old): str(new) for old, new in ids.items()},
             str(rig.clock.run): str(run), ROUTE: epoch}
    def rename(value):
        if isinstance(value, str): return names.get(value, value)
        if isinstance(value, list): return [rename(item) for item in value]
        if isinstance(value, dict): return {key: rename(item) for key, item in value.items()}
        return value
    copied = {cid: record for cid, record in records.items() if cid in pinned}
    for cid, record in records.items():
        if cid not in pinned:
            copied[points[cid]] = replace(record, id=ids[record.id], at=replace(record.at, run=run),
                body=replace(record.body, content=Payload.json(rename(record.body.content.as_json()))))
    return copied, points, rename


@pytest.mark.parametrize("defect", ["skip-one", "other-run", "other-route-epoch"])
def test_belief1_U_requires_the_next_item_of_the_adopted_prefix(make_belief1, defect):
    """K28 decision 6 (:4265): after seq 0, only seq 1 of that run/epoch issues.

    Skipping seq 1 or accepting another run/epoch fails explicit nonissuance.
    The normal seq-1 control issues q=(1/10,9/10), Z=5/16, not a no-op.
    Foreign prefixes retain their complete 0..1 records and pass K26; a missing
    prefix, bad origin/model, or a broken raw reference cannot serve as the fault.
    """
    rig = make_belief1()
    rig.begin()
    for i in range(3): rig.publish(i, last=i == 2)
    rig.until(lambda: len(rig.facts(c.SEGMENT_BINDING)) == 3)
    first_q, _ = rig.callback("belief_update")
    prefix_records = rig.records()
    _work, adopted = rig.update()
    q, _ = rig.callback("belief_update")
    assert adopted.value["previous"] is None and q.value["desc"]["args"]["prior"] == adopted.cid
    normal = belief1_direct(rig, q)
    assert isinstance(normal, u.IssuedUpdate) and plain(normal.result) == EXPECTED[1]
    preserved = {cid: rig.read_stored(cid) for cid in rig.records()}
    records = rig.records()
    value = deepcopy(q.value)
    use, = value["desc"]["args"]["observations"]
    if defect == "skip-one":
        frame = rig.reports("frame")[2]
        assert frame.value["item"]["value"]["sample_seq"] == 2
        binding, = (b for b in rig.facts(c.SEGMENT_BINDING) if b.value["report"] == frame.cid)
        use["binding"] = binding.cid
        # Complete saved 0..2 is visible; only observations selects the wrong 2.
        value["desc"]["input_points"] = sorted(set(value["desc"]["input_points"]) | set(prefix_records))
        value["desc"]["numerical_view"]["boundary"] = sorted(set(value["desc"]["numerical_view"]["boundary"]) | set(prefix_records))
        read = fb.read_acquisition_sequence(records, model=rig.one(MODEL).cid,
            run=rig.clock.run, route_epoch=ROUTE, through_seq=2)
        assert read.likelihood is not None and sum(read.likelihood, Q(0)) / 2 == Q(3, 32)
    else:
        run = Ref(kind=RefKind.RUN, value="k28-52-other-run") if defect == "other-run" else rig.clock.run
        epoch = "k28-52-other-route" if defect == "other-route-epoch" else ROUTE
        pinned = {rig.model_point, first_q.value["desc"]["reader"]}
        copied, points, rename = belief1_reader_scope_copy(rig, prefix_records,
            pinned=pinned, run=run, epoch=epoch)
        records.update(copied)
        foreign_zero = u.compute_finite_update(points[first_q.cid],
            reader=BeliefSnapshotReader(records), registry=rig.registry, evidence=None)
        assert isinstance(foreign_zero, u.IssuedUpdate) and plain(foreign_zero.result) == EXPECTED[0]
        value = rename(value)
        value["desc"]["args"]["prior"] = adopted.cid
        # Keep the real adopted history as well as the foreign complete prefix.
        history = closure(rig, (adopted.cid,)) | {adopted.cid}
        value["desc"]["input_points"] = sorted(set(value["desc"]["input_points"]) | history)
        value["desc"]["numerical_view"]["boundary"] = sorted(set(value["desc"]["numerical_view"]["boundary"]) | history)
        assert value["desc"]["reader"] == q.value["desc"]["reader"]
        assert value["desc"]["args"]["model"] == rig.model_point
        selected, = value["desc"]["args"]["observations"]
        b = records[selected["binding"]].body.content.as_json()
        current = records[b["report"]].body.content.as_json()["item"]["value"]
        assert current["sample_seq"] == 1 and current["route_epoch"] == epoch
        assert current["measurement_id"]["origin"] == str(run)
        assert current["measurement_interval"]["clock"] == str(run)
        read = fb.read_acquisition_sequence(records, model=points[rig.one(MODEL).cid],
            run=run, route_epoch=epoch, through_seq=1)
        assert read.kind == "read" and read.likelihood == (Q(9, 16), Q(1, 16))
    if defect == "skip-one":
        ret = belief1_direct(rig, q, value=value, records=records)
    else:
        # The foreign request's own run is coherent too. Keeping Q in the old
        # run would test K26's run check instead of the adopted-prefix boundary.
        original = rig.read_stored(q.cid)[2]
        name = point(f"K28-52-request:{defect}")
        records[name] = replace(original, id=rig.ids.new(original.id.kind),
            at=replace(original.at, run=run), body=replace(original.body, content=Payload.json(value)))
        ret = u.compute_finite_update(name, reader=BeliefSnapshotReader(records), registry=rig.registry, evidence=None)
    assert isinstance(ret, u.Rejected) and ret.issues, ret
    assert all(issue.code != "model_falsified" for issue in ret.issues)
    assert [a.cid for a in rig.facts(c.BELIEF_ADOPTED)] == [adopted.cid]
    assert all(rig.read_stored(cid) == saved for cid, saved in preserved.items())


@pytest.mark.parametrize("defect", ["renamed-single-u", "schedule"])
def test_belief1_K26_readable_control_rules_must_match_the_repeat_declaration(make_belief1, defect):
    """K28 decision 9 (:4268): K26-valid is insufficient for this acquisition method.

    Ignoring canonical u-id accepts the fully renamed first/after counterexample.
    Ignoring first/after accepts schedule, although K26 reads both with the same
    positive L=(3/4,1/4). The canonical control must adopt (1/4,3/4;1/2).
    """
    belief1_api(status=True)
    for wrong in (False, True):
        def mutate(model, args):
            if not wrong: return model, args
            control, = model.controls
            if defect == "renamed-single-u":
                name = "test.noncanonical-repeat/1"
                model = replace(model, controls=(replace(control, id=name,
                    kernel=replace(control.kernel, id=name)),),
                    control_rule=replace(model.control_rule, args={"first": [name],
                        "after": {symbol: [name] for symbol in (T, E, U, M)}}))
            else:
                model = replace(model, control_rule=replace(model.control_rule,
                    args={"schedule": [[REPEAT_ID]]}))
            return model, args
        rig = make_belief1(symbols=(T,), mutate=mutate)
        rig.begin(); rig.publish(0, last=True)
        model = rig.one(MODEL)
        read = fb.read_acquisition_sequence(rig.records(), model=model.cid,
            run=rig.clock.run, route_epoch=ROUTE, through_seq=0)
        assert read.kind == "read" and read.likelihood == (Q(3, 4), Q(1, 4))
        rig.until(lambda: len(rig.requests("belief_update")) == 1)
        rig.run_stage("belief_update")
        if wrong:
            rig.until(lambda: belief1_status(rig, 0).outcome == "rejected")
            row = belief1_status(rig, 0)
            assert row.reasons and "model_falsified" not in row.reasons
            assert not rig.facts(c.UPDATE_RESULT) and not rig.facts(c.BELIEF_ADOPTED)
            port, event, issued = next(iter(rig.returned.values()))
            assert issued is None
            assert event.outcome.outputs.value["kind"] == "rejected"
        else:
            rig.until(lambda: len(rig.facts(c.BELIEF_ADOPTED)) == 1)
            belief1_chain(rig, EXPECTED[:1])
            assert belief1_status(rig, 0).outcome == "adopted"
        assert rig.host.halted is None


@pytest.mark.parametrize("replay", [False, True], ids=["extra-unobserved-frames", "same-MID-same-meaning"])
def test_belief1_U_applies_only_observations_and_replay_is_exact_noop(make_belief1, replay):
    """K28 decision 6: visible later Frames are not permission; the same MID does not multiply twice."""
    rig = make_belief1()
    rig.begin()
    for i in range(3): rig.publish(i, last=i == 2)
    work, adopted = rig.update()
    q = rig.one(c.WORK_REQUESTED, cid=work.request)
    value = deepcopy(q.value)
    if replay: value["desc"]["args"]["prior"] = adopted.cid
    result = belief1_direct(rig, q, value=value)
    assert isinstance(result, u.IssuedUpdate), result
    assert plain(result.result) == EXPECTED[0]
    if replay: assert result.application_digest == rig.workers.updates[work.request].application_digest
    assert len(rig.facts(c.BELIEF_ADOPTED)) == 1  # U-only contrast did not mutate host belief.


@pytest.mark.parametrize("change", ["correspondence", "kernel"])
def test_belief1_U_same_MID_under_different_declared_meaning_is_conflict(make_belief1, change):
    """K28 decision 6: a valid alternative first issues, but reinterpreting an adopted MID conflicts."""
    belief1_api()
    alternate_model = read1_model({REPEAT_ID: {
        T: ((0, Q(1,2)), (Q(1,4), 0)), E: ((Q(3,4),0), (0,Q(1,2)))}},
        states=("A","B"), groups={T:(T,), E:(E,)}, schedule=(REPEAT_ID,)).declaration
    alternate_model = replace(alternate_model, control_rule=fb.MethodCall(contract=CONTROL,
        args={"first":[REPEAT_ID], "after":{x:[REPEAT_ID] for x in (T,E,U,M)}}))
    rig = make_belief1(symbols=(T,), extra_models=(alternate_model,) if change == "kernel" else ())
    rig.begin(); rig.publish(0, last=True)
    work, adopted = rig.update()
    q = rig.one(c.WORK_REQUESTED, cid=work.request)
    use, = q.value["desc"]["args"]["observations"]
    old = rig.one(c.OBSERVATION_PLAN_2, cid=use["reading"])
    correspondence = rig.one(CORRESPONDENCE)
    value = deepcopy(correspondence.value)
    if change == "correspondence": value["pairs"] = [["A", "B"], ["B", "A"]]
    else:
        value["observation_model"] = next(m.cid for m in rig.facts(MODEL)
            if m.value["declared_at"]["slot"] == "alternative-0")
    alternate = belief1_clone(rig, correspondence, value)
    plan = deepcopy(old.value)
    plan["projection"]["args"].update(correspondence=alternate, observation_model=value["observation_model"])
    changed = belief1_clone(rig, old, plan)
    value = deepcopy(q.value)
    value["desc"]["args"]["observations"][0]["reading"] = changed
    additional = {changed, alternate, plan["projection"]["args"]["observation_model"]}
    value["desc"]["input_points"] = sorted(set(value["desc"]["input_points"]) | additional)
    value["desc"]["numerical_view"]["boundary"] = sorted(set(value["desc"]["numerical_view"]["boundary"]) | additional)
    control = belief1_direct(rig, q, value=value)
    assert isinstance(control, u.IssuedUpdate), control
    assert plain(control.result) == ({"joint": [[3, 4], [1, 4]], "evidence_mass": [1, 2]}
        if change == "correspondence" else {"joint": [[2, 3], [1, 3]], "evidence_mass": [3, 8]})
    value["desc"]["args"]["prior"] = adopted.cid
    ret = belief1_direct(rig, q, value=value)
    assert isinstance(ret, u.Rejected) and {i.code for i in ret.issues} == {"measurement_conflict"}


@pytest.mark.parametrize("defect", ["bare-contract-ref", "nonempty-args"])
def test_belief1_U_requires_exact_time_projection_call_shape(make_belief1, defect):
    """K28-a(f): a correct kernel cannot excuse a different time_projection call value."""
    rig = make_belief1(symbols=(T,))
    rig.begin(); rig.publish(0, last=True)
    work, _ = rig.update()
    q = rig.one(c.WORK_REQUESTED, cid=work.request)
    use, = q.value["desc"]["args"]["observations"]
    plan = rig.one(c.OBSERVATION_PLAN_2, cid=use["reading"])
    valid = deepcopy(plan.value)
    assert valid["projection"]["args"]["time_projection"] == {
        "contract": wire(contract("sui.f.value_only")), "args": {}}
    for bad in (False, True):
        value = deepcopy(valid)
        if bad:
            value["projection"]["args"]["time_projection"] = (wire(contract("sui.f.value_only"))
                if defect == "bare-contract-ref" else {"contract": wire(contract("sui.f.value_only")), "args": {"extra": True}})
        changed = belief1_clone(rig, plan, value)
        request_value = deepcopy(q.value)
        request_value["desc"]["args"]["observations"][0]["reading"] = changed
        request_value["desc"]["input_points"] = sorted(set(request_value["desc"]["input_points"]) | {changed})
        request_value["desc"]["numerical_view"]["boundary"] = sorted(set(request_value["desc"]["numerical_view"]["boundary"]) | {changed})
        ret = belief1_direct(rig, q, value=request_value)
        if not bad:
            assert isinstance(ret, u.IssuedUpdate), ret
            assert plain(ret.result) == EXPECTED[0]
        else:
            assert isinstance(ret, u.Rejected) and ret.issues
            assert all(issue.code != "model_falsified" for issue in ret.issues)


@pytest.mark.parametrize("defect", ["missing-frame", "missing-raw", "foreign-run-raw"])
def test_belief1_U_keeps_reference_and_run_checks_in_the_reader(make_belief1, defect):
    """K28 :4346: authentic host origin does not excuse incomplete or wrong-run numerical inputs."""
    rig = make_belief1(symbols=(T,))
    rig.begin(); raw, (_, frame) = rig.publish(0, last=True)
    q, _ = rig.callback("belief_update")
    records = rig.records()
    if defect == "missing-frame": records.pop(frame.cid)
    elif defect == "missing-raw": records.pop(raw[1].cid)
    else:
        original = records[raw[1].cid]
        other = replace(original, at=replace(original.at, run=Ref(kind=RefKind.RUN, value="belief1-other-run")))
        assert other.body == original.body and other.id == original.id
        records[raw[1].cid] = other
    ret = belief1_direct(rig, q, records=records)
    assert isinstance(ret, u.Rejected), ret
    if defect.startswith("missing-"):
        assert {issue.code for issue in ret.issues} == {"unresolved_reference"}
    assert all(i.code != "model_falsified" for i in ret.issues)
    assert not rig.facts(c.BELIEF_ADOPTED)


def test_belief1_U_rejects_consistent_prior_chain_from_another_origin(make_belief1):
    """K28 :4257: model/previous coherence alone is insufficient; every origin must match Q.reader."""
    from test_fb_loop import ORIGIN
    rig = make_belief1(symbols=(T, E))
    rig.begin(); rig.publish(0); _, adopted = rig.update(); rig.publish(1, last=True)
    q, _ = rig.callback("belief_update")
    origin = rig.one(ORIGIN)
    other = belief1_clone(rig, origin, origin.value)
    value = deepcopy(q.value); value["desc"]["reader"] = other
    ret = belief1_direct(rig, q, value=value)
    assert isinstance(ret, u.Rejected), ret
    assert all(i.code != "model_falsified" for i in ret.issues)
    assert ret.issues
    assert rig.one(c.BELIEF_ADOPTED, cid=adopted.cid).value["origin"] != other


@pytest.mark.parametrize("via_prior", [False, True])
def test_belief1_U_rejects_mixed_acquisition_and_Claim_series_including_prior(make_belief1, via_prior):
    """K28 decision 7: Claim-only control issues; adding a Frame, even through prior, is missing_contract."""
    from test_fb_update_entry import world, request as claim_request
    rig = make_belief1(symbols=(T,))
    rig.begin(); rig.publish(0, last=True); work, adopted = rig.update()
    q = rig.one(c.WORK_REQUESTED, cid=work.request)
    reader, claim_world = world()
    # U's input is a reader, not a producer Post. Rebind both declarations to the
    # same child model and origin; only the unsupported combination is different.
    for rec in reader.records.values():
        value = rec.body.content.as_json()
        if isinstance(value, dict) and value.get("model") == claim_world.model:
            value["model"] = rig.model_point
            rec.body.content = SimpleNamespace(as_json=lambda value=value: value)
    claim_world.model = rig.model_point
    cq = claim_request(reader, "K28-claim-only", claim_world, ("b1",))
    claim_value = reader.records[cq].body.content.as_json()
    claim_value["desc"]["reader"] = q.value["desc"]["reader"]
    reader.records[cq].body.content = SimpleNamespace(as_json=lambda: claim_value)
    merged = {**rig.records(), **reader.records}
    control = u.compute_finite_update(cq, reader=BeliefSnapshotReader(merged), registry=rig.registry, evidence=None)
    assert isinstance(control, u.IssuedUpdate), control
    value = deepcopy(claim_value)
    if via_prior: value["desc"]["args"]["prior"] = adopted.cid
    else: value["desc"]["args"]["observations"] += deepcopy(q.value["desc"]["args"]["observations"])
    mixed = belief1_clone(rig, q, value)
    merged[mixed] = rig.read_stored(mixed)[2]
    ret = u.compute_finite_update(mixed, reader=BeliefSnapshotReader(merged), registry=rig.registry, evidence=None)
    assert isinstance(ret, u.Rejected) and {i.code for i in ret.issues} == {"missing_contract"}


@pytest.mark.parametrize("continuation", [False, True])
def test_belief1_continuation_reads_the_adopted_result_and_new_joint(make_belief1, continuation):
    """K28 migration category 1: host evaluation reads adopted R, not a U-only stand-in or model.initial."""
    rig = make_belief1(symbols=(T, E), continuation=continuation)
    rig.begin()
    for stage in ORDER: rig.run_stage(stage)
    rig.until(lambda: len(rig.facts(c.SELECTION)) == 1)
    first_eq, = rig.requests("evaluation_prepare")
    previous = None
    for i, expected in enumerate(EXPECTED[:2]):
        rig.publish(i, last=i == 1)
        work, adopted = rig.update()
        result = assert_update(rig, work, adopted, expected, previous); previous = adopted.cid
        for _ in range(3): rig.round()
        if not continuation:
            assert [q.cid for q in rig.requests("evaluation_prepare")] == [first_eq.cid]
            continue
        rig.until(lambda: len(rig.requests("evaluation_prepare")) == i+2)
        eq = rig.requests("evaluation_prepare")[-1]
        activity = assert_admitted_evaluation_root(rig, eq, adopted)
        assert {adopted.cid, result.cid, adopted.value["acquisition"]} <= closure(rig, eq.value["desc"]["numerical_view"]["boundary"])
        for stage in ("evaluation_prepare", "selection_draw", "evaluation"): rig.run_stage(stage)
        prepared = rig.workers.prepared_by_request[eq.cid].value
        evaluated = rig.workers.evaluated_by_request[rig.requests("evaluation")[-1].cid].value
        assert prepared.K.belief == evaluated.root.K.belief == rig.read_stored(result.cid)[2].id
        rig.until(lambda: len(rig.facts(c.SELECTION)) == i+2)
        wait_evaluation_activity_end(rig, activity)
    belief1_chain(rig, EXPECTED[:2])


@pytest.mark.parametrize("visible", [False, True], ids=["root-before-adoption", "root-after-adoption"])
def test_belief1_initial_evaluation_reads_only_the_adoption_in_its_fixed_roots(make_belief1, visible):
    """Retain the initial-evaluation positive controls of the retired use-gate cases.

    Ignoring h in the frozen root, or reading a later h absent from that root,
    fails K.belief=None versus the exact adopted R* record id. Production
    acquisition/update run while the TEST computing worker is not invoked.
    No clock ambiguity is substituted for the now-unreachable use conflict.
    """
    def capacity(rig):
        # Measure=1, initial thinking=2, updater=2 may coexist by declaration.
        rig.boot_input = replace(rig.boot_input, declaration=replace(rig.boot_input.declaration,
            capacity=fb.QuantityValue(contract=c.SEATS, value=5)))
    rig = make_belief1(symbols=(T,), before_host=capacity)
    rig.begin()
    candidate_q, _ = rig.callback("candidate_generation")
    if not visible:
        rig.run_stage("candidate_generation")
        rig.until(lambda: len(rig.requests("evaluation_prepare")) == 1)
    rig.publish(0, last=True)
    work, adopted = rig.update()
    result = assert_update(rig, work, adopted, EXPECTED[0])
    assert adopted.cid not in closure(rig, candidate_q.value["desc"]["input_points"])
    if visible:
        rig.run_stage("candidate_generation")
        rig.until(lambda: len(rig.requests("evaluation_prepare")) == 1)
    eq, = rig.requests("evaluation_prepare")
    fixed = eq.value["desc"]["args"]["input"]["fixed_parents"]
    assert (adopted.cid in closure(rig, fixed)) is visible
    preserved = {cid: rig.read_stored(cid) for cid in rig.records()}
    for stage in ORDER[1:]: rig.run_stage(stage)
    rig.until(lambda: len(rig.facts(c.SELECTION)) == 1)
    prepared = rig.workers.prepared_by_request[eq.cid].value
    evaluated = rig.workers.evaluated_by_request[rig.requests("evaluation")[-1].cid].value
    expected = rig.read_stored(result.cid)[2].id if visible else None
    assert prepared.K.belief == evaluated.root.K.belief == expected
    assert all(rig.read_stored(cid) == saved for cid, saved in preserved.items())
    assert rig.host.halted is None


def test_belief1_unreadable_delta_is_visible_before_any_update_or_acquisition(make_belief1):
    """K28 B1: a missing method is reported, never counted as a correct numerical noop."""
    belief1_api(status=True)
    rig = make_belief1(symbols=(T,), delta=contract("test.undeclared_delta"))
    rig.begin(); rig.publish(0, last=True)
    for _ in range(4): rig.round()
    assert not rig.requests("belief_update") and not rig.facts(c.BELIEF_ADOPTED)
    boot_point = rig.one(c.BOOT_DECLARATION).cid
    assert any(p.reason == "delta:method" and p.target == boot_point for p in rig.host.window.status().pending)
    assert rig.host.halted is None


def test_belief1_saved_but_unconfirmed_adoption_blocks_the_next_request(make_belief1):
    """K28 decision 5: physically present A0 is not a confirmed predecessor; retry identical preparation."""
    belief1_api(status=True)
    rig = make_belief1()
    rig.begin()
    for i in range(3): rig.publish(i, last=i == 2)
    write, lost, armed = rig.ledger.write, [], [True]
    def lose_ack(prepared):
        if prepared.record.body.contract == c.BELIEF_ADOPTED and armed[0]:
            result = write(prepared)
            lost.append(prepared)
            raise OSError("test A0 committed but unconfirmed")
        return write(prepared)
    rig.ledger.write = lose_ack
    q, body = rig.callback("belief_update")
    assert belief1_status(rig, 0).outcome == "requested"
    rig.executed.add(q.value["desc"]["work_id"]); body()
    rig.until(lambda: bool(lost))
    assert len(rig.facts(c.BELIEF_ADOPTED)) == 1
    assert len(rig.requests("belief_update")) == 1
    row = belief1_status(rig, 0)
    assert row.outcome == "waiting_confirmation" and row.adopted_through is None
    assert belief1_status(rig, 1).outcome == "waiting_predecessor"
    # Reception remains independent of confirmation of this prepared adoption.
    rig.host.post(fb.Received(route_epoch=ROUTE, media_type="text/plain", data=b"unrelated", claims={}))
    rig.round()
    assert len(rig.requests("belief_update")) == 1
    armed[0] = False
    rig.until(lambda: belief1_status(rig, 0).outcome == "adopted")
    rig.update(); rig.update(); belief1_chain(rig)
    assert any(r.value["data"] == list(b"unrelated") for r in rig.facts(c.RECEIVED))
    assert all(p.cid == lost[0].cid and p.record == lost[0].record for p in lost)
    assert rig.requests("belief_update")[1].value["desc"]["args"]["prior"] == lost[0].cid
    assert len(rig.calls) == 3 and len(rig.workers.entries) == len({w.desc.work_id for w in rig.workers.entries})


def test_belief1_clock_conflict_after_request_waits_for_recording_and_preserves_facts(make_belief1):
    """K28-b(b): clock ambiguity waits at recording/clock, NOT the use-conflict gate.

    Calling this conflicted, entering twice, losing old facts or adopting without
    a clock source fails. Conflicting acquired Frames cannot be made at this API.
    """
    belief1_api(status=True)
    rig = make_belief1(symbols=(T,))
    rig.begin(); rig.publish(0, last=True)
    q, body = rig.callback("belief_update")
    preserved = {cid: rig.read_stored(cid) for cid in rig.records()}
    rig.host.post(fb.ClockDeclared(declaration=replace(rig.clock_declaration, implementation="incompatible-clock")))
    for _ in range(3): rig.round()
    rig.executed.add(q.value["desc"]["work_id"])
    body()
    rig.until(lambda: belief1_status(rig, 0).outcome == "recording")
    assert not rig.facts(c.BELIEF_ADOPTED)
    result, = rig.facts(c.UPDATE_RESULT)
    assert result.value["request"] == q.cid and result.value["result"] == EXPECTED[0]
    assert not [g for g in rig.facts(contract("sui.f.content_acquired")) if result.cid in g.value["contents"]]
    row = belief1_status(rig, 0)
    assert row.request == q.cid and row.reasons == ("clock",)
    use, = rig.update_ports[q.cid].work.desc.args.observations
    assert row.obligation == use.binding
    observed = rig.update_ports[q.cid].evidence()
    own, = (e for e in observed.executions if e.work_id == q.value["desc"]["work_id"])
    assert own.entered == 1 and own.stopped
    for _ in range(3): rig.round()
    assert belief1_status(rig, 0).outcome == "recording" and not rig.facts(c.BELIEF_ADOPTED)
    assert rig.host.halted is None
    assert all(rig.read_stored(cid) == value for cid, value in preserved.items())
    assert rig.host.halted is None


def test_belief1_monitored_is_the_worker_supplied_interval_not_an_acquisition(make_acquire_rig):
    """K28 B3': EI is exactly the interval supplied by the worker; it does not imply source acquisition."""
    rig = make_acquire_rig(acquire1_api(), script=acquire1_quiet)
    key = rig.launch("measure_segment")
    assert rig.started.setdefault(key, Event()).wait(30)
    port = rig.ports[key]
    rig.clock.set(rig.clock.peek()+100)
    interval = f.MeasurementInterval(clock=rig.clock.run, start_ns=0, end_ns=1, closure="(start,end]")
    before = port.evidence()
    port.monitored(interval)
    after = port.evidence()
    assert len(after.intervals) == len(before.intervals)+1
    assert after.intervals[-1].work_id == key and after.intervals[-1].interval == interval
    assert after.sources == before.sources == ()
    assert not rig.source.calls and not rig.calls


@pytest.mark.parametrize("rid", tuple(rid for rid in RAW_FIELD_PROBES if closed_raw_field_probe(rid)))
def test_belief1_closed_raw_field_ingress_is_rejected(rid, stage1_rig):
    """Retain former stage-1 field cases here, inside the closed-ingress exception.

    A malformed variant and its well-typed but unauthorised original both leave
    no record/custody. These are ingress refusals, not isolated proof of an inner
    Frame-field validator: the closest legal Frame comes from SourceMeasurer.
    """
    rig = stage1_rig
    probe = RAW_FIELD_PROBES[rid]
    event = RAW_EXAMPLES[probe["example"]]
    bad = malformed_raw_example(probe)
    before = rig.storage_snapshot()
    if bad is not None:
        with pytest.raises(fb.FbInputError) as caught:
            rig.host.window.accept(rig.envelope(1, bad, 30))
        assert caught.value.reason == "shape" and caught.value.field.startswith("/")
    assert rig.storage_snapshot() == before
    with pytest.raises(fb.FbInputError):
        rig.host.window.accept(rig.envelope(2, event, 30))
    assert rig.storage_snapshot() == before and not rig.facts(c.SEGMENT_REPORT)
    assert rig.host.window.status().receipts == ()


@pytest.mark.parametrize("rid", tuple(rid for rid in RAW_BRANCH_PROBES if closed_raw_branch_probe(rid)))
def test_belief1_closed_raw_branch_contrasts_are_ingress_refusals(rid, stage1_rig):
    """Retain the former branch pairs here; only still-open foils are raw positives."""
    rig = stage1_rig
    probe = RAW_BRANCH_PROBES[rid]
    saved = []
    for number, value in enumerate((probe["event"], probe["foil"]), 1):
        if closed_raw_event(value):
            before = rig.storage_snapshot()
            with pytest.raises(fb.FbInputError):
                rig.host.window.accept(rig.envelope(number, value, 30))
            assert rig.storage_snapshot() == before
        else:
            saved.extend(accept_and_save(rig, rig.envelope(number, value, 30),
                                        c.SEGMENT_REPORT, len(saved) + 1)[-1:])
    assert len(rig.facts(c.SEGMENT_REPORT)) == len(saved)
    assert not rig.facts(c.SEGMENT_BINDING)


@pytest.mark.parametrize("kind", ["coverage_unproved", "gap", "measurement_unavailable"])
def test_only_unproved_may_name_a_future_window(make_belief1, kind):
    """K28/Z56: future Unproved remains open; closed interval branches are refused.

    Gap/Unavailable no longer reach the interval:after_receipt B diagnostic.
    A production acquisition supplies the real work, clock and Started.
    """
    def reading(rig):
        route, = rig.boot_input.declaration.routes
        rig.boot_input = replace(rig.boot_input, declaration=replace(rig.boot_input.declaration,
            routes=(replace(route, value=replace(route.value, reading_contract=c.FINITE_SEGMENT_PROJECTION)),)))
    rig = make_belief1(symbols=(T,), before_host=reading)
    rig.hold_return = True  # do not let a real Ended close the future-window scene
    rig.begin(); rig.publish(0, last=True); rig.clock.set(230)
    period = f.MeasurementInterval(clock=rig.clock.run, start_ns=215, end_ns=260, closure="(start,end]")
    item = segment_items()[kind]
    field = "requested_interval" if kind == "measurement_unavailable" else "interval"
    event = fb.SegmentReport(segment=rig.calls[0].work.request, item_slot="future-window",
        item=replace(item, **{field:period, "route_epoch":ROUTE, "evidence":()}))
    if kind == "coverage_unproved":
        rig.ports[rig.measure_key].post(event)
        rig.until(lambda: any(r.value == wire(event) for r in rig.reports(kind)))
        raw, = [r for r in rig.reports(kind) if r.value == wire(event)]
        rig.until(lambda: any(b.value["report"] == raw.cid for b in rig.facts(c.SEGMENT_BINDING)))
        assert not any(p.target == raw.cid and p.reason == "interval:after_receipt" for p in rig.host.window.status().pending)
    else:
        before = (rig.records(), rig.receipts(), rig.ports[rig.measure_key].evidence())
        with pytest.raises(TypeError): rig.ports[rig.measure_key].post(event)
        with pytest.raises(fb.FbInputError): rig.host.window.accept(fb.Envelope(number=10000, event=event, received_ns=230))
        assert (rig.records(), rig.receipts(), rig.ports[rig.measure_key].evidence()) == before


def test_outside_frame_naming_a_real_segment_is_rejected_without_binding(make_belief1):
    """Z55 now refuses the outside Frame; authentic retry keeps its sole B.

    Saving an unauthenticated original or binding it fails the new entrance.
    """
    from test_fb_acquisition_pending import original_envelopes
    rig = make_belief1(symbols=(T,)); rig.begin(); rig.publish(0, last=True)
    envelope = original_envelopes(rig, rig.calls[0])[-1]
    before = (rig.records(), rig.receipts(), rig.ports[rig.measure_key].evidence())
    with pytest.raises(TypeError): rig.host.post(envelope.event)
    assert (rig.records(), rig.receipts(), rig.ports[rig.measure_key].evidence()) == before
    rig.host.window.accept(envelope)
    for _ in range(3): rig.round()
    frames = {r.cid for r in rig.reports("frame")}
    assert len(frames) == len([b for b in rig.facts(c.SEGMENT_BINDING) if b.value["report"] in frames]) == 1


@pytest.mark.parametrize("wrong", [False, True])
def test_acquired_frame_route_cannot_be_changed_on_replay(make_belief1, wrong):
    """Only the original acquired route may be replayed; changed route is refused.

    The former forged-Frame route:epoch B path is now unreachable, not Conflict.
    """
    from test_fb_acquisition_pending import original_envelopes
    rig = make_belief1(symbols=(T,)); rig.begin(); rig.publish(0, last=True)
    envelope = original_envelopes(rig, rig.calls[0])[-1]
    before = rig.records()
    if wrong:
        frame = envelope.event.item
        changed = replace(frame, route_epoch="other-epoch",
            measurement_id=replace(frame.measurement_id, route_epoch="other-epoch"))
        with pytest.raises(fb.FbInputError): rig.host.window.accept(replace(envelope,
            event=replace(envelope.event, item=changed)))
        assert rig.records() == before
    else: rig.host.window.accept(envelope)
    for _ in range(3): rig.round()
    frames = {r.cid for r in rig.reports("frame")}
    assert len(frames) == len([b for b in rig.facts(c.SEGMENT_BINDING) if b.value["report"] in frames]) == 1


@pytest.mark.parametrize("collision", [False, True])
def test_native_sample_numbers_are_distinct_and_forged_collision_is_rejected(make_belief1, collision):
    """Native MIDs 0/1 learn twice; the old forged collision is refused, not Conflict.

    Two T operations give M_T^2=3/16 I, q=(1/2,1/2), Z=3/16. Dropping or
    recounting the second fails that hand value and the exact adoption chain.
    """
    from test_fb_acquisition_pending import original_envelopes
    rig = make_belief1(symbols=(T,T)); rig.begin(); rig.publish(0); _, first = rig.update()
    rig.publish(1, last=True)
    envelope = original_envelopes(rig, rig.calls[1])[-1]
    assert [r.value["item"]["value"]["sample_seq"] for r in rig.reports("frame")] == [0,1]
    assert rig.calls[0].acquired.item.data == rig.calls[1].acquired.item.data
    if collision:
        old = envelope.event.item
        changed = replace(old, sample_seq=0, measurement_id=replace(old.measurement_id, sample_seq=0))
        before = rig.records()
        with pytest.raises(fb.FbInputError): rig.host.window.accept(replace(envelope, event=replace(envelope.event,item=changed)))
        assert rig.records() == before
    else: rig.host.window.accept(envelope)
    work, second = rig.update()
    assert_update(rig, work, second, {"joint":[[1,2],[1,2]], "evidence_mass":[3,16]}, first.cid)
    frames = {r.cid for r in rig.reports("frame")}
    assert len([b for b in rig.facts(c.SEGMENT_BINDING) if b.value["report"] in frames]) == len(rig.facts(c.BELIEF_ADOPTED)) == 2
    assert not rig.facts(c.CONFLICT)


from test_fb_measure import acquire1_started, acquire1_frame, acquire1_corresponds

@pytest.mark.parametrize("fault", ["no-acquisition", "wrong-raw-id", "different-port", "early-actual-time"])
def test_acquire1_worker_frame_outside_acquire_is_rejected_without_losing_original(make_acquire_rig, fault):
    """K28 decision 4 replaces deferred correspondence checking with producer rejection.

    Preserve no-acquisition, wrong raw, wrong time and different-port scenes.
    A real acquire still saves its original pair; the forged Frame never enters.
    """
    api = acquire1_api()
    rejected = []
    finished = Event()
    def attempt(ctx, event):
        try: ctx.post(event)
        except TypeError as error: rejected.append(type(error))
        finally: finished.set()
    def script(rig, work, ctx):
        before = acquire1_started(rig, work, ctx)
        if fault == "no-acquisition":
            rig.clock.set(rig.clock.peek() + 2)
            frame = acquire1_frame(0, before, ctx.now(), cursor=0, called=True, result={"kind": "empty"})
        else:
            a = ctx.acquire()
            received_id = (rig.other_events.get(timeout=30) if fault in ("early-actual-time", "different-port")
                else str(Ref(kind=RefKind.OBSERVATION, value="acquire1-unrelated")))
            frame = acquire1_frame(0, a.before, a.after, cursor=0, called=True,
                result={"kind": "taken", "received": received_id})
            if fault == "early-actual-time": frame = replace(frame, actual_time=a.before.reading)
        rig.forged = fb.SegmentReport(segment=work.request, item_slot="forbidden-frame", item=frame)
        if fault == "different-port": rig.other_events.put(rig.forged)
        else: attempt(ctx, rig.forged)
        rig.action_done.set()
        assert rig.release.wait(30)
    def other(rig, work, ctx):
        event = rig.other_events.get(timeout=30)
        if event is not None: attempt(ctx, event)
    rig = make_acquire_rig(api, items=(acquire1_item(api),), script=script,
        compute=other if fault == "different-port" else None)
    rig.launch("measure_segment")
    if fault in ("early-actual-time", "different-port"):
        rig.wait_returns(); raw, _ = rig.saved_pair(rig.calls[0])
        rig.other_events.put(str(raw[1].record_id))
    assert rig.action_done.wait(30)
    if fault == "different-port": rig.launch("candidate_generation")
    assert finished.wait(30)
    assert rejected == [TypeError]
    for _ in range(3): rig.round()
    assert not any(r.value["item_slot"] == "forbidden-frame" for r in rig.reports("frame"))
    if fault == "no-acquisition":
        assert not rig.calls and not rig.facts(c.RECEIVED) and not rig.reports("frame")
    else:
        raw, (_, original) = rig.saved_pair(rig.calls[0])
        assert acquire1_corresponds(rig, original, rig.calls[0])
        assert raw[1].value["data"] == wire(RAW)
        assert len(rig.reports("frame")) == 1
    rig.no_belief_update()


@pytest.mark.parametrize("kind,reason", [("same-id", "report:identity"), ("same-sequence", "frame:sample_seq")])
def test_acquire1_worker_extra_frame_is_rejected_before_conflict_material(make_acquire_rig, kind, reason):
    """K28 Z55: neither an extra MID nor a changed body is producer evidence."""
    api = acquire1_api()
    denied = []
    def script(rig, work, ctx):
        acquire1_started(rig, work, ctx)
        a = ctx.acquire()
        frame = acquire1_frame(0, a.before, a.after, cursor=0, called=True, result={"kind": "empty"})
        if kind == "same-sequence":
            frame = replace(frame, measurement_id=replace(frame.measurement_id, component="another_measurement"))
        try: ctx.post(fb.SegmentReport(segment=work.request, item_slot="worker-frame", item=frame))
        except TypeError: denied.append(True)
        rig.action_done.set()
        assert rig.release.wait(30)
    rig = make_acquire_rig(api, items=(acquire1_item(api),), script=script)
    rig.launch("measure_segment")
    assert rig.action_done.wait(30)
    assert denied == [True]
    raw, (_, original) = rig.saved_pair(rig.calls[0])
    assert acquire1_corresponds(rig, original, rig.calls[0])
    assert len(rig.reports("frame")) == len(rig.facts(c.RECEIVED)) == 1
    assert not any(p.kind == "conflict" and p.target == original.cid for p in rig.host.window.status().pending)
    rig.no_belief_update()


def test_belief1_U_binding_frame_must_be_in_declared_inputs_even_with_same_MID_substitute(make_belief1):
    """K28 decision 6 / K28-b(se)-1: B selects a Point, not just a MID.

    p0=(3/4,1/4): T p0=(1/16,9/16), so q=(1/10,9/10), Z=5/8.
    E p0=(3/16,3/16), so q=(1/2,1/2), Z=3/8. Substituting the
    latter Frame must reject observation_binding_mismatch, never issue it or
    call it model_falsified. Searching the whole reader for the omitted T
    Frame also fails: only Q's declared input_points are permission to read it.
    """
    rig = make_belief1(symbols=(T,), prior=(Q(3, 4), Q(1, 4)))
    rig.begin()
    _raw, (_, frame) = rig.publish(0, last=True)
    work, adopted = rig.update()
    q = rig.one(c.WORK_REQUESTED, cid=work.request)
    original = belief1_direct(rig, q)
    expected = {"joint": [[1, 10], [9, 10]], "evidence_mass": [5, 8]}
    assert isinstance(original, u.IssuedUpdate) and plain(original.result) == expected
    belief1_chain(rig, (expected,))

    other = deepcopy(frame.value)
    other["item"]["value"]["value"]["value"]["result"] = {"kind": "empty"}
    substitute = belief1_clone(rig, frame, other)
    # Only result differs; the first cursor remains zero for either outcome.
    restored = deepcopy(other)
    restored["item"]["value"]["value"]["value"]["result"] = deepcopy(
        frame.value["item"]["value"]["value"]["value"]["result"])
    assert restored == frame.value and other != frame.value
    assert other["item"]["value"]["measurement_id"] == frame.value["item"]["value"]["measurement_id"]
    assert other["item"]["value"]["value"]["value"]["cursor"] == 0
    records = rig.records()
    empty_only = {cid: record for cid, record in records.items() if cid != frame.cid}
    read = fb.read_acquisition_sequence(empty_only, model=rig.one(MODEL).cid,
        run=rig.clock.run, route_epoch=ROUTE, through_seq=0)
    assert read.kind == "read" and read.likelihood == (Q(1, 4), Q(3, 4))
    assert belief1_enumerate(RULER, (E,), (Q(3, 4), Q(1, 4)))[:2] == ((Q(1, 2), Q(1, 2)), Q(3, 8))

    value = deepcopy(q.value)
    use, = value["desc"]["args"]["observations"]
    assert rig.one(c.SEGMENT_BINDING, cid=use["binding"]).value["report"] == frame.cid
    assert frame.cid in value["desc"]["input_points"]
    value["desc"]["input_points"] = sorted((set(value["desc"]["input_points"]) - {frame.cid}) | {substitute})
    value["desc"]["numerical_view"]["boundary"] = sorted(
        (set(value["desc"]["numerical_view"]["boundary"]) - {frame.cid}) | {substitute})
    assert value["desc"]["args"]["observations"] == q.value["desc"]["args"]["observations"]
    assert frame.cid in records and substitute in records  # Wider reader is deliberately still complete.
    ret = belief1_direct(rig, q, value=value, records=records)
    assert isinstance(ret, u.Rejected), ret
    assert {issue.code for issue in ret.issues} == {"observation_binding_mismatch"}
    assert [a.cid for a in rig.facts(c.BELIEF_ADOPTED)] == [adopted.cid]


def test_belief1_U_symmetric_kernel_still_conflicts_on_changed_correspondence_replay(make_belief1):
    """K28 decision 6 / K28-b(se)-2: equal numbers do not imply equal meaning.

    T=E=(1/2)I and p0=(1/2,1/2) give q=(1/2,1/2), Z=1/2 under
    either map. Ignoring the canonical correspondence because the permuted
    kernel is numerically unchanged wrongly makes the adopted-MID replay a noop.
    The changed map alone must still issue; only replay under prior conflicts.
    """
    half_identity = ((Q(1, 2), 0), (0, Q(1, 2)))
    rig = make_belief1(symbols=(T,), matrices={T: half_identity, E: half_identity})
    rig.begin(); rig.publish(0, last=True)
    work, adopted = rig.update()
    q = rig.one(c.WORK_REQUESTED, cid=work.request)
    expected = {"joint": [[1, 2], [1, 2]], "evidence_mass": [1, 2]}
    belief1_chain(rig, (expected,))
    original = belief1_direct(rig, q)
    assert isinstance(original, u.IssuedUpdate) and plain(original.result) == expected
    use, = q.value["desc"]["args"]["observations"]
    reading = rig.one(c.OBSERVATION_PLAN_2, cid=use["reading"])
    correspondence = rig.one(CORRESPONDENCE)
    alternate = deepcopy(correspondence.value)
    assert alternate["pairs"] == [["A", "A"], ["B", "B"]]
    alternate["pairs"] = [["A", "B"], ["B", "A"]]
    changed_correspondence = belief1_clone(rig, correspondence, alternate)
    plan = deepcopy(reading.value)
    plan["projection"]["args"]["correspondence"] = changed_correspondence
    changed_reading = belief1_clone(rig, reading, plan)
    value = deepcopy(q.value)
    value["desc"]["args"]["observations"][0]["reading"] = changed_reading
    additional = {changed_correspondence, changed_reading}
    value["desc"]["input_points"] = sorted(set(value["desc"]["input_points"]) | additional)
    value["desc"]["numerical_view"]["boundary"] = sorted(set(value["desc"]["numerical_view"]["boundary"]) | additional)
    assert value["desc"]["args"]["prior"] is None
    changed_first = belief1_direct(rig, q, value=value)
    assert isinstance(changed_first, u.IssuedUpdate) and plain(changed_first.result) == expected
    assert changed_first.application_digest != original.application_digest
    value["desc"]["args"]["prior"] = adopted.cid
    ret = belief1_direct(rig, q, value=value)
    assert isinstance(ret, u.Rejected) and {issue.code for issue in ret.issues} == {"measurement_conflict"}, ret
    assert [a.cid for a in rig.facts(c.BELIEF_ADOPTED)] == [adopted.cid]


@pytest.mark.parametrize("field", ["route", "observation_model"])
@pytest.mark.parametrize("malformed", [False, True], ids=["string-control", "list-is-not-a-slot-name"])
def test_belief1_delta_slot_name_type_is_pending_args_not_a_halted_host(make_belief1, field, malformed):
    """K28-b(u,e,se)-3: three present keys do not excuse a non-string slot name.

    Dictionary lookup before shape validation halts on []; silently ignoring the
    malformed value loses delta:args. Legal names save correspondence and reading.
    Only keep_running advances this Boot; no manual retry or fabricated adoption.
    """
    belief1_api(status=True)
    def mutate(model, args):
        if malformed: args[field] = []
        assert set(args) == {"route", "observation_model", "correspondence"}
        assert args["correspondence"] == {"pairs": [["A", "A"], ["B", "B"]]}
        assert args["observation_model" if field == "route" else "route"] == (
            "observation" if field == "route" else "route")
        return model, args
    rig = make_belief1(symbols=(T,), mutate=mutate, defer_boot=True)
    def done(status):
        if malformed: return any(p.reason == "delta:args" for p in status.pending)
        return bool(rig.facts(CORRESPONDENCE)) and bool(rig.facts(c.OBSERVATION_PLAN_2))
    assert rig.host.keep_running(done, timeout=10), "Boot did not reach its declared delta outcome"
    status = rig.host.window.status()
    boot_point = rig.one(c.BOOT_DECLARATION).cid
    if malformed:
        assert any(p.reason == "delta:args" and p.target == boot_point for p in status.pending)
        assert not rig.facts(CORRESPONDENCE) and not rig.facts(c.OBSERVATION_PLAN_2)
    else:
        assert not any(p.reason.startswith("delta:") and p.target == boot_point for p in status.pending)
    assert not rig.requests("belief_update") and not rig.facts(c.BELIEF_ADOPTED)
    assert rig.host.halted is None and not rig.host.interruptions()


@pytest.mark.parametrize("changed", [False, True], ids=["same-original", "changed-original"])
def test_acquire1_original_frame_on_another_segment_is_closed_at_post(make_acquire_rig, changed):
    """K28: a second producer cannot repost even the unchanged original Frame.

    Same-MID numerical replay/conflict now lives at U's direct reader boundary.
    """
    api = acquire1_api()
    denied = []
    done = Event()
    def script(rig, work, ctx):
        acquire1_started(rig, work, ctx)
        if work.desc.process.slot == "sensing":
            assert rig.acquire_release.wait(30)
            ctx.acquire()
            assert rig.release.wait(30)
        else:
            rig.other_ready.set()
            frame = rig.other_events.get(timeout=30)
            if frame is not None:
                try: ctx.post(fb.SegmentReport(segment=work.request, item_slot="same-original", item=frame))
                except TypeError: denied.append(True)
                done.set()
    rig = make_acquire_rig(api, items=(acquire1_item(api),), script=script, segments=2)
    first = rig.launch("measure_segment", "sensing")
    rig.launch("measure_segment", "sensing-2")
    assert rig.started.setdefault(first, Event()).wait(30) and rig.other_ready.wait(30)
    rig.acquire_release.set(); rig.wait_returns()
    call, = rig.calls
    raw, (_, original) = rig.saved_pair(call)
    frame = acquire1_expected_frame(rig, call, raw[1])
    if changed: frame = replace(frame, value={**frame.value, "result": {"kind": "empty"}})
    rig.other_events.put(frame)
    assert done.wait(30)
    assert denied == [True]
    for _ in range(3): rig.round()
    assert len(rig.reports("frame")) == 1 and acquire1_corresponds(rig, original, call)
    assert not any(p.kind == "conflict" and p.target == original.cid for p in rig.host.window.status().pending)
    rig.no_belief_update()


@pytest.mark.parametrize("changed_cells", [True, False], ids=["repartitioned-cells", "same-value-new-record"])
def test_belief1_U_cell_partition_is_meaning_but_declaration_point_is_not(make_belief1, changed_cells):
    """K28 decision 6 / K28-b(ta): equal summed matrices cannot identify a reading.

    x=I/10,y=I/5,z=3I/10,w=2I/5 sum to I. Original T={x,y}; changed
    T={z}. Both give (3/20,3/20), hence q=(1/2,1/2), Z=3/10.
    Ignoring cell membership wrongly issues a noop for the changed-MID reading;
    hashing declaration Points instead of values wrongly conflicts for a copy.
    Applying a copied reading twice wrongly gives cumulative Z=9/100.
    Both alternate readings must first issue without prior, so an invalid
    declaration cannot masquerade as the required measurement_conflict.
    """
    matrices = {name: ((mass, Q(0)), (Q(0), mass)) for name, mass in (
        ("x", Q(1, 10)), ("y", Q(1, 5)), ("z", Q(3, 10)), ("w", Q(2, 5)))}
    original_groups = {T: ("x", "y"), E: ("z",), U: ("w",)}
    other_groups = {T: ("z",), E: ("x",), U: ("y", "w")} if changed_cells else original_groups

    def declaration(groups):
        model = read1_model({REPEAT_ID: matrices}, states=("A", "B"),
            groups=groups, schedule=(REPEAT_ID,)).declaration
        return replace(model, control_rule=fb.MethodCall(contract=CONTROL,
            args={"first": [REPEAT_ID], "after": {s: [REPEAT_ID] for s in (T, E, U, M)}}))

    primary, alternate = declaration(original_groups), declaration(other_groups)
    assert sum(matrix[0][0] for matrix in matrices.values()) == 1
    for model, groups in ((primary, original_groups), (alternate, other_groups)):
        control, = model.controls
        assert control.id == control.kernel.id == REPEAT_ID
        assert {out.id: out.matrix for out in control.kernel.outcomes} == matrices
        assert {cell.id: cell.outcomes for cell in control.cells} == groups
        outcomes = {out.id: out for out in control.kernel.outcomes}
        for cell in control.cells:
            expected_value = {"result": "unavailable" if cell.id == U else cell.id, "source_called": True}
            assert wire(cell.observation.value) == expected_value
            for name in cell.outcomes:
                assert outcomes[name].evidence.kind == "measurement"
                assert outcomes[name].evidence.measurement_contract == c.ACQUISITION_RESULT_SAMPLING
                assert wire(outcomes[name].evidence.value) == expected_value
        taken = tuple(tuple(sum((matrices[name][r][col] for name in groups[T]), Q(0))
            for col in range(2)) for r in range(2))
        assert taken == ((Q(3, 10), Q(0)), (Q(0), Q(3, 10)))
        assert belief1_enumerate({T: taken}, (T,))[:2] == ((Q(1, 2), Q(1, 2)), Q(3, 10))

    rig = make_belief1(symbols=(T,), matrices=matrices, outcome_groups=original_groups,
        extra_models=(alternate,))
    declared = {item.slot: item.value for item in rig.boot_input.declaration.observation_models}
    assert declared == {"observation": primary, "alternative-0": alternate}
    assert rig.document["initial"] == [[1, 2], [1, 2]]
    assert {state["target"] for state in rig.document["states"]} == {"box"}
    models = {m.value["declared_at"]["slot"]: m for m in rig.facts(MODEL)}
    assert set(models) == {"observation", "alternative-0"}
    original_model, other_model = models["observation"], models["alternative-0"]
    assert original_model.cid != other_model.cid
    assert original_model.value["declared_at"] != other_model.value["declared_at"]
    assert (original_model.value["value"] != other_model.value["value"]) == changed_cells

    rig.begin(); _raw, (_, frame) = rig.publish(0, last=True)
    work, adopted = rig.update()
    expected = {"joint": [[1, 2], [1, 2]], "evidence_mass": [3, 10]}
    belief1_chain(rig, (expected,))
    assert len(rig.calls) == len(rig.source.calls) == 1
    q = rig.one(c.WORK_REQUESTED, cid=work.request)
    original = belief1_direct(rig, q)
    assert isinstance(original, u.IssuedUpdate) and plain(original.result) == expected
    for model in (original_model, other_model):
        read = fb.read_acquisition_sequence(rig.records(), model=model.cid,
            run=rig.clock.run, route_epoch=ROUTE, through_seq=0)
        assert read.kind == "read" and read.likelihood == (Q(3, 10), Q(3, 10))

    use, = q.value["desc"]["args"]["observations"]
    binding = rig.one(c.SEGMENT_BINDING, cid=use["binding"])
    assert binding.value["report"] == frame.cid
    old_reading = rig.one(c.OBSERVATION_PLAN_2, cid=use["reading"])
    correspondence = rig.one(CORRESPONDENCE)
    pairs = deepcopy(correspondence.value)
    assert pairs["pairs"] == [["A", "A"], ["B", "B"]]
    pairs["observation_model"] = other_model.cid
    other_correspondence = belief1_clone(rig, correspondence, pairs)
    plan = deepcopy(old_reading.value)
    plan["projection"]["args"].update(observation_model=other_model.cid, correspondence=other_correspondence)
    other_reading = belief1_clone(rig, old_reading, plan)
    value = deepcopy(q.value)
    value["desc"]["args"]["observations"][0]["reading"] = other_reading
    assert value["desc"]["args"]["observations"][0]["binding"] == binding.cid
    extra = {other_model.cid, other_correspondence, other_reading}
    value["desc"]["input_points"] = sorted(set(value["desc"]["input_points"]) | extra)
    value["desc"]["numerical_view"]["boundary"] = sorted(set(value["desc"]["numerical_view"]["boundary"]) | extra)
    assert value["desc"]["args"]["prior"] is None
    first = belief1_direct(rig, q, value=value)
    assert isinstance(first, u.IssuedUpdate) and plain(first.result) == expected
    value["desc"]["args"]["prior"] = adopted.cid
    replay = belief1_direct(rig, q, value=value)
    if changed_cells:
        assert isinstance(replay, u.Rejected) and {i.code for i in replay.issues} == {"measurement_conflict"}, replay
        assert first.application_digest != original.application_digest
    else:
        assert isinstance(replay, u.IssuedUpdate) and plain(replay.result) == expected
        assert replay.application_digest == first.application_digest == original.application_digest
    assert [a.cid for a in rig.facts(c.BELIEF_ADOPTED)] == [adopted.cid]


@pytest.mark.parametrize("change", ["boolean-to-integer", "object-key-order"])
def test_belief1_U_declaration_JSON_types_are_meaning_but_object_key_order_is_not(make_belief1, change):
    """K28-b(ta,chi): compare full declaration values as canonical JSON bytes.

    T=E=I/2 and p0=(1/2,1/2) give (1/4,1/4), hence q=(1/2,1/2),
    Z=1/2 in both declarations. Only T.available.computation changes.
    Python == merging true and 1 wrongly issues a noop instead of conflict;
    ignoring that JSON leaf also fails the prior-free digest distinction.
    Hashing key insertion order or the saved MODEL Point wrongly rejects the
    reordered-object control; counting that replay twice gives Z=1/4, not 1/2.
    """
    import json

    def canonical(value):
        # Test-side encoding, independent of the production canonicalizer.
        return json.dumps(wire(value), ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False).encode("utf-8")

    different = change == "boolean-to-integer"
    first_json = {"marker": True} if different else {"marker": True, "aux": "fixed"}
    other_json = {"marker": 1} if different else {"aux": "fixed", "marker": True}
    assert type(first_json["marker"]) is bool
    assert type(other_json["marker"]) is (int if different else bool)
    if different:
        assert canonical(first_json) == b'{"marker":true}'
        assert canonical(other_json) == b'{"marker":1}'
    else:
        assert tuple(first_json) != tuple(other_json)
        assert canonical(first_json) == canonical(other_json) == b'{"aux":"fixed","marker":true}'

    half_identity = ((Q(1, 2), Q(0)), (Q(0), Q(1, 2)))
    matrices = {T: half_identity, E: half_identity}
    base = read1_model({REPEAT_ID: matrices}, states=("A", "B"),
        groups={T: (T,), E: (E,)}, schedule=(REPEAT_ID,)).declaration
    base = replace(base, control_rule=fb.MethodCall(contract=CONTROL,
        args={"first": [REPEAT_ID], "after": {s: [REPEAT_ID] for s in (T, E, U, M)}}))

    def with_computation(model, value):
        control, = model.controls
        assert [out.id for out in control.kernel.outcomes].count(T) == 1
        outcomes = tuple(replace(out, available=replace(out.available, computation=value))
            if out.id == T else out for out in control.kernel.outcomes)
        return replace(model, controls=(replace(control, kernel=replace(control.kernel, outcomes=outcomes)),))

    def computation(value):
        control, = value["controls"]
        out, = (out for out in control["kernel"]["outcomes"] if out["id"] == T)
        return out["available"]["computation"]

    primary, alternate = with_computation(base, first_json), with_computation(base, other_json)
    primary_value, alternate_value = wire(primary), wire(alternate)
    assert canonical(computation(primary_value)) == canonical(first_json)
    assert canonical(computation(alternate_value)) == canonical(other_json)
    restored = deepcopy(alternate_value)
    computation(restored).clear()
    computation(restored).update(first_json)
    assert canonical(restored) == canonical(primary_value), "only computation JSON may differ"
    assert (canonical(primary_value) != canonical(alternate_value)) == different
    assert belief1_enumerate(matrices, (T,))[:2] == ((Q(1, 2), Q(1, 2)), Q(1, 2))

    def install(model, args):
        assert canonical(model) == canonical(base)
        return with_computation(model, first_json), args

    rig = make_belief1(symbols=(T,), matrices=matrices, mutate=install, extra_models=(alternate,))
    declared = {item.slot: item.value for item in rig.boot_input.declaration.observation_models}
    assert set(declared) == {"observation", "alternative-0"}
    assert canonical(declared["observation"]) == canonical(primary)
    assert canonical(declared["alternative-0"]) == canonical(alternate)
    models = {m.value["declared_at"]["slot"]: m for m in rig.facts(MODEL)}
    original_model, other_model = models["observation"], models["alternative-0"]
    assert original_model.cid != other_model.cid
    assert canonical(original_model.value["value"]) == canonical(primary_value)
    assert canonical(other_model.value["value"]) == canonical(alternate_value)
    assert (canonical(original_model.value["value"]) != canonical(other_model.value["value"])) == different

    rig.begin(); _raw, (_, frame) = rig.publish(0, last=True)
    work, adopted = rig.update()
    expected = {"joint": [[1, 2], [1, 2]], "evidence_mass": [1, 2]}
    belief1_chain(rig, (expected,))
    assert len(rig.calls) == len(rig.source.calls) == 1
    q = rig.one(c.WORK_REQUESTED, cid=work.request)
    original = belief1_direct(rig, q)
    assert isinstance(original, u.IssuedUpdate) and plain(original.result) == expected
    for model in (original_model, other_model):
        read = fb.read_acquisition_sequence(rig.records(), model=model.cid,
            run=rig.clock.run, route_epoch=ROUTE, through_seq=0)
        assert read.kind == "read" and read.likelihood == (Q(1, 2), Q(1, 2))

    use, = q.value["desc"]["args"]["observations"]
    assert rig.one(c.SEGMENT_BINDING, cid=use["binding"]).value["report"] == frame.cid
    old_reading = rig.one(c.OBSERVATION_PLAN_2, cid=use["reading"])
    correspondence = rig.one(CORRESPONDENCE)
    pairs = deepcopy(correspondence.value)
    assert pairs["pairs"] == [["A", "A"], ["B", "B"]]
    pairs["observation_model"] = other_model.cid
    other_correspondence = belief1_clone(rig, correspondence, pairs)
    plan = deepcopy(old_reading.value)
    plan["projection"]["args"].update(observation_model=other_model.cid, correspondence=other_correspondence)
    other_reading = belief1_clone(rig, old_reading, plan)
    value = deepcopy(q.value)
    value["desc"]["args"]["observations"][0]["reading"] = other_reading
    assert value["desc"]["args"]["observations"][0]["binding"] == use["binding"]
    extra = {other_model.cid, other_correspondence, other_reading}
    value["desc"]["input_points"] = sorted(set(value["desc"]["input_points"]) | extra)
    value["desc"]["numerical_view"]["boundary"] = sorted(set(value["desc"]["numerical_view"]["boundary"]) | extra)
    assert value["desc"]["args"]["prior"] is None
    first = belief1_direct(rig, q, value=value)
    assert isinstance(first, u.IssuedUpdate) and plain(first.result) == expected
    assert (first.application_digest != original.application_digest) == different
    value["desc"]["args"]["prior"] = adopted.cid
    replay = belief1_direct(rig, q, value=value)
    if different:
        assert isinstance(replay, u.Rejected) and {i.code for i in replay.issues} == {"measurement_conflict"}, replay
    else:
        assert isinstance(replay, u.IssuedUpdate) and plain(replay.result) == expected
        assert replay.application_digest == first.application_digest == original.application_digest
    assert [a.cid for a in rig.facts(c.BELIEF_ADOPTED)] == [adopted.cid]

