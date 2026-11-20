"""K34/K34-a: F-b :3560-3561, :4792-4877, Z60 :3804 (public only).

Native names are resolved inside cases; missing K34 does not break collection.
No production function body or private field is inspected or replaced. Public
secrets.randbits and the declared public bits constant are replaced BEFORE fresh
imports in isolated ordinary Python processes. This also permits import-time
aliases; requiring a live module lookup after import would exceed the contract.

Discrimination (one mutation per line):
- Wrong bit count or a second source call fails the exact randbits call witness.
- Accepting out-of-range integers or unreduced fractions fails exact grid values.
- Drawing before validating generator/request or admission fails zero-call cases.
- Reading clocks/readers/prepared/evidence fails independent public-port fences.
- Duplicate posts, swallowed post errors and reuse of an earlier value fail
  exact report counts, exception identity and two different work/value witnesses.
- A non-secrets default misses the fresh-import public secrets.randbits observer.
- A separate bits source for worker/declaration fails the small-grid values or
  the change of the generator's condition and registry_key, respectively.
- Statistical/continuous-uniform claims cannot replace exact small-grid counts.

K34-a closes CG-K34-GUARANTEE-SHAPE: check the seven exact field names, the
four fixed values/types, three nonempty strings (no fixed wording), and exact
equality of the public ContractValue with the registry's sole condition. Check
both sides' integer types explicitly: Python's True == 1 is not JSON equality.
"""

from dataclasses import replace
from fractions import Fraction as Q
from inspect import Parameter, signature
import json
from math import gcd
import os
from pathlib import Path
import secrets
import subprocess
import sys
from threading import Thread

import pytest

from sui import f, fb, fb_contracts as c, f_update2 as u2
from test_fb_skeleton import contract, desc, point
from test_fb_stage1 import wire
from test_fb_stage2 import Stage2Rig, ORDER, DF, terminal, assert_absent
from test_fb_evaluator import EvaluationLoopRig
from test_fb_belief import ROUTE, belief1_chain
from test_fb_bundle import WATCHDOG


OS_DRAW = contract("sui.fb.os_uniform_draw")
GUARANTEE = contract("sui.fb.draw_guarantee")


def draw_type():
    assert hasattr(fb, "UniformDraw"), "K34 public API missing: fb.UniformDraw"
    return fb.UniformDraw


def public_bits():
    assert hasattr(c, "OS_UNIFORM_DRAW_BITS"), "K34 public API missing: fb_contracts.OS_UNIFORM_DRAW_BITS"
    return c.OS_UNIFORM_DRAW_BITS


def guarantee_function():
    assert hasattr(u2, "draw_guarantee"), "K34 public API missing: f_update2.draw_guarantee"
    return u2.draw_guarantee


def assert_guarantee(guarantee, *, bits):
    """K34-a :3561, independent of the production JSON's current contents."""
    assert isinstance(guarantee, f.ContractValue) and guarantee.contract == GUARANTEE
    body = wire(guarantee.value)
    assert isinstance(body, dict)
    assert set(body) == {"law", "source", "grid_bits", "value",
                         "selection_deviation_below", "deviation_is", "provisional"}
    assert body["law"] == {"name": "uniform_unit", "version": "1"}
    assert body["source"] == "os_cryptographic_random"
    assert type(body["grid_bits"]) is int and body["grid_bits"] == bits
    bound = body["selection_deviation_below"]
    assert isinstance(bound, list) and len(bound) == 2
    assert all(type(part) is int for part in bound)
    assert bound == [1, 1 << bits]
    for name in ("value", "deviation_is", "provisional"):
        assert isinstance(body[name], str) and body[name] != ""
    return body


def draw_work(*, label="one", method=OS_DRAW, request=None):
    if request is None:
        request = f.DrawRequest(purpose="selection", context_key="problem-" + label,
            ordinal=0, law=contract("uniform_unit"), args={})
    args = fb.DrawArgs(prepared=point("draw-prepared-" + label),
                       stream_id="stream-" + label, request=request)
    d = replace(desc("selection_draw"), work_id="draw-work-" + label,
                method=method, args=args)
    return fb.Draw(request=point("draw-request-" + label), desc=d)


class DrawPort(fb.FWorkContext):
    def __init__(self, *, allowed=True, post_error=None):
        self.allowed, self.post_error = allowed, post_error
        self.trace, self.posts = [], []
    def enter(self): self.trace.append("enter"); return self.allowed
    def post(self, event, issued=None):
        self.trace.append("post"); self.posts.append((event, issued))
        if self.post_error is not None: raise self.post_error
    def forbidden(self, name):
        self.trace.append(name)
        raise AssertionError("K34 draw must not use ctx." + name)
    def now(self): return self.forbidden("now")
    def read(self, cid): return self.forbidden("read")
    def reader(self): return self.forbidden("reader")
    def prepared(self): return self.forbidden("prepared")
    def acquire(self): return self.forbidden("acquire")
    def monitored(self, interval): return self.forbidden("monitored")
    def evidence(self): return self.forbidden("evidence")


class BitsSource:
    def __init__(self, *values, error=None):
        self.values, self.error, self.calls = iter(values), error, []
    def __call__(self, n):
        self.calls.append(n)
        if self.error is not None: raise self.error
        return next(self.values)


def returned(port, work):
    assert port.trace == ["enter", "post"] and len(port.posts) == 1
    event, issued = port.posts[0]
    assert isinstance(event, fb.DrawReturned) and event.work == work.desc.work_id
    assert issued is None
    return event


def value_from(port, work, expected=None):
    event = returned(port, work)
    assert isinstance(event.outcome, fb.DrawValue)
    body = wire(event.outcome.value)
    assert set(body) == {"u"} and isinstance(body["u"], list) and len(body["u"]) == 2
    numerator, denominator = body["u"]
    assert type(numerator) is int and type(denominator) is int
    assert 0 <= numerator < denominator and gcd(numerator, denominator) == 1
    assert (1 << public_bits()) % denominator == 0
    result = Q(numerator, denominator)
    if expected is not None: assert result == expected
    return result


def failure_from(port, work, *, kind, content=None):
    event = returned(port, work)
    assert isinstance(event.outcome, fb.DrawFailure)
    failed = event.outcome.failure
    assert failed.failure_kind == kind and failed.readings == ()
    body = wire(failed.content)
    if content is not None: assert body == content
    else:
        assert set(body) == {"error_type"}
        assert isinstance(body["error_type"], str) and body["error_type"].isidentifier()
    return event


def test_draw1_public_constructor_run_and_exports():
    cls = draw_type()
    params = signature(cls).parameters
    assert tuple(params) == ("randbits",)
    assert params["randbits"].kind is Parameter.KEYWORD_ONLY
    assert params["randbits"].default is secrets.randbits
    assert tuple(signature(cls.run).parameters) == ("self", "work", "ctx")
    assert "UniformDraw" in fb.__all__ and callable(cls().run)


def test_draw1_public_generator_bits_and_guarantee_contracts():
    for name in ("OS_UNIFORM_DRAW", "DRAW_GUARANTEE"):
        assert hasattr(c, name), "K34 public API missing: fb_contracts." + name
    assert c.OS_UNIFORM_DRAW == OS_DRAW and c.DRAW_GUARANTEE == GUARANTEE
    assert type(public_bits()) is int and public_bits() == 128


def test_draw1_public_guarantee_value_matches_the_seven_field_contract():
    fn = guarantee_function()
    assert callable(fn) and not signature(fn).parameters
    assert_guarantee(fn(), bits=public_bits())


@pytest.mark.parametrize("position", ["zero", "one", "even", "quarter", "half", "three-quarters", "last"])
def test_draw1_exact_reduced_grid_value_uses_one_source_call(position):
    cls = draw_type(); n = public_bits(); size = 1 << n
    k = {"zero": 0, "one": 1, "even": 2, "quarter": size // 4,
         "half": size // 2, "three-quarters": 3 * size // 4, "last": size - 1}[position]
    source = BitsSource(k); work = draw_work(); port = DrawPort()
    cls(randbits=source).run(work, port)
    assert source.calls == [n]
    value_from(port, work, Q(k, size))


@pytest.mark.parametrize("position", ["negative", "upper", "above-upper"])
def test_draw1_out_of_range_integer_is_execution_failure_without_retry(position):
    cls = draw_type(); n = public_bits(); size = 1 << n
    source = BitsSource({"negative": -1, "upper": size, "above-upper": size + 1}[position])
    work = draw_work(); port = DrawPort(); cls(randbits=source).run(work, port)
    assert source.calls == [n]
    failure_from(port, work, kind="execution_error")


@pytest.mark.parametrize("change", ["generator-name", "generator-version", "purpose", "law-name", "law-version", "args"])
def test_draw1_rejection_does_not_consume_source_or_read_port_dependencies(change):
    cls = draw_type(); work = draw_work()
    if change.startswith("generator"):
        method = contract("other.generator") if change.endswith("name") else replace(OS_DRAW, version="2")
        work = replace(work, desc=replace(work.desc, method=method))
        reason = "unknown_generator"
    else:
        request = work.desc.args.request
        changed = {"purpose": {"purpose": "algorithm"},
                   "law-name": {"law": contract("other.law")},
                   "law-version": {"law": replace(contract("uniform_unit"), version="2")},
                   "args": {"args": {"extra": 1}}}[change]
        work = replace(work, desc=replace(work.desc,
            args=replace(work.desc.args, request=replace(request, **changed))))
        reason = "unsupported_request"
    source = BitsSource(); port = DrawPort(); cls(randbits=source).run(work, port)
    assert source.calls == []
    failure_from(port, work, kind="rejected", content={"reason": reason})


class AttributedSourceError(Exception):
    reason, field = "private-source-reason", "/private-source-field"


@pytest.mark.parametrize("error", [OSError("private"), RuntimeError("private"),
    ValueError("private"), TypeError("private"), MemoryError("private"),
    AttributedSourceError("private")], ids=lambda error: type(error).__name__)
def test_draw1_source_exception_is_exact_execution_failure_without_retry(error):
    cls = draw_type(); source = BitsSource(error=error)
    work = draw_work(); port = DrawPort(); cls(randbits=source).run(work, port)
    assert source.calls == [public_bits()]
    failure_from(port, work, kind="execution_error", content={"error_type": type(error).__name__})


@pytest.mark.parametrize("purpose", ["measure_segment", "belief_update", "candidate_generation", "evaluation_prepare", "evaluation"])
def test_draw1_wrong_work_purpose_is_type_error_before_enter(purpose):
    cls = draw_type(); source = BitsSource(); port = DrawPort(); work = draw_work()
    work = replace(work, desc=replace(work.desc, purpose=purpose))
    with pytest.raises(TypeError): cls(randbits=source).run(work, port)
    assert port.trace == [] and port.posts == [] and source.calls == []


@pytest.mark.parametrize("kind", ["compute", "object"])
def test_draw1_non_draw_is_type_error_before_enter(kind):
    cls = draw_type(); source = BitsSource(); port = DrawPort(); work = draw_work()
    other = fb.Compute(request=work.request, desc=work.desc) if kind == "compute" else object()
    with pytest.raises(TypeError): cls(randbits=source).run(other, port)
    assert port.trace == [] and port.posts == [] and source.calls == []


def test_draw1_false_admission_has_no_source_or_other_port_operation():
    cls = draw_type(); source = BitsSource(); port = DrawPort(allowed=False)
    cls(randbits=source).run(draw_work(), port)
    assert port.trace == ["enter"] and port.posts == [] and source.calls == []


@pytest.mark.parametrize("path", ["value", "rejected", "execution_error"])
def test_draw1_post_failure_escapes_and_no_second_post_or_draw_occurs(path):
    cls = draw_type(); error = OSError("post failure")
    source = BitsSource(0, error=RuntimeError("source") if path == "execution_error" else None)
    work = draw_work(method=contract("other.generator") if path == "rejected" else OS_DRAW)
    port = DrawPort(post_error=error)
    with pytest.raises(OSError) as caught: cls(randbits=source).run(work, port)
    assert caught.value is error
    returned(port, work)
    assert source.calls == ([] if path == "rejected" else [public_bits()])


def test_draw1_same_worker_uses_two_current_jobs_and_two_fresh_values():
    cls = draw_type(); n = public_bits(); size = 1 << n
    source = BitsSource(size // 4, 3 * size // 4); worker = cls(randbits=source)
    for i, expected in enumerate([Q(1, 4), Q(3, 4)]):
        work = draw_work(label=str(i)); port = DrawPort()
        work = replace(work, desc=replace(work.desc,
            args=replace(work.desc.args, request=replace(work.desc.args.request, ordinal=i))))
        worker.run(work, port); value_from(port, work, expected)
    assert source.calls == [n, n]


def test_draw1_registry_declares_one_generator_and_one_guarantee_condition():
    for name in ("OS_UNIFORM_DRAW", "DRAW_GUARANTEE"):
        assert hasattr(c, name), "K34 public API missing: fb_contracts." + name
    registry = u2.fb_registry_v1()
    rows = [d for d in registry.declarations if d.kind == "generator" and d.ref == OS_DRAW]
    assert len(rows) == 1
    assert rows[0].args_contract == contract("sui.f.args.empty")
    guarantee = guarantee_function()()
    assert_guarantee(guarantee, bits=public_bits())
    assert rows[0].conditions == (guarantee,)
    assert_guarantee(rows[0].conditions[0], bits=public_bits())
    assert len([i for i in registry.implementations if i.kind == "generator" and i.ref == OS_DRAW]) == 1


def run_isolated_python(script, *args):
    """Use the parent's imported source tree, independently of pytest's paths."""
    env = os.environ.copy()
    source_root = str(Path(fb.__file__).resolve().parents[1])
    inherited = env.get("PYTHONPATH")
    env["PYTHONPATH"] = source_root + (os.pathsep + inherited if inherited else "")
    return subprocess.run([sys.executable, "-B", "-c", script, *args],
        cwd=Path(__file__).resolve().parents[1], env=env,
        capture_output=True, text=True, timeout=30)


# Imported only AFTER public-module substitutions in the child process below.
def isolated_worker_observation(*, bits=None, default_source=False):
    cls = draw_type(); public_bits()
    assert default_source or bits in (2, 3), "fixture enumerates only small grids"
    script = r'''
import json, secrets, sys
sys.path.insert(0, "tests")
settings = json.loads(sys.argv[1])
calls = []
def observed(n):
    calls.append(n)
    return 1
if settings["default_source"]:
    secrets.randbits = observed
from sui import fb_contracts as c
assert "sui.fb" not in sys.modules and "sui.f_update2" not in sys.modules
if settings["bits"] is not None:
    c.OS_UNIFORM_DRAW_BITS = settings["bits"]
import test_fb_draw as t
from sui import fb, f_update2 as u2
from gate_f_facts_cases import assemble, prepare
n = c.OS_UNIFORM_DRAW_BITS
calls.clear()
worker = fb.UniformDraw() if settings["default_source"] else None
assert calls == [], "construction must not consume randomness"
values = []
if settings["default_source"]:
    work = t.draw_work(); port = t.DrawPort(); worker.run(work, port)
    t.value_from(port, work, t.Q(1, 1 << n)); values.append(t.wire(port.posts[0][0].outcome.value)["u"])
else:
    source = t.BitsSource(*range(1 << n)); worker = fb.UniformDraw(randbits=source)
    for k in range(1 << n):
        work = t.draw_work(label=str(k)); port = t.DrawPort(); worker.run(work, port)
        t.value_from(port, work, t.Q(k, 1 << n)); values.append(t.wire(port.posts[0][0].outcome.value)["u"])
    calls = source.calls
draw_calls = list(calls)
registry = u2.fb_registry_v1()
declaration = [d for d in registry.declarations if d.kind == "generator" and d.ref == t.OS_DRAW]
assert len(declaration) == 1
guarantee = t.guarantee_function()()
t.assert_guarantee(guarantee, bits=n)
assert declaration[0].conditions == (guarantee,)
t.assert_guarantee(declaration[0].conditions[0], bits=n)
artifact = prepare(assemble("FA01"), registry=registry)
assert isinstance(artifact.value, t.f.FProblem)
registry_key = json.loads(artifact.canonical_bytes)["environment"]["registry_key"]
print(json.dumps({"bits":n,"calls":draw_calls,"values":values,"registry_key":registry_key,
 "guarantee":t.wire(guarantee),"declaration":t.wire(declaration[0]),
 "other_declarations":[t.wire(d) for d in registry.declarations if d is not declaration[0]]}))
'''
    completed = run_isolated_python(script,
        json.dumps({"bits": bits, "default_source": default_source}))
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def test_draw1_default_source_calls_public_secrets_randbits_once_with_N():
    draw_type(); public_bits()
    observation = isolated_worker_observation(default_source=True)
    assert observation["calls"] == [128]
    assert Q(*observation["values"][0]) == Q(1, 1 << 128)


def test_draw1_changing_the_single_public_N_changes_worker_and_registry_declaration():
    draw_type(); public_bits()
    two = isolated_worker_observation(bits=2)
    three = isolated_worker_observation(bits=3)
    assert two["calls"] == [2] * 4 and three["calls"] == [3] * 8
    assert two["values"] != three["values"]
    assert two["declaration"]["conditions"] != three["declaration"]["conditions"]
    assert two["registry_key"] != three["registry_key"]
    assert two["other_declarations"] == three["other_declarations"]
    for observation, bits in ((two, 2), (three, 3)):
        guarantee = observation["guarantee"]
        assert guarantee["contract"] == wire(GUARANTEE)
        # Validate raw JSON before any ContractValue reconstruction could hide
        # an incorrect scalar representation returned by the child.
        assert type(guarantee["value"]["grid_bits"]) is int
        assert guarantee["value"]["grid_bits"] == bits
        bound = guarantee["value"]["selection_deviation_below"]
        assert all(type(part) is int for part in bound)
        assert bound == [1, 1 << bits]
        assert observation["declaration"]["conditions"] == [guarantee]


@pytest.mark.parametrize("bits", [2, 3])
def test_draw1_small_actual_grid_obeys_strict_interval_error_bound_and_can_miss_a_positive_cell(bits):
    draw_type(); public_bits()
    observation = isolated_worker_observation(bits=bits)
    size = 1 << bits
    values = [Q(*value) for value in observation["values"]]
    assert values == [Q(k, size) for k in range(size)]
    def ceil(value): return -(-value.numerator // value.denominator)
    points = sorted({Q(j, 3 * size) for j in range(3 * size + 1)} |
                    {Q(1, 4 * size), 1 - Q(1, 4 * size)})
    for left in points:
        for right in points:
            if left > right: continue
            count = sum(left <= value < right for value in values)
            assert count == ceil(size * right) - ceil(size * left)
            assert abs(Q(count, size) - (right - left)) < Q(1, size)
    epsilon = Q(1, 4 * size)
    assert epsilon > 0 and sum(1 - epsilon <= value < 1 for value in values) == 0
    if bits == 2:
        assert sum(value < Q(1, 3) for value in values) == 2  # H4's 1/2, not 1/3.


class HostDrawPort(DrawPort):
    def __init__(self, rig, work, delegate):
        super().__init__(); self.rig, self.work, self.delegate = rig, work, delegate
    def enter(self):
        self.trace.append("enter")
        entered = self.delegate.enter()
        if entered:
            self.rig.workers.entries.append(self.work)
            self.rig.workers.contexts["selection_draw"] = self.delegate
        return entered
    def post(self, event, issued=None):
        super().post(event, issued=issued)
        self.rig.draw_posts.append((self.work, event))
        self.rig.workers.sent.append((event, issued))
        self.delegate.post(event, issued=issued)


class HostDrawProbe:
    def __init__(self, rig, worker): self.rig, self.worker = rig, worker
    def run(self, work, ctx): return self.worker.run(work, HostDrawPort(self.rig, work, ctx))


class DrawRig(Stage2Rig):
    def __init__(self, cls, *, source=None, generator=OS_DRAW):
        super().__init__(auto_boot=False)
        self.draw_posts = []
        self.native_draw = cls() if source is None else cls(randbits=source)
        initial = replace(self.boot_input.declaration.initial.value,
                          draw=fb.MethodCall(contract=generator, args={}))
        self.boot_input = replace(self.boot_input, declaration=replace(self.boot_input.declaration,
            initial=replace(self.boot_input.declaration.initial, value=initial)))
        workers = {stage: self.workers for stage in (
            "measure_segment", "belief_update", "candidate_generation", "evaluation_prepare", "selection_draw", "evaluation")}
        workers["selection_draw"] = HostDrawProbe(self, self.native_draw)
        self.host = fb.FThreadHost(ledger=self.ledger, clock=self.clock,
            workers=fb.WorkerBundle(workers), registry=self.registry, launcher=self.launcher)
        self.host.post(self.clock_event); self.host.post(self.boot_input)


@pytest.fixture
def rigs():
    active = []
    def register(rig): active.append(rig); return rig
    yield register
    for rig in reversed(active): rig.close()


@pytest.mark.parametrize("position,choice", [("quarter", "Q"), ("three-quarters", "M")])
def test_draw1_host_saves_native_draw_fact_and_selects_the_determined_candidate(rigs, position, choice):
    cls = draw_type(); n = public_bits(); k = (1 if position == "quarter" else 3) * (1 << (n - 2))
    source = BitsSource(k); rig = rigs(DrawRig(cls, source=source))
    rig.through("evaluation"); rig.drive(lambda: bool(rig.facts(c.SELECTION)))
    work, event = rig.draw_posts[0]
    assert source.calls == [n] and wire(event.outcome.value) == {"u": [1 if position == "quarter" else 3, 4]}
    assert rig.one(DF).value == {"generator": wire(OS_DRAW), "stream_id": work.desc.args.stream_id,
        "request": wire(work.desc.args.request), "value": wire(event.outcome.value)}
    assert terminal(rig, work).value["terminal_kind"] == "value"
    assert rig.workers.issued["evaluation"].value.choice.id == choice
    assert len(rig.draw_posts) == 1 and rig.host.halted is None


@pytest.mark.parametrize("path", ["rejected", "execution_error"])
def test_draw1_host_persists_failure_without_draw_fact_evaluation_or_retry(rigs, path):
    cls = draw_type(); source = BitsSource(error=OSError("private source error"))
    rig = rigs(DrawRig(cls, source=source,
        generator=contract("stage2.scripted_draw") if path == "rejected" else OS_DRAW))
    rig.through("selection_draw")
    work, event = rig.draw_posts[0]
    assert isinstance(event.outcome, fb.DrawFailure)
    t = terminal(rig, work)
    assert t.value["terminal_kind"] == "failure" and t.value["returned"] is None
    assert event.outcome.failure.failure_kind == path
    assert wire(event.outcome.failure.content) == ({"reason": "unknown_generator"}
        if path == "rejected" else {"error_type": "OSError"})
    assert t.value["basis"]["failure"]["content"] == wire(event.outcome.failure.content)
    state = [row for row in rig.host.window.status().works if row.work_id == work.desc.work_id]
    assert len(state) == 1 and state[0].knowledge == "failure"
    assert_absent(rig, (DF, c.WORK_REQUESTED, c.EVALUATED, c.SELECTION))
    rig.settle_steps()
    assert len(rig.draw_posts) == 1 and source.calls == ([] if path == "rejected" else [public_bits()])
    assert rig.host.halted is None


class DrawLoopRig(EvaluationLoopRig):
    """All six bundle uses are native. Only world, clock and launch cut are TEST."""
    def __init__(self, cls, *, source=None):
        super().__init__(fb.Evaluator)
        self.draw_posts = []
        self.native_draw = cls() if source is None else cls(randbits=source)
        initial = replace(self.boot_input.declaration.initial.value,
                          draw=fb.MethodCall(contract=OS_DRAW, args={}))
        self.boot_input = replace(self.boot_input, declaration=replace(self.boot_input.declaration,
            initial=replace(self.boot_input.declaration.initial, value=initial)))
        self.bundle_workers["selection_draw"] = HostDrawProbe(self, self.native_draw)
        self.bundle = fb.WorkerBundle(self.bundle_workers)
        self.host = fb.FThreadHost(ledger=self.ledger, clock=self.clock, workers=self.bundle,
            registry=self.registry, launcher=self.launcher, sources={ROUTE: self.source})
        self.host.post(fb.ClockDeclared(declaration=self.clock_declaration)); self.host.post(self.boot_input)
    def run_stage(self, stage):
        if stage != "selection_draw": return super().run_stage(stage)
        request, body = self.callback(stage); wid = request.value["desc"]["work_id"]
        self.executed.add(wid); body()
        self.drive(lambda: any(row.value["work"] == wid for row in self.facts(c.DRAW_REPORT)))
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
        self.until(lambda: len(self.facts(c.EVALUATED)) == 1)


@pytest.mark.parametrize("mode", ["injected-quarter", "default-OS"])
def test_draw1_main_loop_uses_all_six_native_workers_and_preserves_the_adoption(mode, rigs):
    cls = draw_type(); n = public_bits()
    source = BitsSource(1 << (n - 2), 1 << (n - 2)) if mode == "injected-quarter" else None
    rig = rigs(DrawLoopRig(cls, source=source))
    assert rig.bundle_workers["measure_segment"] is rig.native_measurer
    assert rig.bundle_workers["belief_update"] is rig.native_updater
    assert type(rig.bundle_workers["candidate_generation"]) is fb.CandidateGenerator
    assert rig.bundle_workers["evaluation_prepare"].worker is rig.native_preparer
    assert rig.bundle_workers["evaluation"].worker is rig.native_evaluator
    assert rig.bundle_workers["selection_draw"].worker is rig.native_draw
    rig.start(); rig.publish(0, last=True); rig.update()
    for stage in ORDER[1:]: rig.run_stage(stage)
    rig.until(lambda: len(rig.facts(c.EVALUATED)) == 2)
    belief1_chain(rig, ({"joint": [[4, 5], [1, 5]], "evidence_mass": [5, 32]},))
    assert len(rig.draw_posts) == len(rig.facts(DF)) == len(rig.evaluation_posts) == 2
    for work, event in rig.draw_posts:
        assert isinstance(event.outcome, fb.DrawValue)
        u = Q(*wire(event.outcome.value)["u"])
        assert 0 <= u < 1
        assert any(row.value == {"generator": wire(OS_DRAW), "stream_id": work.desc.args.stream_id,
            "request": wire(work.desc.args.request), "value": wire(event.outcome.value)} for row in rig.facts(DF))
    for work, event, issue in rig.evaluation_posts:
        assert isinstance(event.outcome, fb.WorkOutputs)
        assert isinstance(issue.value, (f.Selected, f.NoDecision))
        if isinstance(issue.value, f.Selected):
            assert issue.value.choice.id in issue.value.evaluation.candidates
        else:
            # K34 does not guarantee numerical evaluation's settlement rate.
            assert mode == "default-OS" and issue.value.outcome == "incomplete"
    if source is not None:
        assert source.calls == [n, n]
        assert all(wire(event.outcome.value) == {"u": [1, 4]} for _, event in rig.draw_posts)
        assert all(isinstance(issue.value, f.Selected) and issue.value.choice.id == "Q"
                   for _, _, issue in rig.evaluation_posts)
        assert len(rig.facts(c.SELECTION)) == 2
    assert rig.host.halted is None and not rig.host.interruptions()
