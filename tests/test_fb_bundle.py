"""K30, F-b v1.11 :3549 and :4441-4509; public declarations and test fixtures.

The missing WorkerBundle name is resolved per case, never at collection.
SourceMeasurer/FiniteUpdater are native workers in BundleLoopRig. The remaining
four purposes execute TEST workers (including the scripted draw), not native
thinking workers. The test source gates real acquisitions; no script acquires.
No implementation body/private host state is inspected, patched or substituted.
"""

from collections.abc import Mapping
from inspect import Parameter, signature
from threading import Event, Thread
from types import MappingProxyType, SimpleNamespace
from typing import get_args, get_origin, get_type_hints

import pytest

from sui import f, fb, fb_contracts as c
from test_fb_skeleton import desc, point, source
from test_fb_stage1 import wire
from test_fb_stage2 import ORDER
from test_fb_loop import Workers, execution_for
from test_fb_measure import AcquireRig, acquire1_api, acquire1_quiet, ROUTE
from test_fb_belief import BeliefRig, T, E, belief1_chain
from test_fb_acquisition_loop import MATRICES


STAGES = ("measure_segment", "candidate_generation", "belief_update",
          "evaluation_prepare", "selection_draw", "evaluation")
THINKING = ("candidate_generation", "evaluation_prepare", "selection_draw", "evaluation")
OPERATIONS = ("enter", "now", "acquire", "read", "monitored", "reader", "prepared", "post", "evidence")
WATCHDOG = 30


def bundle_type():
    assert hasattr(fb, "WorkerBundle"), "K30 public API missing: fb.WorkerBundle"
    return fb.WorkerBundle


def work_for(stage):
    kind = fb.MeasureSegment if stage == "measure_segment" else fb.Draw if stage == "selection_draw" else fb.Compute
    return kind(request=point("bundle-request-" + stage), desc=desc(stage))


class PortSpy:
    """A public-shaped caller-owned port; every operation is independently seen."""
    def __init__(self, entered=True):
        self.calls, self.enter_result = [], entered

    def touch(self, operation):
        self.calls.append(operation)

    def enter(self): self.touch("enter"); return self.enter_result
    def now(self): self.touch("now")
    def acquire(self): self.touch("acquire")
    def read(self, point): self.touch("read")
    def monitored(self, interval): self.touch("monitored")
    def reader(self): self.touch("reader")
    def prepared(self): self.touch("prepared")
    def post(self, event, issued=None): self.touch("post")
    def evidence(self): self.touch("evidence")


class WorkerProbe:
    def __init__(self, action=None):
        self.calls, self.action, self.result = [], action, object()

    def run(self, work, ctx):
        self.calls.append((work, ctx))
        return self.action(work, ctx) if self.action is not None else self.result


class WorkerCrashed(RuntimeError):
    pass


def probes():
    return {stage: WorkerProbe() for stage in STAGES}


def assert_one(workers, stage, work, ctx):
    for name, worker in workers.items():
        assert len(worker.calls) == (1 if name == stage else 0)
        if name == stage:
            assert worker.calls[0][0] is work and worker.calls[0][1] is ctx


def test_bundle1_public_shape_and_exact_six_stage_domain():
    cls = bundle_type()
    assert get_args(fb.Stage) == STAGES
    assert "WorkerBundle" in fb.__all__
    constructor = signature(cls)
    assert tuple(constructor.parameters) == ("workers",)
    assert constructor.parameters["workers"].default is Parameter.empty
    assert constructor.parameters["workers"].kind is Parameter.POSITIONAL_OR_KEYWORD
    annotation = get_type_hints(cls.__init__)["workers"]
    assert get_origin(annotation) is Mapping and get_args(annotation) == (fb.Stage, fb.FWorkers)
    assert tuple(signature(cls.run).parameters) == ("self", "work", "ctx")
    assert get_type_hints(cls.run)["return"] is type(None)


@pytest.mark.parametrize("readonly", [False, True], ids=["dict", "Mapping"])
def test_bundle1_exact_mapping_constructs_without_entering_or_running_workers(readonly):
    cls = bundle_type()
    workers = probes()
    bundle = cls(MappingProxyType(workers) if readonly else workers)
    assert callable(bundle.run)
    assert all(worker.calls == [] for worker in workers.values())


@pytest.mark.parametrize("missing", STAGES)
def test_bundle1_each_missing_purpose_is_value_error(missing):
    cls = bundle_type()
    workers = probes()
    del workers[missing]
    with pytest.raises(ValueError): cls(workers)
    assert all(worker.calls == [] for worker in workers.values())


@pytest.mark.parametrize("shape", ["extra", "five-plus-unknown", "empty"])
def test_bundle1_extra_replacement_and_empty_domains_are_value_error(shape):
    """A six-key map with one unknown key defeats count-only validation."""
    cls = bundle_type()
    workers = probes()
    if shape == "empty": workers.clear()
    else:
        workers["not-a-Stage"] = WorkerProbe()
        if shape == "five-plus-unknown": del workers["evaluation"]
    with pytest.raises(ValueError): cls(workers)
    assert all(worker.calls == [] for worker in workers.values())


@pytest.mark.parametrize("stage", STAGES)
@pytest.mark.parametrize("bad", ["absent", "none", "noncallable"])
def test_bundle1_every_value_requires_a_callable_run(stage, bad):
    cls = bundle_type()
    workers = probes()
    workers[stage] = {"absent": object(), "none": SimpleNamespace(run=None),
                      "noncallable": SimpleNamespace(run=17)}[bad]
    with pytest.raises(TypeError): cls(workers)


@pytest.mark.parametrize("stage", STAGES)
def test_bundle1_dispatches_once_only_to_the_purpose_worker_without_touching_context(stage):
    """Wrong neighbor/type dispatch, duplicate call or ANY port operation fails."""
    cls = bundle_type()
    workers, ctx, work = probes(), PortSpy(), work_for(stage)
    result = cls(workers).run(work, ctx)
    assert result is workers[stage].result
    assert_one(workers, stage, work, ctx)
    assert ctx.calls == []


@pytest.mark.parametrize("stage", STAGES)
def test_bundle1_copies_the_mapping_before_caller_replaces_and_deletes_keys(stage):
    cls = bundle_type()
    supplied = probes()
    original = dict(supplied)
    bundle = cls(supplied)
    replacement = WorkerProbe()
    supplied[stage] = replacement
    del supplied[STAGES[(STAGES.index(stage) + 1) % len(STAGES)]]
    work, ctx = work_for(stage), PortSpy()
    assert bundle.run(work, ctx) is original[stage].result
    assert_one(original, stage, work, ctx)
    assert replacement.calls == [] and ctx.calls == []


def test_bundle1_one_worker_may_cover_all_purposes_and_receives_each_call():
    cls = bundle_type()
    worker = WorkerProbe()
    bundle = cls({stage: worker for stage in STAGES})
    submitted = [(work_for(stage), PortSpy()) for stage in STAGES]
    for work, ctx in submitted: assert bundle.run(work, ctx) is worker.result
    assert len(worker.calls) == len(STAGES)
    assert all(a is work and b is ctx for (a, b), (work, ctx) in zip(worker.calls, submitted))
    assert all(ctx.calls == [] for _work, ctx in submitted)


@pytest.mark.parametrize("stage", STAGES)
def test_bundle1_same_work_with_a_new_context_is_forwarded_again(stage):
    """Bundle call count, not a remembered WorkId, defines once-only forwarding."""
    cls = bundle_type()
    workers, work = probes(), work_for(stage)
    bundle, contexts = cls(workers), [PortSpy(), PortSpy()]
    for ctx in contexts: assert bundle.run(work, ctx) is workers[stage].result
    assert len(workers[stage].calls) == 2
    assert all(a is work and b is ctx for (a, b), ctx in zip(workers[stage].calls, contexts))
    assert all(not worker.calls for name, worker in workers.items() if name != stage)
    assert all(ctx.calls == [] for ctx in contexts)


@pytest.mark.parametrize("stage", STAGES)
@pytest.mark.parametrize("after_entry", [False, True], ids=["before-entry-TypeError", "after-entry"])
def test_bundle1_exact_worker_exception_escapes_without_extra_context_operations(stage, after_entry):
    cls = bundle_type()
    error = WorkerCrashed("test worker") if after_entry else TypeError("test worker before entry")
    def fail(work, ctx):
        if after_entry: assert ctx.enter()
        raise error
    workers, work, ctx = probes(), work_for(stage), PortSpy()
    workers[stage] = WorkerProbe(fail)
    with pytest.raises(type(error)) as caught: cls(workers).run(work, ctx)
    assert caught.value is error
    assert_one(workers, stage, work, ctx)
    assert ctx.calls == (["enter"] if after_entry else [])


@pytest.mark.parametrize("stage", STAGES)
def test_bundle1_false_enter_is_not_replaced_by_bundle_admission_or_work(stage):
    cls = bundle_type()
    reached = []
    token = object()
    def guarded(work, ctx):
        if not ctx.enter(): return token
        reached.append(work)
    workers, ctx, work = probes(), PortSpy(entered=False), work_for(stage)
    workers[stage] = WorkerProbe(guarded)
    assert cls(workers).run(work, ctx) is token
    assert_one(workers, stage, work, ctx)
    assert reached == [] and ctx.calls == ["enter"]


@pytest.mark.parametrize("wrong", ["SourceMeasurer", "FiniteUpdater"])
def test_bundle1_native_purpose_mismatch_is_not_constructor_validation(wrong):
    cls = bundle_type()
    from test_fb_loop import registry
    worker = fb.SourceMeasurer() if wrong == "SourceMeasurer" else fb.FiniteUpdater(registry=registry())
    stage = "belief_update" if wrong == "SourceMeasurer" else "measure_segment"
    workers, ctx = probes(), PortSpy()
    workers[stage] = worker
    bundle = cls(workers)  # run's shape is legal; purpose compatibility is not inspected.
    with pytest.raises(TypeError): bundle.run(work_for(stage), ctx)
    assert ctx.calls == []


@pytest.fixture
def scenes():
    active = []
    def register(scene): active.append(scene); return scene
    yield register
    for scene in reversed(active): scene.close()


class HostScene:
    """Existing Boot/store/launcher fixture, connected to a real bundle at Boot."""
    def __init__(self, cls, worker):
        self.rig = AcquireRig(acquire1_api(), script=acquire1_quiet)
        self.worker, self.threads, self.releases, self.thread_errors = worker, [], [], []
        self.bundle = cls({stage: worker if stage == "measure_segment" else WorkerProbe() for stage in STAGES})
        # AcquireRig has only queued declarations; no host round/body ran yet.
        assert not self.rig.requests("measure_segment")
        self.rig.host = fb.FThreadHost(ledger=self.rig.ledger, clock=self.rig.clock,
            workers=self.bundle, registry=self.rig.registry, launcher=self.rig.launcher,
            sources={ROUTE: self.rig.source})
        from dataclasses import replace
        from test_fb_skeleton import contract
        self.rig.host.post(fb.ClockDeclared(declaration=replace(source(), run=self.rig.clock.run,
            measurement=contract("sui.f.simulated_clock"))))
        self.rig.host.post(self.rig.boot_input)

    def offered(self, count=1):
        def bodies():
            requests = self.rig.requests("measure_segment")
            if not requests: return []
            self.request = requests[0]
            key = self.request.value["desc"]["work_id"]
            return [body for wid, body in self.rig.launcher.attempts if wid == key]
        self.rig.until(lambda: len(bodies()) >= count)
        return bodies()

    def status(self, work):
        return next(row for row in self.rig.host.window.status().works if row.work_id == work.desc.work_id)

    def background(self, body):
        def invoke():
            try: body()
            except BaseException as error: self.thread_errors.append(error)
        thread = Thread(target=invoke, daemon=True)
        self.threads.append(thread); thread.start()
        return thread

    def close(self):
        for release in self.releases: release.set()
        for thread in self.threads:
            thread.join(WATCHDOG)
            assert not thread.is_alive(), "test body did not return"
        self.rig.close()
        assert not self.thread_errors, self.thread_errors


@pytest.mark.parametrize("failure", [False, True], ids=["no-entry-return", "no-entry-TypeError"])
def test_bundle1_host_keeps_unentered_work_pending_and_forwards_retry_with_new_context(scenes, failure):
    cls = bundle_type()
    error, admitted = TypeError("test before admission"), []
    worker = WorkerProbe()
    def act(work, ctx):
        if len(worker.calls) == 1:
            if failure: raise error
            return worker.result
        admitted.append(ctx.enter())
    worker.action = act
    scene = scenes(HostScene(cls, worker))
    first, = scene.offered()
    if failure:
        with pytest.raises(TypeError) as caught: first()
        assert caught.value is error
    else: assert first() is None  # Host's wrapper, not the worker's return value.
    work, first_ctx = worker.calls[0]
    row = scene.status(work)
    assert row.phase == "pending" and not row.stop_confirmed and row.held is None
    observed = execution_for(first_ctx, work.desc.work_id)
    assert observed.entered == 0 and not observed.stopped and observed.reports == ()
    second = scene.offered(2)[-1]
    second()
    assert len(worker.calls) == 2 and admitted == [True]
    later_work, later_ctx = worker.calls[1]
    assert later_work.request == work.request and later_work.desc.work_id == work.desc.work_id
    assert later_ctx is not first_ctx
    assert execution_for(later_ctx, work.desc.work_id).entered == 1
    assert execution_for(later_ctx, work.desc.work_id).stopped
    assert scene.status(later_work).stop_confirmed


@pytest.mark.parametrize("old_not_started", [False, True], ids=["duplicate-wrapper", "old-not-started-wrapper"])
def test_bundle1_host_wrapper_cannot_admit_twice_or_revoke_the_live_owner(scenes, old_not_started):
    cls = bundle_type()
    entered, release, admissions = Event(), Event(), []
    def act(work, ctx):
        ok = ctx.enter(); admissions.append((work, ctx, ok))
        if ok:
            entered.set()
            assert release.wait(WATCHDOG), "test live owner not released"
    worker = WorkerProbe(act)
    scene = scenes(HostScene(cls, worker)); scene.releases.append(release)
    if old_not_started:
        normal = scene.rig.launcher.launch
        rejected = []
        def launch(work_id, body):
            normal(work_id, body)
            target = any(q.value["desc"]["work_id"] == work_id for q in scene.rig.requests("measure_segment"))
            if target and not rejected:
                rejected.append(body); return "not_started"
            return "launched"
        scene.rig.launcher.launch = launch
    callbacks = scene.offered(2 if old_not_started else 1)
    thread = scene.background(callbacks[-1])
    assert entered.wait(WATCHDOG)
    work, ctx, ok = admissions[0]
    assert ok and scene.status(work).phase == "running"
    before = (ctx.evidence().uses, ctx.evidence().intervals, ctx.evidence().sources)
    callbacks[0]()
    if not old_not_started: assert len(worker.calls) == 1
    else: assert all(not ok for _work, _ctx, ok in admissions[1:])
    observed = execution_for(ctx, work.desc.work_id)
    assert observed.entered == 1 and not observed.stopped
    assert scene.status(work).phase == "running" and scene.status(work).held is not None
    assert (ctx.evidence().uses, ctx.evidence().intervals, ctx.evidence().sources) == before
    assert ctx.read(scene.rig.model_point) == scene.rig.read_stored(scene.rig.model_point)[2].body.content.data
    release.set(); thread.join(WATCHDOG)
    assert not thread.is_alive() and not scene.thread_errors
    assert execution_for(ctx, work.desc.work_id).stopped


def test_bundle1_host_observes_exceptional_return_and_preserves_K29_rejection(scenes):
    cls = bundle_type()
    error = WorkerCrashed("after admission")
    def fail(work, ctx):
        assert ctx.enter()
        raise error
    worker = WorkerProbe(fail)
    scene = scenes(HostScene(cls, worker))
    body, = scene.offered()
    with pytest.raises(WorkerCrashed) as caught: body()
    assert caught.value is error and len(worker.calls) == 1
    work, ctx = worker.calls[0]
    observed = execution_for(ctx, work.desc.work_id)
    assert observed.entered == 1 and observed.stopped and scene.status(work).stop_confirmed
    before = (ctx.evidence().uses, ctx.evidence().intervals, ctx.evidence().sources)
    interval = f.MeasurementInterval(clock=scene.rig.clock.run, start_ns=0, end_ns=1, closure="(start,end]")
    for operation in (lambda: ctx.read(scene.rig.model_point), lambda: ctx.monitored(interval), ctx.acquire):
        with pytest.raises(RuntimeError): operation()
    assert (ctx.evidence().uses, ctx.evidence().intervals, ctx.evidence().sources) == before
    assert scene.rig.source.calls == []
    assert ctx.now().reading.run == scene.rig.clock.run
    assert scene.rig.host.halted is None


class BundleLoopRig(BeliefRig):
    """Migrate BeliefRig's main path; native objects are the actual map values.

    The old host has only queued Boot/clock envelopes when defer_boot=True.
    Reconnect before accepting them; the new host receives the declarations.
    Keep test-worker telemetry separate from the actual host workers=bundle.
    """
    def __init__(self, cls, *, candidate_worker=None):
        super().__init__(symbols=(T, E), matrices=MATRICES, targets=("x0", "x1"),
            continuation=True, worker_type=Workers, defer_boot=True)
        self.native_measurer = fb.SourceMeasurer()
        self.native_updater = fb.FiniteUpdater(registry=self.registry)
        self.bundle_workers = {stage: self.workers for stage in THINKING}
        self.native_candidate = candidate_worker
        if candidate_worker is not None:
            self.bundle_workers["candidate_generation"] = candidate_worker
        self.bundle_workers.update(measure_segment=self.native_measurer, belief_update=self.native_updater)
        self.bundle = cls(self.bundle_workers)
        assert not self.requests("candidate_generation") and not self.requests("measure_segment")
        self.host = fb.FThreadHost(ledger=self.ledger, clock=self.clock, workers=self.bundle,
            registry=self.registry, launcher=self.launcher, sources={ROUTE: self.source})
        self.host.post(fb.ClockDeclared(declaration=self.clock_declaration))
        self.host.post(self.boot_input)

    def callback(self, stage):
        # Adoption confirmation and saving its continuation need not share a
        # settle call. Wait for a NEW offered request, not the old last request.
        def offered():
            return [request for request in self.requests(stage)
                if request.value["desc"]["work_id"] not in self.executed and
                any(key == request.value["desc"]["work_id"] for key, _ in self.launcher.attempts)]
        self.until(lambda: bool(offered()))
        request = offered()[0]
        callbacks = [body for key, body in self.launcher.attempts
            if key == request.value["desc"]["work_id"]]
        assert len(callbacks) == 1
        return request, callbacks[0]

    def run_stage(self, stage):
        if stage != "candidate_generation" or self.native_candidate is None:
            return super().run_stage(stage)
        request, body = self.callback(stage)
        work_id = request.value["desc"]["work_id"]
        self.executed.add(work_id)
        body()
        self.drive(lambda: any(item.value["work"] == work_id for item in self.facts(c.WORK_REPORT)))
        self.settle_steps()

    def start(self):
        request, body = self.callback("measure_segment")
        self.measure_key = request.value["desc"]["work_id"]
        self.measurers[self.measure_key] = self.native_measurer
        self.executed.add(self.measure_key)
        def invoke():
            try: body()
            except BaseException as error: self.body_errors.append(error)
        thread = Thread(target=invoke, daemon=True)
        self.threads.append(thread); thread.start()
        assert self.source.ready[0].wait(WATCHDOG)
        for stage in ORDER: self.run_stage(stage)
        self.until(lambda: len(self.facts(c.SELECTION)) == 1)

    def publish(self, index, *, last=False):
        assert self.source.ready[index].wait(WATCHDOG)
        if last: self.native_measurer.stop()
        self.source.release[index].set()
        self.until(lambda: len(self.reports("frame")) == index + 1)
        return self.reports("frame")[index]

    def update(self):
        before = len(self.facts(c.BELIEF_ADOPTED))
        request, body = self.callback("belief_update")
        work_id = request.value["desc"]["work_id"]
        assert work_id not in self.executed
        self.executed.add(work_id); body()
        self.until(lambda: len(self.facts(c.BELIEF_ADOPTED)) == before + 1)
        return self.facts(c.BELIEF_ADOPTED)[-1]


def test_bundle1_native_measurement_update_and_three_selections_use_the_main_loop_bundle(scenes):
    """K30(5)/(6): real acquire -> B -> Q -> native U -> adoption -> continuation.

    Candidate/preparation/scripted draw/evaluation remain TEST workers.
    Skipping native forwarding, double calls or bundle admission fails saved
    reports/chain, actual EW/ES counts or the three selections.
    """
    cls = bundle_type()
    rig = scenes(BundleLoopRig(cls))
    assert type(rig.bundle_workers["measure_segment"]) is fb.SourceMeasurer
    assert type(rig.bundle_workers["belief_update"]) is fb.FiniteUpdater
    rig.start()
    # Declared diagonal kernels: p0=(1/2,1/2), T=(1/4,1/16), E=(1/2,1/4).
    # T: unnormalized (1/8,1/32); TE: (1/16,1/128), without double counting T.
    expected = ({"joint": [[4, 5], [1, 5]], "evidence_mass": [5, 32]},
                {"joint": [[8, 9], [1, 9]], "evidence_mass": [9, 128]})
    for index in range(2):
        rig.publish(index, last=index == 1)
        rig.update()
        for stage in ORDER[1:]: rig.run_stage(stage)
        rig.until(lambda: len(rig.facts(c.SELECTION)) == index + 2)
    belief1_chain(rig, expected)
    assert len(rig.facts(c.UPDATE_RESULT)) == len(rig.requests("belief_update")) == 2
    assert len(rig.reports("frame")) == len(rig.source.calls) == 2
    assert len(rig.facts(c.SEGMENT_BINDING)) == 2 and len(rig.facts(c.SELECTION)) == 3
    assert all(work.desc.purpose in THINKING for work in rig.workers.entries)
    assert {stage: sum(w.desc.purpose == stage for w in rig.workers.entries) for stage in THINKING} == {
        "candidate_generation": 1, "evaluation_prepare": 3, "selection_draw": 3, "evaluation": 3}
    for thread in rig.threads:
        thread.join(WATCHDOG)
        assert not thread.is_alive()
    ctx = rig.workers.contexts["evaluation"]
    assert len(ctx.evidence().sources) == 2
    assert [(s.work_id, s.sample_seq) for s in ctx.evidence().sources] == [(rig.measure_key, 0), (rig.measure_key, 1)]
    for request in rig.requests("measure_segment") + rig.requests("belief_update"):
        observed = execution_for(ctx, request.value["desc"]["work_id"])
        assert observed.entered == 1 and observed.stopped
    assert rig.host.halted is None and not rig.host.interruptions()
