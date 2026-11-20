"""K35 native bit-block worker; decisions 10-13 (:4920-4923), K35-a :3564.

The former fixed-grid assertions are retired: a block is not a sampled point.
The public guarantee has exactly the six K35-a fields; its three explanation
strings are nonempty, with no fixed wording. The sole registry condition equals
that public ContractValue. Strict integer checks distinguish JSON true from 1.
Fresh child processes inherit the parent's imported src, not pytest-only paths.
No production function body or private field is read or replaced.
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


OS_BITS = contract("sui.fb.os_uniform_bits")
GUARANTEE = replace(contract("sui.fb.draw_guarantee"), version="2")


def draw_type():
    assert hasattr(c, "OS_UNIFORM_BITS"), "K35 public API missing: fb_contracts.OS_UNIFORM_BITS"
    assert hasattr(fb, "UniformDraw"), "K35 public API missing: fb.UniformDraw"
    return fb.UniformDraw


def public_bits():
    assert hasattr(c, "OS_UNIFORM_BITS_BLOCK"), "K35 public API missing: fb_contracts.OS_UNIFORM_BITS_BLOCK"
    return c.OS_UNIFORM_BITS_BLOCK


def guarantee_function():
    assert hasattr(u2, "draw_guarantee"), "K35 public API missing: f_update2.draw_guarantee"
    return u2.draw_guarantee


def assert_guarantee(guarantee, *, bits):
    """K35-a :3564; expected fields/values are independent of native output."""
    assert isinstance(guarantee, f.ContractValue) and guarantee.contract == GUARANTEE
    body = wire(guarantee.value)
    assert isinstance(body, dict)
    assert set(body) == {"law", "source", "block_bits", "selection",
                         "not_guaranteed", "completion"}
    assert body["law"] == {"name": "uniform_bits", "version": "1"}
    assert body["source"] == "os_cryptographic_random"
    assert type(body["block_bits"]) is int and body["block_bits"] == bits
    for name in ("selection", "not_guaranteed", "completion"):
        assert isinstance(body[name], str) and body[name] != ""
    return body


def draw_work(*, label="one", method=OS_BITS, request=None):
    if request is None:
        request = f.DrawRequest(purpose="selection", context_key="problem-" + label,
            ordinal=0, law=contract("uniform_bits"), args={"offset": 0, "after": None})
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
    assert set(body) == {"bits", "length"}
    assert type(body["bits"]) is int and type(body["length"]) is int
    assert body["length"] == public_bits() and 0 <= body["bits"] < 1 << body["length"]
    if expected is not None: assert body["bits"] == expected
    return body


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
    for name in ("OS_UNIFORM_BITS", "DRAW_GUARANTEE"):
        assert hasattr(c, name), "K35 public API missing: fb_contracts." + name
    assert c.OS_UNIFORM_BITS == OS_BITS and c.DRAW_GUARANTEE == GUARANTEE
    assert type(public_bits()) is int and public_bits() == 128
    assert not hasattr(c, "OS_UNIFORM_DRAW") and not hasattr(c, "OS_UNIFORM_DRAW_BITS")


def test_draw1_public_guarantee_value_matches_the_six_field_v2_contract():
    fn = guarantee_function()
    assert callable(fn) and not signature(fn).parameters
    assert_guarantee(fn(), bits=public_bits())


@pytest.mark.parametrize("position", ["zero", "one", "even", "quarter", "half", "three-quarters", "last"])
def test_draw1_exact_bit_block_uses_one_source_call(position):
    cls = draw_type(); n = public_bits(); size = 1 << n
    k = {"zero": 0, "one": 1, "even": 2, "quarter": size // 4,
         "half": size // 2, "three-quarters": 3 * size // 4, "last": size - 1}[position]
    source = BitsSource(k); work = draw_work(); port = DrawPort()
    cls(randbits=source).run(work, port)
    assert source.calls == [n]
    value_from(port, work, k)


@pytest.mark.parametrize("position", ["negative", "upper", "above-upper"])
def test_draw1_out_of_range_integer_is_execution_failure_without_retry(position):
    cls = draw_type(); n = public_bits(); size = 1 << n
    source = BitsSource({"negative": -1, "upper": size, "above-upper": size + 1}[position])
    work = draw_work(); port = DrawPort(); cls(randbits=source).run(work, port)
    assert source.calls == [n]
    failure_from(port, work, kind="execution_error")


@pytest.mark.parametrize("change", ["generator-name", "generator-version", "purpose", "law-name", "law-version", "old-unit", "args"])
def test_draw1_rejection_does_not_consume_source_or_read_port_dependencies(change):
    cls = draw_type(); work = draw_work()
    if change.startswith("generator"):
        method = contract("other.generator") if change.endswith("name") else replace(OS_BITS, version="2")
        work = replace(work, desc=replace(work.desc, method=method))
        reason = "unknown_generator"
    else:
        request = work.desc.args.request
        changed = {"purpose": {"purpose": "algorithm"},
                   "law-name": {"law": contract("other.law")},
                   "law-version": {"law": replace(contract("uniform_bits"), version="2")},
                   "old-unit": {"law": contract("uniform_unit"), "args": {}},
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
    work = draw_work(method=contract("other.generator") if path == "rejected" else OS_BITS)
    port = DrawPort(post_error=error)
    with pytest.raises(OSError) as caught: cls(randbits=source).run(work, port)
    assert caught.value is error
    returned(port, work)
    assert source.calls == ([] if path == "rejected" else [public_bits()])


def test_draw1_same_worker_uses_two_current_jobs_and_two_fresh_values():
    cls = draw_type(); n = public_bits(); size = 1 << n
    source = BitsSource(size // 4, 3 * size // 4); worker = cls(randbits=source)
    for i, expected in enumerate([size // 4, 3 * size // 4]):
        work = draw_work(label=str(i)); port = DrawPort()
        work = replace(work, desc=replace(work.desc,
            args=replace(work.desc.args, request=replace(work.desc.args.request, ordinal=i))))
        worker.run(work, port); value_from(port, work, expected)
    assert source.calls == [n, n]


def test_draw1_registry_declares_one_generator_and_one_guarantee_condition():
    draw_type()
    for name in ("OS_UNIFORM_BITS", "DRAW_GUARANTEE"):
        assert hasattr(c, name), "K35 public API missing: fb_contracts." + name
    registry = u2.fb_registry_v1()
    rows = [d for d in registry.declarations if d.kind == "generator" and d.ref == OS_BITS]
    assert len(rows) == 1
    assert not any(d.ref == contract("sui.fb.os_uniform_draw") for d in registry.declarations)
    assert rows[0].args_contract == contract("sui.f.args.empty")
    guarantee = guarantee_function()()
    assert_guarantee(guarantee, bits=public_bits())
    assert rows[0].conditions == (guarantee,)
    assert_guarantee(rows[0].conditions[0], bits=public_bits())
    assert len([i for i in registry.implementations if i.kind == "generator" and i.ref == OS_BITS]) == 1
    assert not any(i.ref == contract("sui.fb.os_uniform_draw") for i in registry.implementations)


@pytest.mark.parametrize("offset,after", [(0, None), (128, "previous-block-not-readable-here")])
def test_exact1_native_worker_takes_one_new_block_without_reading_after(offset, after):
    cls = draw_type(); source = BitsSource(7); port = DrawPort()
    request = replace(draw_work().desc.args.request, args={"offset": offset, "after": after})
    work = draw_work(request=request)
    cls(randbits=source).run(work, port)
    value_from(port, work, 7)
    assert source.calls == [128]


@pytest.mark.parametrize("args", [{"offset": True, "after": None},
    {"offset": -1, "after": "p"}, {"offset": 1.0, "after": "p"},
    {"offset": 0, "after": "p"}, {"offset": 1, "after": None},
    {"offset": 1, "after": []}, {"offset": 0},
    {"offset": 0, "after": None, "extra": 1}])
def test_exact1_native_worker_rejects_invalid_offset_after_without_drawing(args):
    cls = draw_type(); source = BitsSource(); port = DrawPort()
    request = replace(draw_work().desc.args.request, args=args)
    work = draw_work(request=request)
    cls(randbits=source).run(work, port)
    failure_from(port, work, kind="rejected", content={"reason": "unsupported_request"})
    assert source.calls == []


@pytest.mark.parametrize("bad", [True, False, 1.0, "1", None])
def test_exact1_native_worker_rejects_non_integer_source_value_without_retry(bad):
    cls = draw_type(); source = BitsSource(bad); port = DrawPort(); work = draw_work()
    cls(randbits=source).run(work, port)
    failure_from(port, work, kind="execution_error")
    assert source.calls == [128]


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
    c.OS_UNIFORM_BITS_BLOCK = settings["bits"]
import test_fb_draw as t
from sui import fb, f_update2 as u2
from gate_f_facts_cases import assemble, prepare
n = c.OS_UNIFORM_BITS_BLOCK
calls.clear()
worker = fb.UniformDraw() if settings["default_source"] else None
assert calls == [], "construction must not consume randomness"
values = []
if settings["default_source"]:
    work = t.draw_work(); port = t.DrawPort(); worker.run(work, port)
    t.value_from(port, work, 1); values.append(t.wire(port.posts[0][0].outcome.value))
else:
    source = t.BitsSource(*range(1 << n)); worker = fb.UniformDraw(randbits=source)
    for k in range(1 << n):
        work = t.draw_work(label=str(k)); port = t.DrawPort(); worker.run(work, port)
        t.value_from(port, work, k); values.append(t.wire(port.posts[0][0].outcome.value))
    calls = source.calls
draw_calls = list(calls)
registry = u2.fb_registry_v1()
declaration = [d for d in registry.declarations if d.kind == "generator" and d.ref == t.OS_BITS]
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
    assert observation["values"] == [{"bits": 1, "length": 128}]


def test_draw1_changing_the_single_public_N_changes_worker_and_registry_declaration():
    draw_type(); public_bits()
    two = isolated_worker_observation(bits=2)
    three = isolated_worker_observation(bits=3)
    assert two["calls"] == [2] * 4 and three["calls"] == [3] * 8
    assert two["values"] != three["values"]
    assert two["registry_key"] != three["registry_key"]
    assert two["other_declarations"] == three["other_declarations"]
    for observation, bits in ((two, 2), (three, 3)):
        assert observation["guarantee"]["contract"] == wire(GUARANTEE)
        assert type(observation["guarantee"]["value"]["block_bits"]) is int
        assert observation["guarantee"]["value"]["block_bits"] == bits
        assert observation["declaration"]["conditions"] == [observation["guarantee"]]



@pytest.mark.parametrize("bits", [2, 3])
def test_draw1_small_blocks_preserve_all_bits_and_leading_zero_length(bits):
    draw_type(); public_bits()
    observation = isolated_worker_observation(bits=bits)
    assert observation["calls"] == [bits] * (1 << bits)
    assert observation["values"] == [{"bits": k, "length": bits} for k in range(1 << bits)]


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
    def __init__(self, cls, *, source=None, generator=OS_BITS):
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
    assert source.calls == [n] and wire(event.outcome.value) == {"bits": k, "length": n}
    assert rig.one(DF).value == {"generator": wire(OS_BITS), "stream_id": work.desc.args.stream_id,
        "request": wire(work.desc.args.request), "value": wire(event.outcome.value)}
    assert terminal(rig, work).value["terminal_kind"] == "value"
    assert rig.workers.issued["evaluation"].value.choice.id == choice
    assert len(rig.draw_posts) == 1 and rig.host.halted is None


@pytest.mark.parametrize("path", ["rejected", "execution_error"])
def test_draw1_host_persists_failure_without_draw_fact_evaluation_or_retry(rigs, path):
    cls = draw_type(); source = BitsSource(error=OSError("private source error"))
    rig = rigs(DrawRig(cls, source=source,
        generator=contract("stage2.scripted_draw") if path == "rejected" else OS_BITS))
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
                          draw=fb.MethodCall(contract=OS_BITS, args={}))
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


def test_draw1_main_loop_uses_all_six_native_workers_and_preserves_the_adoption(rigs):
    cls = draw_type(); n = public_bits()
    # Deterministic prefixes make this a finite main-loop control. The default
    # OS binding is observed in the fresh-import source test; K35 does not promise
    # that two arbitrary OS blocks finish exactly two logical selections.
    source = BitsSource(1 << (n - 2), 1 << (n - 2))
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
        block = wire(event.outcome.value)
        assert set(block) == {"bits", "length"} and block["length"] == n
        assert type(block["bits"]) is int and 0 <= block["bits"] < 1 << n
        assert any(row.value == {"generator": wire(OS_BITS), "stream_id": work.desc.args.stream_id,
            "request": wire(work.desc.args.request), "value": wire(event.outcome.value)} for row in rig.facts(DF))
    for work, event, issue in rig.evaluation_posts:
        assert isinstance(event.outcome, fb.WorkOutputs)
        assert isinstance(issue.value, f.Selected)
        assert issue.value.choice.id in issue.value.evaluation.candidates
    assert source.calls == [n, n]
    assert all(wire(event.outcome.value) == {"bits": 1 << (n - 2), "length": n} for _, event in rig.draw_posts)
    assert all(issue.value.choice.id == "Q" for _, _, issue in rig.evaluation_posts)
    assert len(rig.facts(c.SELECTION)) == 2
    assert rig.host.halted is None and not rig.host.interruptions()
