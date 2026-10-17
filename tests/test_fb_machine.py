"""Turn-1 tests: graph construction/termination/limit/determinism only.

No INV/L predicates, SC suite, identification cases or mutants yet. The finite
recipes below exercise mechanics, not F-a mathematical or wire compatibility.
Run only: .venv/Scripts/python.exe -m pytest tests/test_fb_machine.py -q
"""

from dataclasses import replace

import pytest

from fb_machine import (
    Action, AllowedPlan, Budget, Contract, Controls, CorrectWindow, Cut,
    Descriptor, E0, Environment, Event, Guard, NumericalView, Object, PlanRef,
    Interval, IntervalFact, IntervalOccurrence, IntervalRequest, Reading,
    Outcome, OutcomeKind, Posting, Program, RecordPlan, Scenario, UnknownNotice,
    explore, interval_cells, obj, receipt_unit_id,
)


def received(data: bytes = b"opaque") -> Event:
    return Event("Received", obj(route_epoch="route-0", media_type="application/octet-stream",
                                 data=data, claims=obj(sender_claim="unresolved name")))


def receiver(count=1, budget=Budget(), boot=False):
    from fb_machine import Posting
    event = (Event("Boot", obj(declaration=obj(capacity=(("think", 2),), scope="one",
                                               routes=("route-0",), initial=None, environment="model")))
             if boot else received())
    return E0(postings=tuple(Posting(f"external-{i}", event, 1) for i in range(count)),
              budget=budget)


def publication():
    # 紙に無い仮定 A-DECL: these three contract names are MODEL labels for the
    # unspecified initial record wire (O-02), not additions to the real registry.
    # No mathematical computation/certification is claimed by this boundary test.
    records = tuple(RecordPlan(slot, Contract("model.initial." + slot, "1"), "Event",
                               obj(origin="bootstrap", initial_slot=slot))
                    for slot in ("process", "reader", "request"))
    process, reader, request = (PlanRef("initial", s) for s in ("process", "reader", "request"))
    desc = Descriptor("w0", process, request, "measurement", "segment-0", reader,
                      Contract("model.measure", "1"), Contract("model.report", "1"), Object(),
                      frozenset((reader,)), NumericalView(), "bootstrap", frozenset((process,)),
                      request, "MeasureSegment", (("measure", 1),), frozenset((request,)))
    plan = AllowedPlan("initial", "O-02", ("initial", 0), records, (desc,))
    initial = obj(generator="declared")
    boot = Event("Boot", obj(declaration=obj(initial=initial, capacity=(("think", 2), ("measure", 1)),
                                             scope="one", routes=("route-0",), environment="model")))
    return E0(initial=initial, postings=(Posting("boot", boot, 0),),
              plans=(plan,), programs=(Program("w0", (), False),))


def unknown_work():
    e0 = publication()
    plan = e0.plans[0]
    desc = replace(plan.works[0], purpose="belief_update", stage="Wr", need=(("think", 1),),
                   method=Contract("finite_update", "1"))
    program = Program("w0", (), False)
    notice = UnknownNotice("unknown-0", "w0", obj(reason="result_not_confirmed"))
    # E0-04 / A-FINITE: independently fixed scene receipt table. No worker
    # replies here; the sole subsequent Post is this one host Unknown delivery.
    return replace(e0, plans=(replace(plan, works=(desc,)),), programs=(program,), unknown_notices=(notice,),
                   receipt_kinds=((0, "Boot"), (1, "WorkFinished")))


def boundary_state(e0, published=False):
    """Reachable prefix, not hand-inserted ledger facts or fabricated EW.

    I0 -> Post/Accept/HostAck(Boot) -> save BOTH slots. Optionally Publish
    initial -> save three slots -> ResolveWork, leaving Pending. All original
    custody, C/E and actual EH/EP/EU history are retained for the local boundary.
    This is an executable connection witness, not an INV/SC check.
    """
    environment, window = Environment(e0), CorrectWindow(e0)
    state = environment.initial()

    def take(action):
        nonlocal state
        state = environment.step(state, action, window).state

    def save(unit, slots):
        for slot in slots:
            take(Action("PrepareReceipt" if unit.startswith("receipt/") else "PrepareOne", (unit, slot)))
            take(Action("PutBody", (unit, slot)))
            take(Action("AddEntry", (unit, slot)))
            take(Action("ConfirmWrite", (unit, slot)))
            take(Action("CompleteWrite", (unit, slot)))

    take(Action("Post", ("boot",)))
    take(Action("Accept", (state.core.h.queue[0],)))
    take(Action("HostAck", (e0.run, 0)))
    save(receipt_unit_id(e0.run, 0), ("boot", "declaration"))
    if published:
        take(Action("PublishUnit", ("initial",)))
        save("initial", ("process", "reader", "request"))
        take(Action("ResolveWork", ("w0",)))
    return state


def receipt_prefix(e0, boot=False):
    """Executable small boundary; preserves the performed prefix observations.

    The full I0 interleavings of two saved slots are outside this smoke graph.
    No order is normalized away: the prefix and every subsequent edge retain it.
    """
    env, window = Environment(e0), CorrectWindow(e0)
    state = env.initial()
    actions = [Action("Post", (e0.postings[0].id,))]
    for action in actions:
        state = env.step(state, action, window).state
    state = env.step(state, Action("Accept", (state.core.h.queue[0],)), window).state
    state = env.step(state, Action("HostAck", (e0.run, 0)), window).state
    key = (receipt_unit_id(e0.run, 0), "boot" if boot else "receipt")
    for operation in ("PrepareReceipt", "PutBody", "AddEntry", "ConfirmWrite", "CompleteWrite"):
        state = env.step(state, Action(operation, key), window).state
    return state


def unknown_receipt_prefix(e0):
    env, window = Environment(e0), CorrectWindow(e0)
    state = boundary_state(e0, published=True)
    for action in (Action("ClaimStart", ("w0",)), Action("Launch", ("w0",)),
                   Action("EnterWorker", ("w0:wrapper:0",)),
                   Action("HostUnknown", ("unknown-0",)),
                   Action("Deliver", ("host-unknown:unknown-0",))):
        state = env.step(state, action, window).state
    return state


def smoke_cases():
    publish = publication()
    held = replace(publication(), budget=Budget(launch_failures=1))
    unknown = unknown_work()
    return (
        Scenario("SMOKE-receipt-one", receiver(), 20_000),
        Scenario("SMOKE-receipt-two-same-bytes", receiver(2), 50_000, receipt_prefix(receiver(2)),
                 initial_connection="I0->Post/Accept/HostAck/save first receipt; remaining second receipt"),
        Scenario("SMOKE-boot-two-slots", receiver(boot=True), 50_000, receipt_prefix(receiver(boot=True), boot=True),
                 initial_connection="I0->Post/Accept/HostAck/save Boot slot; declaration remains unsaved"),
        Scenario("SMOKE-precommit-failure", receiver(budget=Budget(precommit_failures=1)), 50_000),
        Scenario("SMOKE-response-loss", receiver(budget=Budget(lost_responses=1)), 50_000),
        Scenario("SMOKE-window-rebuild", receiver(budget=Budget(window_faults=1)), 50_000),
        Scenario("SMOKE-publish-three-start", publish, 100_000, boundary_state(publish, published=True),
                 cut=Cut("K-U", frozenset(("WorkerStep", "RecognizeTerminal", "Acquire", "Adopt")),
                         ("measurement reports and all downstream processing",)),
                 initial_connection="executable I0->Saved Boot/declaration->Publish/save initial->Pending prefix; boundary_state"),
        Scenario("SMOKE-held-launch-retry", held, 100_000, boundary_state(held, published=True),
                 initial_connection="I0->Saved Boot->Publish/save initial->Pending; boundary_state"),
        Scenario("SMOKE-work-unknown", unknown, 100_000, unknown_receipt_prefix(unknown),
                 cut=Cut("K-T", frozenset(("RecognizeTerminal",)), ("terminal T normative E0 plan",)),
                 initial_connection="I0->Saved Boot/initial->actual body entry->host Unknown->Deliver"),
    )


@pytest.mark.parametrize("scenario", smoke_cases(), ids=lambda s: s.id)
def test_small_graph_finishes_below_per_scenario_limit(scenario, capsys):
    graph = explore(scenario)
    with capsys.disabled():
        print(f"\n{scenario.id}: states={len(graph.states)} edges={len(graph.edges)} "
              f"seconds={graph.elapsed_seconds:.6f} complete={graph.complete}", flush=True)
    assert graph.complete
    assert not graph.frontier
    assert len(graph.states) <= scenario.max_states <= 200_000
    assert len(graph.enabled) == len(graph.states)
    # Wait is part of the graph. Completion does not mean acyclic or all work done.
    assert any(e.source == e.target and e.action.operation == "Wait" for e in graph.edges)


def test_breadth_first_search_is_deterministic(capsys):
    scenario = Scenario("SMOKE-determinism", receiver(), 20_000)
    first, second = explore(scenario), explore(scenario)
    assert first.states == second.states
    assert first.edges == second.edges
    assert first.enabled == second.enabled
    assert first.parents == second.parents
    with capsys.disabled():
        print(f"\n{scenario.id}: states={len(first.states)} runs=2 "
              f"seconds={first.elapsed_seconds:.6f}/{second.elapsed_seconds:.6f}", flush=True)


def test_limit_returns_incomplete_without_inserting_extra_state(capsys):
    graph = explore(Scenario("SMOKE-limit", receiver(2), 3))
    assert not graph.complete
    assert graph.status == "state_limit_reached"
    assert len(graph.states) == 3
    assert graph.frontier
    with capsys.disabled():
        print(f"\n{graph.scenario}: states={len(graph.states)} seconds={graph.elapsed_seconds:.6f} "
              "complete=False (intentional bound test)", flush=True)


@pytest.mark.parametrize("limit", (0, 200_001))
def test_out_of_contract_limits_are_rejected(limit):
    with pytest.raises(ValueError, match="max_states"):
        explore(Scenario("SMOKE-invalid-bound", receiver(), limit))


def test_observer_receives_every_state_and_edge_without_window_objects(capsys):
    # Observer transport test, not a checker implementation or any INV verdict.
    class Collector:
        def __init__(self):
            self.states = []
            self.steps = []
            self.graphs = []

        def on_state(self, observation):
            self.states.append(observation)

        def on_step(self, observation):
            self.steps.append(observation)

        def on_graph(self, observation):
            self.graphs.append(observation)

    collector = Collector()
    graph = explore(Scenario("SMOKE-observer", receiver(), 20_000), observer=collector)
    assert len(collector.states) == len(graph.states)
    assert len(collector.steps) == len(graph.edges)
    assert len(collector.graphs) == 1
    assert all(len(o.populations) == 6 for o in collector.steps)
    assert collector.graphs[0].complete
    from fb_check import ObservationEvent, validate_observation_boundary
    for observation in collector.states:
        trace = observation.observation_trace
        assert trace is observation.state.evidence.observation_trace
        assert trace.clock == observation.state.core.h.reading
        assert trace.bodies == frozenset(observation.state.core.c)
        assert trace.entries == frozenset(observation.state.core.e)
        assert not validate_observation_boundary(observation.observation_contract, trace).violations
    for observation in collector.steps:
        assert observation.before_trace is observation.before.evidence.observation_trace
        assert observation.after_trace is observation.after.evidence.observation_trace
        assert all(type(event) is ObservationEvent for event in observation.actual_events)
    with capsys.disabled():
        print(f"\n{graph.scenario}: states={len(graph.states)} edges={len(graph.edges)} "
              f"seconds={graph.elapsed_seconds:.6f}", flush=True)


def test_store_capabilities_are_independent_of_failure_budget(capsys):
    e0 = receiver()
    initial = Environment(e0).initial(Controls(body_put=False, entry_add=False))
    graph = explore(Scenario("SMOKE-capability-recovery", e0, 20_000, initial))
    assert graph.complete
    assert any(e.action.operation == "RecoverStore" for e in graph.edges)
    with capsys.disabled():
        print(f"\n{graph.scenario}: states={len(graph.states)} edges={len(graph.edges)} "
              f"seconds={graph.elapsed_seconds:.6f}", flush=True)


def test_interval_environment_steps_finish_without_claiming_support(capsys):
    # Queue a request and a report-generation occurrence. No binding, monitoring
    # coverage, INV-12 row or SC case is asserted by this transport smoke test.
    interval = Interval("run-0", "M", 0, 2, True, False)
    request = IntervalRequest("k0", PlanRef("k-plan", "k"), "route-0", "measure-0",
                              interval, Contract("model.measure", "1"), Contract("model.clock", "1"),
                              interval_cells(interval, (0, 1, 2, 3)))
    occurrence = IntervalOccurrence("generated-0", IntervalFact("ReportGenerated", "k0", "route-0",
                                                               Reading("run-0", "M", 0), frozenset(),
                                                               None, obj(branch="Unproved")))
    e0 = E0(intervals=(request,), interval_occurrences=(occurrence,))
    graph = explore(Scenario("SMOKE-EI-transport", e0, 100,
                             cut=Cut("K-K", untested=("k publication/binding/Support",))))
    assert graph.complete
    with capsys.disabled():
        print(f"\n{graph.scenario}: states={len(graph.states)} edges={len(graph.edges)} "
              f"seconds={graph.elapsed_seconds:.6f}", flush=True)


# Independent checker additions. Everything above this line is unchanged.
from fb_check import (
    CONDITION_IDS, CONCRETE_IDENTIFICATION, HUMAN_IDS, ROWS, SCOPE_UNIVERSE,
    Checker, GraphObservation, RelationObservation, StateObservation, StepObservation,
    acyclic, check_exploration, coverage, derive_progress, fair_cycle,
    interval_atoms, progress_counterexamples, report_clashes,
)
def checker_cases():
    # Reuse the original nine recipes and reproduce each remaining existing
    # small graph. Invalid limits have no graph and remain the original tests.
    interval = Interval("run-0", "M", 0, 2, True, False)
    request = IntervalRequest("k0", PlanRef("k-plan", "k"), "route-0", "measure-0", interval, Contract("model.measure", "1"), Contract("model.clock", "1"), interval_cells(interval, (0, 1, 2, 3)))
    occurrence = IntervalOccurrence("generated-0", IntervalFact("ReportGenerated", "k0", "route-0", Reading("run-0", "M", 0), frozenset(), None, obj(branch="Unproved")))
    e0 = E0(intervals=(request,), interval_occurrences=(occurrence,))
    recovery = receiver()
    return (*smoke_cases(), Scenario("CHECK-determinism", receiver(), 20_000), Scenario("CHECK-observer", receiver(), 20_000), Scenario("CHECK-limit", receiver(2), 3), Scenario("CHECK-capability-recovery", recovery, 20_000, Environment(recovery).initial(Controls(body_put=False, entry_add=False))), Scenario("CHECK-EI-transport", e0, 100, cut=Cut("K-K", untested=("k publication/binding/Support",))))
_CHECK_SCENARIOS = checker_cases()
@pytest.fixture(scope="module")
def checked_cases():
    results = []
    for scenario in _CHECK_SCENARIOS:
        graph = explore(scenario)
        results.append((scenario, graph, check_exploration(scenario, graph)))
    return tuple(results)
@pytest.mark.parametrize("case_index", range(len(_CHECK_SCENARIOS)), ids=[s.id for s in _CHECK_SCENARIOS])
def test_independent_rows_on_every_existing_small_scenario(case_index, checked_cases, capsys):
    scenario, graph, report = checked_cases[case_index]
    assert tuple(r.condition_id for r in report.rows) == CONDITION_IDS
    assert sum(report.counts.values()) == 47
    assert report.human == tuple((h, "未点検") for h in HUMAN_IDS)
    assert not report.passed  # smoke reachability is not semantic completeness
    with capsys.disabled():
        print(f"\nCHECK {scenario.id}: states={len(graph.states)} edges={len(graph.edges)} "
              f"counts={report.counts} partial={sum(bool(r.limitations) for r in report.rows)} "
              f"connections={report.connection_counts} missing_ports={report.unconnected_observations} "
              f"human_unchecked={len(report.human)}", flush=True)
        for finding in report.violations:
            print(f"  {finding.condition_id} {finding.location}: {finding.message}; {finding.target!r}", flush=True)
    assert not report.violations, report.violations
def test_checker_denominator_keeps_all_47_conditions_and_all_scopes():
    assert len(ROWS) == 47
    assert {r.condition_id: r.scope for r in ROWS} == dict(SCOPE_UNIVERSE)
    assert sum(r.identification == "具体化済み" for r in ROWS) == 13
    assert sum(r.identification == "未具体化" for r in ROWS) == 34
    assert len(CONCRETE_IDENTIFICATION) == 13
    assert all(len(r.paper_columns) == 7 and r.formula for r in ROWS)
    assert len(coverage()) == sum(len(scopes) for _, scopes in SCOPE_UNIVERSE)
    report = Checker().report()
    assert report.counts == {"違反": 0, "違反なし・識別力確認済み": 0, "違反なし・識別力未確認": 47}
    assert all("not_run" in row.limitations for row in report.rows)
def _candidate_step(e0, before, after, action=Action("Wait")):
    # Frozen counterfactual input to the checker, not an alleged reachable state
    # or a mutant run. No observation schema is invented for opaque Fact values.
    checker = Checker()
    checker.on_state(StateObservation(0, before, e0, (), ()))
    checker.on_state(StateObservation(1, after, e0, (), ()))
    checker.on_step(StepObservation(0, 1, before, after, e0, action, (), None, (), ()))
    return checker.report()
def _row_fails(report, row):
    return bool(next(r for r in report.rows if r.condition_id == row).violations)
@pytest.mark.parametrize("field,value", (
    ("work_id", "different-work"), ("process", PlanRef("initial", "reader")),
    ("trigger", PlanRef("initial", "reader")), ("purpose", "different-purpose"),
    ("stage_slot", "different-stage"), ("reader", PlanRef("initial", "process")),
    ("method", Contract("model.measure", "2")),
    ("output_contract", Contract("model.report", "2")), ("args", obj(extra=1)),
    ("input_points", frozenset()), ("numerical_view", NumericalView(context=obj(changed=1))),
    ("allocation", "different-allocation"), ("permissions", frozenset()),
    ("request", PlanRef("initial", "reader")), ("stage", "Wr"),
    ("need", (("measure", 2),)), ("required", frozenset()),
))
def test_desc_all_fixed_fields_are_checked_by_inv_3_b(field, value):
    e0 = publication()
    before = boundary_state(e0, published=True)
    work = before.core.p.work[0]
    after = replace(before, core=replace(before.core, p=replace(before.core.p, work=(replace(work, descriptor=replace(work.descriptor, **{field: value})),))))
    assert _row_fails(_candidate_step(e0, before, after), "INV-3.b")
    assert not _row_fails(_candidate_step(e0, before, before), "INV-3.b")
def test_deleted_work_is_checked_even_before_start_and_without_termination():
    e0 = publication()
    before = boundary_state(e0, published=True)
    after = replace(before, core=replace(before.core, p=replace(before.core.p, work=())))
    report = _candidate_step(e0, before, after)
    assert _row_fails(report, "INV-2.a")
    assert _row_fails(report, "INV-2.b")
@pytest.mark.parametrize("field", ("record", "parents", "salt", "payload", "seal", "header", "point"))
def test_retry_fixed_fields_checked_by_inv_4_b(field):
    from fb_machine import Point
    e0 = receiver()
    graph = explore(Scenario("CHECK-retry-candidate", e0, 20_000))
    before = next(s for s in graph.states if s.core.p.receipts and
                  s.core.p.receipts[0].unit.slots[0].prepared is not None and not s.core.e)
    receipt = before.core.p.receipts[0]
    slot = receipt.unit.slots[0]
    prepared = slot.prepared
    alternatives = {
        "record": replace(prepared.record, at=Reading("run-0", "M", 100)), "parents": frozenset((Point("other-parent"),)), "salt": b"other-salt", "payload": b"different bytes", "seal": "other-seal", "header": replace(prepared.header, parents=frozenset((Point("other-parent"),))), "point": Point("other-cid"),
    }
    modified = replace(slot, prepared=replace(prepared, **{field: alternatives[field]}))
    new_receipt = replace(receipt, unit=replace(receipt.unit, slots=(modified,)))
    after = replace(before, core=replace(before.core, p=replace(before.core.p, receipts=(new_receipt,))))
    assert _row_fails(_candidate_step(e0, before, after), "INV-4.b")
    assert not _row_fails(_candidate_step(e0, before, before), "INV-4.b")
def test_parent_prediction_and_cycle_clauses_have_their_own_negative_controls():
    from fb_machine import Entry, Header, Point, Record
    assert acyclic({"a": frozenset(), "b": frozenset(("a",))})
    assert acyclic({"a": frozenset(("missing-parent",))})  # missing is not cyclic
    assert not acyclic({"a": frozenset(("b",)), "b": frozenset(("a",))})
    e0 = E0()
    initial = Environment(e0).initial()
    prediction = Record("r", Reading("run-0", "M", 0), Contract("computation_result", "1"), "Prediction", Object(), ())
    event = replace(prediction, name="event", category="Event")
    # Symbolic pre-admission graph as allowed by SC-05-CYCLE. It deliberately
    # cannot pass ledger integrity; the INV-5.c cycle clause must still fail.
    pa, pb = Point("a"), Point("b")
    candidate = replace(initial, core=replace(initial.core, e=(
        Entry(pa, Header(event, "a", frozenset((pb,)))), Entry(pb, Header(prediction, "b", frozenset((pa,)))),
    )))
    checker = Checker()
    checker.on_state(StateObservation(0, candidate, e0, (), ()))
    assert any(f.condition_id == "INV-5.c" and "cycle" in f.message for f in checker.report().violations)
    assert any(f.condition_id == "INV-5.c" and "Prediction" in f.message for f in checker.report().violations)
def test_capacity_is_independent_of_allocation():
    good = E0(capacity=(("think", 2),), allocation=(("think", 1),))
    bad = replace(good, capacity=(("think", 1),), allocation=(("think", 2),))
    for e0, expected in ((good, False), (bad, True)):
        checker = Checker()
        # Invalid E0 is a checker candidate, not an input accepted by the model.
        checker.on_state(StateObservation(0, Environment(good).initial(), e0, (), ()))
        assert _row_fails(checker.report(), "INV-10.a") is expected
def test_report_family_and_cross_measurement_pure_formulas():
    from fb_machine import Point, Report, ReportKind
    a = Report(ReportKind.GAP, Point("segment"), "slot", "route", obj(reason="gap"))
    same = (Point("a"), a), (Point("a-redelivered"), a)
    assert not report_clashes(same)
    b = replace(a, kind=ReportKind.UNAVAILABLE)
    assert any(c.rule == "CL-SAME" for c in report_clashes(((Point("a"), a), (Point("b"), b))))
    assert not report_clashes(((Point("a"), a), (Point("b"), replace(b, item_slot="other"))))
    frame = Report(ReportKind.FRAME, Point("k1"), "frame", "route", obj(measurement_id="m", sample_seq=1, value=3))
    other = replace(frame, segment=Point("k2"))
    assert not report_clashes(((Point("f1"), frame), (Point("f2"), other)))
    changed = replace(other, fields=obj(measurement_id="m", sample_seq=1, value=4))
    clashes = report_clashes(((Point("f1"), frame), (Point("f2"), changed)))
    assert any(c.rule == "CL-MEASUREMENT" and "m" in c.affected for c in clashes)
def test_fairness_uses_targets_and_full_enabled_sets():
    a1, a2 = ("AddEntry", "e1", "slot"), ("AddEntry", "e2", "slot")
    enabled = (frozenset((a1, a2)),)
    # SC-19-T1 is an unfair candidate; the same full graph's T2 is fair.
    assert not fair_cycle({0}, ((0, 0, a1),), enabled)
    assert fair_cycle({0}, ((0, 0, a1), (0, 0, a2)), enabled)
    # A saving exit removed from the pending subgraph remains Enabled.
    assert not progress_counterexamples({0}, ((0, 0, a1), (0, 1, a2)), enabled + (frozenset(),))
    assert progress_counterexamples({0}, ((0, 0, a1), (0, 0, a2)), enabled)
    assert not fair_cycle({0}, (), (frozenset(),))
def test_derive_stable_n_and_p_and_hidden_operation_cases():
    publish, wait = ("PublishMatching", "o"), ("Wait",)
    alternating = ((0, 1, wait), (1, 0, wait), (0, 2, publish))
    enabled = (frozenset((publish,)), frozenset(), frozenset())
    n1 = derive_progress({0, 1}, {0}, set(), set(), alternating, enabled, environment_ready={0, 1, 2})
    assert not n1["N"]  # ReadyN alternating is not StableN
    n2 = derive_progress({0}, {0}, set(), set(), ((0, 0, wait), (0, 1, publish)), (frozenset((publish,)), frozenset()), environment_ready={0, 1})
    assert not n2["N"]  # Wait-only suffix is unfair
    n4 = derive_progress({0}, {0}, set(), set(), ((0, 0, wait),), (frozenset(),), environment_ready={0})
    assert n4["N"]  # independent ReadyN, missing operation, vacuous fairness
    save = ("AddEntry", "u", "q")
    n3 = derive_progress({0}, {0}, {1}, {2}, ((0, 1, publish), (1, 2, save), (2, 2, wait)), (frozenset((publish,)), frozenset((save,)), frozenset()), environment_ready={0, 1, 2})
    assert not n3["N"] and not n3["P"]
    pbad = derive_progress(set(), set(), {0}, set(), ((0, 0, save),), (frozenset((save,)),), environment_ready={0})
    assert pbad["P"]
    assert derive_progress({0}, {0}, set(), set(), (), (frozenset(),), environment_ready={0}, complete=False, frontier=(0,)) is None
def test_relationship_rows_compare_actual_state_pairs():
    e0 = receiver()
    graph = explore(Scenario("CHECK-relation", e0, 20_000))
    index = next(i for i, s in enumerate(graph.states) if s.core.h.queue and not s.core.p.receipts)
    left = StateObservation(index, graph.states[index], e0, graph.enabled[index], ())
    right = replace(left, index=100, enabled=tuple(a for a in left.enabled if a.operation != "Accept"))
    checker = Checker()
    checker.on_relation(RelationObservation(left, right, "same_receipt_projection"))
    assert _row_fails(checker.report(), "INV-11.c")
    positive = Checker()
    positive.on_relation(RelationObservation(left, replace(left, index=101), "same_receipt_projection"))
    assert not _row_fails(positive.report(), "INV-11.c")
    no_initial = left
    has_initial = replace(left, index=102, e0=replace(e0, initial=obj(generator="present")), enabled=right.enabled)
    checker.on_relation(RelationObservation(no_initial, has_initial, "initial_only"))
    assert _row_fails(checker.report(), "INV-13.b")
def test_interval_endpoint_partition_and_no_future_unproved_rejection():
    for left in (False, True):
        for right in (False, True):
            interval = Interval("run-0", "M", 0, 2, left, right)
            cells = interval_atoms(interval, (0, 1, 2, 3))
            assert ((0, 0) in cells) is left
            assert ((2, 2) in cells) is right
            assert (1, 1) in cells and (0, 1) in cells and (1, 2) in cells
def test_success_marks_cannot_replace_actual_saved_values():
    e0 = receiver()
    graph = explore(Scenario("CHECK-saved-claim", e0, 20_000))
    before = next(s for s in graph.states if s.core.p.receipts and not s.core.c and
                  s.core.p.receipts[0].unit.slots[0].prepared is not None)
    receipt = before.core.p.receipts[0]
    slot = replace(receipt.unit.slots[0], body_confirmed=True, entry_confirmed=True, completed=True)
    changed = replace(receipt, unit=replace(receipt.unit, slots=(slot,)))
    after = replace(before, core=replace(before.core, p=replace(before.core.p, receipts=(changed,))))
    report = _candidate_step(e0, before, after)
    assert _row_fails(report, "INV-4.c")
    assert not report.passed
def test_first_preparation_content_is_checked_against_e0_not_its_own_history():
    from fb_check import _encode
    e0 = publication()
    env, window = Environment(e0), CorrectWindow(e0)
    before = env.step(boundary_state(e0), Action("PublishUnit", ("initial",)), window).state
    after = env.step(before, Action("PrepareOne", ("initial", "process")), window).state
    unit = next(u for u in after.core.p.units if u.id == "initial")
    slot = unit.slots[0]
    record = replace(slot.prepared.record, content=obj(origin="changed", initial_slot="process"))
    prepared = replace(slot.prepared, record=record, payload=_encode(record), header=replace(slot.prepared.header, record=record))
    changed = replace(unit, slots=(replace(slot, prepared=prepared), *unit.slots[1:]))
    wrong = replace(after, core=replace(after.core, p=replace(after.core.p, units=(changed,))))
    assert _row_fails(_candidate_step(e0, before, wrong, Action("PrepareOne", ("initial", "process"))), "INV-4.c")
    # It is the first value: retry equality alone cannot catch it.
    assert not _row_fails(_candidate_step(e0, before, wrong), "INV-4.b")
def test_offline_and_streaming_checker_visit_every_state_and_step():
    e0 = receiver()
    scenario = Scenario("CHECK-observer-equivalence", e0, 20_000)
    class Visits(Checker):
        def __init__(self):
            super().__init__()
            self.states_seen, self.edges_seen = [], []
        def on_state(self, observation):
            self.states_seen.append(observation.index)
            super().on_state(observation)
        def on_step(self, observation):
            self.edges_seen.append((observation.source, observation.target, observation.action, observation.actual_events))
            super().on_step(observation)
    checker = Visits()
    graph = explore(scenario, observer=checker)
    offline = check_exploration(scenario, graph)
    assert checker.report() == offline
    assert checker.states_seen == list(range(len(graph.states)))
    assert checker.edges_seen == [(e.source, e.target, e.action, e.actual_events) for e in graph.edges]
    from fb_check import PropertyKind
    for row, result in zip(ROWS, offline.rows):
        if row.kinds <= {PropertyKind.STATE, PropertyKind.ENABLED, PropertyKind.STEP}:
            expected = (len(graph.states) if row.kinds & {PropertyKind.STATE, PropertyKind.ENABLED} else 0)
            expected += len(graph.edges) if PropertyKind.STEP in row.kinds else 0
            # Connected typed clauses add comparisons; graph visitation is an
            # independent property and must not be inferred from their count.
            assert result.observations >= expected
def test_incomplete_or_cut_graph_is_never_a_dead_end_or_a_pass():
    e0 = receiver()
    for scenario in (Scenario("CHECK-boundary", e0, 1), Scenario("CHECK-cut", e0, 100, cut=Cut("save-exit", frozenset(("AddEntry",))))):
        report = check_exploration(scenario, explore(scenario))
        assert not report.complete and not report.passed
        for row in (r for r in report.rows if r.condition_id in ('L-RECEIPT', 'L-DERIVE')):
            assert any("not run" in reason for reason in row.limitations)
def test_long_fair_scc_does_not_depend_on_python_recursion_limit():
    count = 2100
    label = ("AddEntry", "same-envelope", "slot")
    edges = tuple((i, (i + 1) % count, label) for i in range(count))
    enabled = tuple(frozenset((label,)) for _ in range(count))
    assert progress_counterexamples(range(count), edges, enabled) == (frozenset(range(count)),)
def test_all_row_results_remain_in_the_aggregate_report(checked_cases, capsys):
    # Reuse the already checked graphs; no second exploration. 'reached' counts
    # executed comparisons, NOT full satisfaction of the paper's antecedents.
    with capsys.disabled():
        print("\nROW REPORT: ID | kinds | observations | comparisons | violations | identification specification", flush=True)
        for i, contract in enumerate(ROWS):
            results = [report.rows[i] for _, _, report in checked_cases]
            assert all(r.condition_id == contract.condition_id for r in results)
            print(f"{contract.condition_id} | {','.join(sorted(k.value for k in contract.kinds))} | "
                  f"{sum(r.observations for r in results)} | {sum(r.reached for r in results)} | "
                  f"{sum(len(r.violations) for r in results)} | {contract.identification}", flush=True)
# Turn 2: checker-owned observation boundary. Hand-built positives/negatives
# exercise clauses only; NONE are the paper's independently run discriminators.
import fb_check as observation_check
from fb_machine import Body, Entry, Envelope, Generation, Header, Point, PreparedEntry, Record, Unit
def _handmade_encode(value):
    """Test fixture codec; uses data fields only, never any window helper."""
    import json
    from dataclasses import fields, is_dataclass
    from enum import Enum
    def wire(v):
        if isinstance(v, Enum):
            return v.value
        if isinstance(v, bytes):
            return {"bytes": v.hex()}
        if is_dataclass(v):
            return {"type": type(v).__name__, "fields": {f.name: wire(getattr(v, f.name)) for f in fields(v)}}
        if isinstance(v, tuple):
            return [wire(x) for x in v]
        if isinstance(v, frozenset):
            return sorted([wire(x) for x in v], key=lambda x: json.dumps(x, sort_keys=True))
        return v
    return json.dumps(wire(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
def _handmade_prepared(record, parents=frozenset(), salt=b"fixture-salt"):
    from hashlib import sha256
    payload = _handmade_encode(record)
    seal = sha256(b"fb-check-seal/1\0" + len(salt).to_bytes(8, "big") + salt
                  + len(payload).to_bytes(8, "big") + payload).hexdigest()
    header = Header(record, seal, parents)
    point = Point(sha256(_handmade_encode(header)).hexdigest())
    return PreparedEntry(record, parents, salt, payload, seal, header, point)
def _handmade_receipt(kind="Received", envelope=None):
    bc = observation_check
    event = (received(b"raw\xff") if kind == "Received" else
             Event("Boot", obj(declaration=obj(initial=None, environment="opaque", routes=("r",), capacity=(), scope="one"))))
    envelope = envelope or Envelope("run", 1, Reading("run", "M", 1), 1, event, "external")
    created = Reading("run", "M", 2)
    unit = "receipt/" + _handmade_encode((envelope.run, envelope.number)).hex()
    contracts = (("boot", "sui.s4.boot"), ("declaration", "sui.fb.boot_declaration")) if kind == "Boot" else (
        ("receipt", {"Received": "sui.fb.received", "WorkFinished": "sui.fb.work_report", "DrawReturned": "sui.fb.draw_report"}[kind]),)
    plans, firsts = [], []
    for slot, name in contracts:
        contract = Contract(name, "1")
        content = obj(writer="MEMBRANE", route="model/receipt", contract=contract, content=envelope.event, caused_by=None, source_id=None, source_time_ns=None, received_ns=envelope.r)
        plans.append(RecordPlan(slot, contract, "Event", content, at=created))
        record = Record(unit + "/" + slot, created, contract, "Event", content, ())
        firsts.append(_handmade_prepared(record))
    key = bc.ReceiptKey(envelope.run, envelope.number)
    events = [bc.ObservationEvent("Post", key, bc.Posted(envelope)), bc.ObservationEvent("Accept", key, bc.Accepted(envelope, unit, tuple(plans), created)), bc.ObservationEvent("HostAck", key, bc.Posted(envelope))]
    events.extend(bc.ObservationEvent("FirstPrepare", bc.SlotKey(unit, plan.slot), bc.FirstPrepared(first))
                  for plan, first in zip(plans, firsts))
    trace = bc.ObservationTrace(tuple(events), frozenset(Body(p.seal, p.salt, p.payload) for p in firsts), frozenset(Entry(p.point, p.header) for p in firsts), created)
    return bc.ObservationE0(), trace, tuple(firsts)
def _contract_failures(evaluation, row):
    assert not evaluation.boundary.violations, evaluation.boundary.violations
    return tuple(c for c in evaluation.violations if c.row == row)
def test_observation_gap_classification_is_complete_and_does_not_invent_unsupported_meanings():
    bc = observation_check
    assert {p.gap for p in bc.GAP_PARTS} == set(bc.GAPS)
    assert {p.gap for p in bc.GAP_PARTS if p.category == "甲"} == set(bc.GAPS)
    assert {p.gap for p in bc.GAP_PARTS if p.category == "乙"} == {
        "derivation", "completion", "references", "apply", "adoption", "support", "artifact"}
    assert all(p.paper.ids and 1 <= p.paper.lines[0] <= p.paper.lines[1] for p in bc.GAP_PARTS)
    assert len(bc.TAG_BY_NAME) == len(bc.OBSERVATION_TAGS)
    assert all(tag.paper.ids and tag.rows for tag in bc.OBSERVATION_TAGS)
    assert all("紙に無い仮定" in text for _, text, _ in bc.OBSERVATION_ASSUMPTIONS)
@pytest.mark.parametrize("kind", ("Received", "Boot"))
def test_conforming_full_receipt_and_seal_observations(kind):
    bc = observation_check
    contract, trace, firsts = _handmade_receipt(kind)
    result = bc.evaluate_observations(contract, trace)
    assert result.boundary.connection == "約束接続・部分判定"
    assert not result.violations, result.violations
    assert all(bc.ledger_saved(p.point, trace, contract.codec) for p in firsts)
    assert len(firsts) == (2 if kind == "Boot" else 1)
    assert {c.row for c in result.clauses} >= {"INV-1.b", "INV-1.c", "INV-4.a", "INV-4.c"}
@pytest.mark.parametrize("bad", (
    observation_check.ObservationEvent("window_saved", "receipt", True),
    observation_check.ObservationEvent("Post", observation_check.ReceiptKey("run", True), observation_check.Posted(None)),
    observation_check.ObservationEvent("Stop", "w", observation_check.Stopped(None)),
    observation_check.ObservationEvent("Stop", observation_check.WorkToken("w", "t"), observation_check.Stopped(["mutable"])),
    observation_check.ObservationEvent("Stop", observation_check.WorkToken("w", "t"), {"evidence": "mutable"}),
))
def test_contract_boundary_rejects_unknown_tags_keys_and_mutable_payloads(bad):
    bc = observation_check
    result = bc.evaluate_observations(bc.ObservationE0(), bc.ObservationTrace((bad,)))
    assert result.boundary.connection == "約束違反"
    assert result.boundary.violations
    assert not result.clauses  # invalid observations never feed predicates
def test_contract_boundary_distinguishes_missing_transport_from_an_empty_log():
    bc = observation_check
    assert bc.validate_observation_boundary(None, None).connection == "約束の未接続"
    assert bc.validate_observation_boundary(bc.ObservationE0(), bc.ObservationTrace(())).connection == "約束接続・部分判定"
    broken = replace(bc.ObservationE0(), codec=replace(bc.CodecDeclaration(), seal="window-private-seal"))
    assert bc.validate_observation_boundary(broken, bc.ObservationTrace(())).connection == "約束違反"
    assert bc.validate_observation_boundary("not-a-contract", None).connection == "約束違反"
    broken = replace(bc.ObservationE0(), receipt_layouts=bc.RECEIPT_LAYOUTS[1:])
    assert bc.validate_observation_boundary(broken, bc.ObservationTrace(())).connection == "約束違反"
def test_false_saved_and_self_consistent_wrong_receipt_are_not_oracles():
    bc = observation_check
    contract, trace, (first,) = _handmade_receipt()
    corrupt = replace(trace, bodies=frozenset((Body(first.seal, b"wrong-salt", first.payload),)))
    assert not bc.ledger_saved(first.point, corrupt, contract.codec)
    assert _contract_failures(bc.evaluate_observations(contract, corrupt), "INV-4.a")
    # Rebuild every checksum consistently around a wrong content. Only the
    # independent EH -> all-record-fields conversion can catch this candidate.
    wrong = _handmade_prepared(replace(first.record, content=obj(writer="someone-else")))
    events = trace.events[:-1] + (replace(trace.events[-1], value=bc.FirstPrepared(wrong)),)
    corrupt = replace(trace, events=events, bodies=frozenset((Body(wrong.seal, wrong.salt, wrong.payload),)), entries=frozenset((Entry(wrong.point, wrong.header),)))
    assert bc.ledger_saved(wrong.point, corrupt, contract.codec)
    assert _contract_failures(bc.evaluate_observations(contract, corrupt), "INV-4.c")
def test_receipt_reaccept_and_boot_close_save_keep_full_identity_and_both_slots():
    bc = observation_check
    contract, trace, firsts = _handmade_receipt("Boot")
    accepted = trace.events[1]
    changed = replace(accepted, value=replace(accepted.value, created=Reading("run", "M", 99)))
    assert _contract_failures(bc.evaluate_observations(contract, replace(trace, events=trace.events + (changed,))), "INV-1.b")
    slots = tuple(e.key for e in trace.events if e.tag == "FirstPrepare")
    key = bc.CompletionKey("O-01", ("run", 1), "save", slots[0])
    binding = bc.CompletionBinding(key, "Post", bc.ReceiptKey("run", 1), slots, bc.Owner("P.receipts", ("run", 1)))
    contract = replace(contract, completions=(binding,))
    close = bc.ObservationEvent("CloseSave", key, bc.CloseSave(slots))
    assert not bc.evaluate_observations(contract, replace(trace, events=trace.events + (close,))).violations
    short_close = replace(close, value=bc.CloseSave(slots[:1]))
    assert _contract_failures(bc.evaluate_observations(contract, replace(trace, events=trace.events + (short_close,))), "INV-2.a")
    missing_second = replace(trace, entries=frozenset((Entry(firsts[0].point, firsts[0].header),)), events=trace.events + (close,))
    assert _contract_failures(bc.evaluate_observations(contract, missing_second), "INV-4.c")
def _handmade_worker():
    bc = observation_check
    records, bodies, entries = _handmade_ledger(("worker-process", "worker-reader", "worker-request"))
    d = replace(publication().plans[0].works[0], process=records["worker-process"].point, reader=records["worker-reader"].point, request=records["worker-request"].point, trigger=records["worker-request"].point, input_points=frozenset(), required=frozenset(), permissions=frozenset())
    contract = bc.ObservationE0(descriptors=(d,), capacity=(("measure", 1),), allocation=(("measure", 1),), generation_sources=((d.work_id, "actual-port"),))
    key = bc.WorkToken(d.work_id, "one-token")
    events = (
        bc.ObservationEvent("Reserve", key, bc.Reserved(d, d.need)), bc.ObservationEvent("Launch", key, bc.WrapperEvent("wrapper")), bc.ObservationEvent("ConsumeToken", key, bc.WrapperEvent("wrapper")), bc.ObservationEvent("EnterBody", key, bc.BodyEntered("wrapper", Reading("run", "M", 0))), bc.ObservationEvent("ReadInputs", key, bc.InputRead(d, d.numerical_view, ())),
    )
    return contract, bc.ObservationTrace(events, bodies, entries), key
def test_actual_worker_inputs_token_and_stop_release_are_separate_observations():
    bc = observation_check
    contract, trace, key = _handmade_worker()
    assert not bc.evaluate_observations(contract, trace).violations
    release = bc.ObservationEvent("Release", key, bc.Released((("measure", 1),)))
    result = bc.evaluate_observations(contract, replace(trace, events=trace.events + (release,)))
    assert _contract_failures(result, "INV-10.b")
    stopped = bc.ObservationEvent("Stop", key, bc.Stopped("actual-stop-observation"))
    result = bc.evaluate_observations(contract, replace(trace, events=trace.events + (stopped, release)))
    assert not result.violations, result.violations
    double_entry = replace(trace, events=trace.events + (trace.events[2], trace.events[3]))
    assert _contract_failures(bc.evaluate_observations(contract, double_entry), "INV-3.a")
    read = trace.events[-1]
    changed = replace(read, value=replace(read.value, descriptor=replace(read.value.descriptor, args=obj(changed="data"))))
    assert _contract_failures(bc.evaluate_observations(contract, replace(trace, events=trace.events[:-1] + (changed,))), "INV-8.b")
def test_worker_entry_is_atomic_on_edges_and_ew_cannot_be_quotiented():
    bc = observation_check
    contract, trace, key = _handmade_worker()
    before = replace(trace, events=trace.events[:2])
    result = bc.evaluate_observation_step(contract, before, trace, trace.events[2:])
    assert not result.violations, result.violations
    split = replace(before, events=trace.events[:3])
    assert _contract_failures(bc.evaluate_observation_step(contract, before, split, (trace.events[2],)), "INV-3.a")
    assert _contract_failures(bc.evaluate_observation_step(contract, trace, trace, (trace.events[3],)), "INV-3.b")
def test_io_retry_edges_keep_every_occurrence_and_require_actual_body_confirmation():
    bc = observation_check
    contract, trace, (first,) = _handmade_receipt()
    slot = trace.events[-1].key
    put_key = bc.IOKey(slot, "PutBody", "put")
    put = bc.ObservationEvent("IORequest", put_key, bc.IORequest(first))
    body = Body(first.seal, first.salt, first.payload)
    lost = bc.ObservationEvent("IOResponse", put_key, bc.IOResponse("lost", body))
    add = bc.ObservationEvent("IORequest", bc.IOKey(slot, "AddEntry", "entry"), bc.IORequest(first))
    before = replace(trace, events=trace.events + (put, lost), entries=frozenset())
    after = replace(before, events=before.events + (add,))
    assert _contract_failures(bc.evaluate_observation_step(contract, before, after, (add,)), "INV-4.c")
    read_key = bc.IOKey(slot, "ReadBody", "read")
    read = bc.ObservationEvent("IORequest", read_key, bc.IORequest(first))
    readback = bc.ObservationEvent("ReadBack", read_key, bc.ReadBack(body))
    before = replace(before, events=before.events + (read, readback))
    after = replace(before, events=before.events + (add,))
    assert not bc.evaluate_observation_step(contract, before, after, (add,)).violations
    assert not bc.evaluate_observation_step(contract, after, after, (put, lost)).violations
    assert _contract_failures(bc.evaluate_observation_step(contract, before, before, (add,)), "INV-3.b")
def test_application_uses_declared_projection_and_reader_series_not_global_measurement_set():
    bc = observation_check
    key = bc.ApplicationKey(Point("reader"), Point("model"), Point("series"))
    binding = bc.ApplicationBinding(key, Contract("finite_reading", "1"), ("raw", 1), Point("B"), ("transition", 1), "kernel", (1, 2), frozenset(("m1",)), "digest")
    value = bc.Applied(binding.contract, binding.report_meaning, binding.binding, binding.transition_key, binding.kernel, binding.outcomes, binding.measurements, binding.input_digest, "new_application")
    first = bc.ObservationEvent("Apply", key, value)
    other_key = replace(key, reader=Point("another-reader"))
    other = replace(first, key=other_key)
    contract = bc.ObservationE0(applications=(binding, replace(binding, key=other_key)))
    assert not bc.evaluate_observations(contract, bc.ObservationTrace((first, other))).violations
    assert _contract_failures(bc.evaluate_observations(contract, bc.ObservationTrace((first, first))), "INV-6.b")
    replay = replace(first, value=replace(value, purpose="replay"))
    assert not bc.evaluate_observations(contract, bc.ObservationTrace((first, replay))).violations
    unsupported = replace(contract, applications=(replace(binding, unsupported=("bootstrap/2-projection",)),))
    result = bc.evaluate_observations(unsupported, bc.ObservationTrace((first,)))
    assert any("projection" in message for _, message in result.limitations)
def test_handmade_contract_checks_never_promote_identification_or_remove_human_rows(checked_cases):
    bc = observation_check
    contract, trace, _ = _handmade_receipt()
    checker = Checker()
    checker.on_observations(contract, trace)
    report = checker.report()
    assert not report.passed and not report.violations
    assert report.counts["違反なし・識別力確認済み"] == 0
    assert report.connection_counts == {"約束の未接続": 0, "約束違反": 0, "約束接続・部分判定": 47}
    assert report.human == tuple((h, "未点検") for h in HUMAN_IDS)
    disconnected = Checker()
    disconnected.on_observations(None, None)
    unconnected = disconnected.report()
    assert unconnected.connection_counts["約束の未接続"] == len(CONDITION_IDS)
    for result in (unconnected, *(r for _, _, r in checked_cases)):
        assert sum(result.counts.values()) == len(CONDITION_IDS)
        assert sum(result.connection_counts.values()) == len(CONDITION_IDS)
        assert result.counts["違反なし・識別力確認済み"] == 0
        assert not result.passed
        assert result.human == tuple((h, "未点検") for h in HUMAN_IDS)
    for _, _, connected in checked_cases:
        assert connected.connection_counts["約束の未接続"] == 0
        assert connected.connection_counts["約束接続・部分判定"] == len(CONDITION_IDS)
        # Shape connection must not erase a missing semantic observation.
        for row_id, tag in connected.unconnected_observations:
            row = next(r for r in connected.rows if r.condition_id == row_id)
            assert any(tag in reason and "未接続" in reason for reason in row.limitations)
            assert row.classification != "違反なし・識別力確認済み"
        assert not connected.contract_violations
def test_derivation_enumerates_e0_obligations_and_matches_full_plan_then_saved_contents():
    bc = observation_check
    contract, trace, (receipt,) = _handmade_receipt()
    env = trace.events[0].value.envelope
    slot = bc.SlotKey("derived-q", "request")
    qplan = RecordPlan("request", Contract("model.request", "1"), "Event", obj(previous_result=None))
    d = replace(publication().plans[0].works[0], stage="Wr", process=Point("process"), reader=Point("reader"), trigger=receipt.point, request=PlanRef(slot.unit, slot.slot), method=Contract("finite_update", "1"), purpose="derive", stage_slot="s0", args=obj(previous_result=None), input_points=frozenset((receipt.point,)))
    plan = AllowedPlan(slot.unit, "O-03", ("declared", 0), (qplan,), (d,))
    binding = bc.DerivationBinding(Point("delta"), "1", d.process, d.reader, d.purpose, env, trace.events[-1].key, "t0", "s0", frozenset(("t0",)), d.method, d.input_points, frozenset(), frozenset((receipt.point,)), None, slot, plan)
    contract = replace(contract, plans=(plan,), descriptors=(d,), derivations=(binding,))
    status, = bc.derive_observation_status(contract, trace)
    assert status.eligible and not status.published and not status.discharged
    publication_event = bc.ObservationEvent("Publish", bc.UnitKey(slot.unit), bc.Published(plan))
    published = replace(trace, events=trace.events + (publication_event,))
    status, = bc.derive_observation_status(contract, published)
    assert status.matched and not status.discharged
    q = _handmade_prepared(Record("q", Reading("run", "M", 2), qplan.contract, "Event", qplan.content, ()))
    saved = replace(published, events=published.events + (bc.ObservationEvent("FirstPrepare", slot, bc.FirstPrepared(q)),), bodies=published.bodies | frozenset((Body(q.seal, q.salt, q.payload),)), entries=published.entries | frozenset((Entry(q.point, q.header),)))
    assert bc.derive_observation_status(contract, saved)[0].discharged
    assert not bc.evaluate_observations(contract, saved).violations
    changed = replace(plan, works=(replace(d, reader=Point("different-reader")),))
    bad_publish = replace(publication_event, value=bc.Published(changed))
    assert _contract_failures(bc.evaluate_observations(contract, replace(trace, events=trace.events + (bad_publish,))), "INV-2.d")
    # Later added input must not repair Matchδ at the publication edge.
    before = replace(trace, entries=frozenset())
    assert _contract_failures(bc.evaluate_observation_step(contract, before, published, (publication_event,)), "INV-2.b")
    unsupported = replace(contract, derivations=(replace(binding, unsupported=("PATH-QOBS",)),))
    result = bc.evaluate_observations(unsupported, published)
    assert not _contract_failures(result, "INV-2.d")
    assert any("PATH-QOBS" in message for _, message in result.limitations)
def test_completion_handoff_preserves_condition_instance_and_is_not_achievement():
    bc = observation_check
    slot = bc.SlotKey("terminal", "T")
    key = bc.CompletionKey("O-09.b", ("purpose", 0), "handle", slot)
    owner = bc.Owner("P.work", "w")
    binding = bc.CompletionBinding(key, "Publish", bc.UnitKey("G"), (slot,), owner)
    handoff = bc.HandoffPurpose(owner, bc.Owner("P.units", "waiting"), frozenset((key,)), frozenset((key,)))
    contract = bc.ObservationE0(completions=(binding,))
    event = bc.ObservationEvent("HandoffPurpose", key, handoff)
    result = bc.evaluate_observations(contract, bc.ObservationTrace((event,)))
    assert not result.violations
    # History equality alone never establishes a transition; missing actual
    # condition snapshots must remain unconnected on the edge evaluator.
    edge = bc.evaluate_observation_step(contract, bc.ObservationTrace(()), bc.ObservationTrace((event,)), (event,))
    assert not edge.violations and any("owner" in message for _, message in edge.limitations)
    erased = replace(event, value=replace(handoff, after=frozenset()))
    assert _contract_failures(bc.evaluate_observations(contract, bc.ObservationTrace((erased,))), "INV-2.c")
def _handmade_ledger(labels):
    firsts = tuple(_handmade_prepared(Record(label, Reading("run", "M", 0), Contract("model.evidence", "1"), "Event", obj(value=label), ())) for label in labels)
    return (dict(zip(labels, firsts)), frozenset(Body(p.seal, p.salt, p.payload) for p in firsts), frozenset(Entry(p.point, p.header) for p in firsts))
def _handmade_adoption(reader=None):
    from hashlib import sha256
    from fb_machine import ActualAcquisition, Certificate, UpdateTarget, VerificationCall, VerificationReply
    bc = observation_check
    records, bodies, entries = _handmade_ledger(("Q", "R", "P", "C", "G", "A"))
    q, r, p, c = (records[label].point for label in ("Q", "R", "P", "C"))
    reader = Point("reader") if reader is None else reader
    target = UpdateTarget(q, r, frozenset((p,)), c)
    targets = frozenset((q, r, p, c))
    origin = _handmade_prepared(Record("clock-source", Reading("run", "M", 0), Contract("model.clock_source", "1"), "Event", obj(run="run", source="M"), ()))
    clock = _handmade_prepared(Record("acquisition-clock", Reading("run", "M", 2), Contract("clock_reading", "1"), "Event", obj(source=origin.point, reading=Reading("run", "M", 1)), ()))
    records.update(clock=clock, clock_source=origin)
    bodies, entries = bodies | {Body(v.seal, v.salt, v.payload) for v in (origin, clock)}, entries | {Entry(v.point, v.header) for v in (origin, clock)}
    g_content = obj(origin=reader, contents=tuple(sorted(targets, key=lambda point: point.cid)), clock=clock.point)
    g_plan = RecordPlan("g", Contract("content_acquired", "1"), "Event", g_content)
    old_g = records["G"]
    records["G"] = _handmade_prepared(replace(old_g.record, contract=g_plan.contract, content=g_content))
    bodies = (bodies - {Body(old_g.seal, old_g.salt, old_g.payload)}) | {Body(records["G"].seal, records["G"].salt, records["G"].payload)}
    entries = (entries - {Entry(old_g.point, old_g.header)}) | {Entry(records["G"].point, records["G"].header)}
    g, a = records["G"].point, records["A"].point
    g_unit = AllowedPlan("g-unit", "O-08", ("acquisition",), (g_plan,))
    contents = tuple((records[label].point, records[label].payload) for label in ("Q", "R", "P", "C"))
    view = frozenset(rec.point for rec in records.values())
    numerical = NumericalView(frozenset((q,)))
    d = replace(publication().plans[0].works[0], work_id="verify", stage="Wv", request=q, reader=reader, args=obj(target="independently-declared"), numerical_view=numerical)
    acquisition_key = bc.IntentKey(reader, "acquisition")
    adoption_key = bc.IntentKey(reader, "adoption")
    verification_key = bc.VerificationKey("verify", "call")
    call = VerificationCall("verify", target, numerical, view, d.args)
    result = obj(returned="certified-target")
    certificate = Certificate("independent-issued-port", target, reader, contents, numerical, frozenset((p,)), view, "registry-v1", Contract("finite_update_replay", "1"), sha256(_handmade_encode(result)).hexdigest())
    reply = VerificationReply("Success", target, reader, contents, numerical, frozenset((p,)), view, "registry-v1", certificate.checker, result, (), frozenset(), certificate)
    acquisition = ActualAcquisition("acquisition", reader, targets, contents, view, Reading("run", "M", 1), frozenset())
    adopted = bc.Adopted(a, c, r, None, None, verification_key, (acquisition_key,), frozenset((g,)), (bc.CausalNode(a, frozenset((g,))), bc.CausalNode(g, frozenset())), view)
    contract = bc.ObservationE0(descriptors=(d,), plans=(g_unit,), acquisitions=(bc.AcquisitionBinding(acquisition_key, targets, c, frozenset(), PlanRef(g_unit.unit, "g")),), verifications=(bc.VerificationBinding(verification_key, target, reader, numerical, frozenset((p,)), view, "registry-v1", certificate.checker, d.args),), adoptions=(bc.AdoptionBinding(adoption_key, c, r, None, verification_key, (acquisition_key,)),))
    events = (
        bc.ObservationEvent("Acquire", acquisition_key, bc.Acquired(acquisition)), bc.ObservationEvent("Publish", bc.UnitKey(g_unit.unit), bc.Published(g_unit)), bc.ObservationEvent("FirstPrepare", bc.SlotKey(g_unit.unit, "g"), bc.FirstPrepared(records["G"])), bc.ObservationEvent("VerifyCall", verification_key, bc.VerificationInvoked(call)), bc.ObservationEvent("CertificateIssued", verification_key, bc.CertificateIssued(certificate)), bc.ObservationEvent("VerifyReply", verification_key, bc.VerificationReturned(reply)), bc.ObservationEvent("ReserveAdoption", adoption_key, bc.AdoptionReserved(c)), bc.ObservationEvent("Adopt", adoption_key, adopted),
    )
    return contract, bc.ObservationTrace(events, bodies, entries)
def test_adoption_checks_actual_ancestry_not_visibility_and_not_a_success_flag():
    bc = observation_check
    contract, trace = _handmade_adoption()
    result = bc.evaluate_observations(contract, trace)
    assert not result.boundary.violations and not result.violations, result
    adopt = trace.events[-1]
    visible_only = replace(adopt.value, actual_ancestors=frozenset(), causal_dag=(bc.CausalNode(adopt.value.record, frozenset()),))
    bad = replace(trace, events=trace.events[:-1] + (replace(adopt, value=visible_only),))
    assert _contract_failures(bc.evaluate_observations(contract, bad), "INV-9.a")
    unissued = replace(trace, events=tuple(e for e in trace.events if e.tag != "CertificateIssued"))
    assert _contract_failures(bc.evaluate_observations(contract, unissued), "INV-9.a")
    reply = next(e for e in trace.events if e.tag == "VerifyReply")
    wrong_target_bytes = replace(reply.value.reply, target_contents=())
    bad = replace(trace, events=tuple(replace(e, value=bc.VerificationReturned(wrong_target_bytes)) if e is reply else e for e in trace.events))
    assert _contract_failures(bc.evaluate_observations(contract, bad), "INV-9.a")
def test_reference_paths_are_typed_and_operation_specific_without_guessing_closure():
    from fb_machine import TypedReference
    bc = observation_check
    records, bodies, entries = _handmade_ledger(("target",))
    point = records["target"].point
    contract_type = Contract("model.link", "1")
    ref = TypedReference("PATH-RESULT", ("request",), point, "UE", "generation")
    record = Record("linked", Reading("run", "M", 1), contract_type, "Event", obj(request=point, unrelated="Point-looking-text"), (ref,))
    first = _handmade_prepared(record)
    trace = bc.ObservationTrace((), bodies | frozenset((Body(first.seal, first.salt, first.payload),)), entries | frozenset((Entry(first.point, first.header),)))
    rule = bc.ReferenceBinding(contract_type, "PATH-RESULT", ("request",), "UE", "generation", "PrepareOne", "direct")
    contract = bc.ObservationE0(references=(rule,))
    assert not bc.evaluate_observations(contract, trace).violations
    bad_rule = replace(rule, path=("unrelated",))
    assert _contract_failures(bc.evaluate_observations(replace(contract, references=(bad_rule,)), trace), "INV-5.a")
    unsupported_rule = replace(rule, path_id="PATH-QOBS", closure="direct")
    assert bc.validate_observation_boundary(replace(contract, references=(unsupported_rule,)), trace).violations
def test_support_preserves_x_boundary_and_unknown_contract_does_not_become_empty_coverage():
    from fb_machine import Cell
    bc = observation_check
    records, bodies, entries = _handmade_ledger(("report", "evidence", "k"))
    report, evidence, k = (records[label].point for label in ("report", "evidence", "k"))
    key = bc.IntervalKey("k", "route", "run")
    interval = Interval("run", "M", 0, 2, True, False)
    actual = bc.IntervalObserved(Reading("run", "M", 2), interval, frozenset((Cell(0, 0), Cell(0, 2))), "measure", evidence, obj(monitored=True))
    declaration = bc.IntervalBinding(key, k, "measure", interval, (0, 2), Contract("model.measure", "1"), Contract("model.clock", "1"))
    binding = bc.IntervalEvidenceBinding(evidence, key, "Monitored", actual, records["evidence"].record)
    contract = bc.ObservationE0(intervals=(declaration,), interval_evidence=(binding,))
    claim = bc.CoverageClaimed(frozenset((report, evidence)), report, "no_arrival", Contract("unspecified", "1"), frozenset((evidence,)), actual.cells)
    events = (bc.ObservationEvent("Monitored", key, actual), bc.ObservationEvent("CertifiedCoverage", key, claim))
    trace = bc.ObservationTrace(events, bodies, entries)
    result = bc.evaluate_observations(contract, trace)
    assert not result.violations and not result.boundary.violations, result
    assert any("contract-specific Support" in message for _, message in result.limitations)
    outside = replace(events[1], value=replace(claim, view=frozenset((report,))))
    bad = replace(trace, events=(events[0], outside))
    assert _contract_failures(bc.evaluate_observations(contract, bad), "INV-12.a")
def test_artifact_observation_keeps_issued_checked_and_unsupported_semantics_distinct():
    bc = observation_check
    work = "evaluate"
    value = bc.ArtifactValue(Contract("math_artifact", "2"), Contract("compiler", "1"), "view-key", "registry-key", obj(model="opaque"), (), obj(branch="Selected"))
    generation = Generation(work, Point("eq"), "Ee", Reading("run", "M", 0), Reading("run", "M", 1), Outcome(OutcomeKind.RETURNED, obj(port="returned")), "actual-artifact-port")
    checked = bc.ArtifactChecked(value, "Selected", Point("eq"), Point("problem"), Point("df"), frozenset())
    port = bc.ArtifactPortBinding(work, value.contract, value.compiler, value.reader_view_key, value.registry_key, value.inputs, (value,), (checked,))
    contract = bc.ObservationE0(generation_sources=((work, "actual-artifact-port"),), artifacts=(port,))
    issued = bc.ObservationEvent("ArtifactIssued", bc.WorkKey(work), bc.ArtifactIssued(value, generation))
    check = bc.ObservationEvent("ArtifactChecked", bc.WorkKey(work), checked)
    result = bc.evaluate_observations(contract, bc.ObservationTrace((issued, check)))
    assert not result.violations and not result.boundary.violations, result
    assert any("full semantic closure" in message for _, message in result.limitations)
    altered = replace(check, value=replace(checked, result="NoDecision"))
    assert _contract_failures(bc.evaluate_observations(contract, bc.ObservationTrace((issued, altered))), "INV-16.b")
    assert _contract_failures(bc.evaluate_observations(contract, bc.ObservationTrace((check,))), "INV-16.a")
def test_observer_transport_rejects_separate_fake_el_and_changed_e0_without_marking_pass():
    bc = observation_check
    e0 = E0()
    state = Environment(e0).initial()
    contract = bc.ObservationE0(capacity=e0.capacity, allocation=e0.allocation)
    trace = bc.ObservationTrace((), clock=state.core.h.reading)
    checker = Checker()
    checker.on_state(StateObservation(0, state, e0, (), (), contract, trace))
    assert not checker.report().contract_violations
    _, fake_bodies, fake_entries = _handmade_ledger(("not-in-C/E",))
    checker.on_state(StateObservation(1, state, e0, (), (), contract, replace(trace, bodies=fake_bodies, entries=fake_entries)))
    assert any(v.path == "EL" for v in checker.report().contract_violations)
    checker.on_observations(replace(contract, capacity=(("measure", 7),)), trace)
    assert any(v.path == "E0" for v in checker.report().contract_violations)
    assert checker.report().connection_counts["約束違反"] == 47
    assert not checker.report().passed
def test_end_known_uses_actual_generation_first_post_prefix_and_saved_receipt():
    bc = observation_check
    contract, worker_trace, token = _handmade_worker()
    d = replace(contract.descriptors[0], stage="Wr")
    contract = replace(contract, descriptors=(d,))
    worker_trace = replace(worker_trace, events=tuple(
        replace(e, value=replace(e.value, descriptor=d)) if e.tag in ("Reserve", "ReadInputs") else e
        for e in worker_trace.events))
    outcome = Outcome(OutcomeKind.RETURNED, obj(answer="known reply, not certified"))
    generation = Generation(d.work_id, d.request, "Wr", Reading("run", "M", 0), Reading("run", "M", 1), outcome, "actual-port")
    event = Event("WorkFinished", obj(work=d.work_id, started=generation.started, finished=generation.finished, outcome=outcome))
    env = Envelope("run", 1, Reading("run", "M", 1), 1, event, "actual-port")
    _, receipt_trace, _ = _handmade_receipt("WorkFinished", env)
    returned = bc.ObservationEvent("WorkerReturn", token, bc.Returned(generation))
    trace = replace(receipt_trace, bodies=receipt_trace.bodies | worker_trace.bodies, entries=receipt_trace.entries | worker_trace.entries, events=worker_trace.events + (returned,) + receipt_trace.events)
    assert not bc.evaluate_observations(contract, trace).violations
    assert bc.observed_end_known(contract, trace, d.work_id) == (env, generation)
    assert bc.observed_end_known(contract, replace(trace, entries=frozenset()), d.work_id) is None
    # Full raw notice equality and environment provenance are necessary.
    source_lie = replace(env, source="sender-claimed-work-id")
    _, lied_receipt, _ = _handmade_receipt("WorkFinished", source_lie)
    lied = replace(lied_receipt, events=worker_trace.events + (returned,) + lied_receipt.events)
    assert bc.observed_end_known(contract, lied, d.work_id) is None
    false_start = replace(returned, value=bc.Returned(replace(generation, started=Reading("run", "M", 99))))
    bad = replace(trace, events=worker_trace.events + (false_start,) + receipt_trace.events)
    assert _contract_failures(bc.evaluate_observations(contract, bad), "INV-6.a")
def test_observation_schema_cannot_erase_semantic_gaps_or_mix_completion_key_types():
    bc = observation_check
    key = bc.CompletionKey("O-05", ("w",), "run", bc.WorkKey("w"))
    binding = bc.CompletionBinding(key, "EndKnown", bc.ReceiptKey("run", 1), (), bc.Owner("P.work", "w"))
    report = bc.validate_observation_boundary(bc.ObservationE0(completions=(binding,)), bc.ObservationTrace(()))
    assert report.connection == "約束違反"
    assert any("trigger/source" in f.message for f in report.violations)
def test_new_contract_step_clauses_keep_the_paper_property_kind():
    bc = observation_check
    contract, trace, _ = _handmade_worker()
    before = replace(trace, events=trace.events[:2])
    result = bc.evaluate_observation_step(contract, before, trace, trace.events[2:])
    row_kinds = {r.condition_id: r.kinds for r in ROWS}
    from fb_check import PropertyKind
    assert all(PropertyKind.STEP in row_kinds[c.row] for c in result.clauses)
def test_host_unknown_has_its_own_provenance_and_never_implies_actual_return_or_stop():
    bc = observation_check
    contract, worker, token = _handmade_worker()
    d = replace(contract.descriptors[0], stage="D")
    worker = replace(worker, events=tuple(replace(e, value=replace(e.value, descriptor=d))
                     if e.tag in ("Reserve", "ReadInputs") else e for e in worker.events))
    basis = obj(reason="result-not-confirmed")
    outcome = Outcome(OutcomeKind.UNKNOWN, basis)
    env = Envelope("run", 1, Reading("run", "M", 1), 1, Event("DrawReturned", obj(work=d.work_id, outcome=outcome)), "host-observer")
    declaration = bc.HostUnknownBinding(d.work_id, "host-observer", d.request, "D", basis)
    contract = replace(contract, descriptors=(d,), host_unknowns=(declaration,))
    _, receipt, _ = _handmade_receipt("DrawReturned", env)
    unknown = bc.ObservationEvent("HostUnknown", bc.WorkKey(d.work_id), bc.UnknownObserved(env, d.request, "D", basis, (worker.events[3],)))
    trace = replace(receipt, bodies=receipt.bodies | worker.bodies, entries=receipt.entries | worker.entries, events=worker.events + (unknown,) + receipt.events)
    assert not bc.evaluate_observations(contract, trace).violations
    assert bc.observed_end_known(contract, trace, d.work_id) == (env, unknown.value)
    from fb_machine import Source
    assert bc.declaration_value(contract, trace, Source("terminal_basis", d.work_id)) == basis
    for name in ("generation", "started_clock", "finished_clock"):
        with pytest.raises(bc.UnresolvedDeclaration):
            bc.declaration_value(contract, trace, Source(name, d.work_id))
    release = bc.ObservationEvent("Release", token, bc.Released(d.need))
    assert _contract_failures(bc.evaluate_observations(contract, replace(trace, events=trace.events + (release,))), "INV-10.b")
    unsupported_basis = replace(unknown, value=replace(unknown.value, witnesses=()))
    bad = replace(trace, events=worker.events + (unsupported_basis,) + receipt.events)
    assert _contract_failures(bc.evaluate_observations(contract, bad), "INV-15.a")
# Turn 3: first-Accept identity and declarations before materialization. These
# fixtures exercise comparisons; they do NOT establish discriminator coverage.
def test_reaccept_after_clock_advance_preserves_first_accept_creation_time():
    bc = observation_check
    e0 = E0(postings=(Posting("first", received(), 1), Posting("second", received(), 2)))
    env, window = Environment(e0), CorrectWindow(e0)
    state = env.step(env.initial(), Action("Post", ("first",)), window).state
    envelope = state.core.h.queue[0]
    first = env.step(state, Action("Accept", (envelope,)), window)
    assert not bc.evaluate_observation_step(e0.observation_contract, state.evidence.observation_trace, first.state.evidence.observation_trace, first.events).violations
    advanced = env.step(first.state, Action("Post", ("second",)), window).state
    retry = env.step(advanced, Action("Accept", (envelope,)), window)
    assert not bc.evaluate_observation_step(e0.observation_contract, advanced.evidence.observation_trace, retry.state.evidence.observation_trace, retry.events).violations
    before = advanced.evidence.observation_trace
    changed = tuple(replace(e, value=replace(e.value, created=before.clock)) if e.tag == "Accept" else e for e in retry.events)
    after = replace(retry.state.evidence.observation_trace, events=before.events + changed)
    assert _contract_failures(bc.evaluate_observation_step(e0.observation_contract, before, after, changed), "INV-1.b")
    # First-time creation still uses the actual host reading.
    before = state.evidence.observation_trace
    changed = tuple(replace(e, value=replace(e.value, created=Reading(e0.run, e0.clock_source, 99)))
                    if e.tag == "Accept" else e for e in first.events)
    after = replace(first.state.evidence.observation_trace, events=before.events + changed)
    assert _contract_failures(bc.evaluate_observation_step(e0.observation_contract, before, after, changed), "INV-1.b")
def test_reaccept_uses_first_matching_full_original_not_last_or_same_number():
    bc = observation_check
    contract, trace, _ = _handmade_receipt()
    first = next(e for e in trace.events if e.tag == "Accept")
    wrong = replace(first, value=replace(first.value, created=replace(first.value.created, rank=99)))
    before = replace(trace, events=trace.events + (wrong,), clock=wrong.value.created)
    after = replace(before, events=before.events + (wrong,))
    assert _contract_failures(bc.evaluate_observation_step(contract, before, after, (wrong,)), "INV-1.b")
    distinct = replace(first, value=replace(first.value, envelope=replace(first.value.envelope, source="different-original")))
    before = replace(trace, clock=wrong.value.created)
    after = replace(before, events=before.events + (distinct,))
    assert _contract_failures(bc.evaluate_observation_step(contract, before, after, (distinct,)), "INV-1.b")
def _handmade_declared_slot():
    bc = observation_check
    plan = RecordPlan("slot", Contract("model.normative", "1"), "Event", obj(value="declared"))
    unit = AllowedPlan("unit", "O-02", (), (plan,))
    first = _handmade_prepared(Record("fresh-name", Reading("run", "M", 0), plan.contract, plan.category, plan.content, ()))
    events = (bc.ObservationEvent("Publish", bc.UnitKey("unit"), bc.Published(unit)), bc.ObservationEvent("FirstPrepare", bc.SlotKey("unit", "slot"), bc.FirstPrepared(first)))
    trace = bc.ObservationTrace(events, frozenset((Body(first.seal, first.salt, first.payload),)), frozenset((Entry(first.point, first.header),)), first.record.at)
    return bc.ObservationE0(plans=(unit,)), trace, first
def test_planref_is_resolved_from_normative_plan_codec_and_saved_bytes_only():
    bc = observation_check
    contract, trace, first = _handmade_declared_slot()
    ref = PlanRef("unit", "slot")
    assert bc.DeclarationResolver(contract, trace).resolve(ref) == first.point
    with pytest.raises(bc.UnresolvedDeclaration):
        bc.DeclarationResolver(contract, replace(trace, entries=frozenset())).resolve(ref)
    # Entire self-consistent wrong record + CID + body must still fail against E0.
    wrong = _handmade_prepared(replace(first.record, content=obj(value="window-invented")))
    bad = replace(trace, events=(trace.events[0], replace(trace.events[1], value=bc.FirstPrepared(wrong))), bodies=frozenset((Body(wrong.seal, wrong.salt, wrong.payload),)), entries=frozenset((Entry(wrong.point, wrong.header),)))
    assert bc.ledger_saved(wrong.point, bad, contract.codec)
    with pytest.raises(bc.UnresolvedDeclaration):
        bc.DeclarationResolver(contract, bad).resolve(ref)
    assert _contract_failures(bc.evaluate_observations(contract, bad), "INV-4.c")
    worker_contract, worker, _ = _handmade_worker()
    descriptor = replace(worker_contract.descriptors[0], input_points=frozenset((ref,)))
    declaration = replace(contract, descriptors=(descriptor,), capacity=worker_contract.capacity, allocation=worker_contract.allocation)
    actual_descriptor = replace(descriptor, input_points=frozenset((wrong.point,)))
    work_events = tuple(replace(e, value=replace(e.value, descriptor=descriptor)) if e.tag == "Reserve"
                        else replace(e, value=bc.InputRead(actual_descriptor, actual_descriptor.numerical_view, ((ref, wrong.point),)))
                        if e.tag == "ReadInputs" else e for e in worker.events)
    forged = replace(bad, events=bad.events + work_events)
    assert _contract_failures(bc.evaluate_observations(declaration, forged), "INV-8.b")
def test_interval_binding_keeps_planref_without_inventing_a_point():
    bc = observation_check
    scenario = next(s for s in _CHECK_SCENARIOS if s.id == "CHECK-EI-transport")
    contract = bc.bind_interval_declarations(scenario.e0.observation_contract, scenario.e0)
    assert contract.intervals[0].point == PlanRef("k-plan", "k")
    event = bc.ObservationEvent("ReportGenerated", contract.intervals[0].key, bc.IntervalObserved(Reading("run-0", "M", 0), None, frozenset(), "measure-0", None, obj(branch="Unproved")))
    result = bc.evaluate_observations(contract, bc.ObservationTrace((event,)))
    assert not result.boundary.violations and not result.violations
    with pytest.raises(bc.UnresolvedDeclaration):
        bc.DeclarationResolver(contract, bc.ObservationTrace((event,))).resolve(contract.intervals[0].point)
    wrong = replace(event, value=replace(event.value, work="other-work"))
    assert _contract_failures(bc.evaluate_observations(contract, bc.ObservationTrace((wrong,))), "INV-12.a")
def _handmade_source_generation():
    bc = observation_check
    contract, worker, token = _handmade_worker()
    descriptor = contract.descriptors[0]
    outcome = Outcome(OutcomeKind.RETURNED, obj(answer="actual"))
    generation = Generation(descriptor.work_id, descriptor.request, descriptor.stage, Reading("run", "M", 0), Reading("run", "M", 1), outcome, "actual-port")
    envelope = Envelope("run", 1, Reading("run", "M", 1), 1, Event("WorkFinished", obj(work=descriptor.work_id, started=generation.started, finished=generation.finished, outcome=outcome)), "actual-port")
    _, receipt, firsts = _handmade_receipt("WorkFinished", envelope)
    trace = replace(receipt, bodies=receipt.bodies | worker.bodies, entries=receipt.entries | worker.entries, events=worker.events + (bc.ObservationEvent("WorkerReturn", token, bc.Returned(generation)),) + receipt.events)
    return contract, trace, generation, firsts[0].point
@pytest.mark.parametrize("kind", ("first_receipt", "generation", "outcome", "numerical_view"))
def test_source_publication_expands_e0_from_independent_history_and_rejects_changed_values(kind):
    from fb_machine import Source
    bc = observation_check
    contract, trace, generation, receipt = _handmade_source_generation()
    expected = {"first_receipt": receipt, "generation": generation, "outcome": generation.outcome, "numerical_view": contract.descriptors[0].numerical_view}[kind]
    record = RecordPlan("output", Contract("model.source", "1"), "Event", obj(value=Source(kind, generation.work)))
    plan = AllowedPlan("source-unit", "O-06", (), (record,))
    contract = replace(contract, plans=(plan,))
    expanded = replace(plan, records=(replace(record, content=obj(value=expected)),))
    event = bc.ObservationEvent("Publish", bc.UnitKey(plan.unit), bc.Published(expanded))
    result = bc.evaluate_observations(contract, replace(trace, events=trace.events + (event,)))
    assert not result.violations and not result.boundary.violations, result
    wrong = replace(event, value=bc.Published(replace(expanded, records=(replace(record, content=obj(value="wrong")),))))
    assert _contract_failures(bc.evaluate_observations(contract, replace(trace, events=trace.events + (wrong,))), "INV-2.b")
    # Later observations may not provide Source inputs missing at publication.
    early = replace(trace, events=(event,) + trace.events)
    if kind != "numerical_view":
        result = bc.evaluate_observations(contract, early)
        assert any(row == "INV-2.b" and "未接続" in reason for row, reason in result.limitations)
def test_source_first_preparation_matches_the_publication_root_and_full_plan():
    from fb_machine import Source
    bc = observation_check
    contract, trace, generation, _ = _handmade_source_generation()
    plan = AllowedPlan("source-unit", "O-06", (), (
        RecordPlan("output", Contract("model.source", "1"), "Event", obj(value=Source("outcome", generation.work))),))
    contract = replace(contract, plans=(plan,))
    expanded = replace(plan, records=(replace(plan.records[0], content=obj(value=generation.outcome)),))
    first = _handmade_prepared(Record("fresh", trace.clock, expanded.records[0].contract, "Event", expanded.records[0].content, ()))
    events = (bc.ObservationEvent("Publish", bc.UnitKey(plan.unit), bc.Published(expanded)), bc.ObservationEvent("FirstPrepare", bc.SlotKey(plan.unit, "output"), bc.FirstPrepared(first)))
    after = replace(trace, events=trace.events + events)
    assert not bc.evaluate_observations(contract, after).violations
    wrong = _handmade_prepared(replace(first.record, content=obj(value="different-result")))
    bad = replace(after, events=after.events[:-1] + (replace(events[-1], value=bc.FirstPrepared(wrong)),))
    assert _contract_failures(bc.evaluate_observations(contract, bad), "INV-4.c")
    # Unknown Source meanings remain unconnected, even if an output is supplied.
    unknown = replace(plan, records=(replace(plan.records[0], content=obj(value=Source("unknown", "w0"))),))
    result = bc.evaluate_observations(replace(contract, plans=(unknown,)), after)
    assert any("未対応: undeclared Source" in reason for _, reason in result.limitations)
def test_connected_dynamic_source_publication_matches_independent_expansion():
    from fb_machine import Source
    bc = observation_check
    base = publication()
    record = RecordPlan("output", Contract("model.source", "1"), "Event", obj(view=Source("numerical_view", "w0")))
    plan = AllowedPlan("source-unit", "O-06", (), (record,))
    e0 = replace(base, plans=base.plans + (plan,))
    state = boundary_state(e0, published=True)
    env, window = Environment(e0), CorrectWindow(e0)
    published = env.step(state, Action("PublishUnit", (plan.unit,)), window)
    result = bc.evaluate_observations(e0.observation_contract, published.state.evidence.observation_trace)
    assert not result.boundary.violations and not result.violations, result.violations
def test_derivation_source_match_and_discharge_use_the_same_independent_expansion():
    from fb_machine import Source
    bc = observation_check
    contract, trace, (receipt,) = _handmade_receipt()
    envelope = trace.events[0].value.envelope
    slot = bc.SlotKey("derived", "q")
    descriptor = replace(_handmade_worker()[0].descriptors[0], stage="Wr", purpose="derive", stage_slot="s", method=Contract("finite_update", "1"), input_points=frozenset((receipt.point,)),
                         args=obj(previous_result=None), request=PlanRef(slot.unit, slot.slot))
    record = RecordPlan("q", Contract("model.request", "1"), "Event", obj(view=Source("numerical_view", descriptor.work_id)))
    plan = AllowedPlan(slot.unit, "O-03", (), (record,), (descriptor,))
    binding = bc.DerivationBinding(Point("delta"), "1", descriptor.process, descriptor.reader, "derive", envelope,
                                  trace.events[-1].key, "trigger", "s", frozenset(("trigger",)), descriptor.method,
                                  descriptor.input_points, frozenset(), frozenset((receipt.point,)), None, slot, plan)
    contract = replace(contract, plans=(plan,), descriptors=(descriptor,), derivations=(binding,))
    expanded = replace(plan, records=(replace(record, content=obj(view=descriptor.numerical_view)),))
    publish = bc.ObservationEvent("Publish", bc.UnitKey(plan.unit), bc.Published(expanded))
    first = _handmade_prepared(Record("q", trace.clock, record.contract, "Event", expanded.records[0].content, ()))
    saved = replace(trace, events=trace.events + (publish, bc.ObservationEvent("FirstPrepare", slot, bc.FirstPrepared(first))),
                    bodies=trace.bodies | {Body(first.seal, first.salt, first.payload)}, entries=trace.entries | {Entry(first.point, first.header)})
    status, = bc.derive_observation_status(contract, saved)
    assert status.matched and status.discharged and not status.unsupported
    wrong = replace(publish, value=bc.Published(replace(expanded, records=(replace(record, content=obj(view="wrong")),))))
    assert not bc.derive_observation_status(contract, replace(saved, events=trace.events + (wrong, saved.events[-1])))[0].matched
def test_acquisition_before_g_and_saved_g_are_checked_at_separate_boundaries():
    from fb_machine import Source
    bc = observation_check
    contract, complete = _handmade_adoption()
    acquire = complete.events[0]
    g_first = complete.events[2].value.prepared
    g_body, g_entry = Body(g_first.seal, g_first.salt, g_first.payload), Entry(g_first.point, g_first.header)
    before = replace(complete, events=(), bodies=complete.bodies - {g_body}, entries=complete.entries - {g_entry},
                     clock=acquire.value.acquisition.reading)
    acquired = replace(before, events=(acquire,))
    assert acquire.value.record is None
    assert not bc.evaluate_observations(contract, acquired).violations
    assert not bc.evaluate_observation_step(contract, before, acquired, (acquire,)).violations
    assert not bc.acquisition_record_points(contract, acquired, acquire.key, acquire.value.acquisition)
    assert bc.DeclarationResolver(contract, acquired).sources(Source("acquisition", acquire.key.intent)) == acquire.value.acquisition
    with pytest.raises(bc.UnresolvedDeclaration):
        bc.DeclarationResolver(contract, before).sources(Source("acquisition", acquire.key.intent))
    # Actual body and entry writes, with both EP requests retained on the edge.
    prepared = replace(acquired, events=complete.events[:3], bodies=complete.bodies)
    body_key = bc.IOKey(complete.events[2].key, "PutBody", "body")
    prepared = replace(prepared, events=prepared.events + (
        bc.ObservationEvent("IORequest", body_key, bc.IORequest(g_first)),
        bc.ObservationEvent("IOResponse", body_key, bc.IOResponse("acknowledged", g_body))))
    entry_key = bc.IOKey(complete.events[2].key, "AddEntry", "entry")
    events = (bc.ObservationEvent("IORequest", entry_key, bc.IORequest(g_first)),
              bc.ObservationEvent("IOResponse", entry_key, bc.IOResponse("acknowledged", g_entry)))
    after = replace(prepared, events=prepared.events + events, entries=prepared.entries | {g_entry})
    assert not bc.evaluate_observation_step(contract, prepared, after, events).violations
    assert bc.acquisition_record_points(contract, after, acquire.key, acquire.value.acquisition) == frozenset((g_first.point,))
    no_actual = replace(prepared, events=tuple(e for e in prepared.events if e.tag != "Acquire"))
    wrong = replace(after, events=no_actual.events + events)
    assert _contract_failures(bc.evaluate_observation_step(contract, no_actual, wrong, events), "INV-9.a")
    # An internally consistent G with a different clock is still the wrong G.
    lied = replace(acquire.value.acquisition, reading=replace(acquire.value.acquisition.reading, rank=9))
    assert not bc.acquisition_record_points(contract, after, acquire.key, lied)
    early_g = replace(complete, events=(complete.events[1], acquire, *complete.events[2:]))
    assert _contract_failures(bc.evaluate_observations(contract, early_g), "INV-2.b")
    missing_g = replace(contract, acquisitions=(replace(contract.acquisitions[0], record=PlanRef("missing-g", "g")),))
    assert not bc.acquisition_record_points(missing_g, after, acquire.key, acquire.value.acquisition)
    unbound = replace(contract, acquisitions=(replace(contract.acquisitions[0], record=None),))
    assert not bc.acquisition_record_points(unbound, after, acquire.key, acquire.value.acquisition)
    partial = bc.evaluate_observation_step(unbound, prepared, after, events)
    assert not partial.violations and any(row == "INV-9.a" and "未接続" in reason for row, reason in partial.limitations)
# Turn 4: independent occurrence / actual custody / declaration resolution.
# Frozen counterexamples and handmade ports are NOT identification runs.
def _interval_undertaking_fixture():
    bc = observation_check
    interval = Interval("run", "M", 0, 2, True, False)
    request = IntervalRequest("k", PlanRef("k-plan", "k"), "route", "measure", interval,
                              Contract("model.measure", "1"), Contract("model.clock", "1"),
                              interval_cells(interval, (0, 1, 2, 3)))
    key = bc.IntervalKey(request.id, request.route_epoch, interval.run)
    owner = bc.Owner("H", request.id)
    declaration = bc.IntervalBinding(key, request.point, request.work, interval, (0, 1, 2, 3),
                                      request.measurement_contract, request.clock_contract)
    slot = bc.SlotKey("k-plan", "k")
    conditions = tuple(bc.CompletionBinding(bc.CompletionKey("O-04", ("route", "k"), kind, target),
                                            "IntervalRequest", key, (slot,) if kind == "save" else (), owner)
                       for kind, target in (("save", slot), ("handle", bc.WorkKey(request.work))))
    contract = bc.ObservationE0(intervals=(declaration,), completions=conditions)
    event = bc.ObservationEvent("IntervalUndertaken", key, bc.IntervalUndertaken(request, owner, Reading("run", "M", 0)))
    return contract, event
def test_interval_occurrence_requires_actual_undertaking_even_before_publication():
    bc = observation_check
    contract, undertaking = _interval_undertaking_fixture()
    before = bc.ObservationTrace((), clock=undertaking.value.reading)
    assert all(bc.completion_occurred(b, contract, before) is False for b in contract.completions)
    # Configuration, execution, reporting and publication do not stand in for
    # accepting responsibility. These six observations may exist independently.
    for tag in ("RouteApplied", "MeasurementStarted", "Monitored", "Measured", "ReportGenerated", "MeasurementEnded"):
        value = bc.IntervalObserved(before.clock, contract.intervals[0].interval, frozenset(), "measure", None, obj())
        trace = replace(before, events=(bc.ObservationEvent(tag, undertaking.key, value),))
        assert all(bc.completion_occurred(b, contract, trace) is False for b in contract.completions)
    published = replace(before, events=(bc.ObservationEvent("Publish", bc.UnitKey("k-plan"),
                                      bc.Published(AllowedPlan("k-plan", "O-04", (), ()))),))
    assert all(bc.completion_occurred(b, contract, published) is False for b in contract.completions)
    after = replace(before, events=(undertaking,))
    assert all(bc.completion_occurred(b, contract, after) is True for b in contract.completions)
    assert not bc.evaluate_observations(contract, after).violations
    assert not bc.evaluate_observation_step(contract, before, after, (undertaking,)).violations
    assert not bc.validate_observation_boundary(contract, after).violations
@pytest.mark.parametrize("mutation", ("cells", "contract", "clock", "key"))
def test_interval_undertaking_checks_full_request_and_actual_clock(mutation):
    bc = observation_check
    contract, event = _interval_undertaking_fixture()
    before = bc.ObservationTrace((), clock=event.value.reading)
    request = event.value.request
    if mutation == "cells":
        event = replace(event, value=replace(event.value, request=replace(request, cells=frozenset())))
    elif mutation == "contract":
        event = replace(event, value=replace(event.value, request=replace(request, measurement_contract=Contract("wrong", "1"))))
    elif mutation == "clock":
        event = replace(event, value=replace(event.value, reading=replace(event.value.reading, rank=1)))
    else:
        event = replace(event, key=replace(event.key, request="another-request"))
    after = replace(before, events=(event,))
    if mutation == "key":
        assert bc.validate_observation_boundary(contract, after).violations
    elif mutation == "clock":
        assert _contract_failures(bc.evaluate_observation_step(contract, before, after, (event,)), "INV-12.a")
    else:
        assert _contract_failures(bc.evaluate_observations(contract, after), "INV-12.a")
        assert not any(bc.completion_occurred(b, contract, after) for b in contract.completions)
def test_later_interval_undertaking_cannot_justify_an_earlier_close_save():
    bc = observation_check
    contract, undertaken = _interval_undertaking_fixture()
    binding = contract.completions[0]
    slot = binding.slots[0]
    record = Record("k", undertaken.value.reading, Contract("model.interval", "1"), "Event", obj(request="k"), ())
    first = _handmade_prepared(record)
    plan = AllowedPlan(slot.unit, "O-04", (), (RecordPlan(slot.slot, record.contract, "Event", record.content),))
    contract = replace(contract, plans=(plan,))
    prepare = bc.ObservationEvent("FirstPrepare", slot, bc.FirstPrepared(first))
    close = bc.ObservationEvent("CloseSave", binding.key, bc.CloseSave((slot,)))
    trace = bc.ObservationTrace((undertaken, prepare, close), frozenset((Body(first.seal, first.salt, first.payload),)),
                                frozenset((Entry(first.point, first.header),)), record.at)
    assert not bc.evaluate_observations(contract, trace).violations
    assert _contract_failures(bc.evaluate_observations(contract, replace(trace, events=(prepare, close, undertaken))), "INV-2.a")
    concrete = replace(undertaken, value=replace(undertaken.value, request=replace(undertaken.value.request, point=first.point)))
    assert not bc.evaluate_observations(contract, replace(trace, events=trace.events + (concrete,))).violations
    # A future preparation cannot resolve a concrete target at an earlier
    # undertaking, even if the full final ledger already contains that record.
    assert _contract_failures(bc.evaluate_observations(contract, replace(trace, events=(concrete, prepare, close))), "INV-12.a")
    # P-10: preparation precedes undertaking, but a later actual save cannot
    # resolve the undertaking or make it an occurrence at CloseSave.
    history = replace(trace, events=(prepare, concrete, close))
    early, late = _p10_save_order(history, first.point, 1)
    assert not bc.evaluate_observations(contract, early).violations
    failure = bc.evaluate_observations(contract, late)
    for row in ("INV-12.a", "INV-2.a", "INV-4.c"):
        assert _contract_failures(failure, row)
    between = replace(history, events=(prepare, concrete) + _p10_writes(history, first.point) + (close,))
    assert _contract_failures(bc.evaluate_observations(contract, between), "INV-2.a")
def test_live_interval_retention_without_undertaking_is_unconnected_not_occurrence():
    bc = observation_check
    contract, undertaking = _interval_undertaking_fixture()
    e0 = E0(run="run", intervals=(undertaking.value.request,))
    env, window = Environment(e0), CorrectWindow(e0)
    before = env.initial()
    after = env.step(before, Action("RequestInterval", (undertaking.key.request,)), window).state
    checker = Checker()
    checker.on_state(StateObservation(0, before, e0, (), ()))
    checker.on_state(StateObservation(1, after, e0, (), ()))
    trace = after.evidence.observation_trace
    if not any(e.tag == "IntervalUndertaken" for e in trace.events):
        assert not any(bc.completion_occurred(b, contract, trace) for b in contract.completions)
        report = checker.report()
        assert report.unconnected_observations == (("INV-12.a", "IntervalUndertaken"), ("INV-2.a", "IntervalUndertaken"))
        assert all(any("IntervalUndertaken" in s for s in r.limitations) for r in report.rows
                   if r.condition_id in ("INV-2.a", "INV-12.a"))
        assert not report.passed and report.counts["違反なし・識別力確認済み"] == 0
@pytest.fixture(scope="module")
def checked_handoff_case():
    from fb_machine import HandoffRoute
    bc = observation_check
    base = publication()
    key = bc.CompletionKey("O-02", base.plans[0].key, "save", bc.SlotKey("initial", "process"))
    e0 = replace(base, handoff_routes=(HandoffRoute(key, bc.Owner("P.work", "w0")),))
    env, window = Environment(e0), CorrectWindow(e0)
    state = env.step(boundary_state(e0), Action("PublishUnit", ("initial",)), window).state
    scenario = Scenario("CHECK-connected-handoff", e0, 50, state,
                        Cut("K-purpose", frozenset(("PrepareOne", "ClaimStart", "ResolveWork", "Stop", "Release")),
                            ("subsequent work",)))
    graph = explore(scenario)
    edge = next(e for e in graph.edges if any(event.tag == "HandoffPurpose" for event in e.actual_events))
    return scenario, graph, edge, check_exploration(scenario, graph)
def test_connected_handoff_all_rows_use_actual_condition_custody(checked_handoff_case, capsys):
    scenario, graph, edge, report = checked_handoff_case
    assert graph.complete and len(graph.states) <= scenario.max_states <= 200_000
    assert not report.violations and not report.contract_violations, report.violations
    assert report.counts == {"違反": 0, "違反なし・識別力確認済み": 0, "違反なし・識別力未確認": 47}
    assert report.connection_counts == {"約束の未接続": 0, "約束違反": 0, "約束接続・部分判定": 47}
    assert report.human == tuple((h, "未点検") for h in HUMAN_IDS)
    assert not any("condition-owner" in reason for row in report.rows for reason in row.limitations)
    with capsys.disabled():
        print(f"\nCHECK {scenario.id}: states={len(graph.states)} edges={len(graph.edges)} "
              f"counts={report.counts} connections={report.connection_counts} human_unchecked={len(report.human)}", flush=True)
@pytest.mark.parametrize("mutation", ("source", "destination", "erased", "renamed", "achieved", "omitted_event", "no_events"))
def test_handoff_event_cannot_override_actual_before_after_custody(checked_handoff_case, mutation):
    bc = observation_check
    scenario, graph, edge, _ = checked_handoff_case
    before, after = graph.states[edge.source], graph.states[edge.target]
    events = edge.actual_events
    key = events[0].key
    old_rows, new_rows = before.core.p.conditions, after.core.p.conditions
    if mutation == "source":
        before = replace(before, core=replace(before.core, p=replace(before.core.p,
                         conditions=tuple(replace(c, owner=bc.Owner("P.work", "wrong-source")) if c.key == key else c for c in old_rows))))
    elif mutation == "destination":
        new_rows = tuple(replace(c, owner=bc.Owner("P.work", "wrong-destination")) if c.key == key else c for c in new_rows)
    elif mutation == "erased":
        new_rows = tuple(c for c in new_rows if c.key == key)  # removes OTHER members; event still claims all
    elif mutation == "renamed":
        new_rows = tuple(replace(c, key=replace(c.key, target=bc.SlotKey("other", "slot"))) if c.key == key else c for c in new_rows)
    elif mutation == "achieved":
        new_rows = tuple(replace(c, unmet=frozenset()) if c.key == key else c for c in new_rows)
    elif mutation == "omitted_event":
        events = events[1:]
    else:
        events = ()
    after = replace(after, core=replace(after.core, p=replace(after.core.p, conditions=new_rows)))
    # Keep the trace honest to the counterfactual event list; failure must come
    # from the independent P comparison, not merely a missing trace suffix.
    after_trace = replace(after.evidence.observation_trace, events=before.evidence.observation_trace.events + events)
    result = bc.evaluate_observation_step(scenario.e0.observation_contract, before.evidence.observation_trace,
                                          after_trace, events, before_state=before, after_state=after, action=edge.action)
    assert _contract_failures(result, "INV-2.c")
def test_handoff_unmet_union_does_not_assume_each_row_contains_the_whole_obligation(checked_handoff_case):
    bc = observation_check
    scenario, graph, edge, _ = checked_handoff_case
    before, after = graph.states[edge.source], graph.states[edge.target]
    group = frozenset(e.key for e in edge.actual_events)
    # Both per-condition sets and redundant copies of the full obligation set
    # have the same independently observed union. Neither is a success oracle.
    for copied_union in (False, True):
        def rows(state):
            return replace(state, core=replace(state.core, p=replace(state.core.p,
                conditions=tuple(replace(c, unmet=group if copied_union else frozenset((c.key,)))
                                 if c.key in group else c for c in state.core.p.conditions))))
        contract = replace(scenario.e0.observation_contract, completions=tuple(
            replace(b, owner=bc.Owner("P.work", "false-E0-owner")) if b.key in group else b
            for b in scenario.e0.observation_contract.completions))
        result = bc.evaluate_observation_step(contract, before.evidence.observation_trace, after.evidence.observation_trace,
                                              edge.actual_events, before_state=rows(before), after_state=rows(after), action=edge.action)
        assert not result.violations and not result.boundary.violations, result
        assert not any("condition-owner" in reason for _, reason in result.limitations)
    malformed = replace(after, core=replace(after.core, p=replace(after.core.p, conditions=list(after.core.p.conditions))))
    result = bc.evaluate_observation_step(scenario.e0.observation_contract, before.evidence.observation_trace,
                                          after.evidence.observation_trace, edge.actual_events,
                                          before_state=before, after_state=malformed, action=edge.action)
    assert result.boundary.connection == "約束違反" and result.boundary.violations
def _planref_verification_adoption():
    # Rebuild expected values with the test's independent codec; no window or
    # checker resolver constructs actual calls/replies/adoptions for this test.
    from dataclasses import fields, is_dataclass
    bc = observation_check
    reader_records, reader_bodies, reader_entries = _handmade_ledger(("reader",))
    contract, trace = _handmade_adoption(reader_records["reader"].point)
    trace = replace(trace, bodies=trace.bodies | reader_bodies, entries=trace.entries | reader_entries)
    verification = contract.verifications[0]
    arguments = obj(target=verification.target, reader=verification.reader, check_view=verification.check_view)
    contract = replace(contract, descriptors=(replace(contract.descriptors[0], args=arguments),),
                        verifications=(replace(verification, arguments=arguments),))
    trace = replace(trace, events=tuple(replace(e, value=bc.VerificationInvoked(replace(e.value.call, arguments=arguments)))
                                        if e.tag == "VerifyCall" else e for e in trace.events))
    # A-CLOCK-SOURCE: prepare the declared source before its clock evidence.
    roots = tuple(sorted((e for e in trace.entries if e.header.record.name != "G"),
                         key=lambda e: (e.header.record.contract.name != "model.clock_source", e.header.record.name)))
    refs = {e.point: PlanRef("roots", e.header.record.name) for e in roots}
    refs[trace.events[2].value.prepared.point] = PlanRef("g-unit", "g")
    def declare(value):
        if isinstance(value, Point):
            return refs.get(value, value)
        if is_dataclass(value):
            return replace(value, **{f.name: declare(getattr(value, f.name)) for f in fields(value)})
        if isinstance(value, (tuple, frozenset)):
            return type(value)(declare(v) for v in value)
        return value
    plans, firsts = [], []
    for entry in roots:
        record = entry.header.record
        plans.append(RecordPlan(record.name, record.contract, record.category, record.content))
        body = next(b for b in trace.bodies if b.seal == entry.header.seal)
        first = _handmade_prepared(record, entry.header.parents, body.salt)
        assert first.point == entry.point
        firsts.append(bc.ObservationEvent("FirstPrepare", bc.SlotKey("roots", record.name), bc.FirstPrepared(first)))
    contract = declare(replace(contract, plans=(AllowedPlan("roots", "O-02", (), tuple(plans)), *contract.plans)))
    # Publish promises the declaration (including PlanRefs). Resolution is for
    # preparation/actual calls, not a replacement for the declared promise.
    events = tuple(replace(e, value=bc.Published(next(p for p in contract.plans if p.unit == e.key.unit)))
                   if e.tag == "Publish" else e for e in trace.events)
    return contract, replace(trace, events=tuple(firsts) + events)
def test_verification_and_adoption_resolve_all_e0_planrefs_at_the_actual_call():
    bc = observation_check
    contract, trace = _planref_verification_adoption()
    assert isinstance(contract.verifications[0].reader, PlanRef)
    assert isinstance(contract.verifications[0].target.result, PlanRef)
    assert all(isinstance(p, PlanRef) for p in contract.verifications[0].check_view)
    assert isinstance(contract.adoptions[0].key.reader, PlanRef)
    assert isinstance(contract.adoptions[0].completion, PlanRef)
    assert all(isinstance(k.reader, PlanRef) for k in contract.adoptions[0].acquisitions)
    assert not bc.validate_observation_boundary(contract, trace).violations
    result = bc.evaluate_observations(contract, trace)
    assert not result.violations, result
    assert not any(reason.startswith("約束の未接続") for _, reason in result.limitations), tuple(l for l in result.limitations if l[1].startswith("約束の未接続"))
    changed = replace(contract.adoptions[0], previous_result=PlanRef("roots", "R"))
    assert not bc.validate_observation_boundary(replace(contract, adoptions=(changed,)), trace).violations
    assert _contract_failures(bc.evaluate_observations(replace(contract, adoptions=(changed,)), trace), "INV-9.a")
    # A valid shape and handwritten positive are still not discrimination proof.
    checker = Checker()
    checker.on_observations(contract, trace)
    assert checker.report().counts["違反なし・識別力確認済み"] == 0
    # P-10: a final Saved root must not retrospectively satisfy acquisition,
    # verification, or reservation/adoption dependencies.
    reader = next(e.value.prepared.point for e in trace.events if e.tag == "FirstPrepare" and e.key.slot == "reader")
    early, late = _p10_save_order(trace, reader, next(i for i, e in enumerate(trace.events) if e.tag == "Acquire"))
    assert not bc.evaluate_observations(contract, early).violations
    failure = bc.evaluate_observations(contract, late)
    for row, word in (("INV-9.a", "acquisition"), ("INV-9.a", "verification"), ("INV-9.b", "reservation"), ("INV-9.a", "adoption"), ("INV-8.a", "descriptor")):
        assert any(c.row == row and word in c.message for c in failure.violations), (row, word, failure)
@pytest.mark.parametrize("mutation", ("descriptor_args", "reader", "check_view", "adoption_result", "early_call", "plan_content"))
def test_planref_verification_adoption_reject_changed_or_not_yet_resolvable_roots(mutation):
    bc = observation_check
    contract, trace = _planref_verification_adoption()
    if mutation == "descriptor_args":
        contract = replace(contract, descriptors=(replace(contract.descriptors[0], args=obj(wrong=PlanRef("roots", "Q"))),))
        row = "INV-8.a"
    elif mutation == "reader":
        contract = replace(contract, verifications=(replace(contract.verifications[0], reader=PlanRef("roots", "Q")),))
        row = "INV-9.a"
    elif mutation == "check_view":
        contract = replace(contract, verifications=(replace(contract.verifications[0], check_view=frozenset((PlanRef("roots", "Q"),))),))
        row = "INV-9.a"
    elif mutation == "adoption_result":
        contract = replace(contract, adoptions=(replace(contract.adoptions[0], result=PlanRef("roots", "Q")),))
        row = "INV-9.a"
    elif mutation == "early_call":
        call = next(e for e in trace.events if e.tag == "VerifyCall")
        trace = replace(trace, events=(call,) + tuple(e for e in trace.events if e is not call))
        row = "INV-9.a"
    else:
        roots = contract.plans[0]
        contract = replace(contract, plans=(replace(roots, records=tuple(replace(r, content=obj(forged=True))
                                      if r.slot == "Q" else r for r in roots.records)), *contract.plans[1:]))
        row = "INV-9.a"
    assert _contract_failures(bc.evaluate_observations(contract, trace), row)
# Turn 5: independent concrete-path and public declaration boundary regressions.
def test_public_candidate_graph_formulas_accept_finite_iterables_and_keep_completeness_gate():
    # Pre-admission symbols are not forged ledger CIDs. Missing parent existence
    # is separate from cycles, including with a one-shot finite parent iterable.
    assert acyclic({"a": iter(("b",))})
    assert not acyclic({"a": iter(("b",)), "b": iter(("a",))})
    wait = ("Wait", "o")
    # SC-19-N4: ReadyN is independently true even when Publish is hidden. This
    # is a negative abstract input, never a reachable correct-window pass.
    result = derive_progress(iter((0,)), iter((0,)), (), (), ((0, 0, wait),), {0: frozenset((wait,))},
                             environment_ready=(), frontier=iter(()))
    assert result == {"N": (frozenset((0,)),), "P": ()}
    assert derive_progress({0}, {0}, (), (), ((0, 0, wait),), {0: frozenset((wait,))},
                           environment_ready=(), frontier=iter((0,))) is None
def _wildcard_reference_fixture():
    from fb_machine import TypedReference
    bc = observation_check
    records, bodies, entries = _handmade_ledger(("reader",))
    reader = records["reader"].point
    contract_type = Contract("computation_requested", "1")
    # Repeated Points still have distinct occurrences: inputs[0] AND inputs[1].
    content = obj(origin=reader, args=obj(model=reader), inputs=(reader, reader))
    paths = (("origin",), ("args", "model"), ("inputs", 0), ("inputs", 1))
    refs = tuple(TypedReference("PATH-Q0", path, reader, "UE", "numerical") for path in paths)
    record = Record("q", Reading("run", "M", 1), contract_type, "Event", content, refs)
    rules = tuple(bc.ReferenceBinding(contract_type, "PATH-Q0", path, "UE", "numerical", "PrepareOne", "direct")
                  for path in (("origin",), ("args", "model"), ("inputs", "*")))
    return bc.ObservationE0(references=rules), record, bodies, entries
@pytest.mark.parametrize("mutation", (None, "missing", "extra", "role", "use", "path_id", "literal_star", "no_rule"))
def test_wildcard_references_preserve_each_concrete_element_and_declared_roles(mutation):
    from fb_machine import Slot, Unit
    bc = observation_check
    contract, record, bodies, entries = _wildcard_reference_fixture()
    if mutation == "missing":
        record = replace(record, references=record.references[:-1])
    elif mutation == "extra":
        record = replace(record, references=record.references + (replace(record.references[-1], path=("inputs", 2)),))
    elif mutation in ("role", "use", "path_id", "literal_star"):
        changes = {"role": {"role": "E"}, "use": {"use": "outer"}, "path_id": {"path_id": "PATH-QPREV"},
                   "literal_star": {"path": ("inputs", "*")}}[mutation]
        record = replace(record, references=record.references[:-1] + (replace(record.references[-1], **changes),))
    e0 = E0()
    if mutation == "no_rule":
        e0 = replace(e0, field_roles=tuple(r for r in e0.field_roles if r.path != ("inputs", "*")))
        contract = replace(contract, references=contract.references[:-1])
    prepared = _handmade_prepared(record)
    trace = bc.ObservationTrace((), bodies | {Body(prepared.seal, prepared.salt, prepared.payload)},
                                entries | {Entry(prepared.point, prepared.header)})
    result = bc.evaluate_observations(contract, trace)
    assert bool(_contract_failures(result, "INV-5.a")) is (mutation is not None)
    # Exercise the legacy E0.field_roles row as well as ObservationE0.references.
    before = Environment(e0).initial()
    before = replace(before, core=replace(before.core, c=tuple(bodies), e=tuple(entries)))
    plan = RecordPlan("q", record.contract, record.category, record.content, record.references)
    unit = Unit("initial", "O-02", (), (Slot(plan, prepared),), (), frozenset())
    after = replace(before, core=replace(before.core, p=replace(before.core.p, units=(unit,)),
                                        c=tuple(trace.bodies), e=tuple(trace.entries)))
    report = _candidate_step(e0, before, after, Action("PublishUnit", ("initial",)))
    assert _row_fails(report, "INV-5.a") is (mutation is not None)
    # INV-7.b checks the role of EACH actual use; the missing use is INV-5.a's job.
    assert _row_fails(report, "INV-7.b") is (mutation not in (None, "missing"))
    assert report.counts["違反なし・識別力確認済み"] == 0
def test_reference_path_expansion_is_explicit_array_only_and_keeps_nested_indices():
    bc = observation_check
    p, q = Point("p"), Point("q")
    value = obj(groups=(obj(inputs=(p, q)), obj(inputs=(p,))), implicit=p)
    assert bc.reference_paths(value, ("groups", "*", "inputs", "*")) == (
        (("groups", 0, "inputs", 0), p), (("groups", 0, "inputs", 1), q), (("groups", 1, "inputs", 0), p))
    assert bc.reference_paths(obj(inputs=()), ("inputs", "*")) == ()
    assert bc.reference_paths(obj(inputs=frozenset((p,))), ("inputs", "*")) == ()
    assert bc.reference_paths(value, ("inputs", "*")) == ()
def _symbolic_derivation_fixture():
    bc = observation_check
    # Author the relation before an Envelope exists; no number, r, seq or CID.
    source = bc.ReceiptSource("incoming", "external", received(b"raw\xff"))
    receipt_ref = PlanRef(source.unit, source.slot)
    norm = PlanRef("unit", "slot")
    qslot = bc.SlotKey("derived", "q")
    d = replace(publication().plans[0].works[0], process=norm, reader=norm, stage="Wr", purpose="derive",
                trigger=receipt_ref, stage_slot="s", method=Contract("finite_update", "1"),
                args=obj(previous_result=None), input_points=frozenset((receipt_ref,)), request=PlanRef(qslot.unit, qslot.slot))
    qplan = RecordPlan("q", Contract("model.request", "1"), "Event", obj(previous_result=None))
    plan = AllowedPlan(qslot.unit, "O-03", (), (qplan,), (d,))
    binding = bc.DerivationBinding(norm, "1", norm, norm, "derive", source, bc.SlotKey(source.unit, source.slot),
                                  "trigger", "s", frozenset(("trigger",)), d.method, d.input_points,
                                  frozenset(), frozenset((receipt_ref,)), None, qslot, plan)
    contract, roots, _ = _handmade_declared_slot()
    contract = replace(contract, plans=contract.plans + (plan,), descriptors=(d,), receipt_sources=(source,), derivations=(binding,))
    envelope = Envelope("actual-run", 7, Reading("actual-run", "M", 37), 7, received(b"raw\xff"), "external")
    _, receipts, firsts = _handmade_receipt(envelope=envelope)
    trace = replace(receipts, events=roots.events + receipts.events, bodies=roots.bodies | receipts.bodies,
                    entries=roots.entries | receipts.entries)
    return contract, trace, source, binding, firsts[0]
def test_derivation_public_declaration_resolves_receipt_alias_and_planrefs_without_predicting_envelope():
    bc = observation_check
    contract, trace, source, binding, receipt = _symbolic_derivation_fixture()
    assert not bc.validate_observation_boundary(contract, trace).violations
    envelope, slot = bc.resolve_receipt_source(contract, trace, source)
    assert (envelope.number, envelope.r.rank, envelope.receipt_seq) == (7, 37, 7)
    assert slot != binding.receipt
    assert bc.declaration_value(contract, trace, PlanRef(source.unit, source.slot)) == receipt.point
    resolved = bc.resolve_derivation_binding(contract, trace, binding)
    assert resolved.envelope == envelope and resolved.inputs == frozenset((receipt.point,))
    status, = bc.derive_observation_status(contract, trace)
    assert status.eligible and not status.published and not status.unsupported
    publish = bc.ObservationEvent("Publish", bc.UnitKey(binding.plan.unit), bc.Published(binding.plan))
    published = replace(trace, events=trace.events + (publish,))
    status, = bc.derive_observation_status(contract, published)
    assert status.matched and not status.discharged and not status.unsupported
    qplan = binding.plan.records[0]
    q = _handmade_prepared(Record("q", trace.clock, qplan.contract, qplan.category, qplan.content, ()))
    saved = replace(published, events=published.events + (bc.ObservationEvent("FirstPrepare", binding.request, bc.FirstPrepared(q)),),
                    bodies=published.bodies | {Body(q.seal, q.salt, q.payload)}, entries=published.entries | {Entry(q.point, q.header)})
    assert bc.derive_observation_status(contract, saved)[0].discharged
    early, late = _p10_save_order(published, receipt.point, len(trace.events))
    assert bc.derive_observation_status(contract, early)[0].matched
    status, = bc.derive_observation_status(contract, late)
    assert not status.matched and not status.eligible and not status.discharged
    failure = bc.evaluate_observations(contract, late)
    assert _contract_failures(failure, "INV-2.d") or any(row == "INV-2.d" for row, _ in failure.limitations)
    assert any(row == "L-DERIVE" for row, _ in failure.limitations)
@pytest.mark.parametrize("mutation", ("missing_post", "different_event", "ambiguous", "missing_saved", "late_post"))
def test_symbolic_derivation_never_guesses_or_uses_later_receipt_roots(mutation):
    bc = observation_check
    contract, trace, source, binding, _ = _symbolic_derivation_fixture()
    if mutation == "missing_saved":
        trace = replace(trace, entries=frozenset())
    elif mutation == "late_post":
        publish = bc.ObservationEvent("Publish", bc.UnitKey(binding.plan.unit), bc.Published(binding.plan))
        trace = replace(trace, events=(publish,) + trace.events)
    else:
        post = next(e for e in trace.events if e.tag == "Post")
        if mutation == "missing_post":
            trace = replace(trace, events=tuple(e for e in trace.events if e.tag != "Post"))
        elif mutation == "different_event":
            changed = replace(post, value=bc.Posted(replace(post.value.envelope, event=received(b"different"))))
            trace = replace(trace, events=tuple(changed if e is post else e for e in trace.events))
        else:
            other = replace(post.value.envelope, number=8, receipt_seq=8)
            trace = replace(trace, events=trace.events + (bc.ObservationEvent("Post", bc.ReceiptKey(other.run, 8), bc.Posted(other)),))
    status, = bc.derive_observation_status(contract, trace)
    assert not status.matched and not status.discharged and status.unsupported
    assert len(bc.derive_observation_status(contract, trace)) == len(contract.derivations)
def test_planned_interval_evidence_matches_exact_e0_plan_and_actual_saved_record():
    from fb_machine import Cell
    bc = observation_check
    contract, trace, first = _handmade_declared_slot()
    ref = PlanRef("unit", "slot")
    key = bc.IntervalKey("k", "route", "run")
    interval = Interval("run", "M", 0, 2, True, False)
    expected = bc.IntervalObserved(Reading("run", "M", 2), interval, frozenset((Cell(0, 2),)), "measure", ref, obj(monitored=True))
    binding = bc.IntervalEvidenceBinding(ref, key, "Monitored", expected, contract.plans[0].records[0])
    k = bc.IntervalBinding(key, Point("k"), "measure", interval, (0, 2), Contract("model.measure", "1"), Contract("model.clock", "1"))
    contract = replace(contract, intervals=(k,), interval_evidence=(binding,))
    actual = replace(expected, evidence=first.point)
    event = bc.ObservationEvent("Monitored", key, actual)
    trace = replace(trace, events=trace.events + (event,))
    resolved = bc.resolve_interval_evidence(contract, trace, binding)
    assert resolved.record == first.record and resolved.event == actual
    result = bc.evaluate_observations(contract, trace)
    assert not _contract_failures(result, "INV-12.a")
    assert not any("EI evidence binding" in reason for _, reason in result.limitations)
    bad_recipe = replace(binding, record=replace(binding.record, content=obj(changed=True)))
    with pytest.raises(bc.UnresolvedDeclaration):
        bc.resolve_interval_evidence(contract, trace, bad_recipe)
    wrong_event = replace(event, value=replace(actual, content=obj(monitored=False)))
    wrong = replace(trace, events=trace.events[:-1] + (wrong_event,))
    assert _contract_failures(bc.evaluate_observations(contract, wrong), "INV-12.a")
    symbolic_actual = replace(trace, events=trace.events[:-1] + (replace(event, value=expected),))
    assert bc.validate_observation_boundary(contract, symbolic_actual).violations
    early, late = _p10_save_order(trace, first.point, len(trace.events) - 1)
    assert not _contract_failures(bc.evaluate_observations(contract, early), "INV-12.a")
    assert _contract_failures(bc.evaluate_observations(contract, late), "INV-12.a")
def test_artifact_port_planrefs_resolve_per_boundary_without_demanding_future_draw():
    bc = observation_check
    contract, roots, first = _handmade_declared_slot()
    ref = PlanRef("unit", "slot")
    value = bc.ArtifactValue(Contract("math_artifact", "2"), Contract("compiler", "1"), "view", "registry",
                             obj(model=ref), (), obj(branch="Selected"))
    checked = bc.ArtifactChecked(value, "Selected", ref, ref, ref, frozenset((ref,)))
    port = bc.ArtifactPortBinding("evaluate", value.contract, value.compiler, value.reader_view_key,
                                 value.registry_key, value.inputs, (value,), (checked,))
    contract = replace(contract, artifacts=(port,), generation_sources=((port.work, "actual-port"),))
    actual_value = replace(value, inputs=obj(model=first.point))
    actual_checked = replace(checked, artifact=actual_value, request=first.point, problem=first.point,
                             draw=first.point, evidence=frozenset((first.point,)))
    # Independent exact expectations use fixture data, not the checker resolver.
    assert bc.resolve_artifact_port(contract, roots, port.work).possible_returns == (actual_value,)
    assert bc.resolve_artifact_port(contract, roots, port.work, checked=True).checked_returns == (actual_checked,)
    future = replace(port, checked_returns=(replace(checked, draw=PlanRef("future", "draw")),))
    assert bc.resolve_artifact_port(replace(contract, artifacts=(future,)), roots, port.work).possible_returns == (actual_value,)
    with pytest.raises(bc.UnresolvedDeclaration):
        bc.resolve_artifact_port(replace(contract, artifacts=(future,)), roots, port.work, checked=True)
    generation = Generation(port.work, first.point, "Ee", Reading("run", "M", 0), Reading("run", "M", 1),
                            Outcome(OutcomeKind.RETURNED, obj(port="actual")), "actual-port")
    events = (bc.ObservationEvent("ArtifactIssued", bc.WorkKey(port.work), bc.ArtifactIssued(actual_value, generation)),
              bc.ObservationEvent("ArtifactChecked", bc.WorkKey(port.work), actual_checked))
    trace = replace(roots, events=roots.events + events)
    result = bc.evaluate_observations(contract, trace)
    assert not result.violations and not result.boundary.violations, result
    assert any("full semantic closure" in reason for _, reason in result.limitations)
    changed = replace(events[-1], value=replace(actual_checked, request=Point("wrong-eq")))
    assert _contract_failures(bc.evaluate_observations(contract, replace(trace, events=trace.events[:-1] + (changed,))), "INV-16.b")
    assert bc.validate_observation_boundary(contract, replace(trace, events=roots.events + (replace(events[-1], value=checked),))).violations
    early, late = _p10_save_order(trace, first.point, len(roots.events))
    assert not bc.evaluate_observations(contract, early).violations
    failure = bc.evaluate_observations(contract, late)
    assert _contract_failures(failure, "INV-16.b")
    assert any(row == "INV-16.a" and "約束の未接続" in reason for row, reason in failure.limitations)
@pytest.mark.parametrize("kind,field", (("started_clock", "started"), ("finished_clock", "finished")))
def test_clock_sources_project_validated_generation_and_never_receipt_save_time(kind, field):
    from fb_machine import Source
    bc = observation_check
    contract, trace, generation, _ = _handmade_source_generation()
    source = Source(kind, generation.work)
    value = bc.declaration_value(contract, trace, source)
    assert value == getattr(generation, field) and value != trace.clock
    assert not isinstance(value, Point)
    with pytest.raises(bc.UnresolvedDeclaration):
        bc.declaration_value(contract, replace(trace, entries=frozenset()), source)
    with pytest.raises(bc.UnresolvedDeclaration):
        bc.declaration_value(contract, trace, Source(kind, "undeclared-work"))
    # INV-6.a: canonical clock + actual work identity, not equality of readings.
    stage = "Wr" if kind == "started_clock" else "Wp"
    generation = replace(generation, stage=stage)
    contract = replace(contract, descriptors=(replace(contract.descriptors[0], stage=stage),))
    trace = replace(trace, events=tuple(replace(e, value=bc.Returned(generation)) if e.tag == "WorkerReturn" else e for e in trace.events))
    origin = _handmade_prepared(Record("clock-source", trace.clock, Contract("model.clock_source", "1"), "Event", obj(run="run", source="M"), ()))
    record = RecordPlan("clock", Contract("clock_reading", "1"), "Event", obj(source=origin.point, reading=source))
    plan = AllowedPlan("clock-unit", "O-07", (), (record,))
    contract = replace(contract, plans=contract.plans + (plan,))
    first = _handmade_prepared(Record("clock", trace.clock, record.contract, "Event", obj(source=origin.point, reading=value), ()))
    prepared = bc.ObservationEvent("FirstPrepare", bc.SlotKey(plan.unit, record.slot), bc.FirstPrepared(first))
    trace = replace(trace, events=trace.events + (prepared,), bodies=trace.bodies | {Body(v.seal, v.salt, v.payload) for v in (origin, first)},
                    entries=trace.entries | {Entry(v.point, v.header) for v in (origin, first)})
    assert bc.completed_clock_reading(contract, trace, first.point, generation.request, kind) == value
    with pytest.raises(ValueError, match="another request/stage"):
        bc.completed_clock_reading(contract, trace, first.point, Point("another-request"), kind)
    other = replace(generation, stage="Wp" if stage == "Wr" else "Wr")
    wrong_contract = replace(contract, descriptors=(replace(contract.descriptors[0], stage=other.stage),))
    wrong_trace = replace(trace, events=tuple(replace(e, value=bc.Returned(other)) if e.tag == "WorkerReturn" else e for e in trace.events))
    with pytest.raises(ValueError, match="another request/stage"):
        bc.completed_clock_reading(wrong_contract, wrong_trace, first.point, generation.request, kind)
    missing = replace(trace, events=tuple(e for e in trace.events if e.tag != "WorkerReturn"))
    with pytest.raises(bc.UnresolvedDeclaration, match="worker EW/EH generation"):
        bc.completed_clock_reading(contract, missing, first.point, generation.request, kind)
    # Same valid Reading without the source's body is insufficient Saved evidence.
    missing = replace(trace, bodies=frozenset(b for b in trace.bodies if b.seal != origin.seal))
    with pytest.raises(ValueError, match="clock source must reference a Saved record"):
        bc.completed_clock_reading(contract, missing, first.point, generation.request, kind)
    # The source is part of the complete predeclared recipe, not just its value.
    bad_plan = replace(plan, records=(replace(record, content=obj(source=origin.point, reading=Source("acquisition_clock", "other"))),))
    with pytest.raises(ValueError, match="another generation boundary"):
        bc.completed_clock_reading(replace(contract, plans=contract.plans[:-1] + (bad_plan,)), trace, first.point, generation.request, kind)
# Turn 6: clocks are Saved references; terminal recipes are independent E0.
@pytest.mark.parametrize("mutation", ("inline", "missing_body", "wrong_reading", "unsupported", "wrong_run", "wrong_source", "missing_source", "unavailable", "extra_field"))
def test_acquisition_clock_requires_saved_typed_evidence_and_the_actual_reading(mutation):
    bc = observation_check
    contract, trace = _handmade_adoption()
    actual = trace.events[0].value.acquisition
    record = trace.events[2].value.prepared.record
    point = record.content.get("clock")
    assert bc.clock_evidence_reading(contract, trace, point) == actual.reading
    assert bc._acquisition_content_matches(contract, trace, record.content, actual)
    if mutation == "inline":
        with pytest.raises(ValueError):
            bc.clock_evidence_reading(contract, trace, actual.reading)
    elif mutation == "missing_body":
        with pytest.raises(ValueError):
            bc.clock_evidence_reading(contract, replace(trace, bodies=frozenset()), point)
    else:
        old = next(e.header.record for e in trace.entries if e.point == point)
        from fb_machine import Unavailable
        values = dict(old.content.items)
        if mutation == "wrong_reading":
            values["reading"] = replace(actual.reading, rank=99)
        elif mutation == "wrong_run":
            values["reading"] = replace(actual.reading, run="other")
        elif mutation == "wrong_source":
            values["reading"] = replace(actual.reading, source="other")
        elif mutation == "missing_source":
            values["source"] = Point("missing-source")
        elif mutation == "unavailable":
            values["reading"] = Unavailable("unconfirmed")
        elif mutation == "extra_field":
            values["extra"] = "undeclared"
        changed = replace(old, content=obj(**values), contract=Contract("unsupported.clock", "1") if mutation == "unsupported" else old.contract)
        first = _handmade_prepared(changed)
        bad = replace(trace, bodies=trace.bodies | {Body(first.seal, first.salt, first.payload)}, entries=trace.entries | {Entry(first.point, first.header)})
        if mutation == "unsupported":
            with pytest.raises(bc.UnresolvedDeclaration):
                bc.clock_evidence_reading(contract, bad, first.point)
        elif mutation != "wrong_reading":
            with pytest.raises(ValueError):
                bc.clock_evidence_reading(contract, bad, first.point, acquisition=actual)
        else:
            assert not bc._acquisition_content_matches(contract, bad, obj(origin=actual.reader, contents=tuple(actual.targets), clock=first.point), actual)
def test_acquisition_clock_source_waits_and_publication_compares_its_full_value():
    from fb_machine import Source
    bc = observation_check
    contract, trace = _handmade_adoption()
    source = Source("acquisition_clock", trace.events[0].key.intent)
    with pytest.raises(bc.UnresolvedDeclaration):
        bc.declaration_value(contract, replace(trace, events=()), source)
    actual = trace.events[0].value.acquisition
    assert bc.declaration_value(contract, trace, source) == actual.reading
    origin = next(e.point for e in trace.entries if e.header.record.contract.name == "model.clock_source")
    record = RecordPlan("clock", Contract("clock_reading", "1"), "Event", obj(source=origin, reading=source))
    plan = AllowedPlan("clock", "O-08", (), (record,))
    contract = replace(contract, plans=contract.plans + (plan,))
    expected = replace(plan, records=(replace(record, content=obj(source=origin, reading=actual.reading)),))
    event = bc.ObservationEvent("Publish", bc.UnitKey(plan.unit), bc.Published(expected))
    assert not _contract_failures(bc.evaluate_observations(contract, replace(trace, events=trace.events + (event,))), "INV-2.b")
    wrong = replace(event, value=bc.Published(replace(expected, records=(replace(record, content=obj(source=origin, reading=Reading("run", "M", 99))),))))
    assert _contract_failures(bc.evaluate_observations(contract, replace(trace, events=trace.events + (wrong,))), "INV-2.b")
@pytest.mark.parametrize("verification", (False, True))
def test_static_terminal_sources_compare_failure_t_and_definite_wv_t_v(verification):
    from fb_machine import Source, TypedReference
    bc = observation_check
    contract, worker, token = _handmade_worker()
    d = replace(contract.descriptors[0], stage="Wv" if verification else "Wr")
    worker = replace(worker, events=tuple(replace(e, value=replace(e.value, descriptor=d)) if e.tag in ("Reserve", "ReadInputs") else e for e in worker.events))
    reply = next(e.value.reply for e in _handmade_adoption()[1].events if e.tag == "VerifyReply")
    outcome = Outcome(OutcomeKind.RETURNED, reply) if verification else Outcome(OutcomeKind.FAILURE, obj(reason="failure", detail=(1, 2)))
    generation = Generation(d.work_id, d.request, d.stage, Reading("run", "M", 0), Reading("run", "M", 1), outcome, "actual-port")
    envelope = Envelope("run", 1, Reading("run", "M", 2), 1, Event("WorkFinished", obj(work=d.work_id, started=generation.started, finished=generation.finished, outcome=outcome)), "actual-port")
    _, trace, (receipt,) = _handmade_receipt("WorkFinished", envelope)
    trace = replace(trace, bodies=trace.bodies | worker.bodies, entries=trace.entries | worker.entries, events=worker.events + (bc.ObservationEvent("WorkerReturn", token, bc.Returned(generation)),) + trace.events)
    content = obj(work=d.work_id, request=d.request, stage=d.stage, first_receipt=Source("first_receipt", d.work_id),
                  terminal_kind=Source("outcome_kind", d.work_id), returned=Source("outcome_content", d.work_id), basis=Source("terminal_basis", d.work_id),
                  view=Source("terminal_view", d.work_id))
    refs = tuple(TypedReference("PATH-LINK-GENERATION", (field,), ref, "E", "terminal") for field, ref in (("request", d.request), ("first_receipt", Source("first_receipt", d.work_id))))
    t = RecordPlan("T", Contract("sui.fb.work_terminal", "1"), "Event", content, refs, frozenset((d.request, Source("first_receipt", d.work_id))))
    plans = (AllowedPlan("terminal:" + d.work_id, "O-09.a", (d.work_id,), (t,)),)
    expected_t = replace(t, content=obj(work=d.work_id, request=d.request, stage=d.stage, first_receipt=receipt.point, terminal_kind=outcome.kind,
                         returned=outcome.content, basis=None if verification else generation, view=frozenset(e.point for e in trace.entries)),
                         references=(refs[0], replace(refs[1], ref=receipt.point)), parents=frozenset((d.request, receipt.point)))
    expected = (replace(plans[0], records=(expected_t,)),)
    if verification:
        v = RecordPlan("V", Contract("sui.fb.verification", "1"), "Event", obj(work=d.work_id, reply=Source("outcome_content", d.work_id), first_receipt=Source("first_receipt", d.work_id), view=Source("terminal_view", d.work_id)), (refs[1],), frozenset((Source("first_receipt", d.work_id),)))
        plans += (AllowedPlan("verification:" + d.work_id, "O-09.a", (d.work_id,), (v,)),)
        expected += (replace(plans[1], records=(replace(v, content=obj(work=d.work_id, reply=reply, first_receipt=receipt.point, view=frozenset(e.point for e in trace.entries)), references=(replace(refs[1], ref=receipt.point),), parents=frozenset((receipt.point,))),)),)
    contract = replace(contract, descriptors=(d,), plans=plans)
    events = tuple(bc.ObservationEvent("Publish", bc.UnitKey(plan.unit), bc.Published(plan)) for plan in expected)
    complete = replace(trace, events=trace.events + events)
    assert not _contract_failures(bc.evaluate_observations(contract, complete), "INV-2.b")
    assert not any(row == "INV-2.b" for row, _ in bc.evaluate_observations(contract, complete).limitations)
    nonpoint = replace(plans[0], records=(replace(t, parents=frozenset((Source("outcome_content", d.work_id),))),))
    bad_contract = replace(contract, plans=(nonpoint,) + plans[1:])
    with pytest.raises(bc.UnresolvedDeclaration):
        bc.DeclarationResolver(bad_contract, trace).plan(nonpoint.unit)
    assert any(row == "INV-2.b" for row, _ in bc.evaluate_observations(bad_contract, complete).limitations)
    # E0 Source refs are accepted; the identical unresolved refs in EU/Record are not.
    raw = replace(events[0], value=bc.Published(plans[0]))
    assert bc.validate_observation_boundary(contract, replace(trace, events=trace.events + (raw,))).violations
    assert set(dict(expected_t.content.items)) == {"work", "request", "stage", "first_receipt", "terminal_kind", "returned", "basis", "view"}
    for name in ("work", "request", "stage", "first_receipt", "terminal_kind", "returned", "basis", "view"):
        values = dict(expected_t.content.items)
        values[name] = "wrong"
        wrong = replace(expected[0], records=(replace(expected_t, content=obj(**values)),))
        changed = replace(complete, events=trace.events + (replace(events[0], value=bc.Published(wrong)),) + events[1:])
        assert _contract_failures(bc.evaluate_observations(contract, changed), "INV-2.b"), name
    for field in ("references", "parents"):
        wrong = replace(expected[0], records=(replace(expected_t, **{field: () if field == "references" else frozenset()}),))
        assert _contract_failures(bc.evaluate_observations(contract, replace(trace, events=trace.events + (replace(events[0], value=bc.Published(wrong)),))), "INV-2.b")
    fake = _handmade_prepared(Record("bad-reference", trace.clock, t.contract, "Event", expected_t.content, refs))
    invalid = replace(trace, entries=trace.entries | {Entry(fake.point, fake.header)}, bodies=trace.bodies | {Body(fake.seal, fake.salt, fake.payload)})
    assert bc.validate_observation_boundary(contract, invalid).violations
    # Later Saved bytes are absent from the publication view even on a later scan.
    late = _handmade_prepared(Record("late", trace.clock, Contract("model.evidence", "1"), "Event", obj(value="late"), ()))
    body, entry = Body(late.seal, late.salt, late.payload), Entry(late.point, late.header)
    late_events = tuple(bc.ObservationEvent("IOResponse", bc.IOKey(bc.SlotKey("late", "slot"), op, op), bc.IOResponse("acknowledged", value)) for op, value in (("PutBody", body), ("AddEntry", entry)))
    later = replace(complete, events=complete.events + late_events, bodies=trace.bodies | {body}, entries=trace.entries | {entry})
    assert bc.DeclarationResolver(contract, later).plan(plans[0].unit) == expected[0]
    if verification:
        # P-10: both publications precede both preparations; V is saved AFTER
        # T's first preparation. Judge the complete final history, not one edge.
        prepared = tuple(_handmade_prepared(Record(p.unit, trace.clock, p.records[0].contract, "Event", p.records[0].content, p.records[0].references), p.records[0].parents) for p in expected)
        first_events = tuple(bc.ObservationEvent("FirstPrepare", bc.SlotKey(p.unit, p.records[0].slot), bc.FirstPrepared(f)) for p, f in zip(expected, prepared))
        t_first, v_first = prepared
        history = replace(complete, events=complete.events + first_events, bodies=complete.bodies | {Body(v_first.seal, v_first.salt, v_first.payload)}, entries=complete.entries | {Entry(v_first.point, v_first.header)})
        history = replace(history, events=history.events + _p10_writes(history, v_first.point))
        result = bc.evaluate_observations(contract, history)
        assert not _contract_failures(result, "INV-4.c") and not _contract_failures(result, "INV-2.b"), result
        assert not any(row in ("INV-4.c", "INV-2.b") and reason.startswith("約束の未接続") for row, reason in result.limitations)
        for view in (frozenset((receipt.point, v_first.point)), frozenset()):
            wrong_content = obj(**{**dict(t_first.record.content.items), "view": view})
            wrong = _handmade_prepared(replace(t_first.record, content=wrong_content), t_first.parents, t_first.salt)
            changed = replace(history, events=tuple(replace(e, value=bc.FirstPrepared(wrong)) if e == first_events[0] else e for e in history.events))
            assert _contract_failures(bc.evaluate_observations(contract, changed), "INV-4.c")
            wrong_plan = replace(expected[0], records=(replace(expected_t, content=wrong_content),))
            changed = replace(history, events=tuple(replace(e, value=bc.Published(wrong_plan)) if e == events[0] else e for e in history.events))
            assert _contract_failures(bc.evaluate_observations(contract, changed), "INV-2.b")
# P-07: publication declarations and later materialization are separate roots.
@pytest.mark.parametrize("kind", ("G", "Cq"))
def test_publication_keeps_local_slot_identity_and_requires_external_saved_refs(kind):
    bc = observation_check
    contract, complete = _handmade_adoption()
    actual = complete.events[0].value.acquisition
    g = contract.plans[0].records[0]
    old_clock = next(e for e in complete.entries if e.point == g.content.get("clock"))
    clock = RecordPlan("clock", old_clock.header.record.contract, "Event", old_clock.header.record.content)
    twin = replace(clock, slot="twin")  # Identical values do not make slots interchangeable.
    ref = PlanRef("g-unit", "clock")
    body = (obj(origin=actual.reader, contents=tuple(actual.targets), clock=ref) if kind == "G" else
            obj(request=contract.verifications[0].target.request, result=contract.verifications[0].target.result,
                proofs=tuple(contract.verifications[0].target.proofs), started_clock=ref, finished_clock=ref))
    record = replace(g, contract=Contract("content_acquired" if kind == "G" else "computation_completed", "1"), content=body)
    # Paper 390: the work row exists now; its required input resolves at start.
    pending = replace(contract.descriptors[0], required=frozenset((PlanRef("external", "clock"),)))
    plan = replace(contract.plans[0], records=(clock, twin, record), works=(pending,))
    contract = replace(contract, plans=(plan, AllowedPlan("external", "O-07", (), (clock,))), descriptors=(pending,))
    root = replace(complete, events=(complete.events[0],),
                   entries=frozenset(e for e in complete.entries if e.point not in (old_clock.point, complete.events[2].value.prepared.point)),
                   bodies=frozenset(b for b in complete.bodies if b.seal not in (old_clock.header.seal, complete.events[2].value.prepared.seal)))
    event = bc.ObservationEvent("Publish", bc.UnitKey(plan.unit), bc.Published(plan))
    published = replace(root, events=root.events + (event,))
    report = bc.evaluate_observations(contract, published)
    assert not report.violations and not any(row == "INV-2.b" for row, _ in report.limitations), report
    assert bc.publication_value(contract, root, plan.unit, ref) == ref
    field = "clock" if kind == "G" else "started_clock"
    values = dict(body.items)
    values[field] = PlanRef(plan.unit, "twin")
    swapped = replace(plan, records=(clock, twin, replace(record, content=obj(**values))))
    bad = replace(published, events=root.events + (replace(event, value=bc.Published(swapped)),))
    assert _contract_failures(bc.evaluate_observations(contract, bad), "INV-2.b")
    # Even a matching E0/EU declaration cannot exempt a different unsaved unit.
    values[field] = PlanRef("external", "clock")
    external = replace(plan, records=(clock, twin, replace(record, content=obj(**values))))
    promise = replace(contract, plans=(external, AllowedPlan("external", "O-07", (), (clock,))))
    bad = replace(published, events=root.events + (replace(event, value=bc.Published(external)),))
    assert any(row == "INV-2.b" and "first preparation" in reason for row, reason in bc.evaluate_observations(promise, bad).limitations)
    # Publication does not relax the later complete PreparedEntry comparison.
    firsts = tuple(_handmade_prepared(Record(r.slot, Reading("run", "M", 2), r.contract, "Event", r.content, ())) for r in (clock, twin))
    events = tuple(bc.ObservationEvent("FirstPrepare", bc.SlotKey(plan.unit, r.slot), bc.FirstPrepared(f)) for r, f in zip((clock, twin), firsts))
    ready = replace(published, events=published.events + events, bodies=root.bodies | {Body(f.seal, f.salt, f.payload) for f in firsts},
                    entries=root.entries | {Entry(f.point, f.header) for f in firsts})
    for substituted in (False, True):
        values = dict(body.items)
        for name in (("clock",) if kind == "G" else ("started_clock", "finished_clock")):
            values[name] = firsts[0].point
        if substituted:
            values[field] = firsts[1].point
        saved = _handmade_prepared(Record("G" if kind == "G" else "Cq", Reading("run", "M", 2), record.contract, "Event", obj(**values), ()))
        prepare = bc.ObservationEvent("FirstPrepare", bc.SlotKey(plan.unit, record.slot), bc.FirstPrepared(saved))
        trace = replace(ready, events=ready.events + (prepare,), bodies=ready.bodies | {Body(saved.seal, saved.salt, saved.payload)}, entries=ready.entries | {Entry(saved.point, saved.header)})
        result = bc.evaluate_observations(contract, trace)
        assert bool(_contract_failures(result, "INV-4.c")) == substituted
        assert not any(row == "INV-4.c" for row, _ in result.limitations)
    # This Cq fixture covers publication/preparation only, not generation validity.
def test_window_cq_public_evaluation_has_no_unprepared_local_clock_gap(monkeypatch, capsys):
    bc = observation_check
    captured, validate = [], bc.validate_observation_boundary
    def observe(contract, trace):
        result = validate(contract, trace)
        if trace is not None and any(e.header.record.contract.name == "computation_completed" for e in trace.entries):
            captured.append((contract, trace))
        return result
    # Read-only capture at a PUBLIC checker boundary; no window helper oracle.
    monkeypatch.setattr(bc, "validate_observation_boundary", observe)
    test_cq_clock_readings_use_saved_source_points_and_wr_start_wp_finish()
    contract, trace = captured[-1]
    report = bc.evaluate_observations(contract, trace)
    issues = (report.violations, tuple(l for l in report.limitations if l[0] == "INV-2.b"))
    with capsys.disabled():
        print(f"\nP-07 Cq: violations / INV-2.b limitations = {issues}")
    assert not any(issues), issues
@pytest.mark.parametrize("wrong_rule,unknown_first", (("r-only-later-tie", False), ("always-value", True)))
def test_same_r_terminal_rejects_ignoring_seq_and_value_preference(wrong_rule, unknown_first):
    from fb_machine import View
    bc = observation_check
    e0 = _t10_same_r_e0(unknown_first)  # E0 selectors precede execution, not expected outputs.
    env, window = Environment(e0), CorrectWindow(e0)
    state = boundary_state(e0, published=True)
    def take(action):
        nonlocal state
        step = env.step(state, action, window)
        state = step.state
        return step
    for action in (Action("ClaimStart", ("w0",)), Action("Launch", ("w0",), "uncertain_after"),
                   Action("HostUnknown", ("unknown-0",)), Action("WorkerStep", ("w0",))): take(action)
    step = take(Action("DeliverBundle", ("same-r",)))
    posts = tuple(e.value.envelope for e in step.events if e.tag == "Post")
    assert posts[0].r == posts[1].r and posts[0].receipt_seq < posts[1].receipt_seq and posts[0].key != posts[1].key
    checker = Checker()
    for index, envelope in enumerate(posts):
        enabled = tuple(window.enabled(View(state.core, state.controls, state.evidence))) + tuple(env.actions(state))
        checker.on_state(StateObservation(index, state, e0, enabled, ()))
        take(Action("Accept", (envelope,)))
        take(Action("HostAck", envelope.key))
    assert not any(f.condition_id in ("INV-1.a", "INV-11.a") for f in checker.report().violations)
    def save(envelope):
        unit = bc.receipt_unit(envelope)
        for op in ("PrepareReceipt", "PutBody", "AddEntry", "ConfirmWrite", "CompleteWrite"):
            take(Action(op, (unit, "receipt")))
    save(posts[1])
    assert bc.observed_end_known(e0.observation_contract, state.evidence.observation_trace, "w0") is None
    save(posts[0])
    trace = state.evidence.observation_trace
    assert bc.observed_end_known(e0.observation_contract, trace, "w0")[0] == posts[0]
    first = (min(reversed(posts), key=lambda e: e.r.rank) if wrong_rule == "r-only-later-tie" else
             next(e for e in posts if e.event.fields.get("outcome").kind == OutcomeKind.RETURNED))
    assert first == posts[1]  # Both faulty rules pick a later, otherwise valid notice.
    step = take(Action("RecognizeTerminal", ("w0",)))
    result = bc.evaluate_observations(e0.observation_contract, state.evidence.observation_trace)
    assert not result.violations and not any(row == "INV-2.b" for row, _ in result.limitations), result
    publish = next(e for e in step.events if e.tag == "Publish")
    plan, = (e.value.plan for e in step.events if e.tag == "Publish")
    first_point = next(e.value.prepared.point for e in trace.events if e.tag == "FirstPrepare" and e.key == bc.SlotKey(bc.receipt_unit(first), "receipt"))
    outcome = first.event.fields.get("outcome")
    content = dict(plan.records[0].content.items)
    content.update(first_receipt=first_point, terminal_kind=outcome.kind, returned=outcome.content, basis=outcome.content if outcome.kind == OutcomeKind.UNKNOWN else None)
    wrong = replace(publish, value=bc.Published(replace(plan, records=(replace(plan.records[0], content=obj(**content)),))))
    bad = replace(trace, events=trace.events + (wrong,))
    assert _contract_failures(bc.evaluate_observations(e0.observation_contract, bad), "INV-2.b")
    assert checker.report().counts["違反なし・識別力確認済み"] == 0  # Candidates are not independent discrimination proof.
def _p10_writes(trace, point):
    bc = observation_check
    first = next(e for e in trace.events if e.tag == "FirstPrepare" and e.value.prepared.point == point)
    prepared = first.value.prepared
    result = []
    for op, value in (("PutBody", Body(prepared.seal, prepared.salt, prepared.payload)), ("AddEntry", Entry(point, prepared.header))):
        key = bc.IOKey(first.key, op, "p10-actual")
        result.extend((bc.ObservationEvent("IORequest", key, bc.IORequest(prepared)), bc.ObservationEvent("IOResponse", key, bc.IOResponse("lost", value))))
    return tuple(result)
def _p10_save_order(trace, point, index):
    writes = _p10_writes(trace, point)
    return (replace(trace, events=trace.events[:index] + writes + trace.events[index:]), replace(trace, events=trace.events + writes))
def test_p10_trace_roots_preserve_all_fields_and_reject_mixed_prefixes():
    from dataclasses import fields
    bc = observation_check
    contract, trace, first = _handmade_declared_slot()
    _, initial_bodies, initial_entries = _handmade_ledger(("initial",))
    writes = _p10_writes(trace, first.point)
    complete = replace(trace, events=trace.events + writes, bodies=trace.bodies | initial_bodies, entries=trace.entries | initial_entries, clock=Reading("run", "M", 99))
    assert {f.name for f in fields(bc.ObservationTrace)} == {"events", "bodies", "entries", "clock", "origin"}
    for index in range(len(complete.events) + 1):
        root = bc.trace_at(complete, index)
        assert root.events == complete.events[:index]
        assert root.bodies == initial_bodies | (trace.bodies if index > 3 else frozenset())
        assert root.entries == initial_entries | (trace.entries if index > 5 else frozenset())
        assert root.clock == (complete.clock if index == len(complete.events) else None)
        for earlier in range(index + 1):
            assert bc.trace_at(root, earlier) == bc.trace_at(complete, earlier)
    full = bc.trace_at(complete, len(complete.events))
    mixed = replace(full, events=full.events[:2])
    with pytest.raises(bc.UnresolvedDeclaration, match="mixes"):
        bc.publication_root(mixed, 1)
    assert bc.validate_observation_boundary(contract, mixed).violations
    # Missing IO in an allegedly initial ledger is ambiguous if a later
    # preparation establishes that value; publication must not assume Saved.
    with pytest.raises(bc.UnresolvedDeclaration, match="write history"):
        bc.publication_root(bc.trace_at(trace, len(trace.events)), 1)
    readback = bc.ObservationEvent("ReadBack", bc.IOKey(bc.SlotKey("unit", "slot"), "ReadEntry", "read"), bc.ReadBack(next(iter(trace.entries))))
    only_read = replace(trace, events=trace.events + (readback,))
    assert not bc.trace_at(only_read, 2).entries and bc.trace_at(only_read, 3).entries == trace.entries
@pytest.mark.parametrize("tag,row", (("ReadInputs", "INV-8.b"), ("WorkerReturn", "INV-15.a")))
def test_p10_worker_dependencies_require_saved_at_the_actual_event(tag, row):
    bc = observation_check
    base, roots, first = _handmade_declared_slot()
    contract, worker, token = _handmade_worker()
    ref = PlanRef("unit", "slot")
    d = replace(contract.descriptors[0], request=ref, input_points=frozenset((ref,)))
    actual = replace(d, request=first.point, input_points=frozenset((first.point,)))
    contract = replace(contract, plans=base.plans, descriptors=(d,))
    events = tuple(replace(e, value=bc.Reserved(d, d.need)) if e.tag == "Reserve" else replace(e, value=bc.InputRead(actual, actual.numerical_view, ((ref, first.point),))) if e.tag == "ReadInputs" else e for e in worker.events)
    generation = Generation(d.work_id, first.point, d.stage, Reading("run", "M", 0), Reading("run", "M", 1), Outcome(OutcomeKind.RETURNED, obj(answer=1)), "actual-port")
    trace = replace(roots, bodies=roots.bodies | worker.bodies, entries=roots.entries | worker.entries, events=roots.events + events + (bc.ObservationEvent("WorkerReturn", token, bc.Returned(generation)),))
    early, late = _p10_save_order(trace, first.point, len(roots.events))
    assert not bc.evaluate_observations(contract, early).violations
    failure = bc.evaluate_observations(contract, late)
    assert _contract_failures(failure, row)
    if tag == "ReadInputs":
        # A static-point input also uses its historical EL, without a resolver.
        static_contract = replace(contract, descriptors=(actual,))
        static = replace(late, events=tuple(replace(e, value=bc.Reserved(actual, actual.need)) if e.tag == "Reserve" else replace(e, value=bc.InputRead(actual, actual.numerical_view, ())) if e.tag == "ReadInputs" else e for e in late.events))
        assert _contract_failures(bc.evaluate_observations(static_contract, static), "INV-8.b")
def test_p10_end_known_close_save_cannot_borrow_a_later_receipt_save():
    """v0.15 (9-3補-8): connected runtime evidence absence is unmet, not unconnected."""
    bc = observation_check
    contract, trace, generation, point = _handmade_source_generation()
    slot = next(e.key for e in trace.events if e.tag == "FirstPrepare" and e.value.prepared.point == point)
    key = bc.CompletionKey("O-09.a", (generation.work,), "save", slot)
    binding = bc.CompletionBinding(key, "EndKnown", bc.WorkKey(generation.work), (slot,), bc.Owner("P.units", slot.unit))
    contract = replace(contract, completions=(binding,))
    close = bc.ObservationEvent("CloseSave", key, bc.CloseSave((slot,)))
    trace = replace(trace, events=trace.events + (close,))
    early, late = _p10_save_order(trace, point, len(trace.events) - 1)
    assert not bc.evaluate_observations(contract, early).violations
    for ordered, expected in ((early, True), (late, False)):
        close_index = next(i for i, event in enumerate(ordered.events) if event == close)
        at_close = bc.trace_at(ordered, close_index)
        assert bc.completion_occurred(binding, contract, at_close) is expected
        waiting = bc.evaluate_observations(contract, at_close)
        assert not any(c.target == key for c in waiting.violations)
        assert not any(row == "INV-2.a" and repr(key) in reason and "completion occurrence" in reason
                       for row, reason in waiting.limitations)
    # The final ledger now has the receipt; it must not justify the earlier close.
    assert bc.completion_occurred(binding, contract, late) is True
    failure = bc.evaluate_observations(contract, late)
    assert any(c.target == key for c in _contract_failures(failure, "INV-4.c"))
    assert any(c.target == key and c.message == "CloseSave precedes independent occurrence of its condition"
               for c in _contract_failures(failure, "INV-2.a"))
    assert not any(row == "INV-2.a" and repr(key) in reason and "completion occurrence" in reason
                   for row, reason in failure.limitations)
def _c01_state(contract, trace):
    from fb_machine import WorkRow
    plan = AllowedPlan("c01-owner", "O-03", (), (), contract.descriptors)
    e0 = replace(publication(), plans=(plan,), observation_declarations=contract)
    state = Environment(e0).initial()
    unit = Unit(plan.unit, plan.obligation_id, plan.key, (), tuple(d.work_id for d in contract.descriptors), frozenset())
    state = replace(state, core=replace(state.core, c=tuple(trace.bodies), e=tuple(trace.entries), p=replace(state.core.p, units=(unit,), work=tuple(WorkRow(d) for d in contract.descriptors))), evidence=replace(state.evidence, observation_trace=trace))
    return e0, state
def _c01_row(row, e0, state, enabled=()):
    bc = observation_check
    checker = Checker()
    checker._state(row, bc.Probe(checker, row, "paper contrast"), bc.Snapshot(state, e0), enabled)
    assert checker.reached[row] > 0
    return bool(checker.report().violations)
@pytest.mark.parametrize("stage", (0, 1, 2, 3))
def test_c01_start_ready_requires_each_stage_operation(stage):
    bc = observation_check
    contract, trace, key = _handmade_worker()
    events = () if stage == 0 else trace.events[:1] if stage == 1 else trace.events[:2]
    if stage == 2:
        events += (bc.ObservationEvent("LaunchResponse", key, bc.LaunchResponse("wrapper", "not_entered", "confirmed")),)
    trace = replace(trace, events=events)
    e0, state = _c01_state(contract, trace)
    action = Action("ClaimStart", (key.work,)) if stage == 0 else Action("EnterWorker", ("wrapper",)) if stage == 3 else Action("Launch", (key.work,))
    assert not _c01_row("INV-2.e", e0, state, (action,))
    assert _c01_row("INV-2.e", e0, state, ())
@pytest.mark.parametrize("tag", ("Reserve", "EnterBody"))
def test_c01_start_saved_is_checked_for_actual_events_under_any_action(tag):
    bc = observation_check
    contract, trace, key = _handmade_worker()
    i = next(i for i, e in enumerate(trace.events) if e.tag == tag)
    before = replace(trace, events=trace.events[:i])
    after = replace(trace, events=trace.events[:i+1])
    edge = (trace.events[i],)
    assert not _contract_failures(bc.evaluate_observation_step(contract, before, after, edge, action=Action("PrepareOne", ("other", "slot"))), "INV-5.b")
    missing = replace(before, bodies=frozenset(), entries=frozenset())
    assert _contract_failures(bc.evaluate_observation_step(contract, missing, replace(after, bodies=frozenset(), entries=frozenset()), edge, action=Action("Wait")), "INV-5.b")
    assert not _contract_failures(bc.evaluate_observations(contract, trace), "INV-5.b")
    assert _contract_failures(bc.evaluate_observations(contract, replace(trace, bodies=frozenset(), entries=frozenset())), "INV-5.b")
def test_c01_release_counts_every_actual_release_and_keeps_retry_distinct():
    bc = observation_check
    contract, trace, key = _handmade_worker()
    stop = bc.ObservationEvent("Stop", key, bc.Stopped("stopped"))
    release = bc.ObservationEvent("Release", key, bc.Released(contract.descriptors[0].need))
    once = replace(trace, events=trace.events + (stop, release))
    twice = replace(once, events=once.events + (release,))
    assert not _contract_failures(bc.evaluate_observations(contract, once), "INV-3.c")
    assert _contract_failures(bc.evaluate_observations(contract, twice), "INV-3.c")
    assert _contract_failures(bc.evaluate_observation_step(contract, once, once, (release,)), "INV-3.c")
def test_c01_resource_wait_needs_real_shortage_and_keeps_run_responsibility():
    from fb_machine import ConditionCustody, Excuse
    bc = observation_check
    contract, trace, key = _handmade_worker()
    trace = replace(trace, events=())
    e0, state = _c01_state(contract, trace)
    condition = bc.CompletionKey("O-02", (), "run", bc.WorkKey(key.work))
    c = ConditionCustody(condition, bc.Owner("P.work", key.work), frozenset((condition,)))
    excuse = Excuse("O-02", (), "B-RESOURCE", obj(resource="measure"), frozenset(), ("C-O02.run",))
    state = replace(state, core=replace(state.core, p=replace(state.core.p, work=(replace(state.core.p.work[0], purposes=(excuse,)),), conditions=(c,))))
    scarce = replace(e0, allocation=(("measure", 0),))
    assert not _c01_row("INV-2.f", scarce, state)
    assert _c01_row("INV-2.f", replace(e0, allocation=(("measure", 1),)), state)
    closed = replace(state, core=replace(state.core, p=replace(state.core.p, conditions=(replace(c, unmet=frozenset()),))))
    assert _c01_row("INV-2.f", scarce, closed)
def test_c01_end_save_condition_cannot_close_or_disappear_before_saved():
    from fb_machine import ConditionCustody, TypedReference
    bc = observation_check
    contract, trace, (point,) = _c01_report_family((Outcome(OutcomeKind.RETURNED, obj(value=1)),))
    generation = next(e.value.generation for e in trace.events if e.tag == "WorkerReturn")
    slot = bc.SlotKey("future", "T")
    key = bc.CompletionKey("O-05", (generation.work,), "save", slot)
    owner = bc.Owner("P.work", generation.work)
    contract = replace(contract, completions=(bc.CompletionBinding(key, "EndKnown", bc.WorkKey(generation.work), (slot,), owner),))
    e0, state = _c01_state(contract, trace)
    condition = ConditionCustody(key, owner, frozenset((key,)))
    state = replace(state, core=replace(state.core, p=replace(state.core.p, conditions=(condition,))))
    assert not _c01_row("INV-2.c", e0, state)
    for conditions in ((), (replace(condition, unmet=frozenset()),)):
        assert _c01_row("INV-2.c", e0, replace(state, core=replace(state.core, p=replace(state.core.p, conditions=conditions))))
    refs = tuple(TypedReference("PATH-LINK-GENERATION", (field,), value, "E", "terminal") for field, value in (("request", generation.request), ("first_receipt", point)))
    parents = frozenset((generation.request, point))
    record = Record("terminal", Reading("run", "M", 2), Contract("sui.fb.work_terminal", "1"), "Event", obj(work=generation.work, request=generation.request, stage=generation.stage, first_receipt=point, terminal_kind=generation.outcome.kind, returned=generation.outcome.content, basis=None, view=frozenset(e.point for e in trace.entries)), refs)
    first = _handmade_prepared(record, parents)
    plan = AllowedPlan(slot.unit, "O-05", (generation.work,), (RecordPlan(slot.slot, record.contract, record.category, record.content, refs, parents),))
    declared = replace(contract, plans=(plan,))
    planned = replace(trace, events=trace.events + (bc.ObservationEvent("Publish", bc.UnitKey(slot.unit), bc.Published(plan)), bc.ObservationEvent("FirstPrepare", slot, bc.FirstPrepared(first))))
    saved = replace(planned, bodies=planned.bodies | {Body(first.seal, first.salt, first.payload)}, entries=planned.entries | {Entry(first.point, first.header)})
    saved = replace(saved, events=saved.events + _p10_writes(saved, first.point))
    close = bc.ObservationEvent("CloseSave", key, bc.CloseSave((slot,)))
    for root, bad in ((saved, False), (planned, True)):
        assert bool(_contract_failures(bc.evaluate_observations(declared, replace(root, events=root.events + (close,))), "INV-2.c")) is bad
def test_c01_interval_handoff_requires_live_owner_for_every_unreported_cell():
    from fb_machine import ConditionCustody
    bc = observation_check
    contract, event = _interval_undertaking_fixture()
    request = event.value.request
    worker_contract, worker, _ = _handmade_worker()
    d = replace(worker_contract.descriptors[0], work_id=request.work)
    contract = replace(contract, descriptors=(d,))
    group = frozenset(b.key for b in contract.completions)
    owner = bc.Owner("P.work", d.work_id)
    handoffs = tuple(bc.ObservationEvent("HandoffPurpose", b.key, bc.HandoffPurpose(b.owner, owner, group, group)) for b in contract.completions)
    trace = bc.ObservationTrace((event,) + handoffs)
    e0, state = _c01_state(contract, trace)
    conditions = tuple(ConditionCustody(b.key, owner, frozenset((b.key,))) for b in contract.completions)
    state = replace(state, core=replace(state.core, h=replace(state.core.h, interval_requests=(request,)), p=replace(state.core.p, conditions=conditions)), evidence=replace(state.evidence, ei=replace(state.evidence.ei, requests=(request,))))
    assert not _c01_row("INV-12.b", e0, state)
    assert _c01_row("INV-12.b", e0, replace(state, core=replace(state.core, p=replace(state.core.p, work=()))))
    assert _c01_row("INV-12.b", e0, replace(state, core=replace(state.core, p=replace(state.core.p, conditions=()))))
@pytest.mark.parametrize("where", ("Publish", "Reserve", "custody"))
def test_c01_no_initial_uses_process_origin_for_actual_stage(where):
    bc = observation_check
    base = publication()
    plan = replace(base.plans[0], obligation_id="O-04")
    d = plan.works[0]
    contract = bc.ObservationE0(plans=(plan,), descriptors=(d,))
    e0, state = _c01_state(contract, bc.ObservationTrace(()))
    e0 = replace(e0, plans=(plan,), initial=None)
    unit = Unit(plan.unit, plan.obligation_id, plan.key, (), (d.work_id,), frozenset())
    state = replace(state, core=replace(state.core, p=replace(state.core.p, units=(unit,))))
    legal_publish = bc.ObservationEvent("Publish", bc.UnitKey(plan.unit), bc.Published(plan))
    legal = replace(state, evidence=replace(state.evidence, observation_trace=bc.ObservationTrace((legal_publish,))))
    assert not _c01_row("INV-13.a", e0, legal)
    wrong = replace(d, stage="Wr")
    event = bc.ObservationEvent("Publish", bc.UnitKey(plan.unit), bc.Published(replace(plan, works=(wrong,)))) if where == "Publish" else bc.ObservationEvent("Reserve", bc.WorkToken(d.work_id, "t"), bc.Reserved(wrong, wrong.need))
    bad = replace(state, evidence=replace(state.evidence, observation_trace=bc.ObservationTrace((event,))))
    if where == "custody":
        bad = replace(state, core=replace(state.core, p=replace(state.core.p, work=(replace(state.core.p.work[0], descriptor=wrong),))))
    assert _c01_row("INV-13.a", e0, bad)
def test_c01_two_acquisition_intents_are_distinct_even_with_equal_contents():
    bc = observation_check
    contract, trace = _handmade_adoption()
    event = next(e for e in trace.events if e.tag == "Acquire")
    binding = contract.acquisitions[0]
    contract = replace(contract, acquisitions=contract.acquisitions + (replace(binding, key=replace(binding.key, intent="second-intent")),))
    before = replace(trace, events=(), clock=event.value.acquisition.reading)
    after = replace(before, events=(event,))
    assert not _contract_failures(bc.evaluate_observation_step(contract, before, after, (event,), action=Action("Acquire", (event.key.intent,))), "INV-6.c")
    assert _contract_failures(bc.evaluate_observation_step(contract, before, after, (event,), action=Action("Acquire", ("second-intent",))), "INV-6.c")
    assert _contract_failures(bc.evaluate_observations(contract, replace(trace, events=trace.events + (event,))), "INV-6.c")
def _c01_report_family(outcomes, stage="Wr"):
    bc = observation_check
    contract, trace, token = _handmade_worker()
    d = replace(contract.descriptors[0], stage=stage)
    contract = replace(contract, descriptors=(d,))
    trace = replace(trace, events=tuple(replace(e, value=replace(e.value, descriptor=d)) if e.tag in ("Reserve", "ReadInputs") else e for e in trace.events))
    points = []
    for i, outcome in enumerate(outcomes, 1):
        g = Generation(d.work_id, d.request, stage, Reading("run", "M", 0), Reading("run", "M", 1), outcome, "actual-port")
        envelope = Envelope("run", i, Reading("run", "M", 1), i, Event("WorkFinished", obj(work=d.work_id, started=g.started, finished=g.finished, outcome=outcome)), "actual-port")
        _, receipt, (first,) = _handmade_receipt("WorkFinished", envelope)
        points.append(first.point)
        trace = replace(trace, events=trace.events + (bc.ObservationEvent("WorkerReturn", token, bc.Returned(g)),) + receipt.events, bodies=trace.bodies | receipt.bodies, entries=trace.entries | receipt.entries)
    return contract, trace, tuple(points)
@pytest.mark.parametrize("boundary", ("Publish", "FirstPrepare", "Saved"))
@pytest.mark.parametrize("kind", ("V", "Xc"))
def test_c01_issued_evidence_matches_actual_report_family_at_all_boundaries(boundary, kind):
    bc = observation_check
    reply = next(e.value.reply for e in _handmade_adoption()[1].events if e.tag == "VerifyReply")
    outcomes = (Outcome(OutcomeKind.RETURNED, reply),) if kind == "V" else (Outcome(OutcomeKind.RETURNED, obj(value=1)), Outcome(OutcomeKind.RETURNED, obj(value=2)))
    contract, trace, points = _c01_report_family(outcomes, "Wv" if kind == "V" else "Wr")
    d = contract.descriptors[0]
    good = obj(work=d.work_id, reply=reply, first_receipt=points[0], view=frozenset(e.point for e in trace.entries)) if kind == "V" else obj(reports=frozenset(points), rule="CMP-22", affected=frozenset((d.work_id,)), view=frozenset(e.point for e in trace.entries))
    bad = replace(good, items=tuple((k, replace(reply, response="Rejected") if k == "reply" else v) for k, v in good.items)) if kind == "V" else obj(reports=frozenset(points[:1]), rule="CMP-22", affected=frozenset((d.work_id,)), view=frozenset(e.point for e in trace.entries))
    name, row = ("sui.fb.verification_result", "INV-9.a") if kind == "V" else ("sui.fb.conflict", "INV-7.a")
    for content, fails in ((good, False), (bad, True)):
        record = Record("evidence", Reading("run", "M", 2), Contract(name, "1"), "Event", content, ())
        first = _handmade_prepared(record)
        slot = bc.SlotKey("evidence", kind)
        recipe = RecordPlan(kind, record.contract, "Event", content)
        plan = AllowedPlan(slot.unit, "O-05", (), (recipe,))
        declared = replace(contract, plans=(plan,))
        publish = bc.ObservationEvent("Publish", bc.UnitKey(slot.unit), bc.Published(plan))
        prepared = bc.ObservationEvent("FirstPrepare", slot, bc.FirstPrepared(first))
        candidate = replace(trace, events=trace.events + ((publish,) if boundary == "Publish" else (publish, prepared)))
        if boundary == "Saved":
            candidate = replace(candidate, bodies=candidate.bodies | {Body(first.seal, first.salt, first.payload)}, entries=candidate.entries | {Entry(first.point, first.header)})
            candidate = replace(candidate, events=candidate.events + _p10_writes(candidate, first.point))
        result = bc.evaluate_observations(declared, candidate)
        assert any(c.row == row for c in result.clauses)
        assert bool(_contract_failures(result, row)) is fails
@pytest.mark.parametrize("scene_id", ("SC-04-one-reference-missing", "SC-04-initial-publish"))
def test_c02_legal_written_but_unconfirmed_graph(scene_id, capsys):
    import fb_scenes as scenes

    scene = next(s for s in scenes.SCENES if s.id == scene_id)
    scenario, *_ = scenes.instantiate(scene)
    if scene_id == "SC-04-initial-publish":
        env, window = Environment(scenario.e0), CorrectWindow(scenario.e0)
        state = scenario.initial
        actions = (Action("PublishUnit", ("initial",)),) + tuple(
            Action(op, ("initial", "process"))
            for op in ("PrepareOne", "PutBody", "AddEntry", "ConfirmWrite", "CompleteWrite")
        ) + (Action("PrepareOne", ("initial", "reader")),)
        for action in actions:
            state = env.step(state, action, window).state
        scenario = replace(scenario, initial=state, max_states=2000,
            cut=Cut("C-02-storage", frozenset(("ClaimStart", "Launch", "EnterWorker",
                                             "WorkerStep", "RecognizeTerminal", "ResolveWork",
                                             "Drain", "Wait", "Stop", "Release")),
                    ("work execution outside this storage slice",)))
    graph = explore(scenario, window=CorrectWindow(scenario.e0))
    assert graph.complete
    assert 1 < len(graph.states) < 2000
    assert any(edge.action.operation == "AddEntry" for edge in graph.edges)
    report = check_exploration(scenario, graph)
    with capsys.disabled():
        print(f"\nC-02 {scene_id}: states={len(graph.states)} violations={report.violations}")
    assert not report.violations


@pytest.fixture(scope="module")
def c02_reference_states():
    """Paper 299-303,390,1062: write, confirm and resolve are separate steps.

    Execute a small independent declaration through public calls. In particular,
    do not seed already-resolved Points as the only positive control (C-01).
    """
    e0 = publication()
    env, window = Environment(e0), CorrectWindow(e0)
    state = boundary_state(e0)
    state = env.step(state, Action("PublishUnit", ("initial",)), window).state
    for slot in ("process", "reader", "request"):
        operations = ("PrepareOne", "PutBody", "AddEntry")
        if slot != "request":
            operations += ("ConfirmWrite", "CompleteWrite")
        for operation in operations:
            state = env.step(state, Action(operation, ("initial", slot)), window).state
    written = state
    confirmed = env.step(written, Action("ConfirmWrite", ("initial", "request")), window).state
    resolved = env.step(written, Action("ResolveWork", ("w0",)), window).state
    confirmed_resolved = env.step(confirmed, Action("ResolveWork", ("w0",)), window).state
    return e0, {(False, False): written, (True, False): confirmed,
                (False, True): resolved, (True, True): confirmed_resolved}


def _c02_start_actions(e0, state):
    from fb_machine import View

    view = View(state.core, state.controls, state.evidence)
    return tuple(CorrectWindow(e0).enabled(view)) + tuple(Environment(e0).actions(state))


def _c02_start_result(e0, state, enabled):
    checker = Checker()
    checker.on_state(StateObservation(0, state, e0, tuple(enabled), ()))
    return next(row for row in checker.report().rows if row.condition_id == "INV-2.e")


@pytest.mark.parametrize("readback", (False, True))
@pytest.mark.parametrize("resolved", (False, True))
def test_c02_written_confirmed_and_resolved_are_different_premises(c02_reference_states, readback, resolved):
    bc = observation_check
    e0, states = c02_reference_states
    state = states[readback, resolved]
    trace = state.evidence.observation_trace
    desc = e0.plans[0].works[0]
    # All four roots have exactly the same actual Saved bytes, no final-state oracle.
    assert state.core.c == states[False, False].core.c
    assert state.core.e == states[False, False].core.e
    assert bc.start_points_saved(e0.observation_contract, trace, desc)
    assert any(e.tag == "ReadBack" and e.key.slot == bc.SlotKey("initial", "request")
               for e in trace.events) is readback
    assert not any(e.tag == "CloseSave" and bc.SlotKey("initial", "request") in e.value.slots
                   for e in trace.events)
    assert bc.start_references_ready(e0.observation_contract, trace, desc,
                                     state.core.p.work[0].resolutions) is resolved
    enabled = _c02_start_actions(e0, state)
    good = _c02_start_result(e0, state, enabled)
    assert not good.violations
    missing = _c02_start_result(e0, state, (a for a in enabled if a.operation != "ClaimStart"))
    assert bool(missing.violations) is resolved
    if resolved:
        assert missing.reached > 0
        assert any("lacks ClaimStart" in f.message for f in missing.violations)


@pytest.mark.parametrize("readback", (False, True))
def test_c02_resolved_work_still_requires_launch_without_free_seats(c02_reference_states, readback):
    e0, states = c02_reference_states
    env, window = Environment(e0), CorrectWindow(e0)
    state = env.step(states[readback, True], Action("ClaimStart", ("w0",)), window).state
    enabled = _c02_start_actions(e0, state)
    assert not _c02_start_result(e0, state, enabled).violations
    missing = _c02_start_result(e0, state, (a for a in enabled if a.operation != "Launch"))
    assert any("lacks Launch" in f.message for f in missing.violations)


def test_c02_saved_flags_and_mapping_presence_are_not_oracles(c02_reference_states):
    bc = observation_check
    e0, states = c02_reference_states
    unresolved, resolved = states[False, False], states[False, True]
    desc = e0.plans[0].works[0]
    trace = resolved.evidence.observation_trace
    mapping = resolved.core.p.work[0].resolutions
    ref = PlanRef("initial", "request")
    wrong = tuple((key, dict(mapping)[PlanRef("initial", "reader")] if key == ref else point)
                  for key, point in mapping)
    assert not bc.start_references_ready(e0.observation_contract, trace, desc, wrong)
    duplicate = mapping + ((ref, dict(mapping)[ref]),)
    assert not bc.start_references_ready(e0.observation_contract, trace, desc, duplicate)
    missing_body = replace(trace, bodies=frozenset())
    assert not bc.start_references_ready(e0.observation_contract, missing_body, desc, mapping)
    forged_units = tuple(replace(unit, slots=tuple(
        replace(slot, body_confirmed=True, entry_confirmed=True, completed=True)
        for slot in unit.slots)) for unit in unresolved.core.p.units)
    forged = replace(unresolved, core=replace(unresolved.core,
        p=replace(unresolved.core.p, units=forged_units)))
    assert not _c02_start_result(e0, forged, ()).violations
    wrong_work = replace(resolved.core.p.work[0], resolutions=wrong)
    wrong_state = replace(resolved, core=replace(resolved.core,
        p=replace(resolved.core.p, work=(wrong_work,))))
    assert _c01_row("INV-3.b", e0, wrong_state)


@pytest.fixture(scope="module")
def c03_public_end_path():
    """844/1188/1193/1209: the same public Failure prefix and an E0 handoff.

    The destination is declared before I0. Neither the window's completion
    bits nor its condition-birth journal decides the checker's population.
    """
    import fb_scenes as scenes
    from fb_machine import Edge, Exploration, HandoffRoute

    bc = observation_check
    scene = next(s for s in scenes.SCENES if s.id == "SC-04-DESC")
    key = next(b.key for b in scene.e0.observation_contract.completions
               if b.key.obligation == "O-05" and b.key.kind == "handle"
               and b.key.target == bc.WorkKey("wr"))
    save_binding = next(b for b in scene.e0.observation_contract.completions
                        if b.key.obligation == "O-05" and b.key.kind == "save")
    destination = bc.Owner("P.units", save_binding.slots[0].unit)
    scene = replace(scene, e0=replace(scene.e0,
        handoff_routes=(HandoffRoute(key, destination),)))
    scenario, states, edges, _ = scenes.instantiate(scene)
    env, window = Environment(scenario.e0), CorrectWindow(scenario.e0)
    def take(action):
        nonlocal states, edges
        assert action in _c02_start_actions(scenario.e0, states[-1]), action
        step = env.step(states[-1], action, window)
        states += (step.state,)
        edges += (Edge(len(states) - 2, len(states) - 1, action, step.events, step.result),)

    assert bc.observed_end_known(scenario.e0.observation_contract, states[-1].evidence.observation_trace, "wr") is not None
    take(Action("RecognizeTerminal", ("wr",)))
    take(Action("Drain"))
    action = next(a for a in _c02_start_actions(scenario.e0, states[-1])
                  if a.operation == "HandoffPurpose")
    take(action)
    graph = Exploration(scenario.id, states, edges,
        tuple(_c02_start_actions(scenario.e0, state) for state in states),
        False, (len(states) - 1,), (), 0.0,
        (None,) + tuple((edge.source, edge.action) for edge in edges),
        ("declared prefix and handoff, not an exhaustive graph",))
    return scenario, graph, key


def test_c03_public_end_retention_and_handoff(c03_public_end_path, capsys):
    bc = observation_check
    scenario, graph, key = c03_public_end_path
    before, retained, handed = graph.states[-3:]
    assert bc.observed_end_known(scenario.e0.observation_contract, before.evidence.observation_trace, "wr") is not None
    old = next(c for c in before.core.p.conditions if c.key == key)
    kept = next(c for c in retained.core.p.conditions if c.key == key)
    moved = next(c for c in handed.core.p.conditions if c.key == key)
    assert key in old.unmet and kept == old
    assert moved.unmet == kept.unmet and moved.owner != kept.owner
    assert not graph.edges[-2].actual_events
    assert any(e.tag == "HandoffPurpose" and e.key == key for e in graph.edges[-1].actual_events)
    report = check_exploration(scenario, graph)
    assert not report.violations and not report.contract_violations, report.violations
    with capsys.disabled():
        print(f"\nC-03 public prefix: states={len(graph.states)} violations={len(report.violations)}")


@pytest.mark.parametrize("kind,change", (("handle", "delete"), ("handle", "clear"),
                                       ("save", "delete"), ("save", "clear"),
                                       ("handle", "rename"), ("handle", "owner")))
@pytest.mark.parametrize("published", (False, True))
def test_c03_end_condition_loss_without_events(c03_public_end_path, kind, change, published):
    """Nearest counterfactual of a real public Drain; no mutant name or event bit.

    The unmodified edge and the handoff pass all rows in the companion test.
    Only this condition's frozen custody is changed; trace and action are kept.
    These authored candidates are not independent identification evidence.
    """
    bc = observation_check
    scenario, graph, _ = c03_public_end_path
    before = graph.states[-3] if published else graph.states[-4]
    step = Environment(scenario.e0).step(before, Action("Drain"), CorrectWindow(scenario.e0))
    after = step.state
    assert not _c01_row("INV-2.c", scenario.e0, after)
    row = next(c for c in after.core.p.conditions if c.key.obligation == "O-05" and c.key.kind == kind)
    assert row.key in row.unmet and not step.events
    if change == "delete":
        conditions = tuple(c for c in after.core.p.conditions if c.key != row.key)
    else:
        changed = (replace(row, unmet=frozenset()) if change == "clear" else
                   replace(row, key=replace(row.key, obligation_key=("other-work",))) if change == "rename" else
                   replace(row, owner=bc.Owner("P.work", "nonexistent")))
        conditions = tuple(changed if c.key == row.key else c for c in after.core.p.conditions)
    after = replace(after, core=replace(after.core, p=replace(after.core.p, conditions=conditions)))
    assert _c01_row("INV-2.c", scenario.e0, after)
    result = bc.evaluate_observation_step(scenario.e0.observation_contract,
        before.evidence.observation_trace, after.evidence.observation_trace, step.events,
        before_state=before, after_state=after, action=Action("Drain"))
    assert _contract_failures(result, "INV-2.c")
    assert _contract_failures(result, "INV-2.a")
    assert not result.boundary.violations


@pytest.mark.parametrize("kind", ("save", "handle", "run", "issue", "stop"))
def test_c03_every_prior_unmet_kind_is_preserved_without_a_tag(c03_public_end_path, kind, monkeypatch):
    """1193/1194: even an extra promise cannot vanish because it is undeclared.

    Frozen candidate only: the deliberately extra condition is not claimed to
    be a lawful birth or an end-to-end scene. Its lack of conclusion binding
    must stay visible as a limitation, not be converted to completion.
    v0.15 (9-3補-8): keep the exact unknown target; detect independently known loss separately.
    """
    from fb_machine import ConditionCustody

    bc = observation_check
    scenario, graph, _ = c03_public_end_path
    state = graph.states[-3]
    key = bc.CompletionKey("O-05", ("extra-promise",), kind, bc.WorkKey("wr"))
    extra = ConditionCustody(key, bc.Owner("P.work", "wr"), frozenset((key,)))
    before = replace(state, core=replace(state.core,
        p=replace(state.core.p, conditions=state.core.p.conditions + (extra,))))
    trace = before.evidence.observation_trace
    contract = scenario.e0.observation_contract

    def evaluate(after):
        return bc.evaluate_condition_custody(contract, trace, after, before_state=before)

    def assert_unconnected_target(result):
        # Check the full original identity and meaning, not a count of unknowns.
        reports = [j for j in result.custody if j.target == key]
        assert len(reports) == 1, (key, reports)
        report = reports[0]
        assert report.classification == "未接続" and report.direct is None and report.transfer is False
        reason = "independent conclusion for " + repr(key)
        assert reason in report.reasons
        assert all((row, "約束の未接続: " + reason) in result.limitations for row in ("INV-2.a", "INV-2.c"))
        assert not any(c.target == key for c in result.clauses)  # neither pass nor violation

    legal_retention = evaluate(before)
    assert not legal_retention.violations
    assert_unconnected_target(legal_retention)
    save = next(b for b in contract.completions
                if b.key.obligation == "O-05" and b.key.kind == "save" and b.trigger == "EndKnown")
    assert bc.completion_occurred(save, contract, trace) is True
    assert bc.completion_conclusion(save, contract, trace, before) is False
    for after in (state, replace(before, core=replace(before.core,
                  p=replace(before.core.p, conditions=state.core.p.conditions + (replace(extra, unmet=frozenset()),))))):
        result = evaluate(after)
        assert not result.violations
        assert_unconnected_target(result)
        # Unknown extra promises do not suppress this independently unmet T.
        for lose_owner in (False, True):
            conditions = tuple(
                replace(c, owner=bc.Owner("P.units", "absent-terminal-owner")) if c.key == save.key else c
                for c in after.core.p.conditions if lose_owner or c.key != save.key)
            bad = replace(after, core=replace(after.core, p=replace(after.core.p, conditions=conditions)))
            failure = evaluate(bad)
            assert_unconnected_target(failure)
            assert all(any(c.target == save.key for c in _contract_failures(failure, row))
                       for row in ("INV-2.a", "INV-2.c"))

    # Inject reporting faults through the evaluator used above. An omitted
    # target, a hidden limitation, and a count-preserving renamed target must
    # each fail the SAME assertions as the normal evaluations.
    original_evaluate = bc.evaluate_condition_custody
    other = replace(key, obligation_key=("unrelated-promise",))
    for fault in ("omit-target", "omit-limitation", "rename-target"):
        def broken(*args, **kwargs):
            result = original_evaluate(*args, **kwargs)
            if fault == "omit-target":
                return replace(result, custody=tuple(j for j in result.custody if j.target != key))
            if fault == "omit-limitation":
                return replace(result, limitations=tuple((r, why) for r, why in result.limitations if repr(key) not in why))
            return replace(result,
                custody=tuple(replace(j, target=other, reasons=tuple(why.replace(repr(key), repr(other)) for why in j.reasons))
                              if j.target == key else j for j in result.custody),
                limitations=tuple((r, why.replace(repr(key), repr(other))) for r, why in result.limitations))
        with monkeypatch.context() as patch:
            patch.setattr(bc, "evaluate_condition_custody", broken)
            with pytest.raises(AssertionError):
                assert_unconnected_target(evaluate(state))


def test_c03_saved_does_not_close_other_end_conditions(c03_public_end_path):
    bc = observation_check
    scenario, graph, _ = c03_public_end_path
    state = graph.states[-3]
    env, window = Environment(scenario.e0), CorrectWindow(scenario.e0)
    binding = next(b for b in scenario.e0.observation_contract.completions
                   if b.key.obligation == "O-05" and b.key.kind == "save")
    for slot in binding.slots:
        for operation in ("PrepareOne", "PutBody", "AddEntry", "ConfirmWrite", "CompleteWrite"):
            state = env.step(state, Action(operation, (slot.unit, slot.slot)), window).state
    trace = state.evidence.observation_trace
    assert bc.completion_slots_saved(scenario.e0.observation_contract, trace, binding.slots)
    assert not _c01_row("INV-2.c", scenario.e0, state)
    handle = next(c for c in state.core.p.conditions if c.key.obligation == "O-05" and c.key.kind == "handle")
    assert handle.key in handle.unmet
    after = replace(state, core=replace(state.core, p=replace(state.core.p,
        conditions=tuple(replace(c, unmet=frozenset()) if c.key == handle.key else c for c in state.core.p.conditions))))
    assert _c01_row("INV-2.c", scenario.e0, after)


def test_c03_stop_conclusion_cannot_use_a_future_reservation(c03_public_end_path):
    """O-14/INV-10.b: Stop and release must follow the actual holding."""
    bc = observation_check
    scenario, graph, _ = c03_public_end_path
    state = graph.states[-4]
    contract, trace = scenario.e0.observation_contract, state.evidence.observation_trace
    binding = next(b for b in contract.completions if b.key.kind == "stop" and b.key.target == bc.WorkKey("wr"))
    assert bc.completion_conclusion(binding, contract, trace, state) is True
    release_events = tuple(e for e in trace.events if e.tag in ("Stop", "Release"))
    assert {e.tag for e in release_events} == {"Stop", "Release"}
    premature = replace(trace, events=release_events + tuple(e for e in trace.events if e not in release_events))
    assert bc.completion_conclusion(binding, contract, premature, state) is False


# Implementation-owned observation transport tests; checker tests above intact.
def _t9_clock_source_e0(e0):
    from fb_machine import clock_source_record
    # A-CLOCK-SOURCE: this declaration is fixed before any actual window step.
    plan = AllowedPlan("clock-source", "O-02", ("clock-source", e0.run, e0.clock_source),
                       (clock_source_record(e0.run, e0.clock_source),))
    return replace(e0, plans=e0.plans + (plan,))


def _t9_save_clock_source(env, window, state):
    state = env.step(state, Action("PublishUnit", ("clock-source",)), window).state
    return _t5_save(env, window, state, "clock-source", ("source",))


def test_lost_commit_and_repeated_io_keep_actual_values_on_every_edge():
    e0 = receiver(budget=Budget(lost_responses=2))
    env, window = Environment(e0), CorrectWindow(e0)
    state = env.initial()
    for action in (Action("Post", ("external-0",)),):
        state = env.step(state, action, window).state
    envelope = state.core.h.queue[0]
    state = env.step(state, Action("Accept", (envelope,)), window).state
    state = env.step(state, Action("HostAck", envelope.key), window).state
    key = (receipt_unit_id(e0.run, 0), "receipt")
    state = env.step(state, Action("PrepareReceipt", key), window).state
    lost = env.step(state, Action("PutBody", key, "lost_response"), window)
    assert [e.tag for e in lost.events] == ["IORequest", "IOResponse"]
    assert lost.events[1].value.response == "lost"
    assert lost.events[1].value.written in lost.state.core.c
    state = env.step(lost.state, Action("ConfirmBody", key), window).state
    lost_entry = env.step(state, Action("AddEntry", key, "lost_response"), window)
    assert lost_entry.events[1].value.written in lost_entry.state.core.e
    acknowledged = env.step(lost_entry.state, Action("AddEntry", key), window)
    repeated = env.step(acknowledged.state, Action("AddEntry", key), window)
    assert repeated.state == acknowledged.state
    assert repeated.events == acknowledged.events
    assert len(repeated.events) == 2  # state quotient never removes edge calls
    confirmed = env.step(repeated.state, Action("ConfirmWrite", key), window)
    assert [e.key.operation for e in confirmed.events] == ["ReadBody", "ReadBody", "ReadEntry", "ReadEntry"]
    assert not observation_check.evaluate_observation_step(e0.observation_contract,
        repeated.state.evidence.observation_trace, confirmed.state.evidence.observation_trace,
        confirmed.events).violations


def test_finite_presentation_cut_preserves_the_full_enabled_service():
    scenario = Scenario("CONNECT-representation-retry", replace(receiver(), presentation_limit=1), 200)
    graph = explore(scenario)
    assert graph.complete and graph.omitted
    for index, action in graph.omitted:
        assert action.operation == "Accept" and action in graph.enabled[index]
    env, window = Environment(scenario.e0), CorrectWindow(scenario.e0)
    index, action = graph.omitted[0]
    repeated = env.step(graph.states[index], action, window)
    assert [e.tag for e in repeated.events] == ["Present", "Accept"]
    # The real environment/window still permit retries outside this smoke Cut.
    assert len(repeated.state.evidence.observation_trace.events) > len(graph.states[index].evidence.observation_trace.events)


def test_worker_ports_are_scripted_actual_outputs_separate_from_e0_relations():
    from fb_machine import ProgramPortEvent
    bc = observation_check
    # Opaque Points exercise typed transport only, not Saved/F-a validity.
    # The script is fixed BEFORE any Environment/CorrectWindow is created.
    p, m, s = Point("reader"), Point("model"), Point("series")
    artifact = bc.ArtifactValue(Contract("model.artifact", "1"), Contract("model.compiler", "1"),
                                "actual-reader", "actual-registry", obj(input=3), (), obj(result=4))
    application = bc.Applied(Contract("finite_update", "1"), obj(report=1), Point("binding"),
                            "actual-transition", obj(kernel=2), obj(outcome=3), frozenset(("m0",)),
                            "actual-input-digest", "new_application")
    coverage_claim = bc.CoverageClaimed(frozenset(), Point("report"), "Unproved", Contract("model.report", "1"),
                                       frozenset(), frozenset())
    checked = bc.ArtifactChecked(artifact, "Insufficient", Point("request"), None, None, frozenset())
    ports = (ProgramPortEvent(0, "Apply", bc.ApplicationKey(p, m, s), application),
             ProgramPortEvent(0, "CertifiedCoverage", bc.IntervalKey("k", "route", "run-0"), coverage_claim),
             ProgramPortEvent(0, "ArtifactIssued", bc.WorkKey("w0"), artifact),
             ProgramPortEvent(0, "ArtifactChecked", bc.WorkKey("w0"), checked))
    e0 = replace(publication(), programs=(Program("w0", (Outcome(OutcomeKind.RETURNED, obj(port="returned")),),
                                                 True, ports),))
    declared = e0.observation_contract
    assert not declared.applications and not declared.artifacts  # no manufactured normative truth
    env, window = Environment(e0), CorrectWindow(e0)
    state = boundary_state(e0, published=True)
    for action in (Action("ClaimStart", ("w0",)), Action("Launch", ("w0",)),
                   Action("EnterWorker", ("w0:wrapper:0",))):
        state = env.step(state, action, window).state
    returned = env.step(state, Action("WorkerStep", ("w0",)), window)
    assert [e.tag for e in returned.events] == ["WorkerReturn", "Apply", "CertifiedCoverage", "ArtifactIssued", "ArtifactChecked"]
    assert returned.events[1].value == application
    assert returned.events[3].value.artifact == artifact
    assert returned.events[3].value.generation == returned.events[0].value.generation
    assert e0.observation_contract == declared
    assert not bc.validate_observation_boundary(declared, returned.state.evidence.observation_trace, returned.events).violations
    stopped = env.step(returned.state, Action("Stop", ("w0",)), window)
    released = env.step(stopped.state, Action("Release", ("w0",)), window)
    assert stopped.events[0].tag == "Stop" and released.events[0].tag == "Release"
    assert released.events[0].value.resources == e0.plans[0].works[0].need


def test_clock_advance_exposes_reaccept_contract_tension_without_replacing_receipt():
    # Paper 797: advancing the host clock must preserve the first Accept's
    # receipt plan/created reading. The repaired independent contract agrees.
    bc = observation_check
    e0 = E0(postings=(Posting("first", received(), 1), Posting("second", received(), 2)))
    env, window = Environment(e0), CorrectWindow(e0)
    state = env.step(env.initial(), Action("Post", ("first",)), window).state
    envelope = state.core.h.queue[0]
    accepted = env.step(state, Action("Accept", (envelope,)), window).state
    advanced = env.step(accepted, Action("Post", ("second",)), window).state
    repeated = env.step(advanced, Action("Accept", (envelope,)), window)
    assert repeated.state.core.p.receipts == advanced.core.p.receipts
    first_accept = next(e.value for e in accepted.evidence.observation_trace.events if e.tag == "Accept")
    reaccept = next(e.value for e in repeated.events if e.tag == "Accept")
    assert reaccept.plans == first_accept.plans and reaccept.created == first_accept.created
    result = bc.evaluate_observation_step(e0.observation_contract, advanced.evidence.observation_trace,
                                         repeated.state.evidence.observation_trace, repeated.events)
    assert not result.boundary.violations and not result.violations


def test_causal_port_dag_is_independent_of_window_header_parents():
    from fb_machine import CausalPort
    bc = observation_check
    e0 = replace(publication(), causal_ports=(CausalPort(bc.SlotKey("initial", "reader"),
                                      frozenset((PlanRef("initial", "process"),))),))
    # This actual port program is fixed before the prefix runs. Header parents
    # are deliberately empty; an actual causal read cannot be inferred from it.
    state = boundary_state(e0, published=True)
    firsts = {e.key: e.value.prepared.point for e in state.evidence.observation_trace.events if e.tag == "FirstPrepare"}
    reader = firsts[bc.SlotKey("initial", "reader")]
    process = firsts[bc.SlotKey("initial", "process")]
    node = next(n for n in state.evidence.ea.causal_nodes if n.point == reader)
    entry = next(e for e in state.core.e if e.point == reader)
    assert node.parents == frozenset((process,))
    assert entry.header.parents == frozenset()


def test_connection_counts_and_per_scene_elapsed_report(checked_cases, capsys):
    # Reuse checker-owned graphs: reporting adds no second exploration and no
    # semantic pass. A connected schema still has partial/unconnected clauses.
    tags = set()
    with capsys.disabled():
        for scenario, graph, report in checked_cases:
            assert report.connection_counts == {"約束の未接続": 0, "約束違反": 0, "約束接続・部分判定": 47}
            assert len(report.rows) == 47
            assert {"INV-2.g", "INV-16.c"} <= {row.condition_id for row in report.rows}
            if scenario.id == "CHECK-EI-transport":
                assert report.unconnected_observations == ()
            tags.update(e.tag for state in graph.states for e in state.evidence.observation_trace.events)
            print(f"\nCONNECTED {scenario.id}: states={len(graph.states)} edges={len(graph.edges)} "
                  f"seconds={graph.elapsed_seconds:.6f} omitted={len(graph.omitted)} "
                  f"complete_within_cut={graph.complete} connections={report.connection_counts} "
                  f"unconnected_observations={report.unconnected_observations}", flush=True)
        print("\nSMALL-SCENE observed tags: " + ", ".join(sorted(tags)), flush=True)


def test_acquisition_tag_binds_actual_contents_to_the_saved_content_acquired_record():
    from fb_machine import AcquisitionIntent, Source, TypedReference, UpdateTarget, clock_reading_record
    bc = observation_check
    base = publication()
    process, reader, request = (PlanRef("initial", slot) for slot in ("process", "reader", "request"))
    intent = AcquisitionIntent("i0", reader, frozenset((process,)), request, frozenset(),
                               record=PlanRef("g-plan", "g"))
    clock = PlanRef("g-plan", "clock")
    clock_record = clock_reading_record("clock", PlanRef("clock-source", "source"), Source("acquisition_clock", "i0"))
    record = RecordPlan("g", Contract("content_acquired", "1"), "Event",
                        obj(origin=reader, contents=(process,), clock=clock),
                        (TypedReference("PATH-ACQUIRE", ("origin",), reader, "UE", "acquire"),
                         TypedReference("PATH-ACQUIRE", ("contents", 0), process, "UE", "acquire"),
                         TypedReference("PATH-ACQUIRE", ("clock",), clock, "UE", "acquire")))
    wv = replace(base.plans[0].works[0], work_id="wv", stage="Wv", request=request,
                 args=obj(target=UpdateTarget(request, process, frozenset(), request),
                          check_view=frozenset((process, reader, request)), registry="model",
                          checker=Contract("model.verify", "1")), required=frozenset((PlanRef("g-plan", "g"),)))
    plan = AllowedPlan("g-plan", "O-08", ("i0",), (clock_record, record), (wv,), (Guard("acquired", "i0"),))
    # Separate declared scene input and actual port script, both fixed upfront.
    e0 = _t9_clock_source_e0(replace(base, plans=base.plans + (plan,), acquisitions=(intent,),
                                   programs=base.programs + (Program("wv", (), False),)))
    env, window = Environment(e0), CorrectWindow(e0)
    state = boundary_state(e0, published=True)
    state = _t9_save_clock_source(env, window, state)
    acquired = env.step(state, Action("Acquire", ("i0",)), window)
    actual = acquired.state.evidence.ea.acquisitions[0]
    assert actual.contents and all(payload for _, payload in actual.contents)
    observation = next(e for e in acquired.events if e.tag == "Acquire")
    assert observation.value.acquisition == actual and observation.value.record is None
    binding = e0.observation_contract.acquisitions[0]
    assert binding.key.reader == reader and binding.record == PlanRef("g-plan", "g")
    assert not bc.evaluate_observation_step(e0.observation_contract, state.evidence.observation_trace,
                                           acquired.state.evidence.observation_trace, acquired.events).violations
    state = env.step(acquired.state, Action("PublishUnit", ("g-plan",)), window).state
    state = _t5_save(env, window, state, "g-plan", ("clock",))
    key = ("g-plan", "g")
    for operation in ("PrepareOne", "PutBody"):
        state = env.step(state, Action(operation, key), window).state
    written = env.step(state, Action("AddEntry", key), window)
    prepared = next(e.value.prepared for e in written.state.evidence.observation_trace.events
                    if e.tag == "FirstPrepare" and e.key == bc.SlotKey("g-plan", "g"))
    clock_prepared = next(e.value.prepared for e in written.state.evidence.observation_trace.events
                          if e.tag == "FirstPrepare" and e.key == bc.SlotKey("g-plan", "clock"))
    assert prepared.header.record.content.get("clock") == clock_prepared.point
    assert clock_prepared.header.record.content.get("reading") == actual.reading
    source = next(e.value.prepared.point for e in written.state.evidence.observation_trace.events
                  if e.tag == "FirstPrepare" and e.key == bc.SlotKey("clock-source", "source"))
    assert clock_prepared.header.record.content.get("source") == source
    assert not any(e.tag == "Acquire" for e in written.events)
    assert sum(e.tag == "Acquire" for e in written.state.evidence.observation_trace.events) == 1
    assert not bc.evaluate_observation_step(e0.observation_contract, state.evidence.observation_trace,
                                           written.state.evidence.observation_trace, written.events).violations, "G.clock is a saved Point; checker must dereference its reading (F-a 60/66)"
    assert not bc.validate_observation_boundary(e0.observation_contract,
                                               written.state.evidence.observation_trace, written.events).violations


def test_certificate_shaped_reply_never_manufactures_actual_issuance():
    from fb_machine import Certificate, CertificatePortEvent, UpdateTarget, VerificationReply
    # Opaque port-value transport test, not a successful Wv/F-a certification.
    process, reader, request = (PlanRef("initial", s) for s in ("process", "reader", "request"))
    target = UpdateTarget(request, process, frozenset(), request)
    alleged = Certificate("reply-claim", target, reader, (), NumericalView(),
                          frozenset(), frozenset(), "registry", Contract("checker", "1"), "digest")
    issued = replace(alleged, issuer="actual-issuer-port")
    reply = VerificationReply("Success", target, alleged.reader, (), NumericalView(), frozenset(),
                              frozenset(), alleged.registry, alleged.checker, obj(answer=1), (), frozenset(), alleged)

    def returned(issuances):
        base = publication()
        desc = replace(base.plans[0].works[0], stage="Wv",
                       args=obj(target=target, check_view=frozenset((process, reader, request)),
                                registry=alleged.registry, checker=alleged.checker),
                       input_points=frozenset((process, reader, request)))
        e0 = replace(base, plans=(replace(base.plans[0], works=(desc,)),),
                     programs=(Program("w0", (Outcome(OutcomeKind.RETURNED, reply),),
                                                     False, certificate_events=issuances),))
        env, window = Environment(e0), CorrectWindow(e0)
        state = boundary_state(e0, published=True)
        for action in (Action("ClaimStart", ("w0",)), Action("Launch", ("w0",)),
                       Action("EnterWorker", ("w0:wrapper:0",))):
            state = env.step(state, action, window).state
        return env.step(state, Action("WorkerStep", ("w0",)), window)

    merely_replied = returned(())
    assert not merely_replied.state.evidence.ea.issued
    assert not any(e.tag == "CertificateIssued" for e in merely_replied.events)
    separate_port = returned((CertificatePortEvent(0, issued),))
    actual = separate_port.state.evidence.ea.issued[0][1]
    assert actual.issuer == issued.issuer
    assert next(e.value.certificate for e in separate_port.events if e.tag == "CertificateIssued") == actual
    actual_reply = next(e.value.reply for e in separate_port.events if e.tag == "VerifyReply")
    assert actual_reply.certificate.issuer == alleged.issuer
    assert actual_reply.target == actual.target


def test_handoff_moves_all_unmet_instances_from_actual_custody_without_achievement(capsys):
    from fb_machine import HandoffRoute
    bc = observation_check
    base = publication()
    key = bc.CompletionKey("O-02", base.plans[0].key, "save", bc.SlotKey("initial", "process"))
    # Deliberately wrong E0.owner is a negative transport control, not a valid
    # paper scene. It must not manufacture the ACTUAL holder or a Handoff fact.
    declared = base.observation_contract
    declared = replace(declared, completions=tuple(
        replace(b, owner=bc.Owner("P.work", "not-a-carrier")) if b.key.obligation == "O-02" else b
        for b in declared.completions))
    e0 = replace(base, observation_declarations=declared,
                 handoff_routes=(HandoffRoute(key, bc.Owner("P.work", "w0")),))
    env, window = Environment(e0), CorrectWindow(e0)
    state = env.step(boundary_state(e0), Action("PublishUnit", ("initial",)), window).state
    before = {c.key: c for c in state.core.p.conditions}
    group = frozenset(c.key for c in before.values() if c.key.obligation == "O-02")
    assert len(group) == 3 and all(before[k].owner == bc.Owner("P.units", "initial") for k in group)
    handed = env.step(state, Action("HandoffPurpose", (key, bc.Owner("P.work", "w0"))), window)
    after = {c.key: c for c in handed.state.core.p.conditions}
    assert set(after) == set(before)
    assert all(after[k].owner == bc.Owner("P.work", "w0") and after[k].unmet == before[k].unmet for k in group)
    assert len(handed.events) == 3 and all(e.tag == "HandoffPurpose" for e in handed.events)
    for event in handed.events:
        assert event.value.source == bc.Owner("P.units", "initial")
        assert event.value.destination == bc.Owner("P.work", "w0")
        assert event.value.before == event.value.after == group
    assert not bc.evaluate_observation_step(e0.observation_contract, state.evidence.observation_trace,
        handed.state.evidence.observation_trace, handed.events).violations
    assert not bc.evaluate_observations(e0.observation_contract, handed.state.evidence.observation_trace).violations
    # A deleted row must remain deleted so independent checking can see it.
    missing = replace(handed.state, core=replace(handed.state.core, p=replace(handed.state.core.p,
                       conditions=tuple(c for c in handed.state.core.p.conditions if c.key != key))))
    assert not any(c.key == key for c in env.step(missing, Action("Wait"), window).state.core.p.conditions)
    graph = explore(Scenario("CONNECT-handoff", e0, 50, state, Cut("K-purpose", frozenset((
        "PrepareOne", "ClaimStart", "ResolveWork", "Stop", "Release")), ("subsequent work",))))
    assert graph.complete and len(graph.states) <= 50
    with capsys.disabled():
        print(f"\nCONNECT-handoff: states={len(graph.states)} edges={len(graph.edges)} seconds={graph.elapsed_seconds:.6f}")


def test_all_remaining_interval_tags_cross_the_environment_boundary(capsys):
    bc = observation_check
    interval = Interval("run-0", "M", 0, 2, True, False)
    request = IntervalRequest("k-live", PlanRef("future-k", "k"), "route-live", "measure-live",
                              interval, Contract("model.measure", "1"), Contract("model.clock", "1"),
                              interval_cells(interval, (0, 1, 2, 3)))
    tags = ("RouteApplied", "MeasurementStarted", "Monitored", "Measured", "MeasurementEnded")
    occurrences = tuple(IntervalOccurrence("ei-" + str(i), IntervalFact(tag, request.id, request.route_epoch,
                        Reading("run-0", "M", 0), request.cells if tag in ("Monitored", "Measured") else frozenset(),
                        None, obj(transport=tag))) for i, tag in enumerate(tags))
    e0 = E0(intervals=(request,), interval_occurrences=occurrences)
    assert e0.observation_contract.intervals[0].point == request.point
    env, window = Environment(e0), CorrectWindow(e0)
    state = env.step(env.initial(), Action("RequestInterval", (request.id,)), window).state
    for occurrence in occurrences:
        step = env.step(state, Action("IntervalEvent", (occurrence.id,)), window)
        assert tuple(e.tag for e in step.events) == (occurrence.event.kind,)
        assert not bc.evaluate_observation_step(e0.observation_contract, state.evidence.observation_trace,
                                               step.state.evidence.observation_trace, step.events).violations
        state = step.state
    # Actual order is retained; five! orders are explored, not normalized away.
    graph = explore(Scenario("CONNECT-EI-five", e0, 2000, cut=Cut("K-EI", untested=("k/Support semantics",))))
    assert graph.complete and len(graph.states) <= 2000
    with capsys.disabled():
        print(f"\nCONNECT-EI-five: states={len(graph.states)} edges={len(graph.edges)} seconds={graph.elapsed_seconds:.6f}")


def test_actual_acquisition_verification_and_adoption_ports_cross_all_boundaries(capsys):
    from fb_machine import (AcquisitionIntent, AdoptionIntent, CausalPort, Certificate, CertificatePortEvent,
                            FieldRole, ReadContents, Source, TypedReference, UpdateTarget, VerificationReply,
                            clock_reading_record, digest)
    bc = observation_check
    base = publication()
    process, reader, request = (PlanRef("initial", s) for s in ("process", "reader", "request"))
    g = PlanRef("g-unit", "g")
    target = UpdateTarget(request, process, frozenset(), request)
    result = obj(actual_port_result="symbolic success")
    target_reads = ReadContents(frozenset((request, process)))
    evidence_closure = frozenset((request, process, reader))
    certificate = Certificate("model-issuer", target, reader, target_reads, NumericalView(),
                              evidence_closure, frozenset((request, process, reader, g)), "model-registry",
                              Contract("model-checker", "1"), digest(result))
    reply = VerificationReply("Success", target, reader, target_reads, NumericalView(), evidence_closure,
                              certificate.check_view, certificate.registry, certificate.checker,
                              result, (), frozenset(), certificate)
    wv = replace(base.plans[0].works[0], work_id="wv", purpose="verification", stage="Wv",
                 method=Contract("model.verify", "1"), need=(("think", 1),), request=request,
                 args=obj(target=target, check_view=certificate.check_view, registry=certificate.registry,
                          checker=certificate.checker), input_points=evidence_closure,
                 required=frozenset((g, request, reader, process)))
    # MODEL completed carrier; its result field is resolved by the real prepare
    # operation. No expected CID or target payload is computed ahead of time.
    completed = replace(base.plans[0].records[2], content=obj(result=process),
                        references=(TypedReference("PATH-COMPLETE", ("result",), process, "UE", "complete"),))
    initial = replace(base.plans[0], records=(*base.plans[0].records[:2], completed), works=())
    clock = PlanRef("g-unit", "clock")
    clock_record = clock_reading_record("clock", PlanRef("clock-source", "source"), Source("acquisition_clock", "i0"))
    g_record = RecordPlan("g", Contract("content_acquired", "1"), "Event",
                         obj(origin=reader, contents=(process,), clock=clock),
                         (TypedReference("PATH-ACQUIRE", ("origin",), reader, "UE", "acquire"),
                          TypedReference("PATH-ACQUIRE", ("contents", 0), process, "UE", "acquire"),
                          TypedReference("PATH-ACQUIRE", ("clock",), clock, "UE", "acquire")))
    g_plan = AllowedPlan("g-unit", "O-08", ("i0",), (clock_record, g_record), (wv,), (Guard("acquired", "i0"),))
    a_record = RecordPlan("a", Contract("knowledge_adopted", "1"), "Event",
                         obj(origin=reader, completion=request, previous=None),
                         (TypedReference("PATH-ADOPT", ("origin",), reader, "UE", "adopt"),
                          TypedReference("PATH-ADOPT", ("completion",), request, "UE", "adopt")), frozenset((g,)))
    a_plan = AllowedPlan("a-unit", "O-09.b", ("a0",), (a_record,), operation="Adopt")
    st_plan = AllowedPlan("st-unit", "O-09.b", ("a0-stale",), (), operation="Adopt")
    e0 = _t9_clock_source_e0(replace(base, plans=(initial, g_plan, a_plan, st_plan),
                 programs=(Program("wv", (Outcome(OutcomeKind.RETURNED, reply),), True,
                                   certificate_events=(CertificatePortEvent(0, certificate),)),),
                 acquisitions=(AcquisitionIntent("i0", reader, frozenset((process,)), request, frozenset(), record=g),),
                 adoptions=(AdoptionIntent("a0", reader, request, process, None, "wv", ("i0",), "a-unit", "st-unit"),),
                 field_roles=base.field_roles + (FieldRole(completed.contract, "PATH-COMPLETE", ("result",), "UE", "complete"),),
                 causal_ports=(CausalPort(bc.SlotKey("g-unit", "g"), frozenset((reader, process, request))),
                               CausalPort(bc.SlotKey("a-unit", "a"), frozenset((g, request)))),
                 receipt_kinds=((0, "Boot"), (1, "WorkFinished"))))
    # All declarations and ACTUAL port scripts above are fixed before I0.
    env, window = Environment(e0), CorrectWindow(e0)
    state = env.initial()
    observed = []

    def take(action):
        nonlocal state
        before = state
        step = env.step(before, action, window)
        assert not bc.validate_observation_boundary(e0.observation_contract,
                    step.state.evidence.observation_trace, step.events).violations
        state = step.state
        observed.extend(step.events)
        return step

    def save(unit, slots):
        for slot in slots:
            for operation in ("PrepareReceipt" if unit.startswith("receipt/") else "PrepareOne",
                              "PutBody", "AddEntry", "ConfirmWrite", "CompleteWrite"):
                take(Action(operation, (unit, slot)))

    take(Action("Post", ("boot",)))
    take(Action("Accept", (state.core.h.queue[0],)))
    take(Action("HostAck", (e0.run, 0)))
    save(receipt_unit_id(e0.run, 0), ("boot", "declaration"))
    take(Action("PublishUnit", ("initial",)))
    save("initial", ("process", "reader", "request"))
    take(Action("PublishUnit", ("clock-source",)))
    save("clock-source", ("source",))
    actual_acquire = take(Action("Acquire", ("i0",)))
    assert actual_acquire.events[0].tag == "Acquire" and actual_acquire.events[0].value.record is None
    take(Action("PublishUnit", ("g-unit",)))
    save("g-unit", ("clock", "g"))
    for action in (Action("ResolveWork", ("wv",)), Action("ClaimStart", ("wv",)),
                   Action("Launch", ("wv",)), Action("EnterWorker", ("wv:wrapper:0",)),
                   Action("WorkerStep", ("wv",)), Action("Deliver", ("report:wv:0",))):
        take(action)
    take(Action("Accept", (state.core.h.queue[0],)))
    take(Action("HostAck", (e0.run, 1)))
    save(receipt_unit_id(e0.run, 1), ("receipt",))
    ready = state
    take(Action("Adopt", ("a0",)))
    save("a-unit", ("a",))
    by_tag = {e.tag: e for e in observed}
    required = {"Acquire", "VerifyCall", "VerifyReply", "CertificateIssued", "ReserveAdoption", "Adopt", "ReleaseAdoption"}
    assert required <= by_tag.keys()
    adopted = by_tag["Adopt"].value
    assert adopted.record in frozenset(e.point for e in state.core.e)
    assert by_tag["VerifyReply"].value.reply.certificate == by_tag["CertificateIssued"].value.certificate
    assert by_tag["Acquire"].key in adopted.acquisitions
    assert not state.core.p.adoption_reservations
    # Transport only: actual causal paths include G, with no visible-set shortcut.
    g_point = next(e.value.prepared.point for e in state.evidence.observation_trace.events
                   if e.tag == "FirstPrepare" and e.key == bc.SlotKey("g-unit", "g"))
    assert g_point in adopted.actual_ancestors and adopted.causal_dag == state.evidence.ea.causal_nodes
    graph = explore(Scenario("CONNECT-adoption", e0, 5000, ready,
                    Cut("K-adopt", frozenset(("RecognizeTerminal",)), ("T/V semantics and F-a certification",))))
    assert graph.complete and len(graph.states) <= 5000
    assert any(e.tag == "Adopt" for edge in graph.edges for e in edge.actual_events)
    with capsys.disabled():
        print(f"\nCONNECT-adoption: states={len(graph.states)} edges={len(graph.edges)} seconds={graph.elapsed_seconds:.6f}")
        evaluation = bc.evaluate_observations(e0.observation_contract, state.evidence.observation_trace)
        print(f"T7-G-adoption: INV-9.a={tuple(v for v in evaluation.violations if v.row == 'INV-9.a')} "
              f"limitations={tuple(l for l in evaluation.limitations if l[0] in ('INV-2.b', 'INV-9.a'))}")


@pytest.mark.parametrize("rank", (0, 7))
def test_interval_undertaking_observes_full_actual_host_custody_before_publish(rank):
    from fb_machine import declare_observation_e0
    bc = observation_check
    interval = Interval("run-0", "M", 0, 2, True, False)
    request = IntervalRequest("pending-k", PlanRef("unissued-k", "k"), "route-pending", "measure-pending",
                              interval, Contract("model.measure", "1"), Contract("model.clock", "1"),
                              interval_cells(interval, (0, 1, 2, 3)))
    key = bc.IntervalKey(request.id, request.route_epoch, request.interval.run)
    slot = bc.SlotKey("unissued-k", "k")
    conditions = tuple(bc.CompletionBinding(bc.CompletionKey("O-04", ("route-pending", request.id), kind, target),
                         "IntervalRequest", key, (slot,) if kind == "save" else (), bc.Owner("H", request.id))
                       for kind, target in (("save", slot), ("handle", bc.WorkKey(request.work))))
    # The independent requirements are fixed before I0. No k Publish/Point is
    # manufactured to make an undertaking observable (paper 629,1205,1207).
    base = E0(intervals=(request,), postings=(Posting("clock-reading", received(), rank),))
    contract = replace(declare_observation_e0(base), completions=conditions)
    e0 = replace(base, observation_declarations=contract)
    env, window = Environment(e0), CorrectWindow(e0)
    initial = env.initial()
    assert not initial.core.h.interval_requests
    assert not any(e.tag == "IntervalUndertaken" for e in initial.evidence.observation_trace.events)
    assert all(bc.completion_occurred(c, contract, initial.evidence.observation_trace) is False for c in conditions)
    before = env.step(initial, Action("Post", ("clock-reading",)), window).state
    step = env.step(before, Action("RequestInterval", (request.id,)), window)
    event, = step.events
    assert event == bc.ObservationEvent("IntervalUndertaken", key,
                       bc.IntervalUndertaken(step.state.core.h.interval_requests[0], bc.Owner("H", request.id),
                                            before.core.h.reading))
    assert event.value.request == request and event.value.request.point == request.point
    assert event.value.reading.rank == rank
    assert not step.state.core.p.units and not step.state.core.c and not step.state.core.e
    assert step.state.evidence.observation_trace.events == before.evidence.observation_trace.events + step.events
    assert all(bc.completion_occurred(c, contract, step.state.evidence.observation_trace) is True for c in conditions)
    assert {c.key for c in step.state.core.p.conditions} == {b.key for b in conditions}
    assert all(c.owner == bc.Owner("H", request.id) and c.unmet == frozenset((c.key,))
               for c in step.state.core.p.conditions if c.key in {b.key for b in conditions})
    result = bc.evaluate_observation_step(contract, before.evidence.observation_trace,
                     step.state.evidence.observation_trace, step.events, before_state=before, after_state=step.state)
    assert not result.boundary.violations and not result.violations
    # Request retention is one occurrence, not an E0/measurement/Wait stamp.
    waited = env.step(step.state, Action("Wait"), window)
    assert not waited.events and waited.state.evidence.observation_trace.events == step.state.evidence.observation_trace.events
    assert Action("RequestInterval", (request.id,)) not in env.actions(step.state)


# Turn 5 implementation-owned boundary integration; no SC/F-a validity claim.
def _t5_save(env, window, state, unit, slots):
    for slot in slots:
        for operation in ("PrepareReceipt" if unit.startswith("receipt/") else "PrepareOne",
                          "PutBody", "AddEntry", "ConfirmWrite", "CompleteWrite"):
            state = env.step(state, Action(operation, (unit, slot)), window).state
    return state


def _t5_accept_and_save(env, window, state):
    envelope = state.core.h.queue[0]
    state = env.step(state, Action("Accept", (envelope,)), window).state
    unit = next(r.unit for r in state.core.p.receipts if r.envelope == envelope)
    state = env.step(state, Action("HostAck", envelope.key), window).state
    return _t5_save(env, window, state, unit.id, tuple(s.plan.slot for s in unit.slots))


def test_default_reference_declaration_retains_wildcard_rules_and_prepared_q_elements():
    from fb_machine import TypedReference, declare_observation_e0
    bc = observation_check
    base = publication()
    process, reader = PlanRef("initial", "process"), PlanRef("initial", "reader")
    refs = (TypedReference("PATH-Q0", ("origin",), reader, "UE", "numerical"),
            TypedReference("PATH-Q0", ("args", "model"), process, "UE", "numerical"),
            TypedReference("PATH-Q0", ("inputs", 0), reader, "UE", "numerical"),
            TypedReference("PATH-Q0", ("inputs", 1), process, "UE", "numerical"))
    q = RecordPlan("request", Contract("computation_requested", "1"), "Event",
                   obj(origin=reader, args=obj(model=process, previous_result=None),
                       inputs=(reader, process), algorithm_draws=()), refs)
    e0 = replace(base, plans=(replace(base.plans[0], records=(*base.plans[0].records[:2], q)),))
    declared = declare_observation_e0(e0)
    assert len(declared.references) == len(e0.field_roles)
    for role in e0.field_roles:
        assert bc.ReferenceBinding(role.record_contract, role.path_id, role.path, role.role, role.use,
                    "PrepareOne", "unsupported" if role.path_id == "PATH-QOBS" else "direct") in declared.references
    state = boundary_state(e0, published=True)
    prepared = next(e.value.prepared for e in state.evidence.observation_trace.events
                    if e.tag == "FirstPrepare" and e.key == bc.SlotKey("initial", "request"))
    inputs = prepared.record.content.get("inputs")
    actual_refs = tuple(r for r in prepared.record.references if r.path[:1] == ("inputs",))
    assert tuple(r.path for r in actual_refs) == (("inputs", 0), ("inputs", 1))
    assert tuple(r.ref for r in actual_refs) == inputs and all(r.role == "UE" for r in actual_refs)
    assert not bc.evaluate_observations(declared, state.evidence.observation_trace).violations


@pytest.mark.parametrize("order", (("a", "b"), ("b", "a")))
def test_receipt_source_alias_uses_actual_provenance_and_full_event_without_predicting_order(order):
    from fb_machine import View, declare_observation_e0
    bc = observation_check
    base = publication()
    event_a, event_b = received(b"a"), received(b"b")
    a = bc.ReceiptSource("logical-a", "upstream", event_a, run=base.run)
    b = bc.ReceiptSource("logical-b", "upstream", event_b, run=base.run)
    # Same source, different full Events. Acceptance numbers are assigned only
    # by the two possible actual Post orders; E0 does not predict either one.
    plan = replace(base.plans[0], guards=base.plans[0].guards +
                   (Guard("saved", PlanRef(a.unit, a.slot)), Guard("saved", PlanRef(b.unit, b.slot))))
    e0 = replace(base, plans=(plan,), postings=base.postings +
                 (Posting("a", event_a, 1, source="upstream"), Posting("b", event_b, 1, source="upstream")),
                 receipt_kinds=((0, "Boot"), (1, "Received"), (2, "Received")))
    contract = replace(declare_observation_e0(e0), receipt_sources=(a, b))
    e0 = replace(e0, observation_declarations=contract)
    env, window = Environment(e0), CorrectWindow(e0)
    state = boundary_state(e0)
    assert Action("PublishUnit", ("initial",)) not in window.enabled(View(state.core, state.controls, state.evidence))
    for source_id in order:
        state = env.step(state, Action("Post", (source_id,)), window).state
        state = _t5_accept_and_save(env, window, state)
    points = {}
    for alias in (a, b):
        original, slot = bc.resolve_receipt_source(contract, state.evidence.observation_trace, alias)
        assert original.source == alias.source and original.event == alias.event
        assert original.number == 1 + order.index("a" if alias is a else "b")
        points[alias.unit] = bc.declaration_value(contract, state.evidence.observation_trace, PlanRef(alias.unit, alias.slot))
        assert points[alias.unit] in {e.point for e in state.core.e}
    assert len(set(points.values())) == 2
    # Exercise the window's independent resolution through the public guard.
    published = env.step(state, Action("PublishUnit", ("initial",)), window)
    assert any(e.tag == "Publish" for e in published.events)
    assert not bc.evaluate_observations(contract, published.state.evidence.observation_trace).violations


def test_receipt_source_alias_becomes_unconnected_on_multiple_full_matching_posts():
    from fb_machine import Disabled, declare_observation_e0
    bc = observation_check
    base = publication()
    event = received(b"duplicate")
    alias = bc.ReceiptSource("logical-duplicate", "shared-delivery", event, run=base.run)
    plan = replace(base.plans[0], guards=base.plans[0].guards + (Guard("saved", PlanRef(alias.unit, alias.slot)),))
    e0 = replace(base, plans=(plan,), postings=base.postings +
                 (Posting("first-copy", event, 1, source=alias.source), Posting("second-copy", event, 1, source=alias.source)),
                 receipt_kinds=((0, "Boot"), (1, "Received"), (2, "Received")))
    contract = replace(declare_observation_e0(e0), receipt_sources=(alias,))
    e0 = replace(e0, observation_declarations=contract)
    env, window = Environment(e0), CorrectWindow(e0)
    state = boundary_state(e0)
    state = _t5_accept_and_save(env, window, env.step(state, Action("Post", ("first-copy",)), window).state)
    assert bc.declaration_value(contract, state.evidence.observation_trace, PlanRef(alias.unit, alias.slot))
    state = env.step(state, Action("Post", ("second-copy",)), window).state
    with pytest.raises(bc.UnresolvedDeclaration):
        bc.resolve_receipt_source(contract, state.evidence.observation_trace, alias)
    with pytest.raises(Disabled, match="unique actual Post"):
        env.step(state, Action("PublishUnit", ("initial",)), window)


@pytest.mark.parametrize("kind,field", (("started_clock", "started"), ("finished_clock", "finished")))
def test_clock_source_publication_uses_actual_generation_instead_of_later_delivery_or_creation(kind, field):
    from fb_machine import Source, TypedReference, clock_reading_record
    bc = observation_check
    base = publication()
    process, reader = PlanRef("initial", "process"), PlanRef("initial", "reader")
    q = RecordPlan("request", Contract("computation_requested", "1"), "Event",
                   obj(origin=reader, method=Contract("finite_update", "1"),
                       args=obj(model=process, previous_result=None), inputs=(reader, process), algorithm_draws=()),
                   (TypedReference("PATH-Q0", ("origin",), reader, "UE", "numerical"),
                    TypedReference("PATH-Q0", ("args", "model"), process, "UE", "numerical"),
                    TypedReference("PATH-Q0", ("inputs", 0), reader, "UE", "numerical"),
                    TypedReference("PATH-Q0", ("inputs", 1), process, "UE", "numerical")))
    wr = replace(base.plans[0].works[0], stage="Wr", purpose="belief_update",
                 method=Contract("finite_update", "1"), output_contract=Contract("finite_update_result", "1"),
                 args=obj(model=process, previous_result=None), numerical_view=NumericalView(frozenset((reader, process))))
    initial = replace(base.plans[0], records=(*base.plans[0].records[:2], q), works=(wr,))
    record = clock_reading_record("clock", PlanRef("clock-source", "source"), Source(kind, "w0"))
    clock_plan = AllowedPlan("clock-values", "O-05", ("w0", kind), (record,), guards=(Guard("first", "w0"),))
    e0 = _t9_clock_source_e0(replace(base, plans=(initial, clock_plan),
                 postings=base.postings + (Posting("later-clock", received(), 100),),
                 programs=(Program("w0", (Outcome(OutcomeKind.RETURNED, obj(variant="Success")),), True),),
                 receipt_kinds=((0, "Boot"), (1, "Received"), (2, "WorkFinished"))))
    env, window = Environment(e0), CorrectWindow(e0)
    state = boundary_state(e0, published=True)
    state = _t9_save_clock_source(env, window, state)
    for action in (Action("ClaimStart", ("w0",)), Action("Launch", ("w0",)),
                   Action("EnterWorker", ("w0:wrapper:0",)), Action("WorkerStep", ("w0",)),
                   Action("Post", ("later-clock",))):
        state = env.step(state, action, window).state
    state = _t5_accept_and_save(env, window, state)
    state = _t5_accept_and_save(env, window, env.step(state, Action("Deliver", ("report:w0:0",)), window).state)
    generation = next(f.value for f in state.evidence.ew.events if f.kind == "Returned")
    delivered = next(d for d in state.core.network.deliveries if d.message == "report:w0:0")
    assert delivered.envelope.source == generation.provenance == "worker:w0"
    expected = getattr(generation, field)
    assert expected.rank < state.core.h.reading.rank == 100
    before_result = bc.evaluate_observations(e0.observation_contract, state.evidence.observation_trace)
    assert not before_result.violations, (before_result.violations, before_result.limitations)
    published = env.step(state, Action("PublishUnit", ("clock-values",)), window)
    actual = next(e.value.plan.records[0].content.get("reading") for e in published.events if e.tag == "Publish")
    assert actual == expected == bc.declaration_value(e0.observation_contract, state.evidence.observation_trace, Source(kind, "w0"))
    saved = _t5_save(env, window, published.state, "clock-values", ("clock",))
    assert not bc.evaluate_observations(e0.observation_contract, saved.evidence.observation_trace).violations


def test_finished_clock_source_does_not_manufacture_worker_generation_from_host_unknown():
    from fb_machine import Source, MissingContract, clock_reading_record
    base = unknown_work()
    record = clock_reading_record("clock", PlanRef("clock-source", "source"), Source("finished_clock", "w0"))
    e0 = _t9_clock_source_e0(replace(base, plans=base.plans + (AllowedPlan("unknown-clock", "O-05", ("w0",), (record,),
                                                                           guards=(Guard("first", "w0"),)),)))
    env, window = Environment(e0), CorrectWindow(e0)
    state = unknown_receipt_prefix(e0)
    state = _t9_save_clock_source(env, window, state)
    state = _t5_accept_and_save(env, window, state)
    with pytest.raises(MissingContract, match="host Unknown has no worker generation clock"):
        env.step(state, Action("PublishUnit", ("unknown-clock",)), window)
    with pytest.raises(observation_check.UnresolvedDeclaration):
        observation_check.declaration_value(e0.observation_contract, state.evidence.observation_trace,
                                            Source("finished_clock", "w0"))


def test_planned_interval_evidence_crosses_actual_ei_boundary_with_a_resolved_point():
    from fb_machine import declare_observation_e0
    bc = observation_check
    interval = Interval("run-0", "M", 0, 2, True, False)
    request = IntervalRequest("k-proof", PlanRef("future-k", "k"), "route-proof", "measure-proof", interval,
                              Contract("model.measure", "1"), Contract("model.clock", "1"),
                              interval_cells(interval, (0, 1, 2, 3)))
    point = PlanRef("ei-proof", "monitor")
    record = RecordPlan("monitor", Contract("model.interval_evidence", "1"), "Event", obj(kind="Monitored", value=1))
    plan = AllowedPlan("ei-proof", "O-04", (request.id,), (record,), guards=(Guard("interval_intent", request.id),))
    payload = bc.IntervalObserved(Reading("run-0", "M", 0), interval, request.cells, request.work, point, record.content)
    occurrence = IntervalOccurrence("monitor", IntervalFact("Monitored", request.id, request.route_epoch,
                                      payload.reading, request.cells, point, payload.content))
    e0 = E0(intervals=(request,), plans=(plan,), interval_occurrences=(occurrence,))
    binding = bc.IntervalEvidenceBinding(point, bc.IntervalKey(request.id, request.route_epoch, interval.run),
                                         "Monitored", payload, record)
    contract = replace(declare_observation_e0(e0), interval_evidence=(binding,))
    e0 = replace(e0, observation_declarations=contract)
    env, window = Environment(e0), CorrectWindow(e0)
    state = env.step(env.initial(), Action("RequestInterval", (request.id,)), window).state
    assert Action("IntervalEvent", (occurrence.id,)) not in env.actions(state)
    state = env.step(state, Action("PublishUnit", (plan.unit,)), window).state
    state = _t5_save(env, window, state, plan.unit, (record.slot,))
    actual = env.step(state, Action("IntervalEvent", (occurrence.id,)), window)
    event, = actual.events
    resolved = bc.resolve_interval_evidence(contract, state.evidence.observation_trace, binding)
    assert event.value == resolved.event and event.value.evidence == resolved.point
    assert actual.state.evidence.ei.events[-1].evidence_point == resolved.point
    assert binding.point == point and binding.record == record
    assert not bc.evaluate_observations(contract, actual.state.evidence.observation_trace).violations


def test_artifact_issuance_and_later_check_resolve_only_actual_port_inputs_at_each_edge():
    from fb_machine import ProgramPortEvent, declare_observation_e0
    bc = observation_check
    base = publication()
    request, problem, draw = PlanRef("initial", "request"), PlanRef("initial", "process"), PlanRef("later-draw", "df")
    artifact = bc.ArtifactValue(Contract("model.artifact", "1"), Contract("model.compiler", "1"),
                                "view", "registry", obj(request=request), (), obj(value=1))
    checked = bc.ArtifactChecked(artifact, "Selected", request, problem, draw, frozenset((request, draw)))
    # Expectations and actual port script are independent declarations fixed
    # before I0; no actual output is generated by a checker/resolve_* call.
    expected = bc.ArtifactPortBinding("w0", artifact.contract, artifact.compiler, "view", "registry",
                                      obj(request=request), (artifact,), (checked,))
    port = Program("w0", (Outcome(OutcomeKind.RETURNED, obj(variant="FProblem")),
                          Outcome(OutcomeKind.RETURNED, obj(variant="Selected"))), True,
                   port_events=(ProgramPortEvent(0, "ArtifactIssued", bc.WorkKey("w0"), artifact),
                                ProgramPortEvent(1, "ArtifactChecked", bc.WorkKey("w0"), checked)))
    later = AllowedPlan("later-draw", "O-11", ("transport",),
                        (RecordPlan("df", Contract("model.draw_value", "1"), "Event", obj(value=2)),))
    e0 = replace(base, plans=base.plans + (later,), programs=(port,),
                 receipt_kinds=((0, "Boot"), (1, "WorkFinished")))
    contract = replace(declare_observation_e0(e0), artifacts=(expected,))
    e0 = replace(e0, observation_declarations=contract)
    env, window = Environment(e0), CorrectWindow(e0)
    state = boundary_state(e0, published=True)
    for action in (Action("ClaimStart", ("w0",)), Action("Launch", ("w0",)), Action("EnterWorker", ("w0:wrapper:0",))):
        state = env.step(state, action, window).state
    issued = env.step(state, Action("WorkerStep", ("w0",)), window)
    value = next(e.value.artifact for e in issued.events if e.tag == "ArtifactIssued")
    normative = bc.resolve_artifact_port(contract, state.evidence.observation_trace, "w0")
    assert value in normative.possible_returns and normative.checked_returns[0].draw == draw
    with pytest.raises(bc.UnresolvedDeclaration):
        bc.resolve_artifact_port(contract, state.evidence.observation_trace, "w0", checked=True)
    state = env.step(issued.state, Action("PublishUnit", (later.unit,)), window).state
    state = _t5_save(env, window, state, later.unit, ("df",))
    normative_check = bc.resolve_artifact_port(contract, state.evidence.observation_trace, "w0", checked=True)
    checked_step = env.step(state, Action("WorkerStep", ("w0",)), window)
    observed = next(e.value for e in checked_step.events if e.tag == "ArtifactChecked")
    assert observed in normative_check.checked_returns
    assert observed.draw in {e.point for e in state.core.e}
    assert port.port_events[1].value.draw == draw  # E0 actual script stayed frozen.
    assert not bc.validate_observation_boundary(contract, checked_step.state.evidence.observation_trace, checked_step.events).violations


@pytest.mark.parametrize("stage,event_kind", (("Wr", "WorkFinished"), ("D", "DrawReturned")))
def test_report_delivery_preserves_occurrence_id_and_actual_producer_for_each_family(stage, event_kind):
    bc = observation_check
    base = publication()
    descriptor = replace(base.plans[0].works[0], stage=stage)
    e0 = replace(base, plans=(replace(base.plans[0], works=(descriptor,)),),
                 programs=(Program("w0", (Outcome(OutcomeKind.RETURNED, obj(variant="Value", value=1)),), True),),
                 receipt_kinds=((0, "Boot"), (1, event_kind)))
    env, window = Environment(e0), CorrectWindow(e0)
    state = boundary_state(e0, published=True)
    for action in (Action("ClaimStart", ("w0",)), Action("Launch", ("w0",)),
                   Action("EnterWorker", ("w0:wrapper:0",)), Action("WorkerStep", ("w0",))):
        state = env.step(state, action, window).state
    message = state.core.network.messages[0]
    step = env.step(state, Action("Deliver", (message.id,)), window)
    post, = step.events
    envelope = post.value.envelope
    assert message.id == "report:w0:0" and message.id != message.generation.provenance
    assert envelope.source == message.generation.provenance == dict(e0.observation_contract.generation_sources)["w0"]
    assert envelope.event == message.event and envelope.event.kind == event_kind
    assert step.state.core.network.deliveries[-1].message == message.id
    assert step.state.core.network.deliveries[-1].envelope == envelope
    assert not bc.evaluate_observation_step(e0.observation_contract, state.evidence.observation_trace,
                                           step.state.evidence.observation_trace, step.events).violations


def test_host_unknown_delivery_keeps_occurrence_id_and_host_provenance_separate():
    bc = observation_check
    e0 = unknown_work()
    state = unknown_receipt_prefix(e0)
    link = state.core.network.deliveries[-1]
    message = next(m for m in state.core.network.messages if m.id == link.message)
    notice = next(n for n in e0.unknown_notices if "host-unknown:" + n.id == message.id)
    assert link.envelope.source == message.generation.provenance == "host:" + notice.id
    assert link.message == "host-unknown:" + notice.id and link.message != link.envelope.source
    observation = next(e for e in state.evidence.observation_trace.events if e.tag == "HostUnknown")
    assert observation.value.envelope == link.envelope
    assert e0.observation_contract.host_unknowns[0].source == link.envelope.source
    assert not bc.evaluate_observations(e0.observation_contract, state.evidence.observation_trace).violations


def test_acquisition_clock_source_waits_for_actual_acquire_and_keeps_its_reading():
    from fb_machine import AcquisitionIntent, Disabled, Source, clock_reading_record
    base = publication()
    reader, process, request = (PlanRef("initial", slot) for slot in ("reader", "process", "request"))
    record = clock_reading_record("clock", PlanRef("clock-source", "source"), Source("acquisition_clock", "i0"))
    plan = AllowedPlan("clock-evidence", "O-08", ("i0",), (record,))
    e0 = _t9_clock_source_e0(replace(base, plans=base.plans + (plan,),
                 acquisitions=(AcquisitionIntent("i0", reader, frozenset((process,)), request, frozenset()),),
                 postings=base.postings + (Posting("advance", received(), 71),)))
    env, window = Environment(e0), CorrectWindow(e0)
    state = boundary_state(e0, published=True)
    state = _t9_save_clock_source(env, window, state)
    with pytest.raises(Disabled, match="no actual acquisition"):
        env.step(state, Action("PublishUnit", (plan.unit,)), window)
    acquired = env.step(state, Action("Acquire", ("i0",)), window)
    reading = acquired.events[0].value.acquisition.reading
    later = env.step(acquired.state, Action("Post", ("advance",)), window).state
    published = env.step(later, Action("PublishUnit", (plan.unit,)), window)
    assert reading.rank < later.core.h.reading.rank
    assert published.events[0].value.plan.records[0].content.get("reading") == reading


def test_wv_and_adoption_declarations_keep_planrefs_and_the_public_call_id_before_i0():
    from fb_machine import AdoptionIntent, UpdateTarget, declare_observation_e0, verification_call_id
    bc = observation_check
    base = publication()
    process, reader, request = (PlanRef("initial", s) for s in ("process", "reader", "request"))
    target = UpdateTarget(request, process, frozenset(), request)
    closure = frozenset((reader, request, process))
    args = obj(target=target, check_view=closure, registry="finite-registry", checker=Contract("model.verify", "1"))
    wv = replace(base.plans[0].works[0], stage="Wv", args=args, input_points=closure,
                 numerical_view=NumericalView(frozenset((reader,))))
    adoption = AdoptionIntent("a0", reader, request, process, None, "w0", ("i0",), "a-unit", "stale-unit")
    e0 = replace(base, plans=(replace(base.plans[0], works=(wv,)),), adoptions=(adoption,))
    contract = declare_observation_e0(e0)
    assert verification_call_id() == "call/0" and verification_call_id(3) == "call/3"
    assert contract.verifications == (bc.VerificationBinding(bc.VerificationKey("w0", "call/0"), target,
            reader, wv.numerical_view, closure, closure, "finite-registry", Contract("model.verify", "1"), args),)
    assert contract.adoptions == (bc.AdoptionBinding(bc.IntentKey(reader, "a0"), request, process, None,
            bc.VerificationKey("w0", "call/0"), (bc.IntentKey(reader, "i0"),)),)
    assert {p.unit for p in e0.publication_plans} == {"initial", "terminal:w0", "verification:w0"}
    assert contract.plans == e0.publication_plans  # T/V declarations precede I0.
    # Absence is kept explicit; neither E0 nor a later port response repairs args.
    missing = replace(wv, args=obj(target=target, check_view=closure))
    assert not declare_observation_e0(replace(e0, plans=(replace(base.plans[0], works=(missing,)),))).verifications


@pytest.mark.parametrize("verification", (False, True), ids=("Failure-T", "definite-Wv-T-V"))
def test_terminal_publish_has_predeclared_templates_and_independent_inv_2_b(verification, capsys):
    from fb_machine import Disabled, Point, ReadContents, Source, UpdateTarget, VerificationReply
    bc = observation_check
    base = publication()
    process, reader, request = (PlanRef("initial", s) for s in ("process", "reader", "request"))
    closure = frozenset((process, reader, request))
    target = UpdateTarget(request, process, frozenset(), request)
    args = obj(target=target, check_view=closure, registry="model-registry", checker=Contract("model.verify", "1"))
    descriptor = replace(base.plans[0].works[0], stage="Wv" if verification else "Wr",
                         purpose="verification" if verification else "belief_update", need=(("think", 1),),
                         args=args if verification else Object(), input_points=closure)
    reply = VerificationReply("Insufficient", target, reader, ReadContents(frozenset((request, process))),
                              descriptor.numerical_view, closure, closure, "model-registry",
                              Contract("model.verify", "1"), obj(answer="not-certified"), (),
                              frozenset(("proof",)), None)
    outcome = Outcome(OutcomeKind.RETURNED, reply) if verification else Outcome(OutcomeKind.FAILURE, obj(reason="actual-port-failure"))
    e0 = replace(base, plans=(replace(base.plans[0], works=(descriptor,)),),
                 programs=(Program("w0", (outcome,), True),), receipt_kinds=((0, "Boot"), (1, "WorkFinished")))
    contract = e0.observation_contract
    t_promise = next(p for p in e0.publication_plans if p.unit == "terminal:w0")
    assert t_promise in contract.plans
    assert t_promise.records[0].content.get("terminal_kind") == Source("outcome_kind", "w0")
    assert t_promise.records[0].content.get("view") == Source("terminal_view", "w0")
    env, window = Environment(e0), CorrectWindow(e0)
    state = boundary_state(e0, published=True)
    with pytest.raises(Disabled):
        env.step(state, Action("RecognizeTerminal", ("w0",)), window)
    with pytest.raises(Disabled, match="require RecognizeTerminal"):
        env.step(state, Action("PublishUnit", ("terminal:w0",)), window)
    for action in (Action("ClaimStart", ("w0",)), Action("Launch", ("w0",)),
                   Action("EnterWorker", ("w0:wrapper:0",)), Action("WorkerStep", ("w0",)),
                   Action("Deliver", ("report:w0:0",))):
        state = env.step(state, action, window).state
    state = _t5_accept_and_save(env, window, state)
    before = state.evidence.observation_trace
    step = env.step(state, Action("RecognizeTerminal", ("w0",)), window)
    publications = tuple(e for e in step.events if e.tag == "Publish")
    assert tuple(e.key.unit for e in publications) == (("terminal:w0", "verification:w0") if verification else ("terminal:w0",))
    t_record = publications[0].value.plan.records[0]
    generation = next(f.value for f in state.evidence.ew.events if f.kind == "Returned")
    assert frozenset(k for k, _ in t_record.content.items) == frozenset((
        "work", "request", "stage", "first_receipt", "terminal_kind", "returned", "basis", "view"))
    assert t_record.content.get("terminal_kind") == generation.outcome.kind
    assert t_record.content.get("returned") == generation.outcome.content
    assert t_record.content.get("basis") == (None if verification else generation)
    assert t_record.content.get("view") == frozenset(e.point for e in state.core.e)
    saved = step.state
    for issued in publications:
        for record in issued.value.plan.records:
            assert isinstance(record.content.get("first_receipt"), Point)
            assert not any(isinstance(r.ref, Source) for r in record.references)
            assert not any(isinstance(parent, Source) for parent in record.parents)
        saved = _t5_save(env, window, saved, issued.key.unit,
                         tuple(r.slot for r in issued.value.plan.records))
        for record in issued.value.plan.records:
            prepared = next(e.value.prepared for e in saved.evidence.observation_trace.events
                            if e.tag == "FirstPrepare" and e.key == bc.SlotKey(issued.key.unit, record.slot))
            assert all(isinstance(r.ref, Point) for r in prepared.record.references)
            assert all(isinstance(parent, Point) for parent in prepared.parents | prepared.header.parents)
            assert isinstance(prepared.record.content.get("first_receipt"), Point)
            if record.slot == "T":
                assert prepared.record.content.get("request") == generation.request
                assert isinstance(prepared.record.content.get("request"), Point)
    if verification:
        assert publications[1].value.plan.records[0].content.get("reply").response == "Insufficient"
    observed = bc.evaluate_observations(contract, step.state.evidence.observation_trace)
    edge = bc.evaluate_observation_step(contract, before, step.state.evidence.observation_trace,
                                        step.events, before_state=state, after_state=step.state,
                                        action=Action("RecognizeTerminal", ("w0",)))
    with capsys.disabled():
        print(f"\nT7-TERMINAL {'Wv' if verification else 'Failure'}: "
              f"state_violations={tuple(v for v in observed.violations if v.row == 'INV-2.b')} "
              f"step_violations={tuple(v for v in edge.violations if v.row == 'INV-2.b')} "
              f"state_limitations={tuple(l for l in observed.limitations if l[0] == 'INV-2.b')} "
              f"step_limitations={tuple(l for l in edge.limitations if l[0] == 'INV-2.b')}")
    # An unresolved new Source must not masquerade as a passing publication row.
    assert not tuple(v for result in (observed, edge) for v in result.violations if v.row == "INV-2.b")
    assert not tuple(l for result in (observed, edge) for l in result.limitations if l[0] == "INV-2.b"), "Independent Source expansion is not yet connected for T/V"
    assert not bc.evaluate_observations(contract, saved.evidence.observation_trace).violations


@pytest.mark.parametrize("entered", (True, False), ids=("actual-start", "unconfirmed-start"))
def test_host_unknown_terminal_template_preserves_basis_without_worker_return_or_v(entered, capsys):
    from fb_machine import Point, Source, Unavailable
    bc = observation_check
    base = replace(unknown_work(), budget=Budget(uncertain_launches=0 if entered else 1))
    env, window = Environment(base), CorrectWindow(base)
    if entered:
        state = unknown_receipt_prefix(base)
    else:
        state = boundary_state(base, published=True)
        for action in (Action("ClaimStart", ("w0",)), Action("Launch", ("w0",), "uncertain_before"),
                       Action("HostUnknown", ("unknown-0",)), Action("Deliver", ("host-unknown:unknown-0",))):
            state = env.step(state, action, window).state
    state = _t5_accept_and_save(env, window, state)
    published = env.step(state, Action("RecognizeTerminal", ("w0",)), window)
    publications = tuple(e for e in published.events if e.tag == "Publish")
    assert len(publications) == 1 and publications[0].key.unit == "terminal:w0"
    content = publications[0].value.plan.records[0].content
    assert content.get("terminal_kind") == OutcomeKind.UNKNOWN
    assert content.get("basis") == base.unknown_notices[0].basis
    assert frozenset(k for k, _ in content.items) == frozenset((
        "work", "request", "stage", "first_receipt", "terminal_kind", "returned", "basis", "view"))
    generation = next(f.value for f in state.evidence.ew.events if f.kind == "UnknownObserved" and f.key == "w0")
    assert generation.provenance == "host:unknown-0"
    assert generation.finished == Unavailable("host-end-unconfirmed")
    if entered:
        actual_start = next(e.value.started for e in state.evidence.observation_trace.events if e.tag == "EnterBody")
        assert generation.started == actual_start
    else:
        assert generation.started == Unavailable("host-start-unconfirmed")
    assert isinstance(content.get("first_receipt"), Point)
    assert not any(isinstance(r.ref, Source) for r in publications[0].value.plan.records[0].references)
    assert not any(isinstance(p, Source) for p in publications[0].value.plan.records[0].parents)
    assert not any(e.tag in ("WorkerReturn", "VerifyReply", "Stop") for e in published.state.evidence.observation_trace.events)
    saved = _t5_save(env, window, published.state, "terminal:w0", ("T",))
    prepared = next(e.value.prepared for e in saved.evidence.observation_trace.events
                    if e.tag == "FirstPrepare" and e.key == bc.SlotKey("terminal:w0", "T"))
    assert all(isinstance(r.ref, Point) for r in prepared.record.references)
    assert all(isinstance(p, Point) for p in prepared.parents | prepared.header.parents)
    assert isinstance(prepared.record.content.get("request"), Point)
    observed = bc.evaluate_observations(base.observation_contract, published.state.evidence.observation_trace)
    edge = bc.evaluate_observation_step(base.observation_contract, state.evidence.observation_trace,
                published.state.evidence.observation_trace, published.events,
                before_state=state, after_state=published.state, action=Action("RecognizeTerminal", ("w0",)))
    after_save = bc.evaluate_observations(base.observation_contract, saved.evidence.observation_trace)
    with capsys.disabled():
        print(f"\nT8-HOST {'actual-start' if entered else 'unconfirmed-start'}: "
              f"state_violations={observed.violations} step_violations={edge.violations} "
              f"saved_violations={after_save.violations}")
    assert not observed.violations and not edge.violations and not after_save.violations
    assert not tuple(l for result in (observed, edge, after_save) for l in result.limitations if l[0] == "INV-2.b")


def test_cq_clock_readings_use_saved_source_points_and_wr_start_wp_finish():
    from fb_machine import Point, Source, TypedReference, clock_reading_record
    bc = observation_check
    base = publication()
    process, reader, q = (PlanRef("initial", s) for s in ("process", "reader", "request"))
    r, p = PlanRef("clock-source", "result"), PlanRef("clock-source", "proof")
    # v0.12 (11): opaque R/P carriers test structure, not F-a numeric legality.
    wr = replace(base.plans[0].works[0], stage="Wr", purpose="belief_update", need=(("think", 1),))
    wp = replace(wr, work_id="wp", stage="Wp", purpose="proof", required=frozenset((r,)))
    e0 = _t9_clock_source_e0(replace(base, plans=(replace(base.plans[0], works=(wr, wp)),),
        programs=(Program("w0", (Outcome(OutcomeKind.RETURNED, obj(variant="Success", structure_only=True)),), True),
                  Program("wp", (Outcome(OutcomeKind.RETURNED, obj(variant="Success", structure_only=True)),), True)),
        receipt_kinds=((0, "Boot"), (1, "WorkFinished"), (2, "WorkFinished"))))
    carriers = tuple(RecordPlan(slot, Contract("model." + slot, "1"), "Prediction", obj(structure_only=slot))
                     for slot in ("result", "proof"))
    source_plan = replace(e0.plans[-1], records=e0.plans[-1].records + carriers)
    clock_source = PlanRef("clock-source", "source")
    started, finished = PlanRef("cq-clocks", "started"), PlanRef("cq-clocks", "finished")
    cq = RecordPlan("cq", Contract("computation_completed", "1"), "Event",
        obj(request=q, result=r, proofs=(p,), started_clock=started, finished_clock=finished),
        tuple(TypedReference("PATH-COMPLETE", path, ref, "UE", "generation") for path, ref in
              ((('request',), q), (('result',), r), (('proofs', 0), p),
               (('started_clock',), started), (('finished_clock',), finished))))
    clocks = AllowedPlan("cq-clocks", "O-07", ("clock-structure",),
        (clock_reading_record("started", clock_source, Source("started_clock", "w0")),
         clock_reading_record("finished", clock_source, Source("finished_clock", "wp")), cq),
        guards=(Guard("outcome", "w0", ("Success", "Success")),
                Guard("outcome", "wp", ("Success", "Success"))))
    e0 = replace(e0, plans=e0.plans[:-1] + (source_plan, clocks))
    env, window = Environment(e0), CorrectWindow(e0)
    state = boundary_state(e0, published=True)
    state = _t9_save_clock_source(env, window, state)
    state = _t5_save(env, window, state, "clock-source", ("result", "proof"))
    for work in ("w0", "wp"):
        if work == "wp":
            state = env.step(state, Action("ResolveWork", (work,)), window).state
        for action in (Action("ClaimStart", (work,)), Action("Launch", (work,)),
                       Action("EnterWorker", (work + ":wrapper:0",)), Action("WorkerStep", (work,)),
                       Action("Deliver", ("report:" + work + ":0",))):
            state = env.step(state, action, window).state
        state = _t5_accept_and_save(env, window, state)
    state = env.step(state, Action("PublishUnit", ("cq-clocks",)), window).state
    state = _t5_save(env, window, state, "cq-clocks", ("started", "finished", "cq"))
    prepared = {e.key: e.value.prepared for e in state.evidence.observation_trace.events if e.tag == "FirstPrepare"}
    source_point = prepared[bc.SlotKey("clock-source", "source")].point
    generations = {f.key: f.value for f in state.evidence.ew.events if f.kind == "Returned"}
    for slot, expected in (("started", generations["w0"].started), ("finished", generations["wp"].finished)):
        evidence = prepared[bc.SlotKey("cq-clocks", slot)].record
        assert evidence.contract == Contract("clock_reading", "1")
        assert evidence.content == obj(source=source_point, reading=expected)
        assert all(isinstance(ref.ref, Point) for ref in evidence.references)
    completion = prepared[bc.SlotKey("cq-clocks", "cq")].record.content
    assert completion.get("started_clock") == prepared[bc.SlotKey("cq-clocks", "started")].point
    assert completion.get("finished_clock") == prepared[bc.SlotKey("cq-clocks", "finished")].point
    assert not bc.validate_observation_boundary(e0.observation_contract, state.evidence.observation_trace).violations


def test_unavailable_clock_blocks_evidence_cq_and_successor_without_erasing_generation():
    from fb_machine import Disabled, TypedReference, Unavailable, clock_reading_record
    base = unknown_work()
    source = PlanRef("clock-source", "source")
    missing = Unavailable("host-end-unconfirmed")
    with pytest.raises(TypeError, match="requires Reading"):
        clock_reading_record("finished", source, missing)
    # A direct RecordPlan must not bypass the factory's P-08 Reading-only rule.
    clock = RecordPlan("finished", Contract("clock_reading", "1"), "Event",
                      obj(source=source, reading=missing),
                      (TypedReference("A-CLOCK-SOURCE", ("source",), source, "E", "clock_source"),))
    cq = RecordPlan("cq", Contract("computation_completed", "1"), "Event",
                   obj(request=PlanRef("initial", "request"), finished_clock=PlanRef("missing-clock", "finished")))
    successor = replace(base.plans[0].works[0], work_id="success-next", stage="Ep")
    e0 = _t9_clock_source_e0(replace(base, plans=base.plans + (
        AllowedPlan("missing-clock", "O-07", ("P-08",), (clock, cq), (successor,)),)))
    env, window = Environment(e0), CorrectWindow(e0)
    state = unknown_receipt_prefix(e0)
    state = _t9_save_clock_source(env, window, state)
    state = _t5_accept_and_save(env, window, state)
    generation = next(f.value for f in state.evidence.ew.events if f.kind == "UnknownObserved")
    assert generation.finished == missing
    with pytest.raises(Disabled, match="available Reading"):
        env.step(state, Action("PublishUnit", ("missing-clock",)), window)
    assert not any(u.id == "missing-clock" for u in state.core.p.units)
    assert not any(w.descriptor.work_id == "success-next" for w in state.core.p.work)
    for slot in ("finished", "cq"):
        with pytest.raises(Disabled):
            env.step(state, Action("PrepareOne", ("missing-clock", slot)), window)
    assert not any(e.tag == "Publish" and e.key.unit == "missing-clock"
                   for e in state.evidence.observation_trace.events)
    assert not observation_check.evaluate_observations(e0.observation_contract,
                                                       state.evidence.observation_trace).violations


def _t10_same_r_e0(unknown_first):
    from fb_machine import DeliveryBundle, HostNotice, WorkerNotice
    base = unknown_work()
    unknown, value = HostNotice("unknown-0"), WorkerNotice("w0", 0)
    return replace(base, budget=Budget(uncertain_launches=1),
        programs=(Program("w0", (Outcome(OutcomeKind.RETURNED,
                  obj(variant="Success", structure_only=True)),), False),),
        delivery_bundles=(DeliveryBundle("same-r", (unknown, value) if unknown_first else (value, unknown)),),
        receipt_kinds=((0, "Boot"), (1, "WorkFinished"), (2, "WorkFinished")))


@pytest.mark.parametrize("unknown_first", (True, False), ids=("Unknown-first", "value-first"))
@pytest.mark.parametrize("unknown_generated_first", (True, False), ids=("host-created-first", "worker-created-first"))
def test_declared_same_r_delivery_keeps_actual_generation_and_seq_order_through_terminal(
        unknown_first, unknown_generated_first, capsys):
    from time import perf_counter
    from fb_machine import Disabled
    bc = observation_check
    started = perf_counter()
    e0 = _t10_same_r_e0(unknown_first)  # The whole recipe is fixed before I0.
    env, window = Environment(e0), CorrectWindow(e0)
    state = boundary_state(e0, published=True)
    traversed = [state]

    def take(action):
        nonlocal state
        before = state
        step = env.step(before, action, window)
        after = step.state
        edge = bc.evaluate_observation_step(e0.observation_contract,
            before.evidence.observation_trace, after.evidence.observation_trace, step.events,
            before_state=before, after_state=after, action=action)
        result = bc.evaluate_observations(e0.observation_contract, after.evidence.observation_trace)
        assert not edge.violations and not result.violations, (action, edge.violations, result.violations)
        state = after
        traversed.append(state)
        return step

    bundle_action = Action("DeliverBundle", ("same-r",))
    with pytest.raises(Disabled, match="all actual"):
        env.step(state, bundle_action, window)
    take(Action("ClaimStart", ("w0",)))
    take(Action("Launch", ("w0",), "uncertain_after"))  # Actual entry + unknown launch response.
    generation_actions = (Action("HostUnknown", ("unknown-0",)), Action("WorkerStep", ("w0",)))
    if not unknown_generated_first:
        generation_actions = tuple(reversed(generation_actions))
    take(generation_actions[0])
    assert bundle_action not in env.actions(state)
    with pytest.raises(Disabled, match="all actual"):
        env.step(state, bundle_action, window)
    take(generation_actions[1])
    assert bundle_action in env.actions(state)
    for message in state.core.network.messages:
        assert Action("Deliver", (message.id,)) not in env.actions(state)
        with pytest.raises(Disabled, match="declared bundle"):
            env.step(state, Action("Deliver", (message.id,)), window)
    ready = state
    post_step = take(bundle_action)
    # No worker return, clock prediction or save operation is hidden in delivery.
    assert post_step.state.evidence.ew == ready.evidence.ew
    assert post_step.state.core.h.reading == ready.core.h.reading
    assert post_step == Environment(e0).step(ready, bundle_action, CorrectWindow(e0))
    posts = tuple(e.value.envelope for e in post_step.events if e.tag == "Post")
    assert len(posts) == 2 and posts == state.core.h.queue
    assert posts[0].r == posts[1].r == ready.core.h.reading
    assert posts[0].run == posts[1].run == e0.run
    assert posts[1].receipt_seq == posts[0].receipt_seq + 1
    expected = ((OutcomeKind.UNKNOWN, "host:unknown-0"), (OutcomeKind.RETURNED, "worker:w0"))
    if not unknown_first:
        expected = tuple(reversed(expected))
    assert tuple((p.event.fields.get("outcome").kind, p.source) for p in posts) == expected
    assert len(tuple(e for e in post_step.events if e.tag == "HostUnknown")) == 1
    assert tuple(d.envelope for d in state.core.network.deliveries) == posts
    with pytest.raises(Disabled, match="not previously delivered"):
        env.step(state, bundle_action, window)

    # Same-r order is still Post order at Accept, and retry preserves seq/plan.
    for envelope in posts:
        first_accept = take(Action("Accept", (envelope,)))
        acceptance = next(e.value for e in first_accept.events if e.tag == "Accept")
        retry = take(Action("Accept", (envelope,)))
        assert next(e.value for e in retry.events if e.tag == "Accept") == acceptance
        take(Action("HostAck", envelope.key))

    def save_receipt(envelope):
        unit = receipt_unit_id(envelope.run, envelope.number)
        for operation in ("PrepareReceipt", "PutBody", "AddEntry", "ConfirmWrite", "CompleteWrite"):
            take(Action(operation, (unit, "receipt")))

    save_receipt(posts[1])  # Save overtake must not replace the first notification.
    with pytest.raises(Disabled, match="first terminal receipt not saved"):
        env.step(state, Action("RecognizeTerminal", ("w0",)), window)
    save_receipt(posts[0])
    terminal = take(Action("RecognizeTerminal", ("w0",)))
    publication = next(e.value.plan for e in terminal.events if e.tag == "Publish")
    assert publication.records[0].content.get("terminal_kind") == expected[0][0]
    first_point = next(r.unit.slots[0].prepared.point for r in state.core.p.receipts if r.envelope == posts[0])
    assert publication.records[0].content.get("first_receipt") == first_point
    report = bc.evaluate_observations(e0.observation_contract, state.evidence.observation_trace)
    assert not tuple(l for l in report.limitations if l[0] == "INV-2.b")
    with capsys.disabled():
        print(f"\nP-09 {'Unknown-first' if unknown_first else 'value-first'} / "
              f"{'host-created-first' if unknown_generated_first else 'worker-created-first'}: "
              f"path_states={len(traversed)} seconds={perf_counter() - started:.6f} "
              f"r={posts[0].r} seq={tuple(p.receipt_seq for p in posts)} violations={report.violations}")


def test_delivery_bundle_is_predeclared_and_does_not_reuse_messages_or_predict_rank():
    from fb_machine import DeliveryBundle, HostNotice, WorkerNotice
    e0 = _t10_same_r_e0(True)
    invalid = (
        (DeliveryBundle("repeat", (HostNotice("unknown-0"), HostNotice("unknown-0"))),),
        (DeliveryBundle("undefined", (HostNotice("unknown-0"), WorkerNotice("w0", 1))),),
        (DeliveryBundle("undefined", (HostNotice("missing-notice"), WorkerNotice("w0", 0))),),
        e0.delivery_bundles + (DeliveryBundle("overlap", tuple(reversed(e0.delivery_bundles[0].notices))),),
    )
    for bundles in invalid:
        with pytest.raises(ValueError):
            Environment(replace(e0, delivery_bundles=bundles)).initial()
    state = Environment(e0).initial()
    assert not state.core.network.messages and not state.core.h.originals
    assert not state.evidence.observation_trace.events
    assert e0.delivery_bundles[0].notices == (HostNotice("unknown-0"), WorkerNotice("w0", 0))


# MG-01 BEGIN: window-owned M3/M4 tests (paper v0.18 1928-1969).
# The checker-owned sections on either side are unchanged. These are finite
# implementation tests, not independent identification or F-a mathematical proof.
def _mg_record(slot, contract, content, category="Event"):
    from fb_machine import FieldRole, ReferencePath, TypedReference

    def references(value, path=()):
        if isinstance(value, PlanRef):
            yield TypedReference("PATH-MG-WIRE", path, value, "UE", "generation")
        elif isinstance(value, Object):
            for key, child in value.items:
                yield from references(child, path + (key,))
        elif isinstance(value, tuple):
            for index, child in enumerate(value):
                yield from references(child, path + (index,))

    refs = tuple(references(content))
    record = RecordPlan(slot, contract, category, content, refs)
    roles = tuple(FieldRole(contract, "PATH-MG-WIRE", r.path, "UE", "generation") for r in refs)
    return record, roles, ReferencePath("PATH-MG-WIRE", (contract.name,), (), "UE", "generation", "direct")


def _mg_generation_e0(outcome=None, draws=(), reverse_basis=False):
    from fb_machine import Source, candidate_request_content
    process, reader, model, request = (PlanRef("initial", s) for s in ("process", "reader", "model", "Qgen"))
    candidate, context, evaluation = PlanRef("generated", "CG"), PlanRef("context", "context"), PlanRef("evaluation", "EQ")
    basis = (reader, model) if reverse_basis else (model, reader)
    d = Descriptor("wg", process, process, "generate-and-compare", "generation/0", reader,
        Contract("model.internal_generator", "1"), Contract("sui.fb.candidate_generation", "1"),
        obj(draws=draws, method_parameter="whole-args"), frozenset((model, reader)),
        NumericalView(frozenset((model, reader)), (model, reader), obj(model=model, generation_basis=basis)),
        "bootstrap", frozenset((process,)), request, "Wg", (("think", 1),), frozenset((request,)))
    q, qroles, path = _mg_record("Qgen", Contract("sui.fb.candidate_request", "1"), candidate_request_content(d))
    initial_records = tuple(RecordPlan(s, Contract("model.initial." + s, "1"), "Event", obj(origin="bootstrap", slot=s))
                            for s in ("process", "reader", "model")) + (q,)
    declaration = obj(model=model, input_order=("internal-A", "internal-B"), measure=obj(weights=(2, 1)),
        generation=obj(generator=d.method, args=d.args, basis=basis, draws=draws),
        continuation=obj(after=(obj(candidate="internal-A", policy=None), obj(candidate="internal-B", policy=None))))
    # Only the independent worker Program supplies the candidate contents. The
    # initial declaration contains the method, never an external candidate list.
    actual = outcome or Outcome(OutcomeKind.RETURNED, obj(variant="Candidates", declaration=declaration))
    cg = AllowedPlan("generated", "O-G", ("generation", "wg"),
        (RecordPlan("CG", Contract("candidate_declaration", "1"), "Prediction", Source("candidate_declaration", "wg")),),
        guards=(Guard("generation", "wg"),))
    eq_record, eroles, _ = _mg_record("EQ", Contract("sui.fb.evaluation_request", "1"),
        obj(candidates=candidate, reader=reader, model=model, preferences=(model,), context=context, o=(model,), j=(reader,)))
    ep = replace(d, work_id="ep", stage="Ep", stage_slot="evaluation/0", request=evaluation,
                 trigger=candidate, method=Contract("model.prepare_evaluation", "1"),
                 output_contract=Contract("model.evaluation_prepared", "1"),
                 input_points=frozenset((candidate, context, model, reader)),
                 numerical_view=NumericalView(frozenset((candidate, context, model)), (candidate, context), obj(model=model, context=context)),
                 required=frozenset((evaluation, candidate, context)))
    eq = AllowedPlan("evaluation", "O-G", ("evaluation", "wg"), (eq_record,), (ep,),
        (Guard("evaluation", "wg", candidate), Guard("generation_context", context)))
    initial = obj(generator=d.method, args=d.args)
    boot = Event("Boot", obj(declaration=obj(initial=initial)))
    e0 = E0(initial=initial, paper_version="v0.18", budget=Budget(window_faults=1), postings=(Posting("boot", boot, 0),), plans=(
        AllowedPlan("initial", "O-02", ("initial", 0), initial_records, (d,)), cg, eq,
        AllowedPlan("context", "O-13", ("context", 0),
                    (RecordPlan("context", Contract("model.evaluation_context", "1"), "Event", obj(observed="later-context")),),
                    guards=(Guard("saved", model),))),
        programs=(Program("wg", (actual,), False), Program("ep", (), False)))
    return replace(e0, references=e0.references + (path,), field_roles=e0.field_roles + qroles + eroles), declaration


class _MGPath:
    def __init__(self, e0):
        self.e0, self.env, self.window = e0, Environment(e0), CorrectWindow(e0)
        self.state = boundary_state(e0)

    def take(self, operation, target=()):
        step = self.env.step(self.state, Action(operation, target), self.window)
        self.state = step.state
        return step

    def save(self, unit, slots):
        for slot in slots:
            for op in ("PrepareReceipt" if unit.startswith("receipt/") else "PrepareOne",
                       "PutBody", "AddEntry", "ConfirmWrite", "CompleteWrite"):
                self.take(op, (unit, slot))

    def receive(self):
        envelope = self.state.core.h.queue[0]
        self.take("Accept", (envelope,))
        self.take("HostAck", envelope.key)
        self.save(receipt_unit_id(envelope.run, envelope.number), ("receipt",))
        return envelope

    def start(self, work):
        for op in ("ResolveWork", "ClaimStart", "Launch"):
            self.take(op, (work,))
        self.take("EnterWorker", (work + ":wrapper:0",))

    def finish(self, work):
        self.take("WorkerStep", (work,))
        self.take("Deliver", ("report:" + work + ":0",))
        return self.receive()


def _mg_started(e0):
    path = _MGPath(e0)
    path.take("PublishUnit", ("initial",))
    path.save("initial", tuple(r.slot for r in e0.plans[0].records))
    path.start("wg")
    return path


def _mg_condition(path, kind, target):
    return next(c for c in path.state.core.p.conditions
                if c.key.obligation == "O-G" and c.key.kind == kind and c.key.target == target)


def test_mg01_generation_cg_eq_keeps_issue_during_save_and_context_wait_then_atomic_ep():
    from fb_check import Owner, SlotKey, UnitKey, WorkKey
    from fb_machine import Disabled, View
    e0, declaration = _mg_generation_e0()
    path = _MGPath(e0)
    assert len([b for b in e0.observation_contract.completions if b.key.obligation == "O-G"]) == 7
    path.take("PublishUnit", ("initial",))
    assert [w.descriptor.work_id for w in path.state.core.p.work] == ["wg"]
    assert _mg_condition(path, "run", WorkKey("wg")).unmet
    with pytest.raises(Disabled):
        path.take("ClaimStart", ("wg",))  # run exists BEFORE Qgen is Saved.
    path.save("initial", tuple(r.slot for r in e0.plans[0].records))
    path.start("wg")
    envelope = path.finish("wg")
    assert envelope.event.kind == "WorkFinished"
    assert not _mg_condition(path, "run", WorkKey("wg")).unmet
    # FBM3-R01 / paper 1956: the EQ context is already short at EndKnown, so
    # the same owner accepts a target-bearing pG; issue[CG] stays separately.
    early = next(w for w in path.state.core.p.work if w.descriptor.work_id == "wg").purposes
    assert [(e.reason_id, e.witness) for e in early] == [("evaluation context unavailable", PlanRef("context", "context"))]
    assert not _mg_condition(path, "handle", WorkKey("wg")).unmet
    assert _mg_condition(path, "issue", SlotKey("generated", "CG")).unmet
    assert not any(c.key.kind == "issue" and c.key.target == SlotKey("evaluation", "EQ")
                   for c in path.state.core.p.conditions)
    path.take("RecognizeTerminal", ("wg",))
    assert next(u for u in path.state.core.p.units if u.id == "terminal:wg").slots[0].plan.content.get("returned") == envelope.event.fields.get("outcome").content
    path.take("PublishUnit", ("generated",))
    cg = next(u for u in path.state.core.p.units if u.id == "generated")
    expected = envelope.event.fields.get("outcome").content.get("declaration")
    assert cg.slots[0].plan.content == expected
    assert expected.get("input_order") == declaration.get("input_order")
    assert expected.get("generation").get("draws") == ()
    assert cg.generation.descriptor == e0.plans[0].works[0]
    assert cg.generation.candidate == PlanRef("generated", "CG")
    assert cg.generation.evaluation == PlanRef("evaluation", "EQ")
    assert cg.generation.purpose.origin == _mg_condition(path, "run", WorkKey("wg")).key
    issue = _mg_condition(path, "issue", SlotKey("evaluation", "EQ"))
    assert issue.owner == Owner("P.units", "generated") and issue.unmet == frozenset((issue.key,))
    assert not cg.slots[0].prepared
    with pytest.raises(Disabled):
        path.take("PublishUnit", ("evaluation",))
    path.save("generated", ("CG",))
    assert _mg_condition(path, "issue", SlotKey("evaluation", "EQ")).unmet == issue.unmet
    assert not _mg_condition(path, "save", SlotKey("generated", "CG")).unmet
    for op in ("Drain", "FaultWindow", "RebuildWindow", "Drain"):
        path.take(op)
    assert _mg_condition(path, "issue", SlotKey("evaluation", "EQ")).owner == issue.owner
    assert [w.descriptor.work_id for w in path.state.core.p.work] == ["wg"]
    residual = next(w for w in path.state.core.p.work if w.descriptor.work_id == "wg").purposes
    assert any(e.witness == PlanRef("context", "context") and e.obligation_key == cg.generation.purpose for e in residual)
    assert Action("PublishUnit", ("evaluation",)) not in path.window.enabled(View(path.state.core, path.state.controls, path.state.evidence))
    path.take("PublishUnit", ("context",))
    path.save("context", ("context",))
    eqstep = path.take("PublishUnit", ("evaluation",))
    assert tuple(e.key for e in eqstep.events if e.tag == "Publish") == (UnitKey("evaluation"),)
    eq = next(u for u in path.state.core.p.units if u.id == "evaluation")
    ep = next(w for w in path.state.core.p.work if w.descriptor.work_id == "ep")
    assert eq.works == ("ep",) and ep.descriptor.request == PlanRef("evaluation", "EQ")
    assert eq.generation.purpose == cg.generation.purpose and eq.generation.shortages == residual
    assert not _mg_condition(path, "issue", SlotKey("evaluation", "EQ")).unmet
    assert any(c.key.obligation == "O-10" and c.key.kind == "run" and c.key.target == WorkKey("ep") and c.unmet
               for c in path.state.core.p.conditions)
    assert eq.slots[0].plan.content.get("candidates") == next(u for u in path.state.core.p.units if u.id == "generated").slots[0].prepared.point
    assert eq.slots[0].plan.content.get("context") == next(u for u in path.state.core.p.units if u.id == "context").slots[0].prepared.point
    with pytest.raises(Disabled):
        path.take("ClaimStart", ("ep",))
    path.save("evaluation", ("EQ",))
    path.start("ep")
    assert next(w for w in path.state.core.p.work if w.descriptor.work_id == "wg").purposes == residual


@pytest.mark.parametrize("outcome", (
    Outcome(OutcomeKind.RETURNED, obj(variant="NoCandidates", basis=obj(reason="this-method/input-produced-none"))),
    Outcome(OutcomeKind.FAILURE, obj(code="generator-failed", basis="actual-worker-failure")),
    Outcome(OutcomeKind.UNKNOWN, obj(reason="result-unconfirmed", basis="actual-worker-unknown")),
), ids=("NoCandidates", "Failure", "Unknown"))
def test_mg01_non_success_saves_exact_t_and_purpose_without_successors_or_retry(outcome):
    from fb_check import SlotKey, WorkKey
    from fb_machine import Disabled
    e0, _ = _mg_generation_e0(outcome)
    path = _mg_started(e0)
    envelope = path.finish("wg")
    path.take("RecognizeTerminal", ("wg",))
    path.save("terminal:wg", ("T",))
    terminal = next(u for u in path.state.core.p.units if u.id == "terminal:wg").slots[0].prepared.record
    assert terminal.content.get("returned") == outcome.content
    assert terminal.content.get("terminal_kind") == outcome.kind
    assert terminal.content.get("work") == "wg" and terminal.content.get("stage") == "Wg"
    assert terminal.content.get("first_receipt") == next(r.unit.slots[0].prepared.point for r in path.state.core.p.receipts if r.envelope == envelope)
    row = next(w for w in path.state.core.p.work if w.descriptor.work_id == "wg")
    assert row.purposes and row.purposes[0].obligation_key.origin == _mg_condition(path, "run", WorkKey("wg")).key
    assert row.purposes[0].witness.outcome == outcome
    assert not _mg_condition(path, "handle", WorkKey("wg")).unmet
    for unit in ("generated", "evaluation"):
        with pytest.raises(Disabled):
            path.take("PublishUnit", (unit,))
    with pytest.raises(Disabled):
        path.take("ClaimStart", ("wg",))
    assert [w.descriptor.work_id for w in path.state.core.p.work] == ["wg"]
    assert not any(u.id in ("generated", "evaluation") for u in path.state.core.p.units)
    assert not any(e.header.record.contract.name in ("candidate_declaration", "sui.fb.evaluation_request", "draw_fact") for e in path.state.core.e)
    assert not _mg_condition(path, "save", SlotKey("terminal:wg", "T")).unmet


def test_mg01_no_initial_has_no_qgen_or_generation_work():
    from fb_machine import Disabled
    e0, _ = _mg_generation_e0()
    boot = Event("Boot", obj(declaration=obj(initial=None)))
    e0 = replace(e0, initial=None, postings=(Posting("boot", boot, 0),))
    path = _MGPath(e0)
    for unit in ("initial", "generated", "evaluation"):
        with pytest.raises(Disabled):
            path.take("PublishUnit", (unit,))
    assert not path.state.core.p.work and not path.state.core.p.units
    assert not any(e.header.record.contract.name == "sui.fb.candidate_request" for e in path.state.core.e)


@pytest.mark.parametrize("draws", ((obj(purpose="candidate_generation", ordinal=0),), None), ids=("R10-required", "undeclared"))
def test_mg01_generation_draw_requirement_remains_unconnected(draws):
    from fb_machine import MissingContract
    e0, _ = _mg_generation_e0(draws=draws)
    path = _MGPath(e0)
    path.take("PublishUnit", ("initial",))
    path.save("initial", tuple(r.slot for r in e0.plans[0].records))
    path.take("ResolveWork", ("wg",))
    with pytest.raises(MissingContract, match="R10"):
        path.take("ClaimStart", ("wg",))
    assert next(w for w in path.state.core.p.work if w.descriptor.work_id == "wg").descriptor.args.get("draws") == draws
    assert not path.state.core.runners


def test_mg01_success_and_predecessor_save_wait_do_not_invent_residual_purpose():
    from fb_check import SlotKey
    e0, _ = _mg_generation_e0()
    path = _mg_started(e0)
    path.take("PublishUnit", ("context",))
    path.save("context", ("context",))
    assert not next(w for w in path.state.core.p.work if w.descriptor.work_id == "wg").purposes
    path.finish("wg")
    assert not next(w for w in path.state.core.p.work if w.descriptor.work_id == "wg").purposes
    path.take("PublishUnit", ("generated",))
    assert _mg_condition(path, "issue", SlotKey("evaluation", "EQ")).unmet
    assert not next(u for u in path.state.core.p.units if u.id == "generated").generation.shortages
    path.take("Drain")
    assert not next(w for w in path.state.core.p.work if w.descriptor.work_id == "wg").purposes
    path.save("generated", ("CG",))
    path.take("PublishUnit", ("evaluation",))
    assert not next(u for u in path.state.core.p.units if u.id == "evaluation").generation.shortages


def test_mg01_generation_basis_correspondence_is_declared_independently_of_application_order():
    e0, _ = _mg_generation_e0(reverse_basis=True)
    d = e0.plans[0].works[0]
    assert d.numerical_view.context.get("generation_basis") != d.numerical_view.application_order
    path = _mg_started(e0)
    envelope = path.finish("wg")
    path.take("PublishUnit", ("generated",))
    candidate = next(u for u in path.state.core.p.units if u.id == "generated").slots[0].plan.content
    assert candidate.get("generation").get("basis") == envelope.event.fields.get("outcome").content.get("declaration").get("generation").get("basis")
    assert candidate.get("generation").get("basis") == tuple(next(u for u in path.state.core.p.units if u.id == "initial").slots[i].prepared.point for i in (1, 2))


def test_mg01_unit_presence_cannot_create_eq_issue_or_context_purpose_without_publication():
    from fb_check import SlotKey
    from fb_machine import Slot, Unit
    e0, _ = _mg_generation_e0()
    path = _mg_started(e0)
    envelope = path.finish("wg")
    # FBM3-R01: only the EndKnown context shortage exists; the ghost adds none.
    early = next(w for w in path.state.core.p.work if w.descriptor.work_id == "wg").purposes
    assert [e.reason_id for e in early] == ["evaluation context unavailable"]
    cg = e0.plans[1]
    content = envelope.event.fields.get("outcome").content.get("declaration")
    # Counterfactual custody corruption, not an identification run: a P.units
    # mark without any actual EU Publish cannot be an occurrence source.
    ghost = Unit(cg.unit, cg.obligation_id, cg.key, (Slot(replace(cg.records[0], content=content)),), (), frozenset())
    p = replace(path.state.core.p, units=path.state.core.p.units + (ghost,))
    path.state = replace(path.state, core=replace(path.state.core, p=p))
    path.take("Drain")
    assert not any(c.key.kind == "issue" and c.key.target == SlotKey("evaluation", "EQ") for c in path.state.core.p.conditions)
    assert next(w for w in path.state.core.p.work if w.descriptor.work_id == "wg").purposes == early


@pytest.mark.parametrize("fault", ("empty-order", "model", "generator-version", "args", "basis-order", "missing-continuation", "draws"))
def test_mg01_generation_compares_whole_reply_before_any_candidate_issue(fault):
    from fb_machine import Disabled
    from fb_check import SlotKey
    e0, declaration = _mg_generation_e0()
    values = dict(declaration.items)
    generation = dict(values["generation"].items)
    if fault == "empty-order":
        values["input_order"] = ()
    elif fault == "model":
        values["model"] = PlanRef("initial", "reader")
    elif fault == "generator-version":
        generation["generator"] = Contract("model.internal_generator", "2")
    elif fault == "args":
        generation["args"] = obj(draws=(), method_parameter="different-args")
    elif fault == "basis-order":
        generation["basis"] = tuple(reversed(generation["basis"]))
    elif fault == "missing-continuation":
        values["continuation"] = obj()
    else:
        generation["draws"] = None  # Falsy is not the explicit no-draw declaration.
    values["generation"] = obj(**generation)
    reply = Outcome(OutcomeKind.RETURNED, obj(variant="Candidates", declaration=obj(**values)))
    e0 = replace(e0, programs=(replace(e0.programs[0], replies=(reply,)), e0.programs[1]))
    path = _mg_started(e0)
    path.finish("wg")
    path.take("RecognizeTerminal", ("wg",))
    with pytest.raises(Disabled):
        path.take("PublishUnit", ("generated",))
    assert not any(c.key.kind == "issue" and c.key.target in (SlotKey("generated", "CG"), SlotKey("evaluation", "EQ"))
                   for c in path.state.core.p.conditions)
    assert [w.descriptor.work_id for w in path.state.core.p.work] == ["wg"]


@pytest.mark.parametrize("boundary", ("before-CG", "before-EQ", "before-Ep-entry"))
def test_mg01_independent_conflict_blocks_new_generation_use_without_rolling_back(boundary):
    from fb_machine import Disabled
    e0, declaration = _mg_generation_e0()
    changed = obj(**dict(declaration.items, input_order=tuple(reversed(declaration.get("input_order")))))
    second = Outcome(OutcomeKind.RETURNED, obj(variant="Candidates", declaration=changed))
    e0 = replace(e0, programs=(replace(e0.programs[0], replies=e0.programs[0].replies + (second,)), e0.programs[1]))
    path = _mg_started(e0)
    path.finish("wg")
    path.take("PublishUnit", ("context",))
    path.save("context", ("context",))
    if boundary != "before-CG":
        path.take("PublishUnit", ("generated",))
        path.save("generated", ("CG",))
    if boundary == "before-Ep-entry":
        path.take("PublishUnit", ("evaluation",))
        path.save("evaluation", ("EQ",))
        path.take("ResolveWork", ("ep",))
    before = tuple(u.id for u in path.state.core.p.units)
    path.take("WorkerStep", ("wg",))
    path.take("Deliver", ("report:wg:1",))
    path.receive()  # Two genuinely produced incompatible replies, no Xc needed.
    target = ("ClaimStart", ("ep",)) if boundary == "before-Ep-entry" else (
        "PublishUnit", ("generated" if boundary == "before-CG" else "evaluation",))
    with pytest.raises(Disabled, match="conflict"):
        path.take(*target)
    assert tuple(u.id for u in path.state.core.p.units) == before
    assert next(w for w in path.state.core.p.work if w.descriptor.work_id == "wg").purposes
    assert not any(r.work == "ep" for r in path.state.core.runners)


@pytest.mark.parametrize("fault", ("unsaved-Point", "wrong-model"))
def test_mg01_eq_requires_real_saved_inputs_and_the_matching_ep_view(fault):
    from fb_machine import Disabled, Point
    e0, _ = _mg_generation_e0()
    eq = e0.plans[2]
    content = dict(eq.records[0].content.items)
    if fault == "unsaved-Point":
        content["preferences"] = (Point("unconfirmed-preference"),)
    else:
        content["model"] = PlanRef("initial", "process")
    record, roles, _ = _mg_record("EQ", eq.records[0].contract, obj(**content))
    e0 = replace(e0, plans=(e0.plans[0], e0.plans[1], replace(eq, records=(record,)), e0.plans[3]),
                 field_roles=e0.field_roles + roles)
    path = _mg_started(e0)
    # Context saved before EndKnown (FBM3-R01) isolates the EQ input fault.
    path.take("PublishUnit", ("context",))
    path.save("context", ("context",))
    path.finish("wg")
    path.take("PublishUnit", ("generated",))
    path.save("generated", ("CG",))
    with pytest.raises(Disabled):
        path.take("PublishUnit", ("evaluation",))
    assert not any(u.id == "evaluation" for u in path.state.core.p.units)
    assert [w.descriptor.work_id for w in path.state.core.p.work] == ["wg"]
    reasons = next(w for w in path.state.core.p.work if w.descriptor.work_id == "wg").purposes
    if fault == "unsaved-Point":
        assert not reasons  # A Point awaiting storage is not a concrete use shortage.
    else:
        assert any(e.reason_id == "evaluation input correspondence differs" for e in reasons)


@pytest.mark.parametrize("stage,wrong_kind", (("D", "WorkFinished"), ("Wr", "DrawReturned")))
def test_mg01_wrong_notice_family_is_saved_but_not_first_end(stage, wrong_kind):
    from fb_machine import Disabled
    e0 = unknown_work()
    d = replace(e0.plans[0].works[0], stage=stage)
    failure = Outcome(OutcomeKind.FAILURE, obj(variant="DrawFailure", reason="draw-refused"))
    e0 = replace(e0, unknown_notices=(), plans=(replace(e0.plans[0], works=(d,)),),
                 programs=(Program("w0", (failure, Outcome(OutcomeKind.RETURNED, obj(variant="DrawValue", value=0.25))), False),))
    path = _MGPath(e0)
    path.take("PublishUnit", ("initial",))
    path.save("initial", ("process", "reader", "request"))
    path.start("w0")
    path.take("WorkerStep", ("w0",))
    message = path.state.core.network.messages[0]
    generation = message.generation
    # Deliberate environment transport fault, retaining the genuine producer's
    # Generation. An external Posting with no producer linkage cannot identify
    # the old bug: _first_end already ignored such a notice before M4.
    fields = (obj(work="w0", started=generation.started, finished=generation.finished, outcome=failure)
              if wrong_kind == "WorkFinished" else obj(work="w0", outcome=failure))
    wrong = replace(message, event=Event(wrong_kind, fields))
    network = replace(path.state.core.network, messages=(wrong,))
    path.state = replace(path.state, core=replace(path.state.core, network=network))
    path.take("Deliver", (wrong.id,))
    wrong_envelope = path.receive()
    assert wrong_envelope.event.kind == wrong_kind
    assert next(r for r in path.state.core.p.receipts if r.envelope == wrong_envelope).unit.slots[0].prepared.record.contract.name == (
        "sui.fb.work_report" if wrong_kind == "WorkFinished" else "sui.fb.draw_report")
    with pytest.raises(Disabled, match="await report"):
        path.take("RecognizeTerminal", ("w0",))
    assert not any(u.id == "terminal:w0" for u in path.state.core.p.units)
    assert any(c.key.kind == "run" and c.key.target.work == "w0" and c.unmet for c in path.state.core.p.conditions
               if hasattr(c.key.target, "work"))
    path.take("WorkerStep", ("w0",))
    path.take("Deliver", ("report:w0:1",))
    right_envelope = path.receive()
    path.take("RecognizeTerminal", ("w0",))
    terminal = next(u for u in path.state.core.p.units if u.id == "terminal:w0").slots[0].plan.content
    assert right_envelope.event.kind == ("DrawReturned" if stage == "D" else "WorkFinished")
    assert terminal.get("returned") == obj(variant="DrawValue", value=0.25)
    assert terminal.get("first_receipt") == next(r.unit.slots[0].prepared.point for r in path.state.core.p.receipts if r.envelope == right_envelope)


def test_mg01_draw_failure_first_keeps_t_only_despite_late_value():
    from fb_machine import Disabled, Source
    e0 = unknown_work()
    d = replace(e0.plans[0].works[0], stage="D")
    failure = Outcome(OutcomeKind.FAILURE, obj(variant="DrawFailure", reason="draw-refused"))
    later = Outcome(OutcomeKind.RETURNED, obj(variant="DrawValue", value=0.25))
    df = PlanRef("draw-result", "DF")
    ee = replace(d, work_id="ee", stage="Ee", request=df, required=frozenset((df,)))
    result = AllowedPlan("draw-result", "O-11", ("draw-end", "w0"),
        (RecordPlan("DF", Contract("draw_fact", "1"), "Event", Source("outcome_content", "w0")),), (ee,),
        (Guard("outcome", "w0", ("Success", "DrawValue")),))
    e0 = replace(e0, unknown_notices=(), plans=(replace(e0.plans[0], works=(d,)), result), programs=(Program("w0", (failure, later), False),))
    path = _MGPath(e0)
    path.take("PublishUnit", ("initial",))
    path.save("initial", ("process", "reader", "request"))
    path.start("w0")
    first = path.finish("w0")
    assert first.event.kind == "DrawReturned" and first.event.fields.get("outcome") == failure
    path.take("WorkerStep", ("w0",))
    path.take("Deliver", ("report:w0:1",))
    path.receive()
    with pytest.raises(Disabled, match="different terminal branch"):
        path.take("PublishUnit", ("draw-result",))
    path.take("RecognizeTerminal", ("w0",))
    path.save("terminal:w0", ("T",))
    unit = next(u for u in path.state.core.p.units if u.id == "terminal:w0")
    assert unit.slots[0].prepared.record.content.get("returned") == failure.content
    assert unit.slots[0].prepared.record.content.get("terminal_kind") == OutcomeKind.FAILURE
    assert unit.slots[0].prepared.record.content.get("first_receipt") == next(r.unit.slots[0].prepared.point for r in path.state.core.p.receipts if r.envelope == first)
    assert tuple(u.id for u in path.state.core.p.units) == ("initial", "terminal:w0")
    assert [w.descriptor.stage for w in path.state.core.p.work] == ["D"]
    assert not any(e.header.record.contract.name in ("draw_fact", "sui.fb.draw_unknown", "math_artifact", "decision") for e in path.state.core.e)
# MG-01 END: window-owned M3/M4 tests.


# MG-03 BEGIN: window-owned corrections; checker-owned sections are untouched.
@pytest.mark.parametrize("launch", ("normal", "uncertain_after"))
def test_mg03_actual_context_resolves_nested_refs_once_and_keeps_declaration(launch):
    e0, _ = _mg_generation_e0()
    initial, d = e0.plans[0], e0.plans[0].works[0]
    model, reader = PlanRef("initial", "model"), PlanRef("initial", "reader")
    literal = "PlanRef(unit='initial', slot='model')"
    context = obj(model=model, generation_basis=(model, reader),
                  nested=obj(inputs=(reader, obj(model=model)), literal=literal))
    d = replace(d, numerical_view=replace(d.numerical_view, context=context))
    from fb_machine import candidate_request_content
    q, roles, _ = _mg_record("Qgen", Contract("sui.fb.candidate_request", "1"), candidate_request_content(d))
    e0 = replace(e0, plans=(replace(initial, records=initial.records[:-1] + (q,), works=(d,)),) + e0.plans[1:],
                 field_roles=e0.field_roles + roles, budget=replace(e0.budget, uncertain_launches=1))
    path = _MGPath(e0)
    path.take("PublishUnit", ("initial",))
    path.save("initial", tuple(r.slot for r in e0.plans[0].records))
    for op in ("ResolveWork", "ClaimStart"):
        path.take(op, ("wg",))
    step = path.env.step(path.state, Action("Launch", ("wg",), launch), path.window)
    path.state = step.state
    if launch == "normal":
        path.take("EnterWorker", ("wg:wrapper:0",))
    saved = {s.plan.slot: s.prepared.point for u in path.state.core.p.units if u.id == "initial" for s in u.slots}
    expected = NumericalView(frozenset((saved["model"], saved["reader"])), (saved["model"], saved["reader"]),
        obj(model=saved["model"], generation_basis=(saved["model"], saved["reader"]),
            nested=obj(inputs=(saved["reader"], obj(model=saved["model"])), literal=literal)))
    runner = next(r for r in path.state.core.runners if r.work == "wg")
    assert runner.numerical_input == expected
    assert runner.descriptor_read.numerical_view == expected
    assert e0.plans[0].works[0].numerical_view.context == context
    assert next(w for w in path.state.core.p.work if w.descriptor.work_id == "wg").descriptor == d
    path.take("Drain")
    path.take("WorkerStep", ("wg",))
    assert next(r for r in path.state.core.runners if r.work == "wg").numerical_input == expected
    reads = [e for e in path.state.evidence.observation_trace.events if e.tag == "ReadInputs" and e.key.work == "wg"]
    assert len(reads) == 1 and reads[0].value.numerical_view == expected


def test_mg03_fully_typed_cg_and_public_input_have_no_inv8_or_generation_violation():
    # Reuse the independent, publicly authored declaration, not its old bug expectation.
    e0 = _mg02_generation_e0(typed_cg=True)
    declaration = e0.plans[0].works[0]
    scenario, states, edges, take, _ = _mg02_generation_path(e0, "saved-eq")
    cg = next(u for u in states[-1].core.p.units if u.id == "mg-cg").slots[0].prepared
    model = next(u for u in states[-1].core.p.units if u.id == "initial").slots[2].prepared.point
    assert cg.record.content.get("model") == model
    assert cg.record.content.get("generation").get("basis") == (model,)
    assert {r.path: r.ref for r in cg.record.references} == {
        ("model",): model, ("generation", "basis", 0): model}
    assert all((r.role, r.use) == ("UE", "generation") for r in cg.record.references)
    assert all(isinstance(r.ref, PlanRef) for r in e0.plans[1].records[0].references)
    assert e0.plans[0].works[0] == declaration
    for op in ("ResolveWork", "ClaimStart", "Launch"):
        take(Action(op, ("mg-ep",)))
    take(Action("EnterWorker", ("mg-ep:wrapper:0",)))
    report = check_exploration(scenario, _c05_graph(scenario, states, edges))
    assert not report.contract_violations and not report.violations, (report.contract_violations, report.violations)


def test_mg03_source_expansion_cannot_rebind_a_wrong_declared_cg_reference():
    e0 = _mg02_generation_e0(typed_cg=True)
    cg = e0.plans[1]
    record = cg.records[0]
    bad = replace(record, references=tuple(replace(r, ref=PlanRef("initial", "reader"))
                  if r.path == ("model",) else r for r in record.references))
    e0 = replace(e0, plans=(e0.plans[0], replace(cg, records=(bad,))) + e0.plans[2:], observation_declarations=None)
    _, states, _, take, _ = _mg02_generation_path(e0, "cg")
    with pytest.raises(RuntimeError, match="reference path differs from fixed plan"):
        take(Action("PrepareOne", ("mg-cg", "cg")))
    assert next(u for u in states[-1].core.p.units if u.id == "mg-cg").slots[0].prepared is None


def test_mg03_nested_source_and_literal_refs_both_prepare_to_their_declared_targets():
    """model.generation_projection/1 is a name-only fixture contract, not a paper claim."""
    from fb_machine import Source
    e0 = _mg02_generation_e0()
    reply = e0.programs[0].replies[0].content.get("declaration")
    record, roles, rule = _mg_record("projection", Contract("model.generation_projection", "1"),
                                    obj(payload=reply, literal=PlanRef("initial", "reader")))
    record = replace(record, content=obj(payload=Source("candidate_declaration", "mg-wg"),
                                         literal=PlanRef("initial", "reader")))
    plan = AllowedPlan("projection", "O-13", ("projection",), (record,), guards=(Guard("first", "mg-wg"),))
    e0 = replace(e0, plans=e0.plans + (plan,), field_roles=e0.field_roles + roles,
                 references=e0.references + (rule,), observation_declarations=None)
    _, states, _, take, save = _mg02_generation_path(e0, "end")
    take(Action("PublishUnit", ("projection",)))
    published = next(u for u in states[-1].core.p.units if u.id == "projection").slots[0].plan
    assert published.content.get("literal") == PlanRef("initial", "reader")
    save("projection", "projection")
    prepared = next(u for u in states[-1].core.p.units if u.id == "projection").slots[0].prepared
    inputs = {s.plan.slot: s.prepared.point for u in states[-1].core.p.units if u.id == "initial" for s in u.slots}
    assert {r.path: r.ref for r in prepared.record.references} == {
        ("literal",): inputs["reader"], ("payload", "model"): inputs["model"],
        ("payload", "generation", "basis", 0): inputs["model"]}
    assert prepared.record.content.get("literal") == inputs["reader"]
    assert prepared.record.content.get("payload").get("model") == inputs["model"]


def _mg03_point_save_wait_e0():
    from hashlib import sha256
    from fb_machine import Record
    e0, _ = _mg_generation_e0()
    # Author a known Point before I0 with the independent fixture codec. This
    # path prepares the predecessor at rank 2, after Wg entry and its one return.
    planned = e0.plans[3].records[0]
    record = Record("context:context", Reading(e0.run, e0.clock_source, 2), planned.contract,
                    planned.category, planned.content, ())
    salt = sha256(_handmade_encode(("model-salt", record.name))).hexdigest().encode("ascii")
    point = _handmade_prepared(record, salt=salt).point
    old = PlanRef("context", "context")
    eq = e0.plans[2]
    ep = eq.works[0]
    ep = replace(ep, input_points=(ep.input_points - {old}) | {point}, required=(ep.required - {old}) | {point},
        numerical_view=replace(ep.numerical_view, points=(ep.numerical_view.points - {old}) | {point},
            application_order=tuple(point if p == old else p for p in ep.numerical_view.application_order),
            context=obj(**dict(ep.numerical_view.context.items, context=point))))
    body = obj(**dict(eq.records[0].content.items, context=point))
    eq = replace(eq, records=(replace(eq.records[0], content=body),), works=(ep,),
                 guards=tuple(g for g in eq.guards if g.kind != "generation_context") + (Guard("saved", point),))
    return replace(e0, plans=e0.plans[:2] + (eq, e0.plans[3])), point


@pytest.mark.parametrize("body_written", (False, True), ids=("prepared-only", "body-only"))
def test_mg03_pending_point_storage_keeps_eq_issue_without_creating_pg(body_written):
    from fb_check import Owner, SlotKey
    from fb_machine import Disabled
    e0, point = _mg03_point_save_wait_e0()
    path = _mg_started(e0)
    path.finish("wg")
    path.take("PublishUnit", ("context",))
    path.take("PrepareOne", ("context", "context"))
    pending = next(u for u in path.state.core.p.units if u.id == "context").slots[0].prepared
    assert pending.point == point and not any(e.point == point for e in path.state.core.e)
    if body_written:
        path.take("PutBody", ("context", "context"))
    path.take("PublishUnit", ("generated",))
    path.save("generated", ("CG",))
    issue = _mg_condition(path, "issue", SlotKey("evaluation", "EQ"))
    assert issue.owner == Owner("P.units", "generated") and issue.unmet == frozenset((issue.key,))
    assert not next(w for w in path.state.core.p.work if w.descriptor.work_id == "wg").purposes
    with pytest.raises(Disabled):
        path.take("PublishUnit", ("evaluation",))
    if not body_written:
        path.take("PutBody", ("context", "context"))
    for op in ("AddEntry", "ConfirmWrite", "CompleteWrite"):
        path.take(op, ("context", "context"))
    path.take("PublishUnit", ("evaluation",))
    assert not _mg_condition(path, "issue", SlotKey("evaluation", "EQ")).unmet
    eq = next(u for u in path.state.core.p.units if u.id == "evaluation")
    assert eq.slots[0].plan.content.get("context") == point and not eq.generation.shortages
    assert not next(w for w in path.state.core.p.work if w.descriptor.work_id == "wg").purposes


def test_mg03_concrete_context_shortage_creates_original_pg_and_later_eq_does_not_clear_it():
    from fb_check import SlotKey, WorkKey
    e0, _ = _mg_generation_e0()
    path = _mg_started(e0)
    path.finish("wg")
    # FBM3-R01 / paper 1956: born at EndKnown, unchanged by CG PUB.
    purposes = next(w for w in path.state.core.p.work if w.descriptor.work_id == "wg").purposes
    path.take("PublishUnit", ("generated",))
    assert next(w for w in path.state.core.p.work if w.descriptor.work_id == "wg").purposes == purposes
    assert len(purposes) == 1
    residual = purposes[0]
    assert residual.reason_id == "evaluation context unavailable" and residual.witness == PlanRef("context", "context")
    assert residual.obligation_key.origin == _mg_condition(path, "run", WorkKey("wg")).key
    assert _mg_condition(path, "issue", SlotKey("evaluation", "EQ")).unmet
    path.save("generated", ("CG",))
    path.take("PublishUnit", ("context",))
    path.save("context", ("context",))
    path.take("PublishUnit", ("evaluation",))
    assert next(w for w in path.state.core.p.work if w.descriptor.work_id == "wg").purposes == purposes
    assert next(u for u in path.state.core.p.units if u.id == "evaluation").generation.shortages == purposes
# MG-03 END: window-owned corrections.


# MG-05 BEGIN: window-owned public EQ contract and publication boundaries.
def _mg05_literal_e0():
    """Execute the published frozen declaration, never a window/checker body."""
    from textwrap import dedent
    from fb_machine import FieldRole, ReferencePath, TypedReference
    public = dict(PlanRef=PlanRef, obj=obj, frozenset=frozenset, Descriptor=Descriptor,
                  Contract=Contract, NumericalView=NumericalView, TypedReference=TypedReference,
                  RecordPlan=RecordPlan, AllowedPlan=AllowedPlan, Guard=Guard, FieldRole=FieldRole,
                  ReferencePath=ReferencePath)
    fragment = AllowedPlan.__doc__.split("        process = PlanRef('initial', 'process')", 1)[1]
    fragment = "        process = PlanRef('initial', 'process')" + fragment.split("\n    Add evaluation/", 1)[0]
    exec(dedent(fragment), public)
    e0, _ = _mg_generation_e0()
    # One generation input is enough to distinguish the later evaluation view.
    # The checker's sorted(PlanRef set) failure for multiple inputs is reported
    # separately; do not turn that implementation accident into an E0 rule.
    model = PlanRef("initial", "model")
    wg = replace(e0.plans[0].works[0], input_points=frozenset((model,)),
        numerical_view=NumericalView(frozenset((model,)), (model,), obj(model=model, generation_basis=(model,))))
    qbody = obj(process=wg.process, trigger=wg.trigger, reader=wg.reader, purpose=wg.purpose,
        stage_slot=wg.stage_slot, method=wg.method, output_contract=wg.output_contract,
        args=wg.args, input_points=(model,), numerical_view=obj(points=(model,),
        application_order=(model,), context=wg.numerical_view.context), allocation=wg.allocation,
        need=wg.need, permissions=(wg.process,))
    q, qroles, _ = _mg_record("Qgen", Contract("sui.fb.candidate_request", "1"), qbody)
    initial = replace(e0.plans[0], records=e0.plans[0].records[:-1] + (q,), works=(wg,))
    declaration = e0.programs[0].replies[0].content.get("declaration")
    declaration = obj(**dict(declaration.items, generation=obj(**dict(declaration.get("generation").items, basis=(model,)))))
    program = replace(e0.programs[0], replies=(Outcome(OutcomeKind.RETURNED, obj(variant="Candidates", declaration=declaration)),))
    cg_record = replace(e0.plans[1].records[0], slot="cg", references=tuple(
        TypedReference("PATH-CG-INPUT", path, model, "UE", "generation")
        for path in (("model",), ("generation", "basis", 0))))
    cg_roles = tuple(FieldRole(cg_record.contract, ref.path_id, ref.path, ref.role, ref.use) for ref in cg_record.references)
    cg_rule = ReferencePath("PATH-CG-INPUT", ("candidate_declaration/1",), (), "UE", "generation", "direct")
    candidate = replace(e0.plans[1], unit="candidate", records=(cg_record,))
    inputs = AllowedPlan("eval-inputs", "O-02", ("evaluation-inputs",), tuple(
        RecordPlan(name, Contract("model.evaluation_input", "1"), "Event", obj(slot=name))
        for name in ("model", "preferences", "context", "observation", "judgment")))
    e0 = replace(e0, plans=(initial, candidate, public["evaluation"], inputs), programs=(program, e0.programs[1]),
        field_roles=tuple(r for r in e0.field_roles if r.record_contract not in (q.contract, public["record"].contract))
                    + public["roles"] + qroles + cg_roles,
        references=e0.references + (public["rule"], cg_rule),
        observation_declarations=None)
    return e0


class _MG05Path(_MGPath):
    def __init__(self, e0):
        super().__init__(e0)
        self.scenario = Scenario("MG-05-public-boundary", e0, 1)
        self.states, self.edges = [self.state], []

    def take(self, operation, target=()):
        from fb_machine import Edge
        step = super().take(operation, target)
        self.edges.append(Edge(len(self.states) - 1, len(self.states), Action(operation, target), step.events, step.result))
        self.states.append(self.state)
        return step


def _mg05_started(e0):
    path = _MG05Path(e0)
    path.take("PublishUnit", ("initial",))
    path.save("initial", tuple(r.slot for r in e0.plans[0].records))
    path.take("PublishUnit", ("eval-inputs",))
    path.save("eval-inputs", tuple(r.slot for r in e0.plans[3].records))
    path.start("wg")
    return path


def _mg05_before_eq(e0):
    path = _mg05_started(e0)
    path.finish("wg")
    path.take("RecognizeTerminal", ("wg",))
    path.take("PublishUnit", ("candidate",))
    path.save("candidate", ("cg",))
    return path


@pytest.mark.parametrize("preference_tuple", (False, True), ids=("single-preference", "ordered-preferences"))
def test_mg05_literal_eq_contract_resolves_evaluation_inputs_separately_from_generation(preference_tuple):
    from fb_machine import Disabled
    e0 = _mg05_literal_e0()
    if preference_tuple:
        from fb_machine import FieldRole, TypedReference
        eq = e0.plans[2]
        prefs = (PlanRef("eval-inputs", "preferences"), PlanRef("eval-inputs", "model"))
        body = obj(**dict(eq.records[0].content.items, preferences=prefs))
        refs = tuple(r for r in eq.records[0].references if r.path != ("preferences",)) + tuple(
            TypedReference("PATH-EQ-INPUT", ("preferences", i), p, "UE", "math") for i, p in enumerate(prefs))
        record = replace(eq.records[0], content=body, references=refs)
        roles = tuple(FieldRole(record.contract, r.path_id, r.path, r.role, r.use) for r in refs)
        e0 = replace(e0, plans=e0.plans[:2] + (replace(eq, records=(record,)), e0.plans[3]),
                     field_roles=tuple(r for r in e0.field_roles if r.record_contract != record.contract) + roles)
    path = _mg05_before_eq(e0)
    declaration = e0.plans[0].works[0]
    path.take("PublishUnit", ("evaluation",))
    eq = next(u for u in path.state.core.p.units if u.id == "evaluation")
    fixed = {s.plan.slot: s.prepared.point for u in path.state.core.p.units if u.id == "eval-inputs" for s in u.slots}
    cg = next(u for u in path.state.core.p.units if u.id == "candidate").slots[0].prepared.point
    reader = next(u for u in path.state.core.p.units if u.id == "initial").slots[1].prepared.point
    assert eq.slots[0].plan.content == obj(candidates=cg, reader=reader, model=fixed["model"],
        preferences=(fixed["preferences"], fixed["model"]) if preference_tuple else fixed["preferences"],
        context=fixed["context"], o=fixed["observation"], j=fixed["judgment"])
    ep = next(w for w in path.state.core.p.work if w.descriptor.work_id == "ep")
    assert ep.descriptor == e0.plans[2].works[0] and ep.descriptor.request == PlanRef("evaluation", "eq")
    assert ep.descriptor.reader == declaration.reader and ep.descriptor.purpose == declaration.purpose
    assert e0.plans[0].works[0] == declaration
    path.save("evaluation", ("eq",))
    # The generation program has not stopped: release needs its independent Stop.
    with pytest.raises(Disabled):
        path.take("Release", ("wg",))
    path.take("Drain")
    assert not next(w for w in path.state.core.p.work if w.descriptor.work_id == "wg").purposes
    if not preference_tuple:
        # Full finite generation/custody check; not a F-a clock/math certificate.
        report = check_exploration(path.scenario, _c05_graph(path.scenario, path.states, path.edges))
        assert not report.contract_violations and not report.violations, (report.contract_violations, report.violations)


@pytest.mark.parametrize("fault", ("o-scalar", "j-scalar", "preferences-scalar", "extra-key", "missing-key",
                                    "context-missing", "context-exchanged", "o-mirror", "j-mirror", "numerical-input-missing",
                                    "order-unsaved"))
def test_mg05_incomplete_eq_correspondence_cannot_publish_or_discharge_issue(fault):
    from fb_check import Owner, SlotKey
    from fb_machine import Disabled
    e0 = _mg05_literal_e0()
    eq = e0.plans[2]
    body = dict(eq.records[0].content.items)
    ep, view = eq.works[0], eq.works[0].numerical_view
    if fault.endswith("scalar"):
        body[fault.split("-")[0]] = 0
    elif fault == "extra-key":
        body["ignored"] = "not-in-contract"
    elif fault == "missing-key":
        del body["j"]
    elif fault.startswith("context"):
        context = dict(view.context.items)
        if fault == "context-missing":
            del context["context"]
        else:
            context["context"] = PlanRef("eval-inputs", "model")
        ep = replace(ep, numerical_view=replace(view, context=obj(**context)))
    elif fault.endswith("mirror"):
        context = dict(view.context.items)
        context[fault[0]] = PlanRef("eval-inputs", "context")
        ep = replace(ep, numerical_view=replace(view, context=obj(**context)))
    elif fault == "numerical-input-missing":
        missing = PlanRef("eval-inputs", "judgment")
        ep = replace(ep, input_points=ep.input_points - {missing}, numerical_view=replace(view,
            points=view.points - {missing}, application_order=tuple(p for p in view.application_order if p != missing)))
    else:
        from fb_machine import Point
        ep = replace(ep, numerical_view=replace(view, application_order=view.application_order + (Point("unconfirmed-order-input"),)))
    # Reference declarations remain independent of the changed body/type.
    eq = replace(eq, records=(replace(eq.records[0], content=obj(**body)),), works=(ep,))
    e0 = replace(e0, plans=e0.plans[:2] + (eq, e0.plans[3]))
    path = _mg05_before_eq(e0)
    issue = _mg_condition(path, "issue", SlotKey("evaluation", "eq"))
    with pytest.raises(Disabled):
        path.take("PublishUnit", ("evaluation",))
    assert _mg_condition(path, "issue", SlotKey("evaluation", "eq")) == issue
    assert issue.owner == Owner("P.units", "candidate") and issue.unmet == frozenset((issue.key,))
    assert not any(w.descriptor.work_id == "ep" for w in path.state.core.p.work)
    assert not any(u.id == "evaluation" for u in path.state.core.p.units)


@pytest.mark.parametrize("field", ("input_order", "measure"))
def test_mg05_public_publish_boundary_exposes_single_field_cg_substitution(field):
    """Negative input uses the public window seam, not a new legal E0 Source."""
    from fb_machine import Effect, Source

    class SubstituteCG(CorrectWindow):
        def publish_unit(self, view, plan_id):
            decision = super().publish_unit(view, plan_id)
            if plan_id != "candidate":
                return decision
            unit = decision.result
            slot = unit.slots[0]
            original = slot.plan.content
            value = tuple(reversed(original.get("input_order"))) if field == "input_order" else obj(weights=(99, 1))
            changed = obj(**dict(original.items, **{field: value}))
            unit = replace(unit, slots=(replace(slot, plan=replace(slot.plan, content=changed)),))
            return replace(decision, custody=replace(decision.custody,
                units=tuple(unit if u.id == unit.id else u for u in decision.custody.units)), result=unit,
                effects=tuple(Effect(e.kind, e.key, (unit, e.value[1]))
                              if e.kind == "Publish" and e.key == unit.id else e for e in decision.effects))

    e0 = _mg05_literal_e0()
    path = _mg05_started(e0)
    path.finish("wg")
    original = next(r.value.outcome.content.get("declaration") for r in path.state.evidence.ew.events
                    if r.kind == "Returned")
    path.window = SubstituteCG(e0)
    path.take("PublishUnit", ("candidate",))
    published = next(u for u in path.state.core.p.units if u.id == "candidate").slots[0].plan.content
    assert {k for k, v in original.items if published.get(k) != v} == {field}
    assert e0.plans[1].records[0].content == Source("candidate_declaration", "wg")
    assert next(r.value.outcome.content.get("declaration") for r in path.state.evidence.ew.events
                if r.kind == "Returned") == original
    report = check_exploration(path.scenario, _c05_graph(path.scenario, path.states, path.edges))
    assert any(v.condition_id == "INV-16.c" for v in report.violations)


def test_mg05_saved_upstream_conflict_blocks_launched_ep_without_releasing_occupation():
    from fb_machine import Disabled
    e0 = _mg05_literal_e0()
    declaration = e0.programs[0].replies[0].content.get("declaration")
    changed = obj(**dict(declaration.items, measure=obj(weights=(7, 1))))
    e0 = replace(e0, capacity=(("think", 2),), allocation=(("think", 2),), programs=(
        replace(e0.programs[0], replies=e0.programs[0].replies + (Outcome(OutcomeKind.RETURNED,
            obj(variant="Candidates", declaration=changed)),)), e0.programs[1]))
    path = _mg05_before_eq(e0)
    path.take("PublishUnit", ("evaluation",))
    path.save("evaluation", ("eq",))
    for op in ("ResolveWork", "ClaimStart", "Launch"):
        path.take(op, ("ep",))
    before = next(w for w in path.state.core.p.work if w.descriptor.work_id == "ep")
    assert before.held == (("think", 1),) and not before.consumed
    path.take("WorkerStep", ("wg",))
    path.take("Deliver", ("report:wg:1",))
    path.receive()
    with pytest.raises(Disabled, match="conflict"):
        path.take("EnterWorker", ("ep:wrapper:0",))
    after = next(w for w in path.state.core.p.work if w.descriptor.work_id == "ep")
    assert after.held == before.held and after.token == before.token and not after.consumed
    assert [f.value for f in path.state.evidence.ew.events if f.kind == "Reserve" and f.key == "ep"] == [(("think", 1),)]
    assert not any(f.kind == "Release" and f.key == "ep" for f in path.state.evidence.ew.events)
    assert not any(r.work == "ep" for r in path.state.core.runners)
    assert {u.id for u in path.state.core.p.units} >= {"candidate", "evaluation", "terminal:wg"}
# MG-05 END: window-owned public EQ contract and publication boundaries.


# C-05 checker-owned tests, paper v0.15 (9-3補). Only public model steps.
# Both window-owned sections stay byte-identical; checker sections may evolve.
def _c05_scene(name):
    import fb_scenes as scenes
    return next(s for parent in scenes.SCENES for s in (parent, *parent.parts) if s.id == name)


def _c05_graph(scenario, states, edges):
    from fb_machine import Exploration
    return Exploration(scenario.id, tuple(states), tuple(edges),
        tuple(_c02_start_actions(scenario.e0, state) for state in states),
        False, (len(states) - 1,), (), 0.0,
        (None,) + tuple((edge.source, edge.action) for edge in edges),
        ('C-05 finite public path; not exhaustive',))


def _c05_take(scenario, states, edges, action, window=None):
    from fb_machine import Edge
    env = Environment(scenario.e0)
    before = states[-1]
    window = window or CorrectWindow(scenario.e0)
    step = env.step(before, action, window)
    edges.append(Edge(len(states) - 1, len(states), action, step.events, step.result))
    states.append(step.state)
    return step


def _c05_change_window(e0, predicate, change):
    """A public Drain override; independent histories and all other steps stay real.

    This is a counterfactual control, not a new named mutant requirement.
    The production checker never looks at the action name or change spelling.
    """
    class Window(CorrectWindow):
        def drain(self, view):
            decision = super().drain(view)
            rows = []
            for c in decision.custody.conditions:
                if not predicate(c):
                    rows.append(c)
                elif change == 'delete':
                    continue
                elif change == 'clear':
                    rows.append(replace(c, unmet=frozenset()))
                elif change == 'rename':
                    rows.append(replace(c, key=replace(c.key, obligation_key=('renamed',))))
                elif change == 'owner':
                    rows.append(replace(c, owner=observation_check.Owner('P.work', 'absent')))
                else:
                    raise AssertionError(change)
            return replace(decision, custody=replace(decision.custody, conditions=tuple(rows)))
    return Window(e0)


@pytest.fixture(scope='module')
def c05_desc_prefix():
    import fb_scenes as scenes
    scenario, states, edges, _ = scenes.instantiate(_c05_scene('SC-04-DESC'))
    assert len(edges) == 44 and len(states) == 45
    return scenario, states, edges


def test_c05_desc_44_public_edges_all_rows(c05_desc_prefix):
    scenario, states, edges = c05_desc_prefix
    report = check_exploration(scenario, _c05_graph(scenario, states, edges))
    assert not report.violations and not report.contract_violations


@pytest.mark.parametrize('kind,change', (('handle', 'delete'), ('handle', 'clear'),
                                        ('save', 'delete'), ('save', 'clear'),
                                        ('handle', 'rename'), ('handle', 'owner')))
def test_c05_review_drain_wait_cut(c05_desc_prefix, kind, change):
    scenario, states, _ = c05_desc_prefix
    initial = states[-1]
    operations = {a.operation for a in _c02_start_actions(scenario.e0, initial)}
    cut = Cut('C-05-Drain-Wait', frozenset(operations - {'Drain', 'Wait'}),
              ('only Drain/Wait; no full scene exploration',))
    scenario = replace(scenario, initial=initial, max_states=8, cut=cut)
    good = check_exploration(scenario, explore(scenario))
    assert not good.violations and not good.contract_violations
    window = _c05_change_window(scenario.e0,
        lambda c: c.key.obligation == 'O-05' and c.key.kind == kind, change)
    graph = explore(scenario, window=window)
    assert any(e.action.operation == 'Drain' for e in graph.edges)
    bad = check_exploration(scenario, graph)
    assert {v.condition_id for v in bad.violations} >= {'INV-2.a', 'INV-2.c'}


@pytest.fixture(scope='module')
def c05_delta_path():
    import fb_scenes as scenes
    scene = _c05_scene('SC-04-publish-Q-Wr')
    scenario, states, edges, _ = scenes.instantiate(scene)
    states, edges = list(states), list(edges)
    for op in ('PrepareOne', 'PutBody', 'AddEntry', 'ConfirmWrite', 'CompleteWrite'):
        _c05_take(scenario, states, edges, Action(op, ('q-e1', 'q')))
    return scenario, states, edges


def test_c05_delta_unconnected_is_not_false_or_discharged(c05_delta_path):
    bc = observation_check
    scenario, states, edges = c05_delta_path
    report = check_exploration(scenario, _c05_graph(scenario, states, edges))
    assert not report.violations and not report.contract_violations
    state = states[-1]
    result = bc.evaluate_condition_custody(scenario.e0.observation_contract,
                                         state.evidence.observation_trace, state)
    delta = [j for j in result.custody if isinstance(j.target, bc.CompletionKey)
             and j.target.obligation == 'O-03']
    assert delta and all(j.classification == '未接続' and j.direct is None for j in delta)
    assert any('projection' in reason for j in delta for reason in j.reasons)


@pytest.mark.parametrize('change', ('delete', 'clear'))
def test_c05_unwritten_delta_cannot_disappear(c05_delta_path, change):
    scenario, states, _ = c05_delta_path
    before = states[-6]  # Q published; no Q write yet.
    predicate = lambda c: c.key.obligation == 'O-03' and c.key.kind == 'save'
    window = _c05_change_window(scenario.e0, predicate, change)
    step = Environment(scenario.e0).step(before, Action('Drain'), window)
    result = observation_check.evaluate_condition_custody(scenario.e0.observation_contract,
        step.state.evidence.observation_trace, step.state, before_state=before)
    assert {v.row for v in result.violations} >= {'INV-2.a', 'INV-2.c'}


@pytest.fixture(scope='module')
def c05_wp_unknown_path():
    import fb_scenes as scenes
    from fb_machine import HandoffRoute
    bc = observation_check
    scene = _c05_scene('SC-04-publish-R-Wp')
    key = next(b.key for b in scene.e0.observation_contract.completions
               if b.key.obligation == 'O-07' and b.key.kind == 'handle')
    terminal = next(b for b in scene.e0.observation_contract.completions
                    if b.key.obligation == 'O-07' and b.key.kind == 'save' and b.trigger == 'EndKnown')
    e0 = replace(scene.e0, programs=tuple(
        Program('wp', (Outcome(OutcomeKind.UNKNOWN, obj(reason='unconfirmed-proof')),), True)
        if p.work == 'wp' else p for p in scene.e0.programs),
        handoff_routes=(HandoffRoute(key, bc.Owner('P.units', terminal.slots[0].unit)),))
    scenario, states, edges, _ = scenes.instantiate(replace(scene, e0=e0))
    states, edges = list(states), list(edges)
    def take(action):
        return _c05_take(scenario, states, edges, action)
    for op in ('PrepareOne', 'PutBody', 'AddEntry', 'ConfirmWrite', 'CompleteWrite'):
        take(Action(op, ('result', 'r')))
    for op in ('Stop', 'Release'):
        action = Action(op, ('wr',))
        if action in _c02_start_actions(e0, states[-1]):
            take(action)
    for action in (Action('ResolveWork', ('wp',)), Action('ClaimStart', ('wp',)),
                   Action('Launch', ('wp',)), Action('EnterWorker', ('wp:wrapper:0',)),
                   Action('WorkerStep', ('wp',)), Action('Deliver', ('report:wp:0',))):
        take(action)
    envelope = states[-1].core.h.queue[0]
    take(Action('Accept', (envelope,)))
    take(Action('HostAck', envelope.key))
    unit = receipt_unit_id(envelope.run, envelope.number)
    for op in ('PrepareReceipt', 'PutBody', 'AddEntry', 'ConfirmWrite', 'CompleteWrite'):
        take(Action(op, (unit, 'receipt')))
    take(Action('RecognizeTerminal', ('wp',)))
    for slot in terminal.slots:
        for op in ('PrepareOne', 'PutBody', 'AddEntry', 'ConfirmWrite', 'CompleteWrite'):
            take(Action(op, (slot.unit, slot.slot)))
    before_handoff = len(states) - 1
    take(next(a for a in _c02_start_actions(e0, states[-1]) if a.operation == 'HandoffPurpose'))
    return scenario, states, edges, key, before_handoff


def test_c05_wp_unknown_local_handoff_preserves_original_purpose(c05_wp_unknown_path):
    bc = observation_check
    scenario, states, edges, key, _ = c05_wp_unknown_path
    report = check_exploration(scenario, _c05_graph(scenario, states, edges))
    assert not report.violations and not report.contract_violations
    state = states[-1]
    facts = bc.CompletionFacts(scenario.e0.observation_contract, state.evidence.observation_trace, state)
    binding = next(b for b in facts.contract.completions if b.key == key)
    assert bc.completion_conclusion(binding, facts.contract, facts.trace, state) is False
    parts = bc.required_purpose_parts(binding, facts)
    assert len(parts) == 1 and parts[0].origin == key and bc.purpose_carried(parts[0], facts)
    result = bc.evaluate_condition_custody(facts.contract, facts.trace, state)
    assert any(j.target == key and j.classification == '引継ぎ済み' for j in result.custody)
    assert any(j.target == parts[0] and j.classification == '未達のまま保全' for j in result.custody)
    assert not any(u.id in ('proof', 'completed') for u in state.core.p.units)


@pytest.mark.parametrize('change', ('delete', 'rename', 'purpose', 'target'))
def test_c05_wp_saved_t_does_not_erase_purpose(c05_wp_unknown_path, change):
    bc = observation_check
    scenario, states, _, key, _ = c05_wp_unknown_path
    before = states[-1]
    class Window(CorrectWindow):
        def drain(self, view):
            decision = super().drain(view)
            rows = []
            for row in decision.custody.work:
                if row.descriptor.work_id != key.target.work:
                    rows.append(row)
                elif change == 'delete':
                    continue
                else:
                    fields = ({'work_id': 'renamed'} if change == 'rename' else
                              {'purpose': 'other-purpose'} if change == 'purpose' else
                              {'request': PlanRef('initial', 'request')})
                    rows.append(replace(row, descriptor=replace(row.descriptor, **fields)))
            return replace(decision, custody=replace(decision.custody, work=tuple(rows)))
    window = Window(scenario.e0)
    step = Environment(scenario.e0).step(before, Action('Drain'), window)
    result = bc.evaluate_condition_custody(scenario.e0.observation_contract,
        step.state.evidence.observation_trace, step.state, before_state=before)
    assert any(isinstance(v.target, bc.PurposePart) for v in result.violations)
    assert {v.row for v in result.violations} >= {'INV-2.a', 'INV-2.c'}


@pytest.mark.parametrize('change', ('delete', 'clear'))
def test_c05_no_ended_keeps_run_independently_of_stop(change):
    import fb_scenes as scenes
    bc = observation_check
    scenario, states, edges, _ = scenes.instantiate(_c05_scene('SC-04-publish-interval-MeasureSegment'))
    before = states[-1]
    binding = next(b for b in scenario.e0.observation_contract.completions
                   if b.key.obligation == 'O-04' and b.key.kind == 'run')
    assert bc.completion_conclusion(binding, scenario.e0.observation_contract,
                                    before.evidence.observation_trace, before) is False
    assert not bc.evaluate_condition_custody(scenario.e0.observation_contract,
                                            before.evidence.observation_trace, before).violations
    window = _c05_change_window(scenario.e0, lambda c: c.key == binding.key, change)
    step = Environment(scenario.e0).step(before, Action('Drain'), window)
    result = bc.evaluate_condition_custody(scenario.e0.observation_contract,
        step.state.evidence.observation_trace, step.state, before_state=before)
    assert {v.row for v in result.violations} >= {'INV-2.a', 'INV-2.c'}


def test_c05_reached_miss_is_confirmed_but_not_identified(c05_desc_prefix):
    bc = observation_check
    scenario, states, _ = c05_desc_prefix
    before = states[-1]
    window = _c05_change_window(scenario.e0,
        lambda c: c.key.obligation == 'O-05' and c.key.kind == 'handle', 'delete')
    after = Environment(scenario.e0).step(before, Action('Drain'), window).state
    # Normative violation is independently visible, before asking the checker.
    assert bc.observed_end_known(scenario.e0.observation_contract, after.evidence.observation_trace, 'wr')
    assert not any(c.key.obligation == 'O-05' and c.key.kind == 'handle' for c in after.core.p.conditions)
    for complete in (True, False):
        result = bc.contrast_result(normative='違反', detected=False, reached=True, complete=complete)
        assert result == ('確認済み' if complete else '未完', '違反対照の見逃し', '検出できず')
        assert result[2] != '識別力確認済み'  # the prohibited aggregation
    assert bc.contrast_result(normative='合法', detected=False, reached=True, complete=True)[1] == '合法対照を許容'
    assert bc.contrast_result(normative='合法', detected=True, reached=True, complete=True)[1] == '合法対照の誤検出'


def test_c05_51_individual_predicates_and_unknown_stays_in_denominator(c05_desc_prefix):
    bc = observation_check
    predicates = bc.COMPLETION_PREDICATES
    assert len(predicates) == len({cid for cid, _, _ in predicates}) == len({fn for _, fn, _ in predicates}) == 51
    assert {line for _, _, line in predicates} == set(range(1529, 1573)) | set(range(1941, 1948))
    assert bc.classify_custody(None, False, False) == '未接続'
    assert bc.classify_custody(False, False, False) == '削除・消去の違反'
    assert bc.classify_custody(False, False, True) == '未達のまま保全'
    assert bc.classify_custody(True, False, False) == '達成済み'
    assert bc.classify_custody(False, True, False) == '引継ぎ済み'


@pytest.mark.parametrize('branch,reason', (
    ('cells-partial-transfer', 'ConditionCustody/HandoffPurpose carries whole CompletionKey sets; no per-cell A/eta or atomic subset acceptance observation'),
    ('measurement-ended', 'Ended can be Posted, but CMP-04 source/end-reading/reason/evidence -> EI mapping is not connected'),
    ('ended-order', 'firstEnded requires source-confirmed candidates; the public CMP-04/EI/clock correspondence is unconnected, so raw Post/save order cannot decide it'),
    ('same-work-purpose-acceptance', 'public HandoffPurpose requires different owners; no same-P.work local acceptance with separate PurposePart custody'),
))
@pytest.mark.parametrize('control', ('legal', 'violation'))
def test_c05_unconnected_public_contrast_report(branch, reason, control):
    # Explicit denominator, not an invented pass or an unreported omission.
    pytest.skip(f'v0.15 (9-3補-9) {branch}/{control}: 未接続: {reason}')


@pytest.fixture(scope='module')
def c05_finite_delta_path():
    """A-DECL/A-DELTA-FINITE: a fully declared symbolic /1 relation.

    These are model.request records, NOT finite_update Qs with the missing /2
    projection flag removed. Both requests, roots and mappings precede I0.
    """
    import fb_scenes as scenes
    bc = observation_check
    base = publication()
    process, reader, request = (PlanRef('initial', s) for s in ('process', 'reader', 'request'))
    plans, derivations, sources, postings = [], [], [], []
    for name, data in (('a', b'a'), ('b', b'b')):
        source = bc.ReceiptSource('c05-' + name, 'c05-source-' + name, received(data), run=base.run)
        trigger = PlanRef(source.unit, source.slot)
        slot = bc.SlotKey('c05-q-' + name, 'q')
        record = RecordPlan('q', Contract('model.request', '1'), 'Event', obj(purpose='derive', symbol=name))
        work = replace(base.plans[0].works[0], work_id='c05-wr-' + name, stage='Wr',
            purpose='derive', stage_slot=name, process=process, reader=reader, trigger=trigger,
            request=PlanRef(slot.unit, slot.slot), method=Contract('model.delta', '1'),
            args=obj(previous_result=None), input_points=frozenset((trigger,)),
            required=frozenset((trigger, process, reader, PlanRef(slot.unit, slot.slot))))
        plan = AllowedPlan(slot.unit, 'O-03', ('finite-delta', name), (record,), (work,),
                           (Guard('saved', trigger),))
        plans.append(plan)
        sources.append(source)
        postings.append(Posting('c05-' + name, received(data), 1, frozenset((request,)), source.source))
        derivations.append(bc.DerivationBinding(process, '1', process, reader, 'derive', source,
            bc.SlotKey(source.unit, source.slot), name, name, frozenset((name,)), work.method,
            frozenset((trigger,)), frozenset(), frozenset((process, reader, trigger)), None, slot, plan))
    e0 = scenes.fixed(replace(base, plans=base.plans + tuple(plans), postings=base.postings + tuple(postings),
        programs=base.programs + tuple(Program(p.works[0].work_id, (), False) for p in plans),
        receipt_kinds=((0, 'Boot'), (1, 'Received'), (2, 'Received')), observation_declarations=None))
    e0 = replace(e0, observation_declarations=replace(e0.observation_declarations,
        derivations=tuple(derivations), receipt_sources=tuple(sources)))
    scenario = Scenario('C-05-finite-delta', e0, 100)
    states, edges = [Environment(e0).initial()], []
    def take(action):
        return _c05_take(scenario, states, edges, action)
    def save(unit, slot, receipt=False):
        for op in ('PrepareReceipt' if receipt else 'PrepareOne', 'PutBody', 'AddEntry', 'ConfirmWrite', 'CompleteWrite'):
            take(Action(op, (unit, slot)))
    def post_save(name, slots):
        take(Action('Post', (name,)))
        envelope = states[-1].core.h.queue[0]
        take(Action('Accept', (envelope,)))
        take(Action('HostAck', envelope.key))
        for slot in slots:
            save(receipt_unit_id(envelope.run, envelope.number), slot, True)
    post_save('boot', ('boot', 'declaration'))
    take(Action('PublishUnit', ('initial',)))
    for slot in ('process', 'reader', 'request'):
        save('initial', slot)
    for name in ('a', 'b'):
        post_save('c05-' + name, ('receipt',))
        take(Action('PublishUnit', ('c05-q-' + name,)))
    save('c05-q-a', 'q')
    return scenario, states, edges


def test_c05_discharge_delta_is_per_obligation(c05_finite_delta_path):
    bc = observation_check
    scenario, states, edges = c05_finite_delta_path
    state = states[-1]
    contract, trace = scenario.e0.observation_contract, state.evidence.observation_trace
    status = bc.derive_observation_status(contract, trace)
    assert [s.matched for s in status] == [True, True]
    assert [s.discharged for s in status] == [True, False]
    report = check_exploration(scenario, _c05_graph(scenario, states, edges))
    assert not report.violations and not report.contract_violations
    conclusions = {b.key.target.unit: bc.completion_conclusion(b, contract, trace, state)
                   for b in contract.completions if b.key.obligation == 'O-03'}
    assert conclusions == {'c05-q-a': True, 'c05-q-b': False}


@pytest.mark.parametrize('change', ('delete', 'clear'))
def test_c05_discharge_cannot_clear_another_obligation(c05_finite_delta_path, change):
    bc = observation_check
    scenario, states, _ = c05_finite_delta_path
    before = states[-1]
    window = _c05_change_window(scenario.e0,
        lambda c: c.key.obligation == 'O-03' and c.key.target == bc.SlotKey('c05-q-b', 'q'), change)
    after = Environment(scenario.e0).step(before, Action('Drain'), window).state
    result = bc.evaluate_condition_custody(scenario.e0.observation_contract,
        after.evidence.observation_trace, after, before_state=before)
    assert {v.row for v in result.violations} >= {'INV-2.a', 'INV-2.c'}


def test_c05_wr_success_handoff_keeps_unsaved_t():
    import fb_scenes as scenes
    from fb_machine import HandoffRoute
    bc = observation_check
    scene = _c05_scene('SC-04-publish-R-Wp')
    key = next(b.key for b in scene.e0.observation_contract.completions
               if b.key.obligation == 'O-05' and b.key.kind == 'handle')
    scene = replace(scene, e0=replace(scene.e0,
        handoff_routes=(HandoffRoute(key, bc.Owner('P.units', 'result')),)))
    scenario, states, edges, _ = scenes.instantiate(scene)
    states, edges = list(states), list(edges)
    action = next(a for a in _c02_start_actions(scenario.e0, states[-1]) if a.operation == 'HandoffPurpose')
    _c05_take(scenario, states, edges, action)
    after = states[-1]
    result = bc.evaluate_condition_custody(scenario.e0.observation_contract,
        after.evidence.observation_trace, after, before_state=states[-2])
    assert not result.violations
    assert any(j.target == key and j.classification == '引継ぎ済み' for j in result.custody)
    terminal = next(b for b in scenario.e0.observation_contract.completions
                    if b.key.obligation == 'O-05' and b.key.kind == 'save')
    assert not bc.completion_slots_saved(scenario.e0.observation_contract, after.evidence.observation_trace, terminal.slots)
    assert next(c for c in after.core.p.conditions if c.key == terminal.key).unmet
    window = _c05_change_window(scenario.e0, lambda c: c.key == key, 'owner')
    lost = Environment(scenario.e0).step(after, Action('Drain'), window).state
    bad = bc.evaluate_condition_custody(scenario.e0.observation_contract,
        lost.evidence.observation_trace, lost, before_state=after)
    assert {v.row for v in bad.violations} >= {'INV-2.a', 'INV-2.c'}


@pytest.mark.parametrize('change', ('delete', 'clear'))
def test_c05_unknown_cell_a_cannot_hide_independently_unreported_b(change):
    import fb_scenes as scenes
    from fb_machine import Cell
    bc = observation_check
    scene = _c05_scene('SC-04-publish-interval-MeasureSegment')
    occurrence = IntervalOccurrence('c05-part-a', IntervalFact('ReportGenerated', 'k1', 'route-0',
        Reading('run-0', 'M', 0), frozenset((Cell(0, 0),)), None, obj(kind='Unavailable')))
    scene = replace(scene, e0=replace(scene.e0, interval_occurrences=(occurrence,)))
    scenario, states, edges, _ = scenes.instantiate(scene)
    states, edges = list(states), list(edges)
    _c05_take(scenario, states, edges, Action('IntervalEvent', ('c05-part-a',)))
    before = states[-1]
    result = bc.evaluate_condition_custody(scenario.e0.observation_contract,
        before.evidence.observation_trace, before)
    parts = [j for j in result.custody if isinstance(j.target, bc.ConditionPart)]
    assert any(j.target.part == (0, 0) and j.classification == '未接続' for j in parts)
    assert any(j.target.part == (1, 2) and j.classification == '未達のまま保全' for j in parts)
    assert not result.violations
    window = _c05_change_window(scenario.e0,
        lambda c: c.key.obligation == 'O-04' and c.key.kind == 'handle', change)
    after = Environment(scenario.e0).step(before, Action('Drain'), window).state
    bad = bc.evaluate_condition_custody(scenario.e0.observation_contract,
        after.evidence.observation_trace, after, before_state=before)
    assert any(isinstance(v.target, bc.ConditionPart) and v.target.part == (1, 2) for v in bad.violations)
    assert {v.row for v in bad.violations} >= {'INV-2.a', 'INV-2.c'}


@pytest.fixture(scope='module')
def c05_unavailable_released_path():
    import fb_scenes as scenes
    from fb_machine import Report, ReportKind
    bc = observation_check
    scene = _c05_scene('SC-04-publish-interval-MeasureSegment')
    request = scene.e0.intervals[0]
    report = Report(ReportKind.UNAVAILABLE, request.point, 'cannot-measure', request.route_epoch,
        obj(requested_interval=request.interval, reason='sensor-unavailable', evidence=frozenset()))
    posting = Posting('c05-unavailable', Event('SegmentReport', obj(report=report)), 3,
                      frozenset((request.point,)), 'measurement-host')
    e0 = replace(scene.e0, postings=scene.e0.postings + (posting,),
                 programs=(Program(request.work, (), True),), receipt_kinds=((0, 'Boot'), (1, 'SegmentReport')))
    # Preserve the separately authored O-04 undertaking/handle declarations;
    # add only the new EH receipt binding before any execution.
    slot = bc.SlotKey(receipt_unit_id(e0.run, 1), 'receipt')
    receipt = bc.CompletionBinding(bc.CompletionKey('O-01', (e0.run, 1), 'save', slot),
                                  'Post', bc.ReceiptKey(e0.run, 1), (slot,), bc.Owner('H', (e0.run, 1)))
    e0 = replace(e0, observation_declarations=replace(e0.observation_declarations,
                 completions=e0.observation_declarations.completions + (receipt,)))
    scenario, states, edges, _ = scenes.instantiate(replace(scene, e0=e0))
    states, edges = list(states), list(edges)
    def take(action):
        return _c05_take(scenario, states, edges, action)
    for op in ('PrepareOne', 'PutBody', 'AddEntry', 'ConfirmWrite', 'CompleteWrite'):
        take(Action(op, ('segment', 'k')))
    for action in (Action('ResolveWork', (request.work,)), Action('ClaimStart', (request.work,)),
                   Action('Launch', (request.work,)), Action('EnterWorker', (request.work + ':wrapper:0',)),
                   Action('Stop', (request.work,)), Action('Release', (request.work,)),
                   Action('Post', ('c05-unavailable',))):
        take(action)
    envelope = states[-1].core.h.queue[0]
    take(Action('Accept', (envelope,)))
    take(Action('HostAck', envelope.key))
    for op in ('PrepareReceipt', 'PutBody', 'AddEntry', 'ConfirmWrite', 'CompleteWrite'):
        take(Action(op, (slot.unit, slot.slot)))
    return scenario, states, edges


def test_c05_unavailable_and_legal_release_do_not_settle_measurement_run(c05_unavailable_released_path):
    bc = observation_check
    scenario, states, edges = c05_unavailable_released_path
    state = states[-1]
    contract, trace = scenario.e0.observation_contract, state.evidence.observation_trace
    run = next(b for b in contract.completions if b.key.obligation == 'O-04' and b.key.kind == 'run')
    stop = next(b for b in contract.completions if b.key.obligation == 'O-14')
    assert bc.completion_conclusion(stop, contract, trace, state) is True
    assert bc.completion_conclusion(run, contract, trace, state) is False
    assert not any(e.tag == 'Post' and e.value.envelope.event.fields.get('report') is not None
                   and e.value.envelope.event.fields.get('report').kind == 'Ended' for e in trace.events)
    checked = check_exploration(scenario, _c05_graph(scenario, states, edges))
    assert not checked.violations and not checked.contract_violations
    window = _c05_change_window(scenario.e0, lambda c: c.key == run.key, 'clear')
    after = Environment(scenario.e0).step(state, Action('Drain'), window).state
    bad = bc.evaluate_condition_custody(contract, after.evidence.observation_trace, after, before_state=state)
    assert {v.row for v in bad.violations} >= {'INV-2.a', 'INV-2.c'}


def test_c05_missing_issue_adapter_stays_per_instance(c05_finite_delta_path):
    """One mapped issue cannot hide another actual promise of the same schema."""
    bc = observation_check
    original, _, old_edges = c05_finite_delta_path
    contract = original.e0.observation_contract
    saved = next(b for b in contract.completions
                 if b.key.obligation == 'O-03' and b.key.target == bc.SlotKey('c05-q-a', 'q'))
    issue = replace(saved, key=replace(saved.key, kind='issue'))
    # Fix the one new mapping before I0; replay only the original public steps.
    contract = replace(contract, completions=contract.completions + (issue,))
    scenario = replace(original, e0=replace(original.e0, observation_declarations=contract))
    states, edges = [Environment(scenario.e0).initial()], []
    for edge in old_edges:
        _c05_take(scenario, states, edges, edge.action)
    state = states[-1]
    result = bc.evaluate_condition_custody(contract, state.evidence.observation_trace, state)
    missing = [j.target for j in result.custody if isinstance(j.target, bc.UnconnectedCompletion)
               and j.target.condition_id == 'C-O03.issue[Q]']
    assert missing and all(t.witness in (bc.UnitKey('c05-q-b'), bc.SlotKey('c05-q-b', 'q')) for t in missing)
    assert not result.violations


def test_c05_local_discharge_keeps_reconstructible_purpose(c05_wp_unknown_path):
    """Unknown historical acceptance must not force the local row to live forever."""
    bc = observation_check
    scenario, states, _, key, _ = c05_wp_unknown_path
    before = states[-1]
    window = _c05_change_window(scenario.e0, lambda c: c.key == key, 'delete')
    after = Environment(scenario.e0).step(before, Action('Drain'), window).state
    result = bc.evaluate_condition_custody(scenario.e0.observation_contract,
        after.evidence.observation_trace, after, before_state=before)
    local = next(j for j in result.custody if j.target == key)
    purpose = next(j for j in result.custody if isinstance(j.target, bc.PurposePart) and j.target.origin == key)
    assert local.classification == '未接続' and local.transfer is None
    assert purpose.classification == '未達のまま保全' and purpose.direct is False
    assert not result.violations  # no normative success is claimed for the local discharge


def test_c05_same_owner_acceptance_public_step_is_unavailable(c05_wp_unknown_path):
    from fb_machine import HandoffRoute
    bc = observation_check
    scenario, states, _, key, before_handoff = c05_wp_unknown_path
    e0 = replace(scenario.e0, handoff_routes=(HandoffRoute(key, bc.Owner('P.work', key.target.work)),))
    enabled = _c02_start_actions(e0, states[before_handoff])
    assert not any(a.operation == 'HandoffPurpose' for a in enabled)


# C-06 checker-owned tests: occurrence precedes Publish (paper 1203-1241/1586).
@pytest.fixture(scope='module')
def c06_r_prefix():
    import fb_scenes as scenes
    scenario, states, edges, _ = scenes.instantiate(_c05_scene('SC-04-publish-R-Wp'))
    assert len(states) == 52 and edges[-1].action == Action('PublishUnit', ('result',))
    return scenario, states, edges


def _c06_result(scenario, state, before=None):
    return observation_check.evaluate_condition_custody(scenario.e0.observation_contract,
        state.evidence.observation_trace, state, before_state=before)


def _c06_r_key(scenario):
    bc = observation_check
    plan = next(p for p in scenario.e0.observation_contract.plans if p.obligation_id == 'O-06')
    record = next(r for r in plan.records if r.contract.name == 'computation_result')
    return bc.CompletionKey('O-06', plan.key, 'issue', bc.SlotKey(plan.unit, record.slot))


def test_c06_r_occurs_before_publish_then_direct(c06_r_prefix):
    """1241/1540: the original Wr carrier retains R before its own PUB conclusion."""
    scenario, states, edges = c06_r_prefix
    key = _c06_r_key(scenario)
    report = check_exploration(scenario, _c05_graph(scenario, states, edges))
    assert not report.violations and not report.contract_violations
    for index, classification, direct in ((50, '未達のまま保全', False), (51, '達成済み', True)):
        result = _c06_result(scenario, states[index], states[index - 1])
        matching = [j for j in result.custody if j.target == key]
        assert len(matching) == 1
        assert (matching[0].classification, matching[0].direct) == (classification, direct)
        assert not result.violations
    # The issue population must not wait for a window-created condition row.
    assert not any(c.key == key for c in states[50].core.p.conditions)
    assert not any(e.tag == 'Publish' and e.key.unit == key.target.unit
                   for e in states[50].evidence.observation_trace.events)
    assert not any(j.target == key for j in _c06_result(scenario, states[0]).custody)


@pytest.mark.parametrize('change', ('delete', 'clear', 'owner', 'actual-work'))
def test_c06_unpublished_r_cannot_lose_original_carrier(c06_r_prefix, change):
    """1241/1320: deleting the pre-PUB carrier or its unmet loses the issue too."""
    bc = observation_check
    scenario, states, _ = c06_r_prefix
    before = states[50]
    key = _c06_r_key(scenario)
    carrier = next(b for b in scenario.e0.observation_contract.completions
                   if b.key.obligation == 'O-05' and b.key.kind == 'handle')
    if change == 'actual-work':
        class Window(CorrectWindow):
            def drain(self, view):
                decision = super().drain(view)
                return replace(decision, custody=replace(decision.custody,
                    work=tuple(w for w in decision.custody.work if w.descriptor.work_id != carrier.source.work)))
        window = Window(scenario.e0)
    else:
        window = _c05_change_window(scenario.e0, lambda c: c.key == carrier.key, change)
    good = Environment(scenario.e0).step(before, Action('Drain'), CorrectWindow(scenario.e0)).state
    assert not _c06_result(scenario, good, before).violations
    after = Environment(scenario.e0).step(before, Action('Drain'), window).state
    result = _c06_result(scenario, after, before)
    assert not result.boundary.violations
    assert {v.row for v in result.violations if v.target == key} == {'INV-2.a', 'INV-2.c'}
    assert any(j.target == key and j.classification == '削除・消去の違反'
               and j.direct is False for j in result.custody)


@pytest.mark.parametrize('scene_name,operation,unit,cid,witnesses', (
    ('SC-04-publish-initial', 'PublishUnit', 'initial', 'C-O02.issue[initial]',
     (observation_check.UnitKey('initial'),)),
    ('SC-04-publish-Q-Wr', 'PublishUnit', 'q-e1', 'C-O03.issue[Q]',
     (observation_check.SlotKey('q-e1', 'q'),)),
    ('SC-05-structure-p-published', 'PublishUnit', 'proof', 'C-O07.issue[P,Cq]',
     (observation_check.UnitKey('proof'), observation_check.UnitKey('completed'))),
    ('SC-04-publish-G-Wv', 'Acquire', 'acquire-rp', 'C-O08.issue[G]', ()),
))
def test_c06_other_issue_prerequisites_do_not_wait_for_publish(
        scene_name, operation, unit, cid, witnesses, monkeypatch):
    """1203/1205/1216/1218/1586: missing adapters retain exact pre-issuance instances."""
    import fb_scenes as scenes
    bc = observation_check
    scenario, states, edges, _ = scenes.instantiate(_c05_scene(scene_name))
    edge = next(e for e in edges if e.action.operation == operation and e.action.target == (unit,))
    before = states[edge.source]
    if not witnesses:
        witnesses = (scenario.e0.observation_contract.acquisitions[0].key,)
    expected = {bc.UnconnectedCompletion(cid, w) for w in witnesses}

    def check_instances(result):
        present = {j.target: j for j in result.custody}
        assert expected <= present.keys()
        for target in expected:
            item = present[target]
            assert item.classification == '未接続' and item.direct is None and item.transfer is None
            assert item.reasons and all(any(row == inv and repr(target) in reason
                for row, reason in result.limitations) for inv in ('INV-2.a', 'INV-2.c'))
        assert not result.violations

    check_instances(_c06_result(scenario, before, states[edge.source - 1]))
    # This injects the original defect in the checker: omit the observed issue
    # from its denominator. The assertions distinguish contents, not counts.
    original = bc.issue_occurrences
    monkeypatch.setattr(bc, 'issue_occurrences', lambda facts:
        tuple(o for o in original(facts) if o.condition_id != cid))
    with pytest.raises(AssertionError):
        check_instances(_c06_result(scenario, before, states[edge.source - 1]))


def test_c06_ep_issue_without_any_pr_publish():
    """1226/1586: a public Ep/FProblem return exposes the missing full artifact adapter."""
    import fb_scenes as scenes
    bc = observation_check
    scenario, states, edges, _ = scenes.instantiate(_c05_scene('SC-09-structure-artifact-port'))
    states, edges = list(states), list(edges)
    for operation in ('WorkerStep', 'Deliver', 'Accept', 'HostAck', 'PrepareReceipt',
                      'PutBody', 'AddEntry', 'ConfirmWrite', 'CompleteWrite'):
        action = next(a for a in _c02_start_actions(scenario.e0, states[-1]) if a.operation == operation)
        _c05_take(scenario, states, edges, action)
    state = states[-1]
    assert not any(e.tag == 'Publish' and e.value.plan.obligation_id == 'O-10'
                   for e in state.evidence.observation_trace.events)
    target = bc.UnconnectedCompletion('C-O10.issue[artifact,PR]', bc.WorkKey('wr'))
    result = _c06_result(scenario, state, states[-2])
    assert any(j.target == target and j.direct is None and j.classification == '未接続' for j in result.custody)
    assert all(any(row == inv and repr(target) in reason for row, reason in result.limitations)
               for inv in ('INV-2.a', 'INV-2.c'))
    assert not result.violations


def test_c06_wp_unknown_does_not_create_success_issue(c05_wp_unknown_path):
    """1216/1323: the non-success branch must not create an unissued P/Cq obligation."""
    bc = observation_check
    scenario, states, _, _, _ = c05_wp_unknown_path
    result = _c06_result(scenario, states[-1], states[-2])
    assert not any(isinstance(j.target, bc.UnconnectedCompletion)
                   and j.target.condition_id == 'C-O07.issue[P,Cq]' for j in result.custody)
    assert not result.violations


def test_c06_saved_received_without_delta_adapter_remains_visible():
    """1205/1586: absent delta correspondence is an unknown occurrence, not an empty population."""
    import fb_scenes as scenes
    bc = observation_check
    scene = _c05_scene('SC-04-publish-Q-Wr')
    contract = replace(scene.e0.observation_contract, derivations=())
    scene = replace(scene, e0=replace(scene.e0, observation_declarations=contract))
    scenario, states, edges, _ = scenes.instantiate(scene)
    edge = next(e for e in edges if e.action == Action('PublishUnit', ('q-e1',)))
    before = states[edge.source]
    accepted = [e for e in before.evidence.observation_trace.events
                if e.tag == 'Accept' and e.value.envelope.event.kind == 'Received']
    result = _c06_result(scenario, before)
    expected = {bc.UnconnectedCompletion('C-O03.issue[Q]', e.key) for e in accepted}
    assert expected and expected <= {j.target for j in result.custody if j.classification == '未接続'}
    assert all(any(repr(target) in reason for _, reason in result.limitations) for target in expected)
    assert not result.violations


def test_c06_declared_issue_keeps_missing_prepublication_carrier_adapter(c05_finite_delta_path):
    """1584/1586: an E0 issue name does not supply its missing original-carrier mapping."""
    bc = observation_check
    original, _, old_edges = c05_finite_delta_path
    contract = original.e0.observation_contract
    saved = next(b for b in contract.completions
                 if b.key.obligation == 'O-03' and b.key.target == bc.SlotKey('c05-q-a', 'q'))
    issue = replace(saved, key=replace(saved.key, kind='issue'))
    contract = replace(contract, completions=contract.completions + (issue,))
    scenario = replace(original, e0=replace(original.e0, observation_declarations=contract))
    states, edges = [Environment(scenario.e0).initial()], []
    for edge in old_edges:
        if edge.action == Action('PublishUnit', ('c05-q-a',)):
            break
        _c05_take(scenario, states, edges, edge.action)
    result = _c06_result(scenario, states[-1], states[-2])
    item = next(j for j in result.custody if j.target == issue.key)
    assert item.classification == '未接続' and item.direct is False
    assert any('original-carrier adapter' in reason and repr(issue.key) in reason
               for _, reason in result.limitations)
    assert not result.violations


@pytest.mark.parametrize('cid,scene_name,reason', (
    ('C-O11.issue[DF/DU]', 'SC-15-D-stop', 'full PR/FProblem/Draw prefix has no public legal F-a connection'),
    ('C-O12.issue[artifact,EV]', 'SC-15-Ee-stop', 'full DF/Ee/artifact prefix has no public legal F-a connection'),
    ('C-O12.issue[S]', 'SC-09-FProblem-Selected', 'Saved EV/certified Selected prefix has no public legal F-a connection'),
))
def test_c06_unconnected_issue_public_prefix(cid, scene_name, reason):
    """1230/1234/1235/1586: unavailable public prefixes are reported, never counted as passes."""
    import fb_scenes as scenes
    with pytest.raises(ValueError, match='IE/ID'):
        scenes.instantiate(_c05_scene(scene_name))
    pytest.skip(cid + ': ' + reason)


# MG-02 BEGIN: checker-owned v0.18 M3/M4 public-path contrasts.
def _mg02_terminal_e0(stage='D', outcome=None, postings=()):
    """An independent terminal-notice slice, not a claim of F-a validity."""
    from fb_machine import declare_observation_e0
    base = publication()
    work = replace(base.plans[0].works[0], work_id='mg-terminal', stage=stage)
    plan = replace(base.plans[0], works=(work,))
    outcome = outcome or Outcome(OutcomeKind.FAILURE, obj(reason='declared-failure'))
    e0 = replace(base, plans=(plan,), programs=(Program(work.work_id, (outcome,), True),),
                 postings=base.postings + postings, observation_declarations=None,
                 receipt_kinds=((0, 'Boot'), (1, postings[0].event.kind if postings else
                                             'DrawReturned' if stage == 'D' else 'WorkFinished')))
    return replace(e0, observation_declarations=declare_observation_e0(e0))


def _mg02_terminal_path(e0):
    scenario = Scenario('MG-02-terminal', e0, 200)
    states, edges = [Environment(e0).initial()], []
    def take(action, window=None):
        return _c05_take(scenario, states, edges, action, window)
    def save(unit, slot, receipt=False):
        for op in ('PrepareReceipt' if receipt else 'PrepareOne', 'PutBody',
                   'AddEntry', 'ConfirmWrite', 'CompleteWrite'):
            take(Action(op, (unit, slot)))
    def accept_save(slots=('receipt',)):
        envelope = states[-1].core.h.queue[0]
        take(Action('Accept', (envelope,)))
        take(Action('HostAck', envelope.key))
        for slot in slots:
            save(receipt_unit_id(envelope.run, envelope.number), slot, True)
        return envelope
    take(Action('Post', ('boot',)))
    accept_save(('boot', 'declaration'))
    take(Action('PublishUnit', ('initial',)))
    for record in e0.plans[0].records:
        save('initial', record.slot)
    for op in ('ResolveWork', 'ClaimStart', 'Launch'):
        take(Action(op, ('mg-terminal',)))
    take(Action('EnterWorker', ('mg-terminal:wrapper:0',)))
    take(Action('WorkerStep', ('mg-terminal',)))
    return scenario, states, edges, take, save, accept_save


@pytest.mark.parametrize('stage,kind', (('D', 'DrawReturned'), ('Wr', 'WorkFinished')))
@pytest.mark.parametrize('outcome', (
    Outcome(OutcomeKind.RETURNED, obj(value='finite-value')),
    Outcome(OutcomeKind.FAILURE, obj(reason='finite-failure')),
    Outcome(OutcomeKind.UNKNOWN, obj(reason='finite-unknown')),
))
def test_mg02_m4_terminal_family_and_all_outcomes(stage, kind, outcome):
    bc = observation_check
    e0 = _mg02_terminal_e0(stage, outcome)
    scenario, states, edges, take, save, accept_save = _mg02_terminal_path(e0)
    assert bc.observed_end_known(e0.observation_contract, states[-1].evidence.observation_trace,
                                 'mg-terminal') is None
    take(Action('Deliver', ('report:mg-terminal:0',)))
    envelope = accept_save()
    assert envelope.event.kind == kind
    known = bc.observed_end_known(e0.observation_contract, states[-1].evidence.observation_trace,
                                  'mg-terminal')
    assert known[0] == envelope and known[1].outcome == outcome
    take(Action('RecognizeTerminal', ('mg-terminal',)))
    save('terminal:mg-terminal', 'T')
    result = bc.evaluate_condition_custody(e0.observation_contract,
        states[-1].evidence.observation_trace, states[-1])
    assert not result.violations
    run = next(j for j in result.custody if isinstance(j.target, bc.CompletionKey)
               and j.target.kind == 'run' and j.target.target == bc.WorkKey('mg-terminal'))
    assert run.direct is True and run.classification == '達成済み'
    saved = next(j for j in result.custody if isinstance(j.target, bc.CompletionKey)
                 and j.target.kind == 'save' and j.target.target == bc.SlotKey('terminal:mg-terminal', 'T'))
    assert saved.direct is True and saved.classification == '達成済み'
    if stage == 'D' and outcome.kind == OutcomeKind.FAILURE:
        records = [r.header.record.contract.name for r in states[-1].core.e]
        assert 'draw_fact' not in records and 'sui.fb.draw_unknown' not in records
        assert not any(w.descriptor.stage == 'Ee' for w in states[-1].core.p.work)
        assert not any(isinstance(j.target, bc.UnconnectedCompletion)
                       and j.target.condition_id == 'C-O11.issue[DF/DU]' for j in result.custody)
    report = check_exploration(scenario, _c05_graph(scenario, states, edges))
    assert not report.violations and not report.contract_violations


@pytest.mark.parametrize('stage,wrong_kind', (('D', 'WorkFinished'), ('Wr', 'DrawReturned')))
def test_mg02_m4_wrong_family_preserves_receipt_and_unmet_run(stage, wrong_kind):
    from fb_machine import Event
    bc = observation_check
    # Obtain only the public EW readings. Replay from I0 with an independently
    # declared external notice carrying those exact readings and outcome.
    base = _mg02_terminal_e0(stage)
    _, original, _, _, _, _ = _mg02_terminal_path(base)
    generation = next(e.value.generation for e in original[-1].evidence.observation_trace.events
                      if e.tag == 'WorkerReturn')
    fields = dict(work='mg-terminal', outcome=generation.outcome)
    if wrong_kind == 'WorkFinished':
        fields.update(started=generation.started, finished=generation.finished)
    posting = Posting('mg-wrong-family', Event(wrong_kind, obj(**fields)),
                      generation.finished.rank, source=generation.provenance)
    e0 = _mg02_terminal_e0(stage, postings=(posting,))
    scenario, states, edges, take, _, accept_save = _mg02_terminal_path(e0)
    take(Action('Post', ('mg-wrong-family',)))
    envelope = accept_save()
    before = states[-1]
    assert bc.observed_end_known(e0.observation_contract, before.evidence.observation_trace,
                                 'mg-terminal') is None
    result = bc.evaluate_condition_custody(e0.observation_contract, before.evidence.observation_trace, before)
    assert not result.violations
    target = next(j.target for j in result.custody if isinstance(j.target, bc.CompletionKey)
                  and j.target.kind == 'run' and j.target.target == bc.WorkKey('mg-terminal'))
    assert next(j for j in result.custody if j.target == target).classification == '未達のまま保全'
    receipt = [j for j in result.custody if isinstance(j.target, bc.CompletionKey)
               and j.target.obligation == 'O-01' and j.target.obligation_key == envelope.key]
    assert receipt and all(j.direct is True for j in receipt)
    # Public bad Drain output, applied by Environment.step; no patched state.
    take(Action('Drain'), _c05_change_window(e0, lambda c: c.key == target, 'delete'))
    bad = bc.evaluate_condition_custody(e0.observation_contract,
        states[-1].evidence.observation_trace, states[-1], before_state=before)
    assert {v.row for v in bad.violations if v.target == target} == {'INV-2.a', 'INV-2.c'}
    assert next(j for j in bad.custody if j.target == target).classification == '削除・消去の違反'


@pytest.mark.parametrize('family', ('draw_fact', 'sui.fb.draw_unknown', 'Ee'))
@pytest.mark.parametrize('failure', (False, True))
def test_mg02_m4_draw_failure_forbids_each_successor(family, failure):
    from fb_machine import declare_observation_e0
    bc = observation_check
    kind = (OutcomeKind.FAILURE if failure else OutcomeKind.UNKNOWN
            if family == 'sui.fb.draw_unknown' else OutcomeKind.RETURNED)
    base = _mg02_terminal_e0(outcome=Outcome(kind, obj(reason='fixed-terminal-case')))
    # A finite terminal-family slice, not a claim of F-a mathematical validity.
    # On Failure this is an invalid downstream recipe, declared before I0. Its
    # publication through the public port cannot acquire normative authority.
    work = replace(base.plans[0].works[0], work_id='mg-illegal-ee', stage='Ee')
    followup = AllowedPlan('mg-illegal-followup', 'O-11', ('mg-terminal',),
        (RecordPlan('record', Contract('model.followup' if family == 'Ee' else family, '1'),
                    'Event', obj(value='not-a-draw-result')),),
        (work,) if family == 'Ee' else (), (Guard('first', 'mg-terminal'),))
    e0 = replace(base, plans=base.plans + (followup,), observation_declarations=None)
    e0 = replace(e0, observation_declarations=declare_observation_e0(e0))
    _, states, _, take, _, accept_save = _mg02_terminal_path(e0)
    take(Action('Deliver', ('report:mg-terminal:0',)))
    accept_save()
    before = states[-1]
    assert not bc.check_m4_draw_followups(e0.observation_contract, before.evidence.observation_trace).clauses
    take(Action('PublishUnit', (followup.unit,)))
    result = bc.check_m4_draw_followups(e0.observation_contract, states[-1].evidence.observation_trace)
    clauses = result.clauses
    assert not result.limitations
    assert len(clauses) == 1
    assert clauses[0].row == 'INV-15.b' and clauses[0].satisfied is (not failure)
    assert clauses[0].target == (bc.WorkKey('mg-terminal'), bc.UnitKey(followup.unit))
# MG-02 END: checker-owned additions.


# MG-02 M3 BEGIN: independent declarations from the published wire contract.
def _mg02_generation_e0(branch='Candidates', wait=None, draws=(), typed_cg=False, eq_context_wait=False,
                        preferences='single', multiple_inputs=False, parameter=7, reply_parameter=None):
    from fb_machine import FieldRole, ReferencePath, Source, TypedReference, declare_observation_e0
    base = publication()
    model, pref, context = (PlanRef('initial', s) for s in ('model', 'preferences', 'context'))
    if eq_context_wait:
        context = PlanRef('mg-context', 'context')
    extra = PlanRef('initial', 'preference-b')
    inputs = (model, extra) if multiple_inputs else (model,)
    preference = (pref,) if preferences == 'singleton' else (pref, extra) if preferences == 'multiple' else pref
    preference_refs = preference if isinstance(preference, tuple) else (preference,)
    request, candidate, evaluation = PlanRef('initial', 'request'), PlanRef('mg-cg', 'cg'), PlanRef('mg-eq', 'eq')
    wg = replace(base.plans[0].works[0], work_id='mg-wg', stage='Wg',
        purpose='generate-and-compare', stage_slot='generation', request=request,
        trigger=PlanRef('initial', 'process'),
        method=Contract('model.internal-generator', '1'), output_contract=Contract('sui.fb.candidate_generation', '1'),
        args=obj(draws=draws, parameter=parameter), input_points=frozenset(inputs),
        numerical_view=NumericalView(frozenset(inputs), tuple(reversed(inputs)), obj(model=model, generation_basis=inputs)),
        need=(('think', 1),), required=frozenset((*inputs, request)),
        permissions=frozenset((pref, context)) if multiple_inputs else frozenset())
    # Deliberately do not call candidate_request_content or checker constructors.
    qgen = obj(process=wg.process, trigger=wg.trigger, reader=wg.reader, purpose=wg.purpose,
        stage_slot=wg.stage_slot, method=wg.method, output_contract=wg.output_contract,
        args=wg.args, input_points=tuple(sorted(wg.input_points, key=repr)),
        numerical_view=obj(points=tuple(sorted(wg.numerical_view.points, key=repr)),
            application_order=wg.numerical_view.application_order, context=wg.numerical_view.context),
        allocation=wg.allocation, need=wg.need, permissions=tuple(sorted(wg.permissions, key=repr)))
    declaration = obj(model=model, input_order=('generated-a', 'generated-b'), measure=None,
        generation=obj(generator=wg.method, args=wg.args if reply_parameter is None
                       else obj(draws=draws, parameter=reply_parameter), basis=inputs, draws=draws),
        continuation=obj(after=()))
    eq_content = obj(candidates=candidate, reader=wg.reader, model=model,
                     preferences=preference, context=context, o=(), j=())
    ep = replace(wg, work_id='mg-ep', stage='Ep', stage_slot='evaluation', request=evaluation,
        method=Contract('model.evaluate', '1'), output_contract=Contract('model.artifact', '1'),
        input_points=frozenset((candidate, *preference_refs, context)),
        numerical_view=NumericalView(frozenset((model, *preference_refs, context)), (pref, model), obj(model=model, context=context)),
        required=frozenset((evaluation, candidate, model, *preference_refs, context)))
    roles = []
    def record(slot, contract, content, *, reference_content=None, category='Event'):
        references = []
        def walk(value, path=()):
            if isinstance(value, PlanRef):
                name = 'MG-02-' + contract.name + '-' + repr(path)
                roles.append(FieldRole(contract, name, path, 'UE', 'generation'))
                references.append(TypedReference(name, path, value, 'UE', 'generation'))
            elif isinstance(value, Object):
                for key, item in value.items: walk(item, path + (key,))
            elif isinstance(value, (tuple, frozenset)):
                for i, item in enumerate(value): walk(item, path + (i,))
        walk(content if reference_content is None else reference_content)
        return RecordPlan(slot, contract, category, content, tuple(references))
    records = tuple(r for r in base.plans[0].records if r.slot != 'request') + tuple(
        RecordPlan(s, Contract('model.' + s, '1'), 'Event', obj(symbol=s))
        for s in (('model', 'preferences', 'context', 'preference-b')
                  if multiple_inputs or preferences == 'multiple' else ('model', 'preferences', 'context'))) + (
        record('request', Contract('sui.fb.candidate_request', '1'), qgen),)
    initial = replace(base.plans[0], records=records, works=(wg,))
    cg = AllowedPlan('mg-cg', 'O-G', ('generation', wg.work_id),
        (record('cg', Contract('candidate_declaration', '1'), Source('candidate_declaration', wg.work_id),
                reference_content=declaration if typed_cg else obj(), category='Prediction'),), (), (Guard('generation', wg.work_id),))
    missing = PlanRef('mg-context', 'context')
    guards = (Guard('evaluation', wg.work_id, candidate),)
    if wait:
        guards += (Guard(wait, missing),)
    eq = AllowedPlan('mg-eq', 'O-G', ('evaluation', wg.work_id),
        (record('eq', Contract('sui.fb.evaluation_request', '1'), eq_content),), (ep,), guards)
    later = AllowedPlan('mg-context', 'O-02', ('context',),
        (RecordPlan('context', Contract('model.context', '1'), 'Event', obj(symbol='later-context')),))
    outcome = (Outcome(OutcomeKind.RETURNED, obj(variant='Candidates', declaration=declaration)) if branch == 'Candidates'
               else Outcome(OutcomeKind.RETURNED, obj(variant='NoCandidates', basis=obj(reason='none-for-input')))
               if branch == 'NoCandidates' else Outcome(OutcomeKind(branch), obj(reason=branch)))
    e0 = replace(base, plans=(initial, cg, eq, later), programs=(Program(wg.work_id, (outcome,), True), Program(ep.work_id)),
        field_roles=base.field_roles + tuple(roles), receipt_kinds=((0, 'Boot'), (1, 'WorkFinished')),
        references=base.references + tuple(ReferencePath(r.path_id,
            (r.record_contract.name + '/' + r.record_contract.version,),
            ('.'.join(map(str, r.path)),), r.role, r.use, 'declared_identity_only') for r in roles),
        observation_declarations=None)
    return replace(e0, observation_declarations=declare_observation_e0(e0))


def _mg02_generation_path(e0, through='end'):
    scenario = Scenario('MG-02-generation', e0, 200)
    states, edges = [Environment(e0).initial()], []
    def take(action, window=None):
        try:
            return _c05_take(scenario, states, edges, action, window)
        except Exception as error:
            raise RuntimeError(f'{action}: {type(error).__name__}: {error}') from None
    def save(unit, slot, receipt=False):
        for op in ('PrepareReceipt' if receipt else 'PrepareOne', 'PutBody', 'AddEntry', 'ConfirmWrite', 'CompleteWrite'):
            take(Action(op, (unit, slot)))
    def accept_save(slots):
        envelope = states[-1].core.h.queue[0]
        take(Action('Accept', (envelope,))); take(Action('HostAck', envelope.key))
        for slot in slots: save(receipt_unit_id(envelope.run, envelope.number), slot, True)
    take(Action('Post', ('boot',))); accept_save(('boot', 'declaration'))
    take(Action('PublishUnit', ('initial',)))
    if through == 'initial': return scenario, states, edges, take, save
    for r in e0.plans[0].records: save('initial', r.slot)
    for op in ('ResolveWork', 'ClaimStart', 'Launch'): take(Action(op, ('mg-wg',)))
    take(Action('EnterWorker', ('mg-wg:wrapper:0',)))
    if through == 'entered': return scenario, states, edges, take, save
    take(Action('WorkerStep', ('mg-wg',))); take(Action('Deliver', ('report:mg-wg:0',)))
    accept_save(('receipt',))
    if through == 'end': return scenario, states, edges, take, save
    take(Action('RecognizeTerminal', ('mg-wg',)))
    if through == 'terminal': return scenario, states, edges, take, save
    take(Action('PublishUnit', ('mg-cg',)))
    if through == 'cg': return scenario, states, edges, take, save
    save('mg-cg', 'cg')
    if through == 'saved-cg': return scenario, states, edges, take, save
    take(Action('PublishUnit', ('mg-eq',)))
    if through == 'eq': return scenario, states, edges, take, save
    save('mg-eq', 'eq')
    return scenario, states, edges, take, save


def test_mg02_generation_public_input_contract():
    e0 = _mg02_generation_e0(typed_cg=True)
    try:
        scenario, states, edges, _, _ = _mg02_generation_path(e0, 'saved-eq')
    except Exception as error:
        pytest.fail(type(error).__name__ + ': ' + str(error), pytrace=False)
    assert {w.descriptor.work_id for w in states[-1].core.p.work} == {'mg-wg', 'mg-ep'}
    assert any(e.header.record.contract.name == 'candidate_declaration' for e in states[-1].core.e)
    assert any(e.header.record.contract.name == 'sui.fb.evaluation_request' for e in states[-1].core.e)
    result = observation_check.evaluate_generation_custody(e0.observation_contract,
        states[-1].evidence.observation_trace, states[-1])
    assert not result.violations, result.violations
    report = check_exploration(scenario, _c05_graph(scenario, states, edges))
    assert not report.contract_violations, report.contract_violations
    assert not report.violations, report.violations


def _mg02_result(e0, state, before=None):
    return observation_check.evaluate_generation_custody(e0.observation_contract,
        state.evidence.observation_trace, state, before_state=before)


def _mg02_change(e0, change):
    class Changed(CorrectWindow):
        def drain(self, view):
            decision = super().drain(view)
            return replace(decision, custody=change(decision.custody), effects=())
    return Changed(e0)


@pytest.mark.parametrize('cid,branch,through', (
    ('C-OG.run[Wg]', 'Candidates', 'initial'),
    ('C-OG.save[T]', 'Candidates', 'end'),
    ('C-OG.handle[Wg]', 'Failure', 'end'),
    ('C-OG.issue[CG]', 'Candidates', 'terminal'),
    ('C-OG.save[CG]', 'Candidates', 'cg'),
    ('C-OG.issue[EQ]', 'Candidates', 'cg'),
    ('C-OG.save[EQ]', 'Candidates', 'eq'),
))
@pytest.mark.parametrize('change', ('delete', 'clear', 'owner'))
def test_mg02_seven_conditions_own_positive_and_negative(cid, branch, through, change):
    bc = observation_check
    e0 = _mg02_generation_e0(branch)
    _, states, _, take, _ = _mg02_generation_path(e0, through)
    before = states[-1]
    f = bc.GenerationFacts(e0.observation_contract, before.evidence.observation_trace, before)
    fn = next(fn for name, fn, _ in bc.GENERATION_PREDICATES if name == cid)
    binding = f.bindings(e0.plans[0].works[0])[fn]
    good = _mg02_result(e0, before)
    assert not good.violations, good.violations
    own = next(j for j in good.custody if j.target == binding.key)
    assert own.classification == ('引継ぎ済み' if cid == 'C-OG.handle[Wg]' else '未達のまま保全')
    if cid == 'C-OG.handle[Wg]':
        # Local handle may be removed after Transfer. The violation is removal
        # of the accepted residual's real carrier, not removal of a settled row.
        take(Action('Drain'), _mg02_change(e0, lambda c: replace(c, work=tuple(
            replace(w, descriptor=replace(w.descriptor, purpose='discarded-original'), purposes=()) for w in c.work))))
    else:
        take(Action('Drain'), _c05_change_window(e0, lambda c: c.key == binding.key, change))
    bad = _mg02_result(e0, states[-1], before)
    own = next(j for j in bad.custody if j.target == binding.key)
    assert own.direct is False and own.transfer is False
    assert own.classification == '削除・消去の違反'
    assert any(v.row == 'INV-2.g' and v.target == binding.key for v in bad.violations)


@pytest.mark.parametrize('branch', ('NoCandidates', 'Failure', 'Unknown'))
@pytest.mark.parametrize('change', ('delete', 'rename'))
def test_mg02_non_success_residual_has_original_identity_and_never_direct(branch, change):
    bc = observation_check
    e0 = _mg02_generation_e0(branch)
    _, states, _, take, _ = _mg02_generation_path(e0, 'terminal')
    before = states[-1]
    good = _mg02_result(e0, before)
    assert not good.violations, good.violations
    purposes = [j for j in good.custody if isinstance(j.target, bc.PurposePart)]
    assert len(purposes) == 1
    purpose = purposes[0]
    assert purpose.direct is False and purpose.classification == '未達のまま保全'
    assert purpose.target.origin == bc.CompletionKey('O-G', ('work', 'mg-wg'), 'run', bc.WorkKey('mg-wg'))
    assert purpose.target.part == PlanRef('initial', 'request')
    assert not any(u.id in ('mg-cg', 'mg-eq') for u in before.core.p.units)
    assert {w.descriptor.work_id for w in before.core.p.work} == {'mg-wg'}
    def alter(custody):
        if change == 'delete': return replace(custody, work=tuple(replace(w,
            descriptor=replace(w.descriptor, purpose='discarded-original'), purposes=()) for w in custody.work))
        def changed(work):
            return replace(work, purposes=tuple(replace(x, obligation_key=replace(x.obligation_key,
                origin=replace(x.obligation_key.origin, obligation_key=('renamed',)))) for x in work.purposes))
        return replace(custody, work=tuple(changed(w) for w in custody.work))
    take(Action('Drain'), _mg02_change(e0, alter))
    bad = _mg02_result(e0, states[-1], before)
    assert any(v.row == 'INV-2.g' and v.target == purpose.target for v in bad.violations)
    assert next(j for j in bad.custody if j.target == purpose.target).direct is False


@pytest.mark.parametrize('wait,expected_pg', ((None, False), ('saved', False), ('generation_context', True)))
def test_mg02_issue_eq_birth_is_not_readiness_or_save_wait(wait, expected_pg):
    bc = observation_check
    e0 = _mg02_generation_e0(wait=wait)
    _, states, _, take, save = _mg02_generation_path(e0, 'cg')
    for saved in (False, True):
        if saved: save('mg-cg', 'cg')
        state = states[-1]
        result = _mg02_result(e0, state)
        assert not result.violations, result.violations
        f = bc.GenerationFacts(e0.observation_contract, state.evidence.observation_trace, state)
        b = f.bindings(e0.plans[0].works[0])[bc.direct_og_issue_eq]
        own = next(j for j in result.custody if j.target == b.key)
        assert own.direct is False and own.classification == '未達のまま保全'
        purposes = [j for j in result.custody if isinstance(j.target, bc.PurposePart)]
        assert bool(purposes) is expected_pg
        if expected_pg:
            assert purposes[0].direct is False and purposes[0].classification == '未達のまま保全'
    if wait:
        with pytest.raises(RuntimeError, match='Disabled'):
            take(Action('PublishUnit', ('mg-eq',)))
        take(Action('PublishUnit', ('mg-context',)))
        save('mg-context', 'context')
    take(Action('PublishUnit', ('mg-eq',)))
    result = _mg02_result(e0, states[-1])
    assert not result.violations, result.violations
    assert bool([j for j in result.custody if isinstance(j.target, bc.PurposePart)]) is expected_pg


def test_mg02_inv16c_whole_qgen_detects_changed_argument_not_just_count():
    bc = observation_check
    e0 = _mg02_generation_e0()
    _, states, _, take, _ = _mg02_generation_path(e0, 'initial')
    before = states[-1]
    assert not _mg02_result(e0, before).violations
    def alter(custody):
        def slot(s):
            if s.plan.slot != 'request': return s
            fields = dict(s.plan.content.items)
            fields['args'] = obj(draws=(), parameter=8)
            return replace(s, plan=replace(s.plan, content=obj(**fields)))
        return replace(custody, units=tuple(replace(u, slots=tuple(slot(s) for s in u.slots))
                                             if u.id == 'initial' else u for u in custody.units))
    take(Action('Drain'), _mg02_change(e0, alter))
    bad = _mg02_result(e0, states[-1], before)
    assert any(v.row == 'INV-16.c' and v.target == bc.SlotKey('initial', 'request')
               and 'changed a field' in v.message for v in bad.violations)


def test_mg02_typed_cg_public_preparation_contract():
    # Paper 859-860: a first preparation must match both the independent plan
    # and its body/reference correspondence; a consistent codec is not enough.
    bc = observation_check
    e0 = _mg02_generation_e0(typed_cg=True)
    scenario, states, edges, take, _ = _mg02_generation_path(e0, 'cg')
    assert not _mg02_result(e0, states[-1]).violations
    take(Action('PrepareOne', ('mg-cg', 'cg')))
    trace = states[-1].evidence.observation_trace
    key = bc.SlotKey('mg-cg', 'cg')
    event = next(e for e in trace.events if e.tag == 'FirstPrepare' and e.key == key)
    first = event.value.prepared
    model = dict(first.record.content.items)['model']
    generation = dict(dict(first.record.content.items)['generation'].items)
    assert {(r.path, r.ref) for r in first.record.references} == {
        (('model',), model), (('generation', 'basis', 0), generation['basis'][0])}
    assert isinstance(model, Point) and generation['basis'] == (model,)
    report = check_exploration(scenario, _c05_graph(scenario, states, edges))
    assert not report.contract_violations and not report.violations, report

    # Counterfactual checker input, not a state claimed reachable at the window.
    # Replace one reference with a different Saved Point; keep the body and
    # reference count, and recompute all bytes/seal/header/CID independently.
    pref = next(e.point for e in trace.entries if e.header.record.contract.name == 'model.preferences')
    wrong_record = replace(first.record, references=tuple(
        replace(r, ref=pref) if r.path == ('model',) else r for r in first.record.references))
    wrong = _handmade_prepared(wrong_record, first.parents, first.salt)
    assert wrong.record.content == first.record.content and pref != model
    assert bc.ledger_saved(pref, trace, e0.observation_contract.codec)
    assert bc.prepared_consistent(wrong, e0.observation_contract.codec)
    bad_trace = replace(trace, origin=None, events=tuple(
        replace(e, value=replace(e.value, prepared=wrong)) if e is event else e for e in trace.events))
    bad = bc.evaluate_observations(e0.observation_contract, bad_trace)
    assert not bad.boundary.violations, bad.boundary.violations
    assert any(v.row == 'INV-4.c' and v.target == key
               and v.message == 'first preparation differs from independent permitted plan/codec'
               for v in bad.violations)


@pytest.mark.parametrize('draws', (('needs-RG',), None))
def test_mg02_d6_random_generation_remains_unconnected(draws):
    e0 = _mg02_generation_e0(draws=draws)
    _, states, _, _, _ = _mg02_generation_path(e0, 'initial')
    result = _mg02_result(e0, states[-1])
    assert any(row == 'INV-16.c' and 'R10/D6' in reason for row, reason in result.limitations)
    assert not result.violations, result.violations
    with pytest.raises(RuntimeError, match='MissingContract'):
        _mg02_generation_path(e0, 'entered')
    before = states[-1]
    def coerce(c):
        return replace(c, work=tuple(replace(w, descriptor=replace(w.descriptor,
            args=obj(draws=(), parameter=7))) for w in c.work))
    scenario = Scenario('MG-02-D6-coercion', e0, 200)
    _c05_take(scenario, states, [], Action('Drain'), _mg02_change(e0, coerce))
    bad = _mg02_result(e0, states[-1], before)
    assert any(v.row == 'INV-16.c' and v.target == observation_check.WorkKey('mg-wg')
               and 'coerced' in v.message for v in bad.violations)


def test_mg02_seven_distinct_direct_conclusions_and_handle_transfer():
    bc = observation_check
    e0 = _mg02_generation_e0()
    _, states, _, take, save = _mg02_generation_path(e0, 'terminal')
    unit = next(u for u in states[-1].core.p.units if u.id == 'terminal:mg-wg')
    for slot in unit.slots: save(unit.id, slot.plan.slot)
    take(Action('PublishUnit', ('mg-cg',)))
    save('mg-cg', 'cg')
    take(Action('PublishUnit', ('mg-eq',)))
    save('mg-eq', 'eq')
    result = _mg02_result(e0, states[-1])
    assert not result.violations, result.violations
    f = bc.GenerationFacts(e0.observation_contract, states[-1].evidence.observation_trace, states[-1])
    bindings = f.bindings(e0.plans[0].works[0])
    for cid, fn, _ in bc.GENERATION_PREDICATES:
        own = next(j for j in result.custody if j.target == bindings[fn].key)
        assert own.direct is (cid != 'C-OG.handle[Wg]'), (cid, own)
        assert own.transfer is (cid == 'C-OG.handle[Wg]'), (cid, own)


@pytest.mark.parametrize('through,wait', (('initial', None), ('entered', None), ('cg', 'saved')))
def test_mg02_no_residual_for_delivery_or_predecessor_save_wait(through, wait):
    from fb_machine import Excuse
    bc = observation_check
    e0 = _mg02_generation_e0(wait=wait)
    _, states, _, take, _ = _mg02_generation_path(e0, through)
    before = states[-1]
    good = _mg02_result(e0, before)
    assert not good.violations and not any(isinstance(j.target, bc.PurposePart) for j in good.custody)
    if through != 'cg':
        assert {j.target.kind for j in good.custody if isinstance(j.target, bc.CompletionKey)} == {'run'}
    f = bc.GenerationFacts(e0.observation_contract, before.evidence.observation_trace, before)
    part = f.purpose(e0.plans[0].works[0])
    invented = Excuse('O-G', part, 'mere delivery/save wait', obj(reason='not-a-use-shortage'), frozenset(), ('pG',))
    take(Action('Drain'), _mg02_change(e0, lambda c: replace(c,
        work=tuple(replace(w, purposes=w.purposes + (invented,)) for w in c.work))))
    result = _mg02_result(e0, states[-1], before)
    assert any(v.row == 'INV-2.g' and v.target == part and 'invented' in v.message for v in result.violations)


@pytest.mark.parametrize('field', ('descriptor', 'candidate', 'evaluation', 'purpose'))
def test_mg02_continuation_reconstructs_original_identity(field):
    bc = observation_check
    e0 = _mg02_generation_e0(wait='generation_context')
    _, states, _, take, _ = _mg02_generation_path(e0, 'saved-cg')
    before = states[-1]
    assert not _mg02_result(e0, before).violations
    def alter(c):
        def unit(u):
            if u.id != 'mg-cg': return u
            g = u.generation
            value = (replace(g.descriptor, purpose='other') if field == 'descriptor' else
                     replace(g.purpose, origin=replace(g.purpose.origin, obligation_key=('other',))) if field == 'purpose' else
                     PlanRef('other', field))
            return replace(u, generation=replace(g, **{field: value}))
        return replace(c, units=tuple(unit(u) for u in c.units))
    take(Action('Drain'), _mg02_change(e0, alter))
    bad = _mg02_result(e0, states[-1], before)
    assert any(v.row == 'INV-2.g' and 'cannot reconstruct' in v.message and
               v.target == bc.UnitKey('mg-cg') for v in bad.violations)


def test_mg02_saved_conflicting_return_preserves_commitments_and_original_pg():
    from fb_machine import declare_observation_e0
    bc = observation_check
    base = _mg02_generation_e0()
    first = base.programs[0].replies[0]
    second = Outcome(OutcomeKind.FAILURE, obj(reason='later-conflicting-return'))
    program = replace(base.programs[0], replies=(first, second))
    e0 = replace(base, programs=(program, base.programs[1]),
        receipt_kinds=((0, 'Boot'), (1, 'WorkFinished'), (2, 'WorkFinished')), observation_declarations=None)
    e0 = replace(e0, observation_declarations=declare_observation_e0(e0))
    _, states, _, take, save = _mg02_generation_path(e0, 'cg')
    take(Action('WorkerStep', ('mg-wg',)))
    take(Action('Deliver', ('report:mg-wg:1',)))
    envelope = states[-1].core.h.queue[0]
    take(Action('Accept', (envelope,))); take(Action('HostAck', envelope.key))
    save(receipt_unit_id(envelope.run, envelope.number), 'receipt', True)
    result = _mg02_result(e0, states[-1])
    assert not result.violations, result.violations
    purposes = [j for j in result.custody if isinstance(j.target, bc.PurposePart)]
    assert len(purposes) == 1 and purposes[0].direct is False
    assert any(j.target == bc.CompletionKey('O-G', ('generation', 'mg-wg'), 'save', bc.SlotKey('mg-cg', 'cg'))
               and j.classification == '未達のまま保全' for j in result.custody)
    save('mg-cg', 'cg')
    with pytest.raises(RuntimeError, match='Disabled'):
        take(Action('PublishUnit', ('mg-eq',)))


@pytest.mark.parametrize('cid', tuple(cid for cid, _, _ in observation_check.GENERATION_PREDICATES))
def test_mg02_missing_e0_condition_adapter_stays_in_denominator(cid):
    bc = observation_check
    base = _mg02_generation_e0()
    initial = Environment(base).initial()
    f = bc.GenerationFacts(base.observation_contract, initial.evidence.observation_trace, initial)
    fn = next(fn for name, fn, _ in bc.GENERATION_PREDICATES if name == cid)
    omitted = f.bindings(base.plans[0].works[0])[fn]
    declared = replace(base.observation_contract,
        completions=tuple(b for b in base.observation_contract.completions if b != omitted))
    e0 = replace(base, observation_declarations=declared)
    _, states, _, _, _ = _mg02_generation_path(e0, 'initial')
    result = _mg02_result(e0, states[-1])
    gap = next(j for j in result.custody if isinstance(j.target, bc.UnconnectedCompletion)
               and j.target.condition_id == cid)
    assert gap.target.witness == bc.WorkKey('mg-wg') and gap.classification == '未接続'
    assert gap.direct is None and gap.transfer is None and gap.reasons
    assert any(cid in reason for _, reason in result.limitations)


def test_mg02_unknown_generation_use_contract_is_not_a_false_conclusion():
    from fb_machine import declare_observation_e0
    bc = observation_check
    base = _mg02_generation_e0()
    cg = replace(base.plans[1], semantic_limits=('MG-02-unconnected-use-contract',))
    e0 = replace(base, plans=(base.plans[0], cg, *base.plans[2:]), observation_declarations=None)
    e0 = replace(e0, observation_declarations=declare_observation_e0(e0))
    _, states, _, _, _ = _mg02_generation_path(e0, 'end')
    result = _mg02_result(e0, states[-1])
    f = bc.GenerationFacts(e0.observation_contract, states[-1].evidence.observation_trace, states[-1])
    target = f.bindings(e0.plans[0].works[0])[bc.direct_og_issue_cg].key
    own = next(j for j in result.custody if j.target == target)
    assert own.classification == '未接続' and own.direct is None
    p = next(j for j in result.custody if isinstance(j.target, bc.PurposePart))
    assert p.classification == '未接続' and p.direct is False
    assert not result.violations, result.violations


@pytest.mark.parametrize('cid,through,owner', (
    ('C-OG.run[Wg]', 'initial', observation_check.Owner('P.units', 'initial')),
    ('C-OG.save[T]', 'end', observation_check.Owner('P.units', 'initial')),
    ('C-OG.issue[CG]', 'terminal', observation_check.Owner('P.units', 'initial')),
    ('C-OG.save[CG]', 'cg', observation_check.Owner('P.work', 'mg-wg')),
    ('C-OG.issue[EQ]', 'cg', observation_check.Owner('P.work', 'mg-wg')),
    ('C-OG.save[EQ]', 'eq', observation_check.Owner('P.work', 'mg-wg')),
))
def test_mg02_existing_but_wrong_owner_is_not_a_valid_carrier(cid, through, owner):
    bc = observation_check
    e0 = _mg02_generation_e0()
    _, states, _, take, _ = _mg02_generation_path(e0, through)
    before = states[-1]
    f = bc.GenerationFacts(e0.observation_contract, before.evidence.observation_trace, before)
    fn = next(fn for name, fn, _ in bc.GENERATION_PREDICATES if name == cid)
    key = f.bindings(e0.plans[0].works[0])[fn].key
    assert not _mg02_result(e0, before).violations
    assert bc.actual_owner_exists(before, owner)
    take(Action('Drain'), _mg02_change(e0, lambda c: replace(c, conditions=tuple(
        replace(row, owner=owner) if row.key == key else row for row in c.conditions))))
    bad = _mg02_result(e0, states[-1], before)
    assert any(v.row == 'INV-2.g' and v.target == key for v in bad.violations)
# MG-02 M3 END.


# MG-02 follow-up 3 BEGIN: repaired contracts and missing save-wait contrast.
@pytest.mark.parametrize('field', ('model', 'generation_basis'))
def test_mg02_unresolved_actual_input_context_is_rejected(field):
    # Paper 870: actual input, including nested context, must equal the fixed
    # resolved input. This input to the checker retains just one recipe field.
    bc = observation_check
    e0 = _mg02_generation_e0(typed_cg=True)
    _, states, _, _, _ = _mg02_generation_path(e0, 'entered')
    trace = states[-1].evidence.observation_trace
    good = bc.evaluate_observations(e0.observation_contract, trace)
    assert not good.boundary.violations and not good.violations, good
    event = next(e for e in trace.events if e.tag == 'ReadInputs' and e.key.work == 'mg-wg')
    actual = event.value.numerical_view
    model = dict(actual.context.items)['model']
    assert isinstance(model, Point) and dict(actual.context.items)['generation_basis'] == (model,)
    context = dict(actual.context.items)
    context[field] = PlanRef('initial', 'model') if field == 'model' else (PlanRef('initial', 'model'),)
    wrong = replace(actual, context=obj(**context))
    assert (wrong.points, wrong.application_order) == (actual.points, actual.application_order)
    bad_trace = replace(trace, origin=None, events=tuple(
        replace(e, value=replace(e.value, numerical_view=wrong)) if e is event else e for e in trace.events))
    bad = bc.evaluate_observations(e0.observation_contract, bad_trace)
    assert not bad.boundary.violations, bad.boundary.violations
    assert {(v.row, v.target, v.message) for v in bad.violations} == {
        ('INV-8.b', (trace.events.index(event), event.key),
         'actual descriptor/numerical input differs from E0 fixed values')}


@pytest.mark.parametrize('carrier', ('Wg', 'CG'))
def test_mg02_eq_body_point_save_wait_rejects_unnecessary_pg(carrier):
    # Paper 1935,1946,1959: an EQ content Point waiting for its predecessor's
    # save is not a generation_context shortage. Do not add either wait guard.
    from fb_machine import Excuse
    bc = observation_check
    e0 = _mg02_generation_e0(typed_cg=True, eq_context_wait=True)
    eq = next(p for p in e0.plans if p.unit == 'mg-eq')
    assert tuple(g.kind for g in eq.guards) == ('evaluation',)
    assert dict(eq.records[0].content.items)['context'] == PlanRef('mg-context', 'context')
    scenario, states, edges, take, save = _mg02_generation_path(e0, 'saved-cg')
    before = states[-1]
    good = _mg02_result(e0, before)
    assert not good.violations, good.violations
    assert not any(isinstance(j.target, bc.PurposePart) for j in good.custody)
    continuation = next(u.generation for u in before.core.p.units if u.id == 'mg-cg')
    assert not continuation.shortages
    assert not any(w.purposes for w in before.core.p.work)
    issue_eq = bc.CompletionKey('O-G', ('work', 'mg-wg'), 'issue', bc.SlotKey('mg-eq', 'eq'))
    own = next(j for j in good.custody if j.target == issue_eq)
    assert own.direct is False and own.classification == '未達のまま保全'
    with pytest.raises(RuntimeError, match='Disabled'):
        take(Action('PublishUnit', ('mg-eq',)))

    # Original pG identity from paper 1959, not from checker/window birth flags.
    d = e0.plans[0].works[0]
    part = bc.PurposePart(bc.CompletionKey('O-G', ('work', d.work_id), 'run', bc.WorkKey(d.work_id)),
        (d.purpose, d.process, d.reader, d.request, d.stage_slot), d.request)
    invented = Excuse('O-G', part, 'mere predecessor save wait', obj(waiting=PlanRef('mg-context', 'context')),
                      frozenset(), ('pG',))
    custody = before.core.p
    if carrier == 'Wg':
        custody = replace(custody, work=tuple(replace(w, purposes=(invented,))
            if w.descriptor.work_id == d.work_id else w for w in custody.work))
    else:
        custody = replace(custody, units=tuple(replace(u, generation=replace(u.generation, shortages=(invented,)))
            if u.id == 'mg-cg' else u for u in custody.units))
    # Frozen checker input only: do not feed this state back into Environment.
    counterfactual = replace(before, core=replace(before.core, p=custody))
    bad = _mg02_result(e0, counterfactual, before)
    assert any(v.row == 'INV-2.g' and v.target == part
               and v.message == 'pG was invented for delivery/save wait or has changed its original target'
               for v in bad.violations)
    assert not any(isinstance(j.target, bc.PurposePart) for j in bad.custody)

    # Continue the unchanged real path: saving that Point permits EQ without pG.
    take(Action('PublishUnit', ('mg-context',)))
    save('mg-context', 'context')
    take(Action('PublishUnit', ('mg-eq',)))
    save('mg-eq', 'eq')
    report = check_exploration(scenario, _c05_graph(scenario, states, edges))
    assert not report.contract_violations and not report.violations, report
    assert not any(isinstance(j.target, bc.PurposePart) for j in _mg02_result(e0, states[-1]).custody)
# MG-02 follow-up 3 END



# Pre-commit review FBM3-R01/R02 BEGIN (sui-fb-model-review3).
@pytest.mark.parametrize('context_at,expected_pg', (('entered', False), ('end', True), ('saved-cg', True)))
def test_fbm3_r01_context_shortage_at_endknown_keeps_pg_even_if_saved_before_cg(context_at, expected_pg):
    # Paper 1956/1959, D3: a declared EQ-use shortage seen after EndKnown(Wg)
    # enters the pG branch then; saving the context before CG PUB keeps it.
    bc = observation_check
    e0 = _mg02_generation_e0(wait='generation_context', eq_context_wait=True, typed_cg=True)
    scenario, states, edges, take, save = _mg02_generation_path(e0, context_at)
    def context():
        take(Action('PublishUnit', ('mg-context',)))
        save('mg-context', 'context')
    context()
    if context_at == 'entered':
        take(Action('WorkerStep', ('mg-wg',))); take(Action('Deliver', ('report:mg-wg:0',)))
        envelope = states[-1].core.h.queue[0]
        take(Action('Accept', (envelope,))); take(Action('HostAck', envelope.key))
        save(receipt_unit_id(envelope.run, envelope.number), 'receipt', True)
    if context_at != 'saved-cg':
        take(Action('RecognizeTerminal', ('mg-wg',)))
        take(Action('PublishUnit', ('mg-cg',)))
        save('mg-cg', 'cg')
    take(Action('PublishUnit', ('mg-eq',)))
    save('mg-eq', 'eq')
    result = _mg02_result(e0, states[-1])
    assert not result.violations, result.violations
    purposes = [j for j in result.custody if isinstance(j.target, bc.PurposePart)]
    assert bool(purposes) is expected_pg
    assert all(j.direct is False and j.classification == '未達のまま保全' for j in purposes)
    assert any(w.purposes for w in states[-1].core.p.work if w.descriptor.work_id == 'mg-wg') is expected_pg
    report = check_exploration(scenario, _c05_graph(scenario, states, edges))
    assert not report.contract_violations and not report.violations, report


@pytest.mark.parametrize('reply', ('same-point', 'other-point'))
def test_fbm3_r02_generation_args_compare_resolved_planrefs(reply):
    # Paper 583/1006/1933: a PlanRef in Wg args is fixed and resolved once; the
    # reply carrying that resolved Point is not a changed argument, another
    # Saved Point is. The literal-argument control is the default helper path.
    from fb_machine import Point
    bc = observation_check
    model = PlanRef('initial', 'model')
    # Both Points are in Wg's actual input read; only the reply's choice differs.
    e0 = _mg02_generation_e0(typed_cg=True, multiple_inputs=True, parameter=model,
                             reply_parameter=None if reply == 'same-point' else PlanRef('initial', 'preference-b'))
    assert e0.plans[0].works[0].args.get('parameter') == model
    if reply == 'other-point':
        scenario, states, edges, take, _ = _mg02_generation_path(e0, 'terminal')
        with pytest.raises(RuntimeError, match='Disabled'):
            take(Action('PublishUnit', ('mg-cg',)))
        return
    scenario, states, edges, _, _ = _mg02_generation_path(e0, 'saved-eq')
    cg = next(e.header.record for e in states[-1].core.e if e.header.record.contract.name == 'candidate_declaration')
    parameter = cg.content.get('generation').get('args').get('parameter')
    assert isinstance(parameter, Point) and parameter.cid
    result = _mg02_result(e0, states[-1])
    assert not result.violations, result.violations
    assert not any(isinstance(j.target, bc.PurposePart) for j in result.custody)
    assert not any(w.purposes for w in states[-1].core.p.work)
    report = check_exploration(scenario, _c05_graph(scenario, states, edges))
    assert not report.contract_violations and not report.violations, report
# Pre-commit review FBM3-R01/R02 END


# Post-commit review FBM3-R03 BEGIN (sui-fb-model-review3, window side).
@pytest.mark.parametrize('where', (None, 'eq', 'cg'))
def test_fbm3_r03_issue_cg_birth_waits_for_cg_generation_context(where):
    # 1327/1937/1956: issue[CG] is born only when the CG use conditions hold.
    # A CG-side shortage leaves handle with Wg; an EQ-side one does not delay it.
    from fb_machine import declare_observation_e0
    e0 = _mg02_generation_e0(wait='generation_context' if where == 'eq' else None)
    if where == 'cg':  # the same concrete shortage, declared on CG itself
        cg_wait = Guard('generation_context', PlanRef('mg-context', 'context'))
        e0 = replace(e0, plans=tuple(replace(q, guards=q.guards + (cg_wait,)) if q.unit == 'mg-cg' else q
                                     for q in e0.plans), observation_declarations=None)
        e0 = replace(e0, observation_declarations=declare_observation_e0(e0))
    _, states, _, take, save = _mg02_generation_path(e0, 'end')
    issue = observation_check.CompletionKey('O-G', ('work', 'mg-wg'), 'issue', observation_check.SlotKey('mg-cg', 'cg'))
    def born():
        state = states[-1]
        row = any(c.key == issue for c in state.core.p.conditions)
        assert row is (issue in state.evidence.condition_births)
        assert not _mg02_result(e0, state).violations
        return row
    assert born() is (where != 'cg')
    take(Action('RecognizeTerminal', ('mg-wg',)))
    assert born() is (where != 'cg')
    if where == 'cg':
        with pytest.raises(RuntimeError, match='Disabled'):
            take(Action('PublishUnit', ('mg-cg',)))
        take(Action('PublishUnit', ('mg-context',)))
        assert born() is False
        save('mg-context', 'context')
        assert born() is True
    take(Action('PublishUnit', ('mg-cg',)))
    assert born() is True
# Post-commit review FBM3-R03 END

# MG-02 follow-up 4 BEGIN: MG05-C independent public-contract contrasts.
@pytest.mark.parametrize('shape', ('single', 'singleton', 'multiple'))
def test_mg05_preferences_reference_members_and_fixed_content(shape):
    # Paper 861,1935,1937; public EQ wire: preserve tuple order but check each Ref.
    bc = observation_check
    e0 = _mg02_generation_e0(typed_cg=True, preferences=shape)
    scenario, states, edges, _, _ = _mg02_generation_path(e0, 'saved-eq')
    report = check_exploration(scenario, _c05_graph(scenario, states, edges))
    assert not report.contract_violations, report.contract_violations
    assert not report.violations, tuple((v.condition_id, v.message, v.target) for v in report.violations)
    trace = states[-1].evidence.observation_trace
    event = next(e for e in trace.events if e.tag == 'Publish' and e.key == bc.UnitKey('mg-eq'))
    record = event.value.plan.records[0]
    content = dict(record.content.items)
    actual = content['preferences']
    pref = next(e.point for e in trace.entries if e.header.record.contract.name == 'model.preferences')
    if shape == 'single':
        assert actual == pref
    elif shape == 'singleton':
        assert actual == (pref,)
    else:
        extra = next(e.point for e in trace.entries if e.header.record.contract.name == 'model.preference-b')
        assert actual == (pref, extra) and pref != extra

    # Frozen checker input: different Saved preference, same tuple/scalar shape
    # and cardinality. E0 remains unchanged; count-only comparison would miss it.
    other = content['context']
    assert other != pref
    content['preferences'] = (other, *actual[1:]) if isinstance(actual, tuple) else other
    wrong = replace(event.value.plan, records=(replace(record, content=obj(**content)),))
    bad_trace = replace(trace, origin=None, events=tuple(
        replace(e, value=replace(e.value, plan=wrong)) if e is event else e for e in trace.events))
    bad = bc.evaluate_generation_custody(e0.observation_contract, bad_trace, states[-1])
    assert any(v.row == 'INV-16.c' and v.target == bc.UnitKey('mg-eq')
               and 'full corresponding' in v.message for v in bad.violations)


def test_mg05_multiple_qgen_refs_keep_sets_and_application_order_separate():
    bc = observation_check
    e0 = _mg02_generation_e0(typed_cg=True, multiple_inputs=True)
    scenario, states, edges, _, _ = _mg02_generation_path(e0, 'saved-eq')
    report = check_exploration(scenario, _c05_graph(scenario, states, edges))
    assert not report.contract_violations, report.contract_violations
    assert not report.violations, report.violations
    d = e0.plans[0].works[0]
    assert d.input_points == frozenset((PlanRef('initial', 'model'), PlanRef('initial', 'preference-b')))
    assert d.numerical_view.application_order == (PlanRef('initial', 'preference-b'), PlanRef('initial', 'model'))
    assert d.permissions == frozenset((PlanRef('initial', 'preferences'), PlanRef('initial', 'context')))
    # Mismatched pre-execution declarations are checker inputs, not window runs.
    for field in ('input_points', 'points', 'permissions', 'application_order'):
        q = next(r for r in e0.plans[0].records if r.slot == 'request')
        content, numerical = dict(q.content.items), dict(dict(q.content.items)['numerical_view'].items)
        if field == 'application_order':
            numerical[field] = tuple(reversed(numerical[field]))
        elif field == 'points':
            numerical[field] = (numerical[field][0], numerical[field][0])
        else:
            content[field] = (content[field][0], content[field][0])
        content['numerical_view'] = obj(**numerical)
        initial = replace(e0.plans[0], records=tuple(replace(r, content=obj(**content)) if r is q else r
                                                   for r in e0.plans[0].records))
        contract = replace(e0.observation_contract, plans=tuple(initial if p.unit == initial.unit else p
                                                               for p in e0.observation_contract.plans))
        bad = bc.evaluate_generation_custody(contract, states[-1].evidence.observation_trace, states[-1])
        assert any(v.row == 'INV-16.c' and v.target == bc.WorkKey('mg-wg')
                   and 'whole fixed Wg descriptor' in v.message for v in bad.violations), field


@pytest.mark.parametrize('missing_index', (0, 1))
def test_mg05_each_preference_must_belong_to_ep_input_set(missing_index):
    # A self-consistent E0/EU declaration can still violate the paper's EQ/Ep
    # correspondence. Merely skipping preferences would pass the other contrast.
    bc = observation_check
    e0 = _mg02_generation_e0(typed_cg=True, preferences='multiple')
    _, states, _, _, _ = _mg02_generation_path(e0, 'eq')
    before = states[-1]
    assert not _mg02_result(e0, before).violations
    plan = next(p for p in e0.plans if p.unit == 'mg-eq')
    ep = plan.works[0]
    preferences = dict(plan.records[0].content.items)['preferences']
    missing = preferences[missing_index]
    assert missing in ep.input_points and missing in ep.numerical_view.points
    bad_ep = replace(ep, input_points=ep.input_points - {missing},
                     numerical_view=replace(ep.numerical_view, points=ep.numerical_view.points - {missing}))
    bad_plan = replace(plan, works=(bad_ep,))
    contract = replace(e0.observation_contract,
        plans=tuple(bad_plan if p.unit == plan.unit else p for p in e0.observation_contract.plans),
        descriptors=tuple(bad_ep if d.work_id == ep.work_id else d for d in e0.observation_contract.descriptors))
    trace = before.evidence.observation_trace
    trace = replace(trace, origin=None, events=tuple(
        replace(e, value=replace(e.value, plan=replace(e.value.plan, works=(bad_ep,))))
        if e.tag == 'Publish' and e.key == bc.UnitKey(plan.unit) else e for e in trace.events))
    state = replace(before, core=replace(before.core, p=replace(before.core.p,
        work=tuple(replace(w, descriptor=bad_ep) if w.descriptor.work_id == ep.work_id else w
                   for w in before.core.p.work))), evidence=replace(before.evidence, observation_trace=trace))
    # Frozen checker input only. The window must not execute this bad declaration.
    bad = bc.evaluate_generation_custody(contract, trace, state)
    assert any(v.row == 'INV-16.c' and v.target == bc.UnitKey(plan.unit)
               and 'full corresponding' in v.message for v in bad.violations), missing


def test_mg05_upstream_conflict_blocks_entry_but_not_responsibility():
    from fb_machine import declare_observation_e0
    bc = observation_check
    base = _mg02_generation_e0(typed_cg=True)
    replies = (*base.programs[0].replies, Outcome(OutcomeKind.FAILURE, obj(reason='independent-later-failure')))
    e0 = replace(base, capacity=(('think', 2),), allocation=(('think', 2),),
        programs=(replace(base.programs[0], replies=replies), base.programs[1]),
        receipt_kinds=((0, 'Boot'), (1, 'WorkFinished'), (2, 'WorkFinished')), observation_declarations=None)
    e0 = replace(e0, observation_declarations=declare_observation_e0(e0))
    scenario, states, edges, take, save = _mg02_generation_path(e0, 'saved-eq')
    for op in ('ResolveWork', 'ClaimStart', 'Launch'):
        take(Action(op, ('mg-ep',)))
    ready = states[-1]
    entry = Action('EnterWorker', ('mg-ep:wrapper:0',))
    offered = _c02_start_actions(e0, ready)
    assert entry in offered
    assert not _c02_start_result(e0, ready, offered).violations
    missing = _c02_start_result(e0, ready, tuple(a for a in offered if a != entry))
    assert any(v.message == 'ready launched work lacks EnterWorker' and v.target == 'mg-ep'
               for v in missing.violations)

    take(Action('WorkerStep', ('mg-wg',)))
    take(Action('Deliver', ('report:mg-wg:1',)))
    envelope = states[-1].core.h.queue[0]
    take(Action('Accept', (envelope,))); take(Action('HostAck', envelope.key))
    unsaved = states[-1]
    offered = _c02_start_actions(e0, unsaved)
    assert entry in offered  # EW return/receipt claims alone are not Saved Reports.
    missing = _c02_start_result(e0, unsaved, tuple(a for a in offered if a != entry))
    assert any(v.message == 'ready launched work lacks EnterWorker' and v.target == 'mg-ep'
               for v in missing.violations)
    save(receipt_unit_id(envelope.run, envelope.number), 'receipt', True)
    blocked = states[-1]
    assert entry not in _c02_start_actions(e0, blocked)
    with pytest.raises(RuntimeError, match='Disabled'):
        take(entry)
    assert not any(e.tag == 'EnterBody' and e.key.work == 'mg-ep' for e in blocked.evidence.observation_trace.events)
    held, wrappers, entered, _, _ = bc.actual_start_history(blocked.evidence.observation_trace)
    assert 'mg-ep' not in entered and wrappers['mg-ep'] == {'mg-ep:wrapper:0'}
    assert any(k.work == 'mg-ep' and resources == (('think', 1),) for k, resources in held.items())
    report = check_exploration(scenario, _c05_graph(scenario, states, edges))
    assert not report.contract_violations, report.contract_violations
    assert not report.violations, tuple((v.condition_id, v.message, v.target) for v in report.violations)
# MG-02 follow-up 4 END


# MG-02 follow-up 5 BEGIN: INV-16.c Qgen versus actual EW input, before CG/EQ.
@pytest.mark.parametrize('field', (
    'args', 'reader', 'input_points', 'numerical_points', 'application_order', 'numerical_context',
))
def test_mg06_inv16c_actual_wg_read_matches_fixed_qgen(field):
    # Paper 1004,1006,1931,1961: the full request/actual-generation relation
    # already applies at entry. A later return or CG/EQ is not its trigger.
    bc = observation_check
    e0 = _mg02_generation_e0(typed_cg=True, multiple_inputs=True)
    scenario, states, edges, _, _ = _mg02_generation_path(e0, 'entered')
    report = check_exploration(scenario, _c05_graph(scenario, states, edges))
    assert not report.contract_violations, report.contract_violations
    assert not report.violations, report.violations
    state = states[-1]
    trace = state.evidence.observation_trace
    event = next(e for e in trace.events if e.tag == 'ReadInputs' and e.key.work == 'mg-wg')
    assert any(e.tag == 'EnterBody' and e.key == event.key for e in trace.events)
    assert not any(e.tag == 'WorkerReturn' for e in trace.events)
    assert not any(e.tag == 'Publish' and e.key in (bc.UnitKey('mg-cg'), bc.UnitKey('mg-eq'))
                   for e in trace.events)
    qgen = next(e.header.record for e in trace.entries
                if e.header.record.contract.name == 'sui.fb.candidate_request')
    content = dict(qgen.content.items)
    numerical = dict(content['numerical_view'].items)
    actual = event.value
    assert actual.descriptor.args == content['args'] == obj(draws=(), parameter=7)
    assert actual.descriptor.reader == content['reader']
    assert actual.descriptor.input_points == frozenset(content['input_points'])
    assert actual.descriptor.numerical_view == actual.numerical_view
    assert actual.numerical_view.points == frozenset(numerical['points'])
    assert actual.numerical_view.application_order == numerical['application_order']
    assert actual.numerical_view.context == numerical['context']
    assert not _mg02_result(e0, state).violations

    # Counterfactual checker input only: keep E0, Qgen, all Saved records and
    # resolution evidence fixed. Change one logical field of the actual read.
    # For a numerical field, both EW copies agree, so mere self-consistency
    # checking cannot detect this mismatch with the independently fixed Qgen.
    alternate = next(e.point for e in trace.entries
                     if e.header.record.contract.name == 'model.preferences')
    view = actual.numerical_view
    assert alternate not in view.points and alternate != actual.descriptor.reader
    first, second = view.application_order
    assert first != second and view.points == frozenset((first, second))
    if field == 'args':
        wrong = replace(actual, descriptor=replace(actual.descriptor, args=obj(draws=(), parameter=8)))
    elif field == 'reader':
        wrong = replace(actual, descriptor=replace(actual.descriptor, reader=alternate))
    elif field == 'input_points':
        wrong = replace(actual, descriptor=replace(actual.descriptor,
            input_points=(actual.descriptor.input_points - {first}) | {alternate}))
    else:
        if field == 'numerical_points':
            changed = replace(view, points=(view.points - {first}) | {alternate})
        elif field == 'application_order':
            changed = replace(view, application_order=(second, first))
        else:
            context = dict(view.context.items)
            context['model'] = alternate
            changed = replace(view, context=obj(**context))
        wrong = replace(actual, descriptor=replace(actual.descriptor, numerical_view=changed),
                        numerical_view=changed)
    assert wrong != actual and wrong.resolutions == actual.resolutions
    bad_trace = replace(trace, origin=None, events=tuple(
        replace(e, value=wrong) if e is event else e for e in trace.events))
    bad_state = replace(state, evidence=replace(state.evidence, observation_trace=bad_trace))
    observed = bc.evaluate_observations(e0.observation_contract, bad_trace)
    target = (trace.events.index(event), event.key)
    assert not observed.boundary.violations, observed.boundary.violations
    assert {(v.row, v.target, v.message) for v in observed.violations} == {
        ('INV-8.b', target, 'actual descriptor/numerical input differs from E0 fixed values')}
    checked = bc.evaluate_generation_custody(e0.observation_contract, bad_trace, bad_state)
    assert {(v.row, v.target, v.message) for v in checked.violations} == {
        ('INV-16.c', target, 'actual Wg input differs from the fixed Qgen descriptor/numerical view')}
# MG-02 follow-up 5 END


# MG-02 follow-up 6 BEGIN: FBM3-R03 excess occurrence.
def _r03_claim(e0, binding):
    from fb_machine import ConditionCustody
    bc = observation_check
    row = ConditionCustody(binding.key, binding.owner, frozenset((binding.key,)))
    return _mg02_change(e0, lambda custody: replace(custody,
        conditions=tuple(c for c in custody.conditions if c.key != binding.key) + (row,)))


def _r03_e0(where=None):
    from fb_machine import declare_observation_e0
    e0 = _mg02_generation_e0(typed_cg=True, wait='generation_context' if where == 'eq' else None)
    if where == 'cg':
        e0 = replace(e0, plans=tuple(replace(p,
            guards=p.guards + (Guard('generation_context', PlanRef('mg-context', 'context')),))
            if p.unit == 'mg-cg' else p for p in e0.plans), observation_declarations=None)
        e0 = replace(e0, observation_declarations=declare_observation_e0(e0))
    return e0


@pytest.mark.parametrize('where', (None, 'eq', 'cg'))
def test_r03_generation_waits_have_no_excess_occurrence(where):
    # 1944/1946/1956: EQ readiness is not issue[CG] birth, nor issue[EQ] birth.
    bc = observation_check
    e0 = _r03_e0(where)
    scenario, states, edges, take, save = _mg02_generation_path(e0, 'end')
    key = bc.CompletionKey('O-G', ('work', 'mg-wg'), 'issue', bc.SlotKey('mg-cg', 'cg'))
    def assert_birth(expected):
        state = states[-1]
        assert any(c.key == key for c in state.core.p.conditions) is expected
        assert (key in state.evidence.condition_births) is expected
        assert not _mg02_result(e0, state).violations
    assert_birth(where != 'cg')
    take(Action('RecognizeTerminal', ('mg-wg',)))
    assert_birth(where != 'cg')
    if where == 'cg':
        with pytest.raises(RuntimeError, match='Disabled'):
            take(Action('PublishUnit', ('mg-cg',)))
        take(Action('PublishUnit', ('mg-context',)))
        assert_birth(False)
        save('mg-context', 'context')
        assert_birth(True)
    take(Action('PublishUnit', ('mg-cg',)))
    assert_birth(True)
    report = check_exploration(scenario, _c05_graph(scenario, states, edges))
    assert not report.contract_violations and not report.violations, report


def test_r03_cg_wait_cannot_claim_issue_cg_even_with_an_owner():
    bc = observation_check
    e0 = _r03_e0('cg')
    scenario, states, edges, _, _ = _mg02_generation_path(e0, 'end')
    before = states[-1]
    binding = next(b for b in e0.observation_contract.completions if b.key.obligation == 'O-G'
                   and b.key.kind == 'issue' and b.key.target == bc.SlotKey('mg-cg', 'cg'))
    assert not any(c.key == binding.key for c in before.core.p.conditions)
    good = Environment(e0).step(before, Action('Drain'), CorrectWindow(e0)).state
    assert not _mg02_result(e0, good, before).violations
    after = Environment(e0).step(before, Action('Drain'), _r03_claim(e0, binding)).state
    assert any(c.key == binding.key and c.owner == bc.Owner('P.work', 'mg-wg')
               and c.unmet == frozenset((binding.key,)) for c in after.core.p.conditions)
    result = _mg02_result(e0, after, before)
    assert {(v.row, v.target) for v in result.violations
            if v.message == 'condition claimed before independent occurrence'} == {
        (row, binding.key) for row in ('INV-2.g', 'INV-2.a', 'INV-2.c')}
    # A previous invented claim cannot legitimate itself on the next edge.
    again = Environment(e0).step(after, Action('Drain'), _r03_claim(e0, binding)).state
    assert any(v.row == 'INV-2.g' and v.target == binding.key
               and v.message == 'condition claimed before independent occurrence'
               for v in _mg02_result(e0, again, after).violations)


_R03_OG = (
    ('run', 'work', 'mg-wg', 1941), ('save', 'terminal:mg-wg', 'T', 1942),
    ('handle', 'work', 'mg-wg', 1943), ('issue', 'mg-cg', 'cg', 1944),
    ('save', 'mg-cg', 'cg', 1945), ('issue', 'mg-eq', 'eq', 1946),
    ('save', 'mg-eq', 'eq', 1947),
)


@pytest.mark.parametrize('kind,unit,target,paper_line', _R03_OG)
def test_r03_each_og_condition_rejects_a_claim_before_its_trigger(kind, unit, target, paper_line):
    bc = observation_check
    e0 = _r03_e0()
    identity = bc.WorkKey(target) if unit == 'work' else bc.SlotKey(unit, target)
    binding = next(b for b in e0.observation_contract.completions
                   if b.key.obligation == 'O-G' and b.key.kind == kind and b.key.target == identity)
    before = Environment(e0).initial()
    if kind == 'handle':
        # Public transport needs the real Wg carrier; EndKnown is still absent.
        _, states, _, _, _ = _mg02_generation_path(e0, 'initial')
        before = states[-1]
    good = Environment(e0).step(before, Action('Drain'), CorrectWindow(e0)).state
    assert not _mg02_result(e0, good).violations
    after = Environment(e0).step(before, Action('Drain'), _r03_claim(e0, binding)).state
    result = _mg02_result(e0, after, before)
    assert any(v.row == 'INV-2.g' and v.target == binding.key
               and v.message == 'condition claimed before independent occurrence'
               for v in result.violations), (paper_line, result)


# The population and expected branches below come from 1206-1243, not a
# completion predicate's return value. Each negative is a public Drain subclass.
_R03_REGISTERED = (
    ('C-O01.save[receipt_slot]', 1206, 'SC-04-publish-initial', 'O-01', 'save', None),
    ('C-O02.save[\u5404slot]', 1208, 'SC-04-publish-initial', 'O-02', 'save', ('initial', 'process')),
    ('C-O03.save[Q]', 1210, 'SC-04-publish-Q-Wr', 'O-03', 'save', ('q-e1', 'q')),
    ('C-O04.save[k]', 1211, 'SC-04-publish-interval-MeasureSegment', 'O-04', 'save', ('segment', 'k')),
    ('C-O04.run[MeasureSegment]', 1212, 'SC-04-publish-interval-MeasureSegment', 'O-04', 'run', None),
    ('C-O04.handle[cells]', 1213, 'SC-04-publish-interval-MeasureSegment', 'O-04', 'handle', None),
    ('C-O05.run[Wr]', 1214, 'SC-04-publish-initial', 'O-05', 'run', None),
    ('C-O05.save[T]', 1215, 'SC-04-publish-initial', 'O-05', 'save', None),
    ('C-O05.handle[Wr]', 1215, 'SC-04-publish-initial', 'O-05', 'handle', None),
    ('C-O06.save[R]', 1217, 'SC-04-publish-R-Wp', 'O-06', 'save', None),
    ('C-O07.run[Wp]', 1218, 'SC-04-publish-R-Wp', 'O-07', 'run', None),
    ('C-O07.save[T]', 1219, 'SC-04-publish-R-Wp', 'O-07', 'save', ('terminal:wp', 'T')),
    ('C-O07.handle[Wp]', 1219, 'SC-04-publish-R-Wp', 'O-07', 'handle', None),
    ('C-O07.save[P]', 1221, 'SC-04-publish-R-Wp', 'O-07', 'save', ('proof', 'p')),
    ('C-O07.save[Cq]', 1221, 'SC-04-publish-R-Wp', 'O-07', 'save', ('completed', 'c')),
    ('C-O08.save[G]', 1223, 'SC-04-publish-G-Wv', 'O-08', 'save', ('acquisition', 'g')),
    ('C-O09a.run[Wv]', 1224, 'SC-04-publish-G-Wv', 'O-09.a', 'run', None),
    ('C-O09a.save[T]', 1225, 'SC-04-publish-G-Wv', 'O-09.a', 'save', ('terminal:wv', 'T')),
    ('C-O09b.save[\u51e6\u7406slot]', 1227, 'SC-04-publish-G-Wv', 'O-09.b', 'save', None),
    ('C-O10.run[Ep]', 1228, 'SC-09-structure-artifact-port', 'O-10', 'run', None),
    ('C-O10.save[T]', 1229, 'SC-09-structure-artifact-port', 'O-10', 'save', None),
    ('C-O14.stop[w]', 1243, 'SC-04-publish-initial', 'O-14', 'stop', None),
)


@pytest.mark.parametrize('cid,paper_line,scene,obligation,kind,slot', _R03_REGISTERED)
def test_r03_registered_condition_rejects_premature_claim(cid, paper_line, scene, obligation, kind, slot):
    bc = observation_check
    e0 = _c05_scene(scene).e0
    binding = next(b for b in e0.observation_contract.completions
                   if b.key.obligation == obligation and b.key.kind == kind
                   and (slot is None or b.key.target == bc.SlotKey(*slot)))
    before = Environment(e0).initial()
    good = Environment(e0).step(before, Action('Drain'), CorrectWindow(e0)).state
    result = bc.evaluate_condition_custody(e0.observation_contract, good.evidence.observation_trace, good)
    assert not result.boundary.violations and not result.violations, (cid, result)
    bad = Environment(e0).step(before, Action('Drain'), _r03_claim(e0, binding)).state
    result = bc.evaluate_condition_custody(e0.observation_contract, bad.evidence.observation_trace, bad)
    assert {(v.row, v.target) for v in result.violations
            if v.message == 'condition claimed before independent occurrence'} == {
        ('INV-2.a', binding.key), ('INV-2.c', binding.key)}, (cid, paper_line, result)


_R03_EXTRA = (
    ('C-O02.issue[initial]', 1207, 'SC-04-publish-initial', 'O-02', 'issue', 'initial', 'q', None),
    ('C-O03.issue[Q]', 1209, 'SC-04-publish-Q-Wr', 'O-03', 'issue', 'q-e1', 'q', None),
    ('C-O06.issue[R]', 1216, 'SC-04-publish-R-Wp', 'O-06', 'issue', 'result', 'r', 'wr'),
    ('C-O07.issue[P,Cq]', 1220, 'SC-04-publish-R-Wp', 'O-07', 'issue', 'proof', 'p', 'wp'),
    ('C-O08.issue[G]', 1222, 'SC-04-publish-G-Wv', 'O-08', 'issue', 'acquisition', 'g', None),
    ('C-O09a.save[V]', 1225, 'SC-04-publish-G-Wv', 'O-09.a', 'save', 'verification:wv', 'V', 'wv'),
    ('C-O09b.handle[\u76ee\u7684]', 1226, 'SC-04-publish-G-Wv', 'O-09.b', 'handle', 'acquisition', 'g', 'wv'),
)


def _r03_extra_binding(case):
    bc = observation_check
    cid, line, scene, obligation, kind, unit, slot, work = case
    e0 = _c05_scene(scene).e0
    contract = e0.observation_contract
    plan = next(p for p in contract.plans if p.unit == unit)
    target = bc.WorkKey(work) if kind == 'handle' else bc.SlotKey(unit, slot)
    source = bc.WorkKey(work) if work else bc.UnitKey(unit)
    trigger = 'EndKnown' if work else 'Publish'
    if obligation == 'O-08':
        source, trigger = contract.acquisitions[0].key, 'Acquire'
    if kind == 'handle':
        source, trigger = bc.UnitKey(unit), 'Publish'
    binding = bc.CompletionBinding(bc.CompletionKey(obligation, plan.key, kind, target),
        trigger, source, (bc.SlotKey(unit, slot),),
        bc.Owner('P.work', work) if work else bc.Owner('P.units', unit))
    contract = replace(contract, completions=contract.completions + (binding,))
    return replace(e0, observation_declarations=contract), binding


@pytest.mark.parametrize('case', _R03_EXTRA, ids=lambda case: case[0])
def test_r03_additional_declared_condition_rejects_premature_claim(case):
    bc = observation_check
    e0, binding = _r03_extra_binding(case)  # fixed before I0; no observation copied
    before = Environment(e0).initial()
    good = Environment(e0).step(before, Action('Drain'), CorrectWindow(e0)).state
    assert not bc.evaluate_condition_custody(e0.observation_contract,
        good.evidence.observation_trace, good).violations
    bad = Environment(e0).step(before, Action('Drain'), _r03_claim(e0, binding)).state
    checked = bc.evaluate_condition_custody(e0.observation_contract, bad.evidence.observation_trace, bad)
    assert {(v.row, v.target) for v in checked.violations
            if v.message == 'condition claimed before independent occurrence'} == {
        ('INV-2.a', binding.key), ('INV-2.c', binding.key)}, (case[0], checked)


@pytest.mark.parametrize('stage,kind', (('D', 'run'), ('D', 'save'), ('Ee', 'run'), ('Ee', 'save'), ('Ee', 'handle')))
def test_r03_terminal_condition_cannot_precede_its_promise_or_end(stage, kind):
    # 1232/1233/1236/1237. Only the pre-publication cut is asserted here;
    # this does not claim a connected full F-a PR/DF/Ee prefix.
    bc = observation_check
    e0 = _mg02_terminal_e0(stage=stage)
    obligation = 'O-11' if stage == 'D' else 'O-12'
    binding = next(b for b in e0.observation_contract.completions
                   if b.key.obligation == obligation and b.key.kind == kind)
    before = Environment(e0).initial()
    good = Environment(e0).step(before, Action('Drain'), CorrectWindow(e0)).state
    assert not bc.evaluate_condition_custody(e0.observation_contract,
        good.evidence.observation_trace, good).violations
    bad = Environment(e0).step(before, Action('Drain'), _r03_claim(e0, binding)).state
    checked = bc.evaluate_condition_custody(e0.observation_contract, bad.evidence.observation_trace, bad)
    assert {(v.row, v.target) for v in checked.violations
            if v.message == 'condition claimed before independent occurrence'} == {
        ('INV-2.a', binding.key), ('INV-2.c', binding.key)}


@pytest.mark.parametrize('family', ('O-02', 'O-G'))
def test_r03_birth_mark_alone_is_not_independent_birth_evidence(family):
    bc = observation_check
    e0 = _r03_e0()
    binding = next(b for b in e0.observation_contract.completions
                   if b.key.obligation == family and b.key.kind == ('issue' if family == 'O-G' else 'save'))
    before = Environment(e0).initial()
    assert not before.core.p.conditions and binding.key not in before.evidence.condition_births
    # Explicit checker input, never fed back to the window: a historical claim
    # remains auditable even if its current custody row was removed/cleared.
    forged = replace(before, evidence=replace(before.evidence,
                     condition_births=before.evidence.condition_births | {binding.key}))
    good = bc.evaluate_condition_custody(e0.observation_contract, before.evidence.observation_trace, before)
    assert not good.violations
    checked = bc.evaluate_condition_custody(e0.observation_contract, forged.evidence.observation_trace, forged)
    expected_rows = {'INV-2.a', 'INV-2.c', 'INV-2.g'} if family == 'O-G' else {'INV-2.a', 'INV-2.c'}
    assert {v.row for v in checked.violations if v.target == binding.key
            and v.message == 'condition claimed before independent occurrence'} == expected_rows


def test_r03_unconnected_cg_occurrence_is_neither_excess_nor_achievement():
    from fb_machine import declare_observation_e0
    bc = observation_check
    e0 = _r03_e0()
    e0 = replace(e0, plans=tuple(replace(p, semantic_limits=('r03-undeclared-generation-use',))
                                if p.unit == 'mg-cg' else p for p in e0.plans), observation_declarations=None)
    e0 = replace(e0, observation_declarations=declare_observation_e0(e0))
    _, states, _, _, _ = _mg02_generation_path(e0, 'end')
    binding = next(b for b in e0.observation_contract.completions if b.key.obligation == 'O-G'
                   and b.key.kind == 'issue' and b.key.target == bc.SlotKey('mg-cg', 'cg'))
    after = Environment(e0).step(states[-1], Action('Drain'), _r03_claim(e0, binding)).state
    checked = _mg02_result(e0, after)
    entries = [j for j in checked.custody if j.target == binding.key]
    assert entries and all(j.classification == '\u672a\u63a5\u7d9a' and j.direct is None for j in entries)
    assert not any(v.target == binding.key for v in checked.violations)
    assert any('excess occurrence adapter unconnected' in reason and repr(binding.key) in reason
               for _, reason in checked.limitations)


@pytest.mark.parametrize('published', (False, True))
def test_r03_unconnected_initial_issue_keeps_its_claimed_completion_key(published):
    import fb_scenes as scenes
    bc = observation_check
    e0, binding = _r03_extra_binding(_R03_EXTRA[0])
    scene = replace(_c05_scene('SC-04-publish-initial'), e0=e0)
    _, states, edges, _ = scenes.instantiate(scene)
    edge = next(e for e in edges if e.action == Action('PublishUnit', ('initial',)))
    before = states[edge.target if published else edge.source]  # full birth adapter is unconnected
    after = Environment(e0).step(before, Action('Drain'), _r03_claim(e0, binding)).state
    result = bc.evaluate_condition_custody(e0.observation_contract, after.evidence.observation_trace, after)
    assert not any(v.target == binding.key for v in result.violations)
    entries = [j for j in result.custody if j.target == binding.key]
    assert entries and all(j.classification == '\u672a\u63a5\u7d9a' and j.direct is None for j in entries)
    assert any('excess occurrence adapter unconnected' in reason and repr(binding.key) in reason
               for _, reason in result.limitations)


# Explicit unconnected denominator for the remaining 10 registered types.
# Full ordinary and O-G tables: paper 1206-1243 and 1941-1947 (44 + 7).
_R03_UNCONNECTED = (
    ('C-O08.handle[\u53d6\u5f97\u610f\u56f3]', 1222, 'separate acceptance of the acquisition intent is not exposed by Acquire'),
    ('C-O10.issue[artifact,PR]', 1230, 'full artifact/FProblem-or-NoDecision instance and use correspondence'),
    ('C-O10.save[artifact,PR\u306e\u5404slot]', 1231, 'no connected artifact/PR plan and slot binding in the legal public prefix'),
    ('C-O11.issue[DF/DU]', 1234, 'full PR/FProblem/Draw generation and use correspondence'),
    ('C-O11.save[DF/DU/\u5225\u306e\u5fc5\u9808\u7d42\u308f\u308aslot]', 1235, 'no connected legal PR/Draw-to-DF/DU slot binding'),
    ('C-O12.issue[artifact,EV]', 1238, 'full DF/Ee/artifact and use correspondence'),
    ('C-O12.issue[S]', 1239, 'Saved EV/certified Selected/root/Draw/request correspondence'),
    ('C-O12.save[artifact,EV,S\u306e\u5404slot]', 1240, 'no connected legal EV/S slot binding'),
    ('C-O13.handle[\u5831\u544a/\u9375/\u6839]', 1241, 'independent Saved report-to-processing-need instance adapter'),
    ('C-O13.save[\u51e6\u7406slot]', 1242, 'no independently mapped B/Xc/shortage processing slot'),
)


def test_r03_registration_population_is_explicit_including_unconnected():
    bc = observation_check
    tested = {row[0] for row in _R03_REGISTERED + _R03_EXTRA} | {
        'C-O11.run[D]', 'C-O11.save[T]', 'C-O12.run[Ee]', 'C-O12.save[T]',
        'C-O12.handle[\u8a55\u4fa1\u306e\u7d42\u308f\u308a]',
        'C-OG.run[Wg]', 'C-OG.save[T]', 'C-OG.handle[Wg]', 'C-OG.issue[CG]',
        'C-OG.save[CG]', 'C-OG.issue[EQ]', 'C-OG.save[EQ]',
    }
    gaps = {cid for cid, _, _ in _R03_UNCONNECTED}
    assert len(tested) == 41 and len(gaps) == 10 and not tested & gaps
    assert tested | gaps == {cid for cid, _, _ in bc.COMPLETION_PREDICATES}


@pytest.mark.parametrize('cid,line,reason', _R03_UNCONNECTED)
def test_r03_unconnected_contrast_stays_in_the_denominator(cid, line, reason):
    pytest.skip(f'{cid} (paper {line}): {reason}; no verified excess-occurrence contrast')



@pytest.mark.parametrize('family', ('O-13', 'O-G'))
def test_r03_unmapped_actual_condition_is_reported_with_its_identity(family):
    bc = observation_check
    e0 = publication() if family == 'O-G' else _r03_e0()
    target = bc.SlotKey('r03-unit', 'r03-target') if family == 'O-G' else bc.WorkKey('r03-target')
    key = bc.CompletionKey(family, ('r03-unmapped-processing',), 'issue' if family == 'O-G' else 'handle', target)
    binding = bc.CompletionBinding(key, 'EndKnown', bc.WorkKey('r03-target'), (), bc.Owner('P.units', 'r03-unit'))
    assert key not in {b.key for b in e0.observation_contract.completions}
    before = Environment(e0).initial()
    after = Environment(e0).step(before, Action('Drain'), _r03_claim(e0, binding)).state
    result = bc.evaluate_condition_custody(e0.observation_contract, after.evidence.observation_trace, after)
    assert not any(v.target == key for v in result.violations)
    entries = [j for j in result.custody if j.target == key]
    assert entries and all(j.classification == '\u672a\u63a5\u7d9a' and j.direct is None for j in entries)
    assert any('excess occurrence adapter unconnected' in reason and repr(key) in reason
               for _, reason in result.limitations)
# MG-02 follow-up 6 END


# MG-02 follow-up 7 BEGIN: FBM3-R03-A preservation under unconnected birth.
def _r03a_review_path(*, conclusion_connected=True):
    """1199/1220/1311/1588: actual Wp custody, before any P or Cq Publish.

    Only the observer's P/Cq slot correspondence is omitted in the unknown
    conclusion control. The declared window plans and all public steps stay
    the same. No State, ledger, trace or expected result is fabricated.
    """
    import fb_scenes as scenes
    bc = observation_check
    scene = _c05_scene('SC-05-structure-p-published')
    contract = scene.e0.observation_contract
    slots = tuple(bc.SlotKey(p.unit, r.slot) for p in contract.plans for r in p.records
                  if r.contract.name in ('computation_proof', 'computation_completed'))
    key = bc.CompletionKey('O-07', ('wp',), 'issue', bc.SlotKey('proof', 'p'))
    binding = bc.CompletionBinding(key, 'EndKnown', bc.WorkKey('wp'),
        slots if conclusion_connected else slots[:1], bc.Owner('P.work', 'wp'))
    assert key not in {b.key for b in contract.completions}
    contract = replace(contract, completions=contract.completions + (binding,))
    e0 = replace(scene.e0, observation_declarations=contract)
    scenario, states, edges, _ = scenes.instantiate_v2(replace(scene, e0=e0))
    publish = next(e for e in edges if e.action == Action('PublishUnit', ('proof',)))
    states, edges = list(states[:publish.source + 1]), list(edges[:publish.source])
    before = states[-1]
    assert len(states) == 72  # review witness; identity/content checks follow
    held = next(c for c in before.core.p.conditions if c.key == key)
    assert held.owner == binding.owner and key in held.unmet
    assert bc.actual_owner_exists(before, held.owner)
    assert not any(e.tag == 'Publish' and e.key in (bc.UnitKey('proof'), bc.UnitKey('completed'))
                   for e in before.evidence.observation_trace.events)
    facts = bc.CompletionFacts(contract, before.evidence.observation_trace, before)
    assert bc.excess_occurrence(binding, facts, bc.issue_occurrences(facts)) is None
    assert bc.condition_transfer(binding, facts) is False
    assert bc.completion_conclusion(binding, contract, before.evidence.observation_trace, before) is (
        False if conclusion_connected else None)
    return scenario, states, edges, binding


@pytest.fixture(scope='module')
def r03a_review_path():
    return _r03a_review_path()


def _r03a_evaluate(e0, before, after):
    return observation_check.evaluate_condition_custody(e0.observation_contract,
        after.evidence.observation_trace, after, before_state=before)


def _r03a_assert_unknown_birth(result, key):
    # Birth uncertainty remains visible even when preservation is decidable.
    assert any(j.target == key and j.classification == '\u672a\u63a5\u7d9a'
               and 'occurrence adapter' in j.reasons for j in result.custody)
    assert any('condition occurrence adapter: ' + repr(key) in reason
               for _, reason in result.limitations)


def test_r03a_unconnected_birth_does_not_hide_retained_unmet(r03a_review_path):
    scenario, states, edges, binding = r03a_review_path
    states, edges = list(states), list(edges)
    before = states[-1]
    after = _c05_take(scenario, states, edges, Action('Drain')).state
    result = _r03a_evaluate(scenario.e0, before, after)
    assert not result.boundary.violations and not result.violations
    _r03a_assert_unknown_birth(result, binding.key)
    assert any(j.target == binding.key and j.classification == '\u672a\u9054\u306e\u307e\u307e\u4fdd\u5168'
               and j.direct is False and j.transfer is False for j in result.custody)
    report = check_exploration(scenario, _c05_graph(scenario, states, edges))
    assert not report.contract_violations and not report.violations


@pytest.mark.parametrize('change', ('delete', 'clear', 'owner'))
def test_r03a_review_unmet_loss_is_reported_despite_unknown_birth(r03a_review_path, change):
    bc = observation_check
    scenario, states, edges, binding = r03a_review_path
    states, edges = list(states), list(edges)
    before = states[-1]
    key = binding.key
    def changed(custody):
        if change == 'delete':
            conditions = tuple(c for c in custody.conditions if c.key != key)
        else:
            conditions = tuple((replace(c, unmet=frozenset()) if change == 'clear' else
                                replace(c, owner=bc.Owner('P.units', 'r03a-absent-owner')))
                               if c.key == key else c for c in custody.conditions)
        return replace(custody, conditions=conditions)
    after = _c05_take(scenario, states, edges, Action('Drain'),
        _mg02_change(scenario.e0, changed)).state
    result = _r03a_evaluate(scenario.e0, before, after)
    _r03a_assert_unknown_birth(result, key)
    assert {(v.row, v.target) for v in result.violations} == {
        ('INV-2.a', key), ('INV-2.c', key)}
    assert any(j.target == key and j.classification == '\u524a\u9664\u30fb\u6d88\u53bb\u306e\u9055\u53cd'
               and j.direct is False and j.transfer is False for j in result.custody)
    assert not any(v.message == 'condition claimed before independent occurrence' for v in result.violations)
    if change == 'delete':
        report = check_exploration(scenario, _c05_graph(scenario, states, edges))
        assert not report.contract_violations
        assert {(v.condition_id, v.target) for v in report.violations} == {
            ('INV-2.a', key), ('INV-2.c', key)}


def test_r03a_unknown_conclusion_is_not_rounded_into_deletion_violation():
    scenario, states, _, binding = _r03a_review_path(conclusion_connected=False)
    before = states[-1]
    after = Environment(scenario.e0).step(before, Action('Drain'), _mg02_change(scenario.e0,
        lambda custody: replace(custody, conditions=tuple(c for c in custody.conditions
                                                         if c.key != binding.key)))).state
    result = _r03a_evaluate(scenario.e0, before, after)
    assert not result.boundary.violations and not result.violations
    _r03a_assert_unknown_birth(result, binding.key)
    entries = [j for j in result.custody if j.target == binding.key]
    assert len(entries) == 1
    entry = entries[0]
    assert entry.classification == '\u672a\u63a5\u7d9a' and entry.direct is None and entry.transfer is False
    assert 'issue record-family correspondence: ' + repr(binding.key) in entry.reasons
    assert all(any(row == wanted and 'issue record-family correspondence: ' + repr(binding.key) in reason
                   for row, reason in result.limitations) for wanted in ('INV-2.a', 'INV-2.c'))


@pytest.mark.parametrize('delete', (False, True))
def test_r03a_actual_promised_save_evaluates_conclusion_without_birth_adapter(delete):
    """1200/1311/1588: EU promises count even without a previous-state input.

    The observer lacks Wp's descriptor, so EndKnown and T's full conclusion
    cannot be connected. Actual Publish still requires a target-specific
    conclusion/transfer report; it must not disappear with the birth skip.
    """
    import fb_scenes as scenes
    bc = observation_check
    scene = _c05_scene('SC-05-structure-p-published')
    contract = scene.e0.observation_contract
    binding = next(b for b in contract.completions if b.key.obligation == 'O-07'
                   and b.key.kind == 'save' and b.trigger == 'EndKnown')
    contract = replace(contract, descriptors=tuple(d for d in contract.descriptors if d.work_id != 'wp'))
    e0 = replace(scene.e0, observation_declarations=contract)
    _, states, _, _ = scenes.instantiate_v2(replace(scene, e0=e0))
    before = Environment(e0).step(states[-1], Action('RecognizeTerminal', ('wp',)), CorrectWindow(e0)).state
    assert any(c.key == binding.key and binding.key in c.unmet for c in before.core.p.conditions)
    assert any(e.tag == 'Publish' and e.key == bc.UnitKey(binding.slots[0].unit)
               for e in before.evidence.observation_trace.events)
    assert bc.completion_occurred(binding, contract, before.evidence.observation_trace) is None
    window = (_mg02_change(e0, lambda custody: replace(custody,
        conditions=tuple(c for c in custody.conditions if c.key != binding.key))) if delete else CorrectWindow(e0))
    after = Environment(e0).step(before, Action('Drain'), window).state
    # No before_state: only the actual published record puts this key in the loop.
    result = bc.evaluate_condition_custody(contract, after.evidence.observation_trace, after)
    assert not any(v.target == binding.key for v in result.violations)
    _r03a_assert_unknown_birth(result, binding.key)
    entries = [j for j in result.custody if j.target == binding.key]
    assert len(entries) == 1 and entries[0].classification == '\u672a\u63a5\u7d9a'
    assert entries[0].direct is None and entries[0].transfer is False
    assert 'terminal save -> E0 work/stage: ' + repr(binding.key) in entries[0].reasons
# MG-02 follow-up 7 END
