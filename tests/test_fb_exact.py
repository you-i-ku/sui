"""K35 exact selection from saved bit prefixes (paper :4911-4986).

Read boundary: specifications, public declarations/docstrings, existing tests.
Expected probabilities come from equal-J finite policies, normalized declared
cost probabilities, or FA01's analytic q=(1/3,2/3). No private implementation.

Discrimination, one error per line:
- A left/mid/rounded point cannot replace an interval straddling 1/3.
- The half-open right endpoint permits equality at the next exact boundary.
- Missing/overlapping/foreign blocks cannot authenticate a single logical draw.
- A new block keeps ordinal and changes offset, ID, root and full-prefix witness.
- A continuation must preserve each terminal and not create a comparison pG.
- Replays use sealed saved blocks, never the current random source.
- Numerical refinement and bit refinement are independent obligations.

K35-a (:3564) closes the three CGs: the guarantee's six-field JSON is tested in
test_fb_draw; a sealed ancestor cycle is outside public construction; a second
host firing with the same stream/problem_key remains unverified and is assigned
to review and mutation checks. Neither deferred case is counted as a test pass.
Work terminals are retained per decision 9(d), not mistaken for process failure.
Only work-row existence is fixed while saving; Held's exact display subtype is
the explicitly deferred issue at :4993.

Request 80 fixture corrections: host rounds admit queued Posts before assertions;
late reports reuse their original WorkId's public port (B6); pending callbacks
are selected by unexecuted WorkId, never ledger enumeration order. The replay
observer permits dependency setup and forbids randomness only during replay,
including calls through aliases captured during import. Evaluator cap tests bind
the reader with an adequate budget before applying the smaller evaluation cap.
"""

from dataclasses import fields, replace
from fractions import Fraction as Q
from hashlib import sha256
import json
from pathlib import Path

import pytest

from sui import f, f_contracts as fc, f_facts as ff, fb, fb_contracts as c
from sui.records import Observed, Payload
from sui.rate import RateBudget
from gate_f_facts_cases import (assemble, prepare, add_draw, bound, plain,
    canonical, Reader, MissingBodyReader, declaration, idle_kernel, action, policy,
    BUDGET)
from test_fb_skeleton import contract
from test_fb_stage2 import (Stage2Rig, ORDER, DF, CG, MATH, REQUESTS, terminal,
    additional_terminal, raw_for, comparison_purposes)
from test_fb_draw import (BitsSource, HostDrawProbe, DrawLoopRig, draw_type,
    public_bits)
from test_fb_evaluator import flat_case, flat_document


BITS = contract("uniform_bits")
GENERATOR = contract("sui.fb.os_uniform_bits")


def require_exact():
    assert hasattr(f, "DrawPrefix"), "K35 public API missing: f.DrawPrefix"
    return f.DrawPrefix


def budget(**changes):
    return replace(BUDGET, **changes)


def equal_case(masses=(Q(1, 2), Q(1, 2))):
    """Analytic finite fixtures; no weighted-measure extension is assumed.

    Half/half: J=0 for both idle operations. Third/two-thirds: FA01 information
    gives exp(-J)=(1,2). Tiny last cell: three normalized dyadic preferences give
    weights ((1-2^-50)^3, (2^-50)^3), hence epsilon < 2^-128.
    """
    if masses == (Q(1, 3), Q(2, 3)):
        return assemble("FA01")
    kernel = idle_kernel("same", elapsed=0)
    actions = (action("Q", "same"), action("M", "same"))
    document = declaration([kernel], actions, [policy(a.id, kernel) for a in actions])
    case = assemble("FA01", document=document, order=["Q", "M"])
    if masses != (Q(1, 2), Q(1, 2)):
        assert 0 < masses[1] < Q(1, 1 << 128)
        for _ in range(3):
            case.preference({"kind": "item", "rule": {"name": "table", "version": "1"},
                "args": {"feature": {"name": "started_actions", "version": "1"},
                    "probs": [[["Q"], 1 - 2.**-50], [["M"], 2.**-50]]}})
        case.context()
    return case


def add_block(case, problem_key, k, length, *, offset=0, after=None,
              ordinal=0, stream="exact-selection", generator=GENERATOR,
              law=BITS, parents=None):
    fact = f.FDrawFact(generator=generator, stream_id=stream,
        request=f.DrawRequest(purpose="selection", context_key=problem_key,
            ordinal=ordinal, law=law, args={"offset": offset, "after": after}),
        value={"bits": k, "length": length})
    return case.put("block-" + str(len(case.ledger.entries())),
        Observed(route="draw", content=Payload.json(plain(fact)),
            contract=fc.DRAW_FACT, received_ns=case.clock.mono_ns()), parents=parents)


def block_chain(case, prepared, blocks):
    points, offset = [], 0
    for k, length in blocks:
        points.append(add_block(case, prepared.value.problem_key, k, length,
            offset=offset, after=points[-1] if points else None))
        offset += length
    return points


def evaluate(case, prepared, point, *, cap=BUDGET):
    return ff.evaluate_f_from_draw(prepared, point, reader=case.reader, budget=cap)


def assert_selected(value, choice, k, length):
    prefix_type = require_exact()
    assert isinstance(value, f.Selected) and value.choice.id == choice
    assert value.u is None and value.prefix == prefix_type(bits=k, length=length)
    assert value.previous.upper <= Q(k, 1 << length)
    assert Q(k + 1, 1 << length) <= value.current.lower


def assert_boundary(value):
    assert isinstance(value, f.NoDecision)
    assert value.outcome == "incomplete" and value.reason == "selection_boundary"
    assert isinstance(value.progress, f.FEvaluation)


def test_exact1_public_prefix_and_optional_u_shape():
    cls = require_exact()
    assert [x.name for x in fields(cls)] == ["bits", "length"]
    assert "selection_prefix" in {x.name for x in fields(f.FRoot)}
    assert "prefix" in {x.name for x in fields(f.Selected)}
    from inspect import signature
    assert signature(f.certify_f_choice).parameters["u"].default is None


@pytest.mark.parametrize("k,length,choice", [(0, 128, "Q"), (1 << 127, 128, "M"),
    ((1 << 128) - 1, 128, "M"), (0, 1, "Q"), (1, 1, "M")])
def test_exact1_closed_enclosure_fits_half_open_selection_interval(k, length, choice):
    require_exact(); case = equal_case(); prepared = prepare(case)
    draw = add_block(case, prepared.value.problem_key, k, length)
    result = evaluate(case, prepared, draw)
    assert_selected(result.value, choice, k, length)
    assert result.value.root.contract == replace(contract("sui.f.root"), version="4")
    assert result.value.previous.lower == result.value.previous.upper
    assert result.value.current.lower == result.value.current.upper


def test_exact1_straddling_interval_is_not_its_left_midpoint_or_rounded_point():
    require_exact(); case = equal_case((Q(1, 3), Q(2, 3))); prepared = prepare(case)
    # [1/4,1/2) straddles 1/3; both point conventions would choose something.
    first = add_block(case, prepared.value.problem_key, 1, 2)
    result = evaluate(case, prepared, first)
    assert_boundary(result.value)
    follow = add_block(case, prepared.value.problem_key, 0, 2, offset=2, after=first)
    assert_selected(evaluate(case, prepared, follow).value, "Q", 4, 4)
    other = add_block(case, prepared.value.problem_key, 3, 2, offset=2, after=first)
    assert_selected(evaluate(case, prepared, other).value, "M", 7, 4)


def test_exact1_partial_one_bit_completion_is_not_the_conditioned_q_distribution():
    require_exact(); case = assemble("FA01"); prepared = prepare(case)
    zero = add_block(case, prepared.value.problem_key, 0, 1)
    one = add_block(case, prepared.value.problem_key, 1, 1)
    assert_boundary(evaluate(case, prepared, zero).value)
    assert_selected(evaluate(case, prepared, one).value, "M", 1, 1)
    # Ideal fair first bits: completion mass=1/2; conditional chosen M=1,
    # while the fixed problem's q_M=2/3. No OS statistical claim is made.


def test_exact1_tiny_last_cell_and_right_endpoint_one_are_reachable():
    require_exact(); epsilon = Q(1, 1 << 140)
    case = equal_case((1 - epsilon, epsilon)); prepared = prepare(case)
    # The actual worker supplies both blocks; only their immutable fact records
    # are assembled by the F-a fixture, as permitted for mathematical tests.
    from test_fb_draw import DrawPort, draw_work, value_from
    source = BitsSource((1 << 128) - 1, (1 << 128) - 1)
    worker = fb.UniformDraw(randbits=source)
    def take(offset, after):
        request = f.DrawRequest(purpose="selection", context_key=prepared.value.problem_key,
            ordinal=0, law=BITS, args={"offset": offset, "after": after})
        work = draw_work(request=request); port = DrawPort(); worker.run(work, port)
        return value_from(port, work)
    block = take(0, None)
    first = add_block(case, prepared.value.problem_key, block["bits"], block["length"])
    assert_boundary(evaluate(case, prepared, first).value)
    block = take(128, first)
    last = add_block(case, prepared.value.problem_key, block["bits"], block["length"],
                     offset=128, after=first)
    assert_selected(evaluate(case, prepared, last).value, "M", (1 << 256) - 1, 256)
    assert source.calls == [128, 128]


def test_exact1_variable_lengths_leading_zeroes_extend_without_mutating_prior_root():
    require_exact(); case = equal_case(); prepared = prepare(case)
    points = block_chain(case, prepared, [(0, 3), (1, 2), (0, 4)])
    roots = [ff.bind_f_draw(prepared, p, reader=case.reader, budget=BUDGET) for p in points]
    before = roots[0].canonical_bytes
    last = roots[-1].value
    assert len(last.selection_prefix) == 3
    assert [plain(x.value) for x in last.selection_prefix] == [
        {"bits": 0, "length": 3}, {"bits": 1, "length": 2}, {"bits": 0, "length": 4}]
    assert last.selection_draw == last.selection_prefix[-1] and last.draw_point == points[-1]
    assert len({x.value.root_key for x in roots}) == 3
    assert roots[0].canonical_bytes == before
    assert_selected(evaluate(case, prepared, points[-1]).value, "Q", 16, 9)


def test_exact1_draw_id_separates_positions_but_not_after_reference_or_value():
    require_exact(); case = equal_case(); prepared = prepare(case)
    first = add_block(case, prepared.value.problem_key, 0, 2)
    same = add_block(case, prepared.value.problem_key, 1, 2)
    second = add_block(case, prepared.value.problem_key, 0, 2, offset=2, after=first)
    other_after = add_block(case, prepared.value.problem_key, 0, 2, offset=2, after=same)
    read = lambda p: ff.bind_f_draw(prepared, p, reader=case.reader, budget=BUDGET).value.selection_draw
    a, b, x, y = map(read, (first, same, second, other_after))
    assert a.id == b.id and x.id == y.id and a.id != x.id
    expected = {"domain": "sui.f.draw/2", "generator": plain(GENERATOR),
        "stream_id": "exact-selection", "purpose": "selection",
        "context_key": prepared.value.problem_key, "ordinal": 0,
        "law": plain(BITS), "offset": 2}
    assert x.id == "sha256:" + sha256(canonical(expected)).hexdigest()


def test_exact1_root_key_binds_block_points_even_when_prefix_bits_and_draw_ids_match():
    require_exact(); case = equal_case(); prepared = prepare(case)
    first = add_block(case, prepared.value.problem_key, 1, 3)
    other = add_block(case, prepared.value.problem_key, 1, 3)
    a = ff.bind_f_draw(prepared, first, reader=case.reader, budget=BUDGET)
    b = ff.bind_f_draw(prepared, other, reader=case.reader, budget=BUDGET)
    assert a.value.selection_prefix == b.value.selection_prefix
    assert a.value.draw_point != b.value.draw_point
    assert a.value.root_key != b.value.root_key


@pytest.mark.parametrize("fault", ["gap", "overlap", "stream", "ordinal", "law",
    "generator", "context", "not-ancestor", "first-offset"])
def test_exact1_one_broken_chain_condition_is_invalid_draw(fault):
    require_exact(); case = equal_case(); prepared = prepare(case)
    first = add_block(case, prepared.value.problem_key, 0, 3)
    kwargs = {"offset": 3, "after": first}
    problem_key = prepared.value.problem_key
    if fault == "gap": kwargs["offset"] = 4
    if fault == "overlap": kwargs["offset"] = 2
    if fault == "stream": kwargs["stream"] = "different-stream"
    if fault == "ordinal": kwargs["ordinal"] = 1
    if fault == "law": kwargs["law"] = contract("uniform_unit")
    if fault == "generator": kwargs["generator"] = contract("different.generator")
    if fault == "context": problem_key += "-other"
    if fault == "not-ancestor": kwargs["parents"] = case.fixed_parents
    if fault == "first-offset": kwargs.update(offset=3, after=None)
    last = add_block(case, problem_key, 1, 2, **kwargs)
    with pytest.raises(f.FInputError) as caught:
        ff.bind_f_draw(prepared, last, reader=case.reader, budget=BUDGET)
    assert caught.value.reason == "invalid_draw" and caught.value.field.startswith("/draw")


@pytest.mark.parametrize("value", [{"bits": True, "length": 2}, {"bits": 0, "length": True},
    {"bits": -1, "length": 2}, {"bits": 4, "length": 2}, {"bits": 0, "length": 0},
    {"bits": 0, "length": 2, "extra": 1}])
def test_exact1_invalid_bit_values_are_named_input_errors(value):
    require_exact(); case = equal_case(); prepared = prepare(case)
    p = add_block(case, prepared.value.problem_key, 0, 2)
    record = case.reader.record(p)
    body = record.body.content.as_json(); body["value"] = value
    bad = case.put("bad", replace(record.body, content=Payload.json(body)))
    with pytest.raises(f.FInputError) as caught:
        ff.bind_f_draw(prepared, bad, reader=case.reader, budget=BUDGET)
    assert caught.value.reason == "invalid_draw" and caught.value.field.startswith("/draw")


@pytest.mark.parametrize("op", ["choice", "evaluate"])
@pytest.mark.parametrize("fault", ["missing", "changed"])
@pytest.mark.parametrize("outcome", ["selected", "no_decision"])
def test_exact1_replay_authenticates_every_saved_block_without_randomness(op, fault, outcome, monkeypatch):
    require_exact(); case = equal_case() if outcome == "selected" else assemble("FA01")
    prepared = prepare(case)
    blocks = [(0, 3), (1, 2)] if outcome == "selected" else [(1, 2), (1, 2)]
    first, last = block_chain(case, prepared, blocks)
    root = ff.bind_f_draw(prepared, last, reader=case.reader, budget=BUDGET)
    result = (f.certify_f_choice(f.evaluate_f_recursive(root.value, budget=BUDGET))
              if op == "choice" else evaluate(case, prepared, last))
    data = ff.f_math_json(result)
    if outcome == "selected": assert isinstance(result.value if hasattr(result, "value") else result, f.Selected)
    else: assert_boundary(result.value if hasattr(result, "value") else result)
    calls = []
    def forbidden(n): calls.append(n); raise AssertionError("replay drew fresh bits")
    import secrets
    monkeypatch.setattr(secrets, "randbits", forbidden)
    good = ff.restore_f_math_result(data, reader=case.reader,
        registry=f.builtin_f_registry(), budget=BUDGET)
    assert ff.f_math_json(good) == data
    if fault == "missing":
        reader = MissingBodyReader(case.ledger, first)
        expected = f.FReplayUnavailable
    else:
        class Changed(Reader):
            def record(self, cid):
                original = super().record(cid)
                if cid != first: return original
                body = original.body.content.as_json(); body["value"]["bits"] ^= 1
                return replace(original, body=replace(original.body, content=Payload.json(body)))
        reader = Changed(case.ledger); expected = f.FReplayMismatch
    with pytest.raises(expected):
        ff.restore_f_math_result(data, reader=reader, registry=f.builtin_f_registry(), budget=BUDGET)
    assert calls == []


@pytest.mark.parametrize("op", ["choice", "evaluate"])
@pytest.mark.parametrize("outcome", ["selected", "no_decision"])
def test_exact1_fresh_import_replay_never_calls_OS_even_through_import_time_aliases(op, outcome):
    require_exact()
    from test_fb_draw import run_isolated_python
    script = r'''
import json, secrets, sys
sys.path.insert(0, "tests")
calls=[]
original_randbits=secrets.randbits
phase="setup"
def observed(n):
    # Dependencies may legitimately seed themselves while being imported. Keep
    # this observer installed early so import-time aliases are still monitored,
    # but activate the prohibition only for the mathematical replay itself.
    if phase=="replay":
        calls.append(n)
        raise AssertionError("mathematical replay used OS random source")
    return original_randbits(n)
secrets.randbits=observed
import test_fb_exact as t
op,outcome=sys.argv[1:]
case=t.equal_case() if outcome=="selected" else t.assemble("FA01")
p=t.prepare(case)
d=t.add_block(case,p.value.problem_key,0 if outcome=="selected" else 1,2)
root=t.ff.bind_f_draw(p,d,reader=case.reader,budget=t.BUDGET)
result=(t.f.certify_f_choice(t.f.evaluate_f_recursive(root.value,budget=t.BUDGET))
        if op=="choice" else t.evaluate(case,p,d))
data=t.ff.f_math_json(result)
phase="replay"
restored=t.ff.restore_f_math_result(data,reader=case.reader,registry=t.f.builtin_f_registry(),budget=t.BUDGET)
assert t.ff.f_math_json(restored)==data
assert calls==[]
print(json.dumps({"OS_calls":calls,"same_bytes":True}))
'''
    child = run_isolated_python(script, op, outcome)
    assert child.returncode == 0, child.stderr
    assert json.loads(child.stdout) == {"OS_calls": [], "same_bytes": True}


@pytest.mark.parametrize("kind", ["root", "selected"])
def test_exact1_old_point_artifact_bytes_remain_identical_and_default_fields_omitted(kind):
    require_exact()
    saved = json.loads(Path(__file__).with_name("k35_old_point_artifacts.json").read_text(encoding="utf-8"))
    case = assemble("FA01"); prepared, draw, root = bound(case)
    result = root if kind == "root" else evaluate(case, prepared, draw)
    data = saved[kind].encode("utf-8")
    restored = ff.restore_f_math_result(data, reader=case.reader,
        registry=f.builtin_f_registry(), budget=BUDGET)
    assert restored.canonical_bytes == result.canonical_bytes == data
    assert restored.value.root_key == root.value.root_key if kind == "root" else restored.value.u == Q(1, 2)
    body = json.loads(data)
    claim = body["claim"]["value"]
    target = claim if kind == "root" else claim["root"]
    assert "selection_prefix" not in target
    if kind == "selected": assert "prefix" not in claim
    changed = json.loads(data)
    changed_claim = changed["claim"]["value"]
    if kind == "root": changed_claim["selection_prefix"] = []
    else: changed_claim["prefix"] = None
    with pytest.raises(f.FInputError) as caught:
        ff.restore_f_math_result(canonical(changed), reader=case.reader,
            registry=f.builtin_f_registry(), budget=BUDGET)
    assert caught.value.reason == "noncanonical"


@pytest.mark.parametrize("max_refinements", [1, 2, None])
def test_exact1_exact_boundary_requests_bits_even_on_last_refinement(max_refinements):
    require_exact(); case = equal_case((Q(1, 3), Q(2, 3))); prepared = prepare(case)
    first = add_block(case, prepared.value.problem_key, 1, 2)
    assert_boundary(evaluate(case, prepared, first, cap=budget(max_refinements=max_refinements)).value)


@pytest.mark.parametrize("limited", ["max_cells", "max_terms"])
def test_exact1_unbounded_refinements_preserve_other_finite_limits(limited):
    require_exact(); case = assemble("FA01"); prepared = prepare(case)
    draw = add_block(case, prepared.value.problem_key, 1, 2)
    # Capture/authenticate the reader with an adequate budget first. This case
    # isolates the evaluator's limits, not the earlier reader-capture exception.
    root = ff.bind_f_draw(prepared, draw, reader=case.reader, budget=BUDGET)
    result = f.evaluate_f(root.value,
        budget=budget(max_refinements=None, **{limited: 1}))
    assert isinstance(result, f.NoDecision) and result.reason == "budget_exhausted"
    control = f.evaluate_f(root.value,
        budget=budget(max_cells=None, max_terms=None, max_refinements=None))
    assert isinstance(control, (f.Selected, f.NoDecision))
    if isinstance(control, f.NoDecision): assert control.reason == "selection_boundary"


def test_exact1_finite_numerical_precision_exhaustion_is_not_a_bit_request():
    require_exact(); case = assemble("FA01"); prepared = prepare(case)
    # 400 known digits require much finer arithmetic than the first 1e-24 pass.
    length = 400; k = (1 << length) // 3
    draw = add_block(case, prepared.value.problem_key, k, length)
    exhausted = evaluate(case, prepared, draw,
        cap=budget(max_cells=None, max_terms=None, max_refinements=1)).value
    assert isinstance(exhausted, f.NoDecision) and exhausted.reason == "budget_exhausted"
    precise = evaluate(case, prepared, draw,
        cap=budget(max_cells=None, max_terms=None, max_refinements=40)).value
    assert_boundary(precise)


def test_exact1_nonfinite_branch_selects_away_from_boundary():
    require_exact(); case = flat_case(); prepared = prepare(case)
    p = add_block(case, prepared.value.problem_key, 1, 2)
    assert_selected(evaluate(case, prepared, p).value, "Q", 1, 2)


def test_exact1_nonfinite_fixed_arithmetic_precision_is_not_replaced_by_endless_bit_requests():
    require_exact()
    case = assemble("FA14", document=flat_document(), order=["Q", "M"])
    prepared = prepare(case)
    away = add_block(case, prepared.value.problem_key, 0, 2)
    assert_selected(evaluate(case, prepared, away).value, "Q", 0, 2)
    near = add_block(case, prepared.value.problem_key, (1 << 128) // 3, 128)
    result = evaluate(case, prepared, near, cap=budget(max_refinements=8)).value
    assert isinstance(result, f.NoDecision) and result.reason == "budget_exhausted"
    # The same q and bit interval on the finite-tree branch can refine arithmetic.
    finite = assemble("FA01"); p = prepare(finite)
    d = add_block(finite, p.value.problem_key, (1 << 128) // 3, 128)
    assert_boundary(evaluate(finite, p, d, cap=budget(max_refinements=8)).value)


def test_exact1_left_boundary_with_nonzero_enclosure_width_needs_bits_not_an_invented_point():
    require_exact(); case = assemble("FA01")
    # FA01 information gives weights (1,2). Cost probabilities (1/2,1/4)
    # balance these to (1/2,1/2); the unused empty-history atom normalizes the
    # preference declaration. Exact q=1/2, with nontrivial log/exp enclosures.
    case.preference({"kind": "item", "rule": {"name": "table", "version": "1"},
        "args": {"feature": {"name": "started_actions", "version": "1"},
            "probs": [[["Q"], .5], [["M"], .25], [[], .25]]}})
    case.context(); prepared = prepare(case)
    p = add_block(case, prepared.value.problem_key, 1 << 127, 128)
    root = ff.bind_f_draw(prepared, p, reader=case.reader, budget=BUDGET)
    coarse = f.evaluate_f_recursive(root.value, budget=BUDGET)
    assert coarse.cumulative[1].lower < Q(1, 2) < coarse.cumulative[1].upper
    assert_boundary(evaluate(case, prepared, p).value)
    last = add_block(case, prepared.value.problem_key, (1 << 128) - 1, 128,
                     offset=128, after=p)
    assert_selected(evaluate(case, prepared, last).value, "M", (1 << 255) + (1 << 128) - 1, 256)


def test_exact1_old_bridge_rejects_bit_law_at_named_draw_boundary():
    require_exact()
    from gate_f_facts_cases import assemble_legacy_bridge, prepare_bridge
    case, _ = assemble_legacy_bridge(); prepared = prepare_bridge(case)
    draw = add_block(case, prepared.value.problem_key, 1, 2)
    with pytest.raises(f.FInputError) as caught:
        ff.evaluate_legacy_bridge_from_draw(prepared, draw, reader=case.reader, budget=BUDGET)
    assert caught.value.reason == "invalid_draw" and caught.value.field == "/draw/request"


def test_exact1_independent_draw_ordinals_are_distinct_from_same_draw_offsets():
    require_exact(); case = equal_case(); prepared = prepare(case)
    p0 = add_block(case, prepared.value.problem_key, 1, 2)
    p1 = add_block(case, prepared.value.problem_key, 1, 2, ordinal=1)
    r0 = ff.bind_f_draw(prepared, p0, reader=case.reader, budget=BUDGET).value
    r1 = ff.bind_f_draw(prepared, p1, reader=case.reader, budget=BUDGET).value
    assert r0.selection_draw.id != r1.selection_draw.id
    assert r0.selection_draw.ordinal == 0 and r1.selection_draw.ordinal == 1


@pytest.fixture
def exact_rigs():
    active = []
    def add(rig): active.append(rig); return rig
    yield add
    for rig in reversed(active): rig.close()


class ExactHostRig(Stage2Rig):
    """Native draw+evaluator, manually released launch callbacks, no sleeps."""
    def __init__(self, values, *, masses=(Q(1, 3), Q(2, 3)), evaluate_budget=None, document=None):
        require_exact(); super().__init__(auto_boot=False)
        self.draw_posts, self.evaluation_posts = [], []
        self.source = BitsSource(*values); self.executed = set()
        self.work_ports = {}
        self.native_draw = fb.UniformDraw(randbits=self.source)
        initial = replace(self.boot_input.declaration.initial.value,
            draw=fb.MethodCall(contract=GENERATOR, args={}),
            evaluate_budget=evaluate_budget or budget(max_refinements=None))
        self.boot_input = replace(self.boot_input, declaration=replace(self.boot_input.declaration,
            initial=replace(self.boot_input.declaration.initial, value=initial)))
        # The saved finite model is replaced BEFORE Boot, through the public ledger.
        document = equal_case(masses).document if document is None else document
        from sui.records import Prediction, Role
        from sui.ids import RefKind
        record = self.record(Prediction(target="model.exact", about=(), basis=(),
            content=Payload.json({"document": document}), contract=contract("sui.f.model_source")),
            RefKind.PREDICTION, Role.MODEL)
        self.model_point = self.ledger.append(record, ()).cid
        self.boot_input = replace(self.boot_input, declaration=replace(self.boot_input.declaration,
            initial=replace(self.boot_input.declaration.initial,
                value=replace(initial, model=self.model_point))))
        rig = self
        class EvalPort(fb.FWorkContext):
            def __init__(self, delegate, work): self.delegate, self.work = delegate, work
            def __getattr__(self, name): return getattr(self.delegate, name)
            def now(self): return self.delegate.now()
            def read(self, point): return self.delegate.read(point)
            def reader(self): return self.delegate.reader()
            def prepared(self): return self.delegate.prepared()
            def evidence(self): return self.delegate.evidence()
            def acquire(self): return self.delegate.acquire()
            def monitored(self, interval): return self.delegate.monitored(interval)
            def enter(self):
                ok = self.delegate.enter()
                if ok:
                    rig.workers.entries.append(self.work)
                    rig.workers.contexts["evaluation"] = self.delegate
                return ok
            def post(self, event, issued=None):
                rig.evaluation_posts.append((self.work, event, issued))
                rig.workers.sent.append((event, issued)); self.delegate.post(event, issued=issued)
        class Evaluation:
            def __init__(self): self.worker = fb.Evaluator()
            def run(self, work, ctx): return self.worker.run(work, EvalPort(ctx, work))
        workers = {stage: self.workers for stage in (*ORDER, "measure_segment", "belief_update")}
        self.draw_probe = HostDrawProbe(self, self.native_draw)
        workers["selection_draw"] = self.draw_probe
        self.evaluation_delegate = Evaluation()
        workers["evaluation"] = self.evaluation_delegate
        class CapturedWorker(fb.FWorkers):
            def __init__(self, worker): self.worker = worker
            def run(self, work, ctx):
                # Retain exactly the public port delivered to this WorkId.
                # Late reports must use that port (paper B6), even after return.
                rig.work_ports[work.desc.work_id] = ctx
                return self.worker.run(work, ctx)
        workers = {stage: CapturedWorker(worker) for stage, worker in workers.items()}
        self.host = fb.FThreadHost(ledger=self.ledger, clock=self.clock,
            workers=fb.WorkerBundle(workers), registry=self.registry, launcher=self.launcher)
        self.host.post(self.clock_event); self.host.post(self.boot_input)

    def settle_steps(self):
        # Unlike FWindow.settle(), the public host round admits posted envelopes.
        # Fixed rounds are only a safety probe; positive progress uses drive().
        for _ in range(32):
            try: self.host.run_until(lambda _status: True, timeout=2)
            except SaveResponseLost:
                self.loss_status = self.host.window.status()

    def post_late_report(self, work, event, *, issued=None):
        assert event.work == work.desc.work_id
        self.work_ports[work.desc.work_id].post(event, issued=issued)

    def drive(self, predicate):
        for _ in range(8):
            try: return super().drive(predicate)
            except SaveResponseLost:
                self.loss_status = self.host.window.status()
        raise AssertionError("test storage response did not recover")

    def request_rows(self, stage):
        return [q for q in self.facts(REQUESTS[stage]) if q.value["desc"]["purpose"] == stage]

    def next_callback(self, stage):
        def available():
            return [(q, body) for q in self.request_rows(stage)
                for key, body in self.launcher.attempts
                if key == q.value["desc"]["work_id"] and key not in self.executed]
        self.drive(lambda: bool(available()))
        offered = available()
        assert len(offered) == 1, "expected one unexecuted continuation at this public boundary"
        return offered[0]

    def invoke_next(self, stage):
        request, body = self.next_callback(stage)
        self.executed.add(request.value["desc"]["work_id"])
        body()
        work_id = request.value["desc"]["work_id"]
        self.drive(lambda: any(t.value["work"] == work_id for t in self.facts(c.WORK_TERMINAL)))
        self.settle_steps()
        return request

    def prepare_first(self):
        self.invoke_next("candidate_generation"); self.invoke_next("evaluation_prepare")

    def one_round(self):
        d = self.invoke_next("selection_draw"); e = self.invoke_next("evaluation")
        return d, e


def assert_no_comparison_purpose(rig):
    assert not [p for p in rig.host.window.status().purposes if p.role == "compare" and p.unmet]


@pytest.mark.parametrize("rounds", [2, 4])
def test_exact1_host_continues_same_draw_preserves_all_terminal_outputs_and_no_pG(exact_rigs, rounds):
    require_exact(); size = 1 << 128
    # 1/3 = .0101... . Keep the interval straddling it, then take the upper tail.
    k = size // 3
    rig = exact_rigs(ExactHostRig([k] * (rounds - 1) + [size - 1]))
    rig.prepare_first(); previous = None
    for index in range(rounds):
        d, e = rig.one_round()
        request = d.value["desc"]["args"]["request"]
        assert request["ordinal"] == 0 and request["law"] == plain(BITS)
        assert request["args"] == {"offset": index * 128, "after": previous}
        draw = next(x for x in rig.facts(DF) if x.value["request"] == request)
        if previous is not None: assert previous in rig.ledger.ancestors((draw.cid,))
        previous = draw.cid
        work, _, issued = rig.evaluation_posts[index]
        assert terminal(rig, work).value["terminal_kind"] == "outputs"
        if index < rounds - 1:
            assert_boundary(issued.value)
            assert any(r.response == "no_decision" for r in rig.host.window.status().readings)
            assert not rig.facts(c.SELECTION)
            assert_no_comparison_purpose(rig)
            rig.drive(lambda: len(rig.request_rows("selection_draw")) == index + 2)
            # Ledger enumeration order is not the order of logical rounds.
            next_d, _ = rig.next_callback("selection_draw")
            rows = [r for r in rig.host.window.status().works if r.work_id == next_d.value["desc"]["work_id"]]
            assert len(rows) == 1 and not rows[0].stop_confirmed
        else:
            assert isinstance(issued.value, f.Selected) and issued.value.choice.id == "M"
    rig.drive(lambda: bool(rig.facts(c.SELECTION)))
    assert rig.source.calls == [128] * rounds
    assert len({q.value["desc"]["work_id"] for q in rig.request_rows("selection_draw")}) == rounds
    assert len(rig.facts(c.EVALUATED)) == rounds
    assert_no_comparison_purpose(rig)
    assert rig.host.halted is None


@pytest.mark.parametrize("kind,path,field,default", [
    ("root", (), "selection_prefix", []),
    ("selected", (), "prefix", None),
    ("selected", ("root",), "selection_prefix", []),
], ids=["root-empty-prefix", "selected-null-prefix", "nested-root-empty-prefix"])
def test_exact1_structural_value_decoder_rejects_explicit_legacy_defaults(kind, path, field, default):
    """K35 decision 4, :4914: use structural VALUE/3, not artifact replay.

    The unchanged old claim is a positive control. Add just one omitted default
    to the typed JSON; its spelling is noncanonical even inside another value.
    No reader, registry, restore/verify call, or issued handle is involved.
    """
    require_exact()
    from sui import f_entry as codec
    saved = json.loads(Path(__file__).with_name("k35_old_point_artifacts.json").read_text(encoding="utf-8"))
    claim = json.loads(saved[kind])["claim"]
    assert claim["type"] == ("FRoot" if kind == "root" else "Selected")
    document = {"type": claim["type"], "value": claim["value"]}
    decoded = codec.f_from_json(canonical(document), contract=fc.VALUE_FACTS)
    assert isinstance(decoded, f.FRoot if kind == "root" else f.Selected)
    root = decoded if kind == "root" else decoded.root
    assert root.selection_prefix == () and root.contract == fc.ROOT_FACTS
    if kind == "selected": assert decoded.prefix is None and decoded.u == Q(1, 2)
    changed = json.loads(canonical(document))
    target = changed["value"]
    for name in path: target = target[name]
    assert field not in target
    target[field] = default
    with pytest.raises(f.FInputError) as caught:
        codec.f_from_json(canonical(changed), contract=fc.VALUE_FACTS)
    assert caught.value.reason == "noncanonical"


def test_exact1_structural_root_decoder_rejects_explicit_empty_selection_prefix():
    """K35 decision 4: also reach the public fixed ROOT/3 structural codec."""
    require_exact()
    from sui import f_entry as codec
    saved = json.loads(Path(__file__).with_name("k35_old_point_artifacts.json").read_text(encoding="utf-8"))
    document = json.loads(saved["root"])["claim"]["value"]
    assert "selection_prefix" not in document
    decoded = codec.f_from_json(canonical(document), contract=fc.ROOT_FACTS)
    assert isinstance(decoded, f.FRoot) and decoded.selection_prefix == ()
    assert decoded.contract == fc.ROOT_FACTS
    changed = dict(document, selection_prefix=[])
    with pytest.raises(f.FInputError) as caught:
        codec.f_from_json(canonical(changed), contract=fc.ROOT_FACTS)
    assert caught.value.reason == "noncanonical"


@pytest.mark.parametrize("k,choice", [(1 << 126, "Q"), (1 << 127, "M"), ((1 << 128) - 1, "M")])
def test_exact1_host_single_round_including_exact_left_boundary_never_requests_more_bits(exact_rigs, k, choice):
    require_exact(); rig = exact_rigs(ExactHostRig([k], masses=(Q(1, 2), Q(1, 2))))
    rig.prepare_first(); rig.one_round(); rig.drive(lambda: bool(rig.facts(c.SELECTION)))
    assert_selected(rig.evaluation_posts[0][2].value, choice, k, 128)
    assert len(rig.request_rows("selection_draw")) == len(rig.evaluation_posts) == 1
    assert rig.source.calls == [128]
    assert_no_comparison_purpose(rig)


def test_exact1_host_nonfinite_precision_exhaustion_ends_without_drawing_more_bits(exact_rigs):
    require_exact()
    rig = exact_rigs(ExactHostRig([(1 << 128) // 3], evaluate_budget=budget(max_refinements=8),
        document=assemble("FA14", document=flat_document(), order=["Q", "M"]).document))
    rig.prepare_first(); rig.one_round(); rig.settle_steps()
    issue = rig.evaluation_posts[0][2]
    assert isinstance(issue.value, f.NoDecision) and issue.value.reason == "budget_exhausted"
    assert rig.source.calls == [128] and len(rig.request_rows("selection_draw")) == 1
    assert not rig.facts(c.SELECTION)


@pytest.mark.parametrize("kind", ["failure", "rejected", "unknown"])
def test_exact1_continuation_draw_terminal_ends_without_retry_and_retains_pG(exact_rigs, kind):
    require_exact(); rig = exact_rigs(ExactHostRig([(1 << 128) // 3]))
    rig.prepare_first(); rig.one_round()
    # Deliver the next returned terminal through its real entered worker port.
    class EndDraw:
        def run(self, work, ctx):
            if not ctx.enter(): return
            rig.workers.entries.append(work)
            outcome = (fb.DrawUnknown(unknown=fb.UnknownInfo(reason="test unknown", basis=()))
                if kind == "unknown" else fb.DrawFailure(failure=fb.FailureInfo(
                    failure_kind=kind, content={"fixture": "continuation"}, readings=(), basis=())))
            ctx.post(fb.DrawReturned(work=work.desc.work_id, outcome=outcome))
    # Replace the test probe's delegate, not a production function or field.
    rig.native_draw = EndDraw()
    # Keep the same actual host and saved obligations, replacing a TEST delegate.
    rig.draw_probe.worker = rig.native_draw
    rig.invoke_next("selection_draw"); rig.settle_steps()
    rig.drive(lambda: any(p.role == "compare" and p.unmet for p in rig.host.window.status().purposes))
    assert len(rig.request_rows("selection_draw")) == 2 and len(rig.evaluation_posts) == 1
    assert rig.source.calls == [128] and not rig.facts(c.SELECTION)
    assert any(p.role == "compare" and p.unmet for p in rig.host.window.status().purposes)


@pytest.mark.parametrize("upstream", ["candidate_generation", "evaluation_prepare", "selection_draw", "evaluation"])
@pytest.mark.parametrize("save_pending", [False, True])
def test_exact1_late_ancestor_clash_blocks_unentered_continuation_even_before_conflict_save(exact_rigs, upstream, save_pending):
    require_exact(); k = (1 << 128) // 3
    rig = exact_rigs(ExactHostRig([k, k, (1 << 128) - 1]))
    rig.prepare_first(); rig.one_round(); rig.one_round()
    rig.drive(lambda: len(rig.request_rows("selection_draw")) == 3)
    q, callback = rig.next_callback("selection_draw")
    wid = q.value["desc"]["work_id"]
    work, report, issued, _ = additional_terminal(rig, upstream, "failure")
    before = {fact.cid: fact.value for fact in rig.facts(c.WORK_TERMINAL)}
    original_write = rig.ledger.write
    attempted = []
    def delayed(prepared):
        if save_pending and prepared.record.body.contract in (c.WORK_REPORT, c.DRAW_REPORT):
            attempted.append(prepared)
            raise OSError("test report save pending")
        return original_write(prepared)
    rig.ledger.write = delayed
    try:
        rig.post_late_report(work, report)
        if save_pending:
            try: rig.host.run_until(lambda _status: bool(attempted), timeout=2)
            except OSError: assert attempted
            assert attempted, "conflict report save cut never fired"
        else:
            rig.drive(lambda: len(raw_for(rig, work.desc.work_id)) == 2)
        # The test invokes only the already-offered callback. It must still
        # check inherited uses before beginning the new source operation.
        callback()
        assert rig.source.calls == [128, 128]
        assert all(w.desc.work_id != wid for w in rig.workers.entries)
    finally:
        rig.ledger.write = original_write
    rig.drive(lambda: any(p.role == "compare" and p.unmet for p in rig.host.window.status().purposes))
    assert len(rig.request_rows("selection_draw")) == 3
    assert len(rig.evaluation_posts) == 2
    assert all(any(fact.cid == cid and fact.value == value for fact in rig.facts(c.WORK_TERMINAL))
               for cid, value in before.items())
    assert any(p.role == "compare" and p.unmet for p in rig.host.window.status().purposes)


@pytest.mark.parametrize("upstream", ["candidate_generation", "evaluation_prepare", "selection_draw", "evaluation"])
def test_exact1_clash_after_selection_adds_unmet_without_erasing_selected_fact(exact_rigs, upstream):
    require_exact(); size = 1 << 128
    rig = exact_rigs(ExactHostRig([size // 3, size - 1]))
    rig.prepare_first(); rig.one_round(); rig.one_round()
    rig.drive(lambda: bool(rig.facts(c.SELECTION)))
    saved = tuple((x.cid, x.value) for x in rig.facts(c.SELECTION))
    work, event, _, _ = additional_terminal(rig, upstream, "failure")
    rig.post_late_report(work, event)
    rig.drive(lambda: any(p.role == "compare" and p.unmet for p in rig.host.window.status().purposes))
    assert tuple((x.cid, x.value) for x in rig.facts(c.SELECTION)) == saved
    assert any(p.role == "compare" and p.unmet for p in rig.host.window.status().purposes)
    assert rig.source.calls == [128, 128]


class SaveResponseLost(OSError):
    pass


@pytest.mark.parametrize("target", ["EV", "next-D"])
def test_exact1_next_draw_work_is_visible_while_continuation_publication_is_pending(exact_rigs, target):
    require_exact(); size = 1 << 128
    rig = exact_rigs(ExactHostRig([size // 3, size - 1])); rig.prepare_first()
    rig.invoke_next("selection_draw")
    original = rig.ledger.write; fired = []
    def hold(prepared):
        ref = prepared.record.body.contract
        match = ref == c.EVALUATED if target == "EV" else ref == c.DRAW_REQUESTED
        if match:
            fired.append(prepared)
            raise SaveResponseLost("test held continuation publication")
        return original(prepared)
    rig.ledger.write = hold
    try:
        def offered():
            return [(q, body) for q in rig.request_rows("evaluation")
                for key, body in rig.launcher.attempts
                if key == q.value["desc"]["work_id"] and key not in rig.executed]
        rig.drive(lambda: bool(offered()))
        request, body = offered()[0]; wid = request.value["desc"]["work_id"]
        rig.executed.add(wid); body()
        try: rig.host.run_until(lambda _status: bool(fired), timeout=2)
        except SaveResponseLost: pass
        assert fired, "held publication boundary was not reached"
        state = rig.host.window.status()
        assert len([r for r in state.works if r.purpose == "selection_draw"]) == 2
        assert any(r.response == "no_decision" for r in state.readings)
        assert_no_comparison_purpose(rig)
        assert rig.source.calls == [128]
    finally:
        rig.ledger.write = original
    rig.invoke_next("selection_draw"); rig.invoke_next("evaluation")
    rig.drive(lambda: bool(rig.facts(c.SELECTION)))
    assert_no_comparison_purpose(rig)


class SaveResponseLoss:
    """Test-owned public Ledger.write adapter; fixed preparation is retried."""
    def __init__(self, rig, target, *, next_d=False):
        self.rig, self.target, self.next_d = rig, target, next_d
        self.original, self.prepared, self.fired = rig.ledger.write, None, False
        self.attempts = []
    def __call__(self, prepared):
        body = prepared.record.body
        matches = body.contract == self.target
        value = body.content.as_json()
        if self.next_d and matches:
            matches = value["desc"]["args"]["request"]["args"]["offset"] > 0
        if matches:
            if self.prepared is None: self.prepared = prepared
            if prepared.cid == self.prepared.cid: self.attempts.append(prepared)
            if not self.fired:
                self.fired = True
                raise SaveResponseLost("test temporary failure before public write")
        return self.original(prepared)


@pytest.mark.parametrize("target", ["D", "DF", "math", "EV", "next-D"])
def test_exact1_continuation_save_retry_keeps_one_block_per_position_and_visible_obligation(exact_rigs, target):
    require_exact(); size = 1 << 128
    rig = exact_rigs(ExactHostRig([size // 3, size - 1]))
    if target != "D": rig.prepare_first()
    contracts = {"D": c.DRAW_REQUESTED, "DF": DF, "math": MATH,
                 "EV": c.EVALUATED, "next-D": c.DRAW_REQUESTED}
    cut = SaveResponseLoss(rig, contracts[target], next_d=target == "next-D")
    rig.ledger.write = cut
    try:
        if target == "D": rig.prepare_first()
        for stage in ("selection_draw", "evaluation", "selection_draw", "evaluation"):
            rig.invoke_next(stage)
        rig.drive(lambda: bool(rig.facts(c.SELECTION)))
    finally:
        rig.ledger.write = cut.original
    assert cut.fired and cut.prepared is not None, "requested public save cut never fired"
    assert len(cut.attempts) >= 2 and all(x == cut.attempts[0] for x in cut.attempts)
    assert rig.source.calls == [128, 128]
    assert len(rig.request_rows("selection_draw")) == len(rig.facts(DF)) == len(rig.facts(c.EVALUATED)) == 2
    assert_no_comparison_purpose(rig)


@pytest.mark.parametrize("kind", ["failure", "unknown", "no_decision"])
def test_exact1_nonboundary_evaluation_terminal_stops_continuation_without_redraw(exact_rigs, kind):
    require_exact(); size = 1 << 128
    values = [size // 3, size // 3 if kind == "no_decision" else size - 1]
    cap = budget(max_refinements=8) if kind == "no_decision" else None
    rig = exact_rigs(ExactHostRig(values, evaluate_budget=cap))
    rig.prepare_first(); rig.one_round()
    rig.invoke_next("selection_draw")
    class StopEvaluation:
        def run(self, work, ctx):
            if not ctx.enter(): return
            rig.workers.entries.append(work)
            issued = None
            outcome = (fb.WorkUnknown(unknown=fb.UnknownInfo(reason="test unknown", basis=()))
                if kind == "unknown" else fb.WorkFailure(failure=fb.FailureInfo(
                    failure_kind="execution_error", content={"error_type": "RuntimeError"}, readings=(), basis=())))
            rig.workers.post(ctx, rig.workers.finished(work, outcome), issued)
    if kind != "no_decision": rig.evaluation_delegate.worker = StopEvaluation()
    rig.invoke_next("evaluation"); rig.settle_steps()
    rig.drive(lambda: any(p.role == "compare" and p.unmet for p in rig.host.window.status().purposes))
    if kind == "no_decision":
        issued = rig.evaluation_posts[-1][2]
        assert isinstance(issued.value, f.NoDecision) and issued.value.reason == "budget_exhausted"
    assert len(rig.request_rows("selection_draw")) == 2
    assert rig.source.calls == [128, 128] and not rig.facts(c.SELECTION)
    assert any(p.role == "compare" and p.unmet for p in rig.host.window.status().purposes)


def test_exact1_main_loop_all_six_native_workers_keep_fixed_prefix_and_adoption(exact_rigs):
    require_exact(); cls = draw_type()
    rig = exact_rigs(DrawLoopRig(cls, source=BitsSource(1 << 126, 1 << 126)))
    from test_fb_belief import belief1_chain
    rig.start(); rig.publish(0, last=True); rig.update()
    for stage in ORDER[1:]: rig.run_stage(stage)
    rig.until(lambda: len(rig.facts(c.EVALUATED)) == 2)
    belief1_chain(rig, ({"joint": [[4, 5], [1, 5]], "evidence_mass": [5, 32]},))
    assert rig.source is not None and len(rig.facts(DF)) == 2
    assert all(isinstance(issue.value, f.Selected) for _, _, issue in rig.evaluation_posts)
    assert all(issue.value.choice.id in issue.value.evaluation.candidates for _, _, issue in rig.evaluation_posts)
    assert rig.host.halted is None


@pytest.mark.parametrize("upstream", ["candidate_generation", "evaluation_prepare", "selection_draw", "evaluation"])
@pytest.mark.parametrize("clash", [False, True], ids=["equal-control", "ancestor-clash"])
def test_exact1_ancestor_clash_before_continuation_request_prevents_its_publication(exact_rigs, upstream, clash):
    """K35 9(h), paper :4919: gate successor creation, not merely entry.

    The second EV is prepared but not saved; no third D has been saved or
    offered. Accept a first-round ancestor report at this public storage cut.
    Equal redelivery is the nearest control and must permit the third D.
    """
    require_exact(); size = 1 << 128; k = size // 3
    rig = exact_rigs(ExactHostRig([k, k, size - 1]))
    rig.prepare_first(); rig.one_round(); rig.invoke_next("selection_draw")
    request, body = rig.next_callback("evaluation")
    rig.executed.add(request.value["desc"]["work_id"])
    original_write, original_accept = rig.ledger.write, rig.host.window.accept
    held, accepted = [], []

    def hold_second_ev(prepared):
        if prepared.record.body.contract == c.EVALUATED:
            held.append(prepared)
            raise SaveResponseLost("test second EV awaiting storage")
        return original_write(prepared)

    def observe_accept(envelope):
        original_accept(envelope)
        accepted.append(envelope)

    rig.ledger.write = hold_second_ev
    try:
        body()
        try: rig.host.run_until(lambda _status: bool(held), timeout=2)
        except SaveResponseLost: pass
        assert held, "the public EV storage cut was not reached"
        assert_boundary(rig.evaluation_posts[-1][2].value)
        assert len(rig.facts(c.EVALUATED)) == 1
        assert len(rig.request_rows("selection_draw")) == len(rig.facts(DF)) == 2
        assert rig.source.calls == [128, 128]
        saved = [(ref, fact.cid, fact.value) for ref in
                 (c.WORK_TERMINAL, c.DRAW_REQUESTED, DF, c.EVALUATED)
                 for fact in rig.facts(ref)]
        work, report, issue, _ = additional_terminal(rig, upstream, "failure" if clash else "equal")
        rig.host.window.accept = observe_accept
        rig.post_late_report(work, report, issued=issue)
        try: rig.host.run_until(lambda _status: bool(accepted), timeout=2)
        except SaveResponseLost: pass
        assert len(accepted) == 1, "ancestor report was not accepted while EV remained pending"
        assert len(rig.request_rows("selection_draw")) == 2
    finally:
        rig.ledger.write = original_write
        rig.host.window.accept = original_accept

    rig.drive(lambda: len(rig.facts(c.EVALUATED)) == 2
              and len(raw_for(rig, work.desc.work_id)) == 2)
    if clash:
        rig.drive(lambda: any(p.role == "compare" and p.unmet
                              for p in rig.host.window.status().purposes))
        rig.settle_steps()
        assert len(rig.request_rows("selection_draw")) == 2
        assert len(rig.facts(DF)) == len(rig.evaluation_posts) == 2
        assert rig.source.calls == [128, 128]
        assert not rig.facts(c.SELECTION)
    else:
        third, _ = rig.next_callback("selection_draw")
        assert len(rig.request_rows("selection_draw")) == 3
        assert third.value["desc"]["args"]["request"]["ordinal"] == 0
        assert third.value["desc"]["args"]["request"]["args"]["offset"] == 256
        rig.one_round()
        rig.drive(lambda: bool(rig.facts(c.SELECTION)))
        assert rig.source.calls == [128, 128, 128]
        assert_no_comparison_purpose(rig)
    assert all(any(fact.cid == cid and fact.value == value for fact in rig.facts(ref))
               for ref, cid, value in saved)
    assert rig.host.halted is None


HOST_BIT_VALUE_CASES = (
    ("zero-control", {"bits": 0, "length": 128}, "Q"),
    ("maximum-control", {"bits": (1 << 128) - 1, "length": 128}, "M"),
    ("upper-bound", {"bits": 1 << 128, "length": 128}, None),
    ("negative-bits", {"bits": -1, "length": 128}, None),
    ("bool-bits", {"bits": True, "length": 128}, None),
    ("string-bits", {"bits": "1", "length": 128}, None),
    ("bool-length", {"bits": 0, "length": True}, None),
    ("zero-length", {"bits": 0, "length": 0}, None),
    ("extra-field", {"bits": 0, "length": 128, "extra": 1}, None),
    ("missing-bits", {"length": 128}, None),
    ("missing-length", {"bits": 0}, None),
    ("not-an-object", [], None),
)


@pytest.mark.parametrize("label,value,choice", HOST_BIT_VALUE_CASES,
                         ids=[row[0] for row in HOST_BIT_VALUE_CASES])
def test_exact1_host_checks_bit_value_before_draw_fact_or_evaluation(exact_rigs, label, value, choice):
    """K35 9(b), :4919: invalid worker JSON is held at D, not failed by Ee.

    Use a test draw worker so native UniformDraw's own validation cannot mask
    the householder's check. Both legal endpoint values proceed to selection.
    """
    require_exact(); rig = exact_rigs(ExactHostRig([]))

    class ReturnedJSON:
        def run(self, work, ctx):
            if ctx.enter():
                ctx.post(fb.DrawReturned(work=work.desc.work_id,
                                        outcome=fb.DrawValue(value=value)))

    rig.draw_probe.worker = ReturnedJSON()
    rig.prepare_first(); rig.invoke_next("selection_draw")
    work, event = rig.draw_posts[0]
    raw = raw_for(rig, work.desc.work_id)
    assert len(raw) == 1 and raw[0].value == {
        "work": work.desc.work_id, "outcome": {"kind": "value", "value": value}}
    t = terminal(rig, work)
    assert t.value["terminal_kind"] == "value"
    assert t.value["returned"] == {"kind": "draw_value", "value": value}
    assert rig.source.calls == [] and len(rig.draw_posts) == 1
    if choice is None:
        # As in stage 2, the public PendingStatus stores the local reason.
        # Combine it with this D's stage, not with a nonexistent Ee failure.
        reason = "draw:value"
        rig.drive(lambda: any(row.reason == reason for row in rig.host.window.status().pending)
                  or bool(rig.facts(DF)) or bool(rig.request_rows("evaluation")))
        state = rig.host.window.status()
        purposes = comparison_purposes(rig, unmet=True)
        pending = [row for row in state.pending if row.reason == reason
                   and row.target in {purpose.target for purpose in purposes}]
        assert pending, [row.reason for row in state.pending]
        assert {work.desc.purpose + ":" + row.reason for row in pending} == {"selection_draw:draw:value"}
        assert not rig.facts(DF) and not rig.request_rows("evaluation")
        assert not rig.evaluation_posts and not rig.facts(c.EVALUATED) and not rig.facts(c.SELECTION)
        assert not any(row.purpose == "evaluation" for row in state.works)
    else:
        rig.invoke_next("evaluation"); rig.drive(lambda: bool(rig.facts(c.SELECTION)))
        assert rig.one(DF).value["value"] == value
        assert rig.evaluation_posts[-1][2].value.choice.id == choice
        assert not any(row.reason == "draw:value" for row in rig.host.window.status().pending)
        assert_no_comparison_purpose(rig)
    assert rig.host.halted is None
