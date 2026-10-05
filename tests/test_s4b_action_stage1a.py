"""S4b v0.19 §3-6 T1-4/T7-9/T16/R2/R4, through published APIs.

Fixture defaults and physical/record units are in s4b_action_cases. T9 requires
known nonzero Q (stage2), and the full R4=T15 requires unknown B/Theta (stage1b):
both are normal future-facing tests, not claimed as stage1a-only requirements.
All information references come from tests/fixed_s4b_action.json or explicit
Fraction laws. No expected values are measured from production output.
"""
from fractions import Fraction as F
import math

import pytest

from s4b_action_cases import (NS, I, C, FLIP, FAIR, api, assert_bounds, assert_distribution,
    budget, command, declaration, fixed, outcome_of, rig, root_case, table, view_of)


def advance(node, cmd, certificate, *, deadline=NS):
    result = api("action_lookahead").branches(node, cmd, deadline_ns=deadline,
                                             certificate=certificate, budget=budget())
    assert_bounds(result.total_mass, F(1), exact=True)
    assert sum((atom.probability.exact for atom in result.atoms), F()) == 1
    return result.atoms


def potential(root, node, certificate):
    return api("action_reference").information_potential(root, node,
        certificate=certificate, budget=budget())


def reference(root, node, targets, certificate):
    ref = api("action_reference").reference_target(root, node, tuple(targets),
        certificate=certificate, budget=budget())
    return api("action_reference").reference_state_marginal(ref, budget=budget())


def terminal_distribution(root, node, certificate):
    return reference(root, node, node.targets, certificate)


def test_v022_plan_attempt_labels_and_public_trigger():
    r, root, node, certificate = root_case(declaration())
    assert node.trigger is None
    atoms = advance(node, command(r, "a", stage=3, position=2), certificate)
    assert len(atoms) == 2
    cls = api("action_types").TargetRef
    expected = tuple(cls(attempt="plan:3:2", position=p, side="post")
                     for p in ("measurement", "completion"))
    for atom in atoms:
        assert atom.child.targets == expected
        assert atom.child.trigger == expected[-1]
        # The published value type can be reconstructed without private origins.
        current = api("action_types").ActionNode(belief=atom.child.belief,
            controls=atom.child.controls, targets=expected, terminal=atom.child.terminal,
            trigger=atom.child.trigger)
        assert_bounds(potential(root, current, certificate), math.log(2))


def test_t1_action_choice_does_not_create_information():
    """Fair A, X=A, constant record. Each controlled reference is delta_A."""
    d = declaration(("a0", "a1"), kernels={"a0": C, "a1": [[0, 0], [1, 1]]}, observed=False)
    r, root, node, certificate = root_case(d)
    for choice, state in (("a0", "0"), ("a1", "1")):
        atoms = advance(node, command(r, choice), certificate)
        assert len(atoms) == 1
        child = atoms[0].child
        assert_bounds(potential(root, child, certificate), fixed("T1", "information"))
        assert len(child.targets) > 0
        expected = {(state,) * len(child.targets): F(1)}
        assert_distribution(terminal_distribution(root, child, certificate), expected)
        assert_distribution(api("action_joint").target_marginal(child.belief, child.targets,
                            budget=budget()), expected)
    from sui.agent import plan
    data = plan(view_of(r), ("a1", "a0"), u=.25).content.as_json()
    assert data["candidates"] == ["a0", "a1"]
    assert data["information"] == pytest.approx([0., 0.], abs=1e-9)
    assert data["q_pi"] == pytest.approx([.5, .5], abs=1e-9)


def test_t2_adaptive_identity_preserves_the_original_information():
    """O1=X, A2=O1; full action sequence is not conditioned into reference."""
    d = declaration(("read", "a0", "a1"), kernels={a: I for a in ("read", "a0", "a1")})
    r, root, node, certificate = root_case(d, H=2*NS)
    initial = advance(node, command(r, "read"), certificate, deadline=2*NS)
    assert {outcome_of(atom) for atom in initial} == {"0", "1"}
    for atom in initial:
        assert_bounds(atom.probability, F(1, 2), exact=True)
        first = atom.child
        assert_bounds(potential(root, first, certificate), fixed("T2", "information"))
        chosen = "a" + outcome_of(atom)
        children = advance(first, command(r, chosen, reading_ns=NS, stage=1),
                           certificate, deadline=2*NS)
        assert len(children) == 1
        child = children[0].child
        assert_bounds(potential(root, child, certificate), fixed("T2", "information"))
        n = len(child.targets)
        assert_distribution(terminal_distribution(root, child, certificate),
                            {("0",)*n: F(1, 2), ("1",)*n: F(1, 2)})
        # All old targets survive; their reference marginal remains fair.
        assert all(t in child.targets for t in first.targets)
        assert_distribution(reference(root, child, first.targets, certificate),
                            {("0",)*len(first.targets): F(1, 2), ("1",)*len(first.targets): F(1, 2)})


@pytest.mark.parametrize("kernel,key", [(FLIP, "flip_information"), (C, "reset_information")])
def test_t3_known_deterministic_effect_is_not_automatically_zero(kernel, key):
    d = declaration(kernels={"a": kernel})
    r, root, node, certificate = root_case(d)
    atoms = advance(node, command(r, "a"), certificate)
    expected = fixed("T3", key)
    for atom in atoms:
        assert_bounds(potential(root, atom.child, certificate), expected)
    assert len(atoms) == (2 if key == "flip_information" else 1)
    from sui.agent import plan
    data = plan(view_of(r), ("a",), u=.25).content.as_json()
    assert data["information"] == pytest.approx([expected], abs=1e-9)


def test_t4_independent_resets_register_joint_state_information():
    r, root, node, certificate = root_case(declaration(), H=2*NS)
    first = advance(node, command(r, "a"), certificate, deadline=2*NS)
    assert len(first) == 2
    leaves = []
    for atom in first:
        assert_bounds(atom.probability, F(1, 2), exact=True)
        assert_bounds(potential(root, atom.child, certificate), fixed("T4", "once"))
        children = advance(atom.child, command(r, "a", reading_ns=NS, stage=1),
                           certificate, deadline=2*NS)
        assert len(children) == 2
        for child in children:
            assert_bounds(child.probability, F(1, 2), exact=True)
            assert_bounds(potential(root, child.child, certificate), fixed("T4", "twice"))
            assert all(t in child.child.targets for t in atom.child.targets)
            # Query two distinct completion targets, one from each physical report.
            old = next(t for t in atom.child.targets if t.position == "completion")
            new = next(t for t in child.child.targets
                       if t.position == "completion" and t not in atom.child.targets)
            assert_distribution(reference(root, child.child, (old, new), certificate),
                                {(a, b): F(1, 4) for a in ("0", "1") for b in ("0", "1")})
            leaves.append(atom.probability.exact * child.probability.exact)
    assert leaves == [F(1, 4)]*4


@pytest.mark.parametrize("side,key", [("pre", "start_pre"), ("post", "start_post")])
def test_t7_start_measurement_pre_post_and_completion_labels(side, key):
    d = declaration(kernels={"a": C})
    d["effects"]["a"]["measure"] = {"at": "start", "side": side}
    r, root, node, certificate = root_case(d)
    for atom in advance(node, command(r, "a"), certificate):
        child = atom.child
        assert_bounds(potential(root, child, certificate), fixed("T7", key))
        measurement = next(t for t in child.targets if t.position == "measurement")
        completion = next(t for t in child.targets if t.position == "completion")
        assert measurement.side == side
        assert_distribution(api("action_joint").target_marginal(child.belief, (completion,),
                            budget=budget()), {("0",): F(1)})
        # A pre/post distinction changes the fair/constant measurement reference.
        expected = {("0",): F(1, 2), ("1",): F(1, 2)} if side == "pre" else {("0",): F(1)}
        assert_distribution(reference(root, child, (measurement,), certificate), expected)


@pytest.mark.parametrize("deadline", [0, NS-1])
def test_t7_no_report_by_deadline_does_not_register_future_state(deadline):
    r, root, node, certificate = root_case(declaration())
    atoms = advance(node, command(r, "a"), certificate, deadline=deadline)
    assert len(atoms) == 1
    assert atoms[0].child.targets == ()
    assert_bounds(potential(root, atoms[0].child, certificate), 0.)


@pytest.mark.parametrize("order,key", [(("z_reset", "a_flip"), "C_then_F"),
                                       (("a_flip", "z_reset"), "F_then_C")])
def test_t8_same_time_effects_follow_causal_position_not_name(order, key):
    d = declaration(("z_reset", "a_flip"), kernels={"z_reset": C, "a_flip": FLIP},
                    initial=(F(1), F(0)))
    r, root, _, certificate = root_case(d)
    controls = tuple(command(r, choice, position=i) for i, choice in enumerate(order))
    target = api("action_types").FixedLabel(time_s=F(0), causal_stage=0,
                                             causal_position=1, side="post")
    expected = fixed("T8", key)
    current = api("action_types").ActionNode(belief=root, controls=controls, targets=(), terminal=False, trigger=None)
    assert_distribution(reference(root, current, (target,), certificate),
                        {(str(i),): F(*p) for i, p in enumerate(expected)})


@pytest.mark.parametrize("order,key", [("effect_then_flow", "P_C_b"), ("flow_then_effect", "C_P_b")])
def test_t9_flow_and_impulse_do_not_commute(order, key):
    """Known Q fixture (stage2): Q[1,0]=ln2 / second, initial state 1."""
    d = declaration(kernels={"a": C}, initial=(F(0), F(1)))
    d["activity"]["Q_by_mode"]["idle"] = [[-math.log(2), 0.], [math.log(2), 0.]]
    at = 0 if order == "effect_then_flow" else NS
    d["choices"]["a"]["reservation"]["not_before_ns"] = at
    r, root, _, certificate = root_case(d, H=2*NS)
    target = api("action_types").FixedLabel(time_s=F(1), causal_stage=0,
                                             causal_position=0, side="post")
    expected = fixed("T9", key)
    current = api("action_types").ActionNode(belief=root, controls=(command(r, "a"),),
                                            targets=(), terminal=False, trigger=None)
    assert_distribution(reference(root, current, (target,), certificate),
                        {(str(i),): F(*p) for i, p in enumerate(expected)}, exact=False)


def test_t16_public_evaluate_and_plan_match_independent_one_report_tree():
    d = declaration(("read", "reset"), kernels={"read": I, "reset": C})
    r = rig(d)
    view = view_of(r)
    from sui.agent import plan
    from sui.preference import current, resolve
    resolved = resolve(current(view.preferences), view)
    entry = api("action_entry")
    support = entry.certify_action_scope(view, ("read", "reset"), resolved, budget=budget())
    assert support.status == "certified"
    draft = entry.public_evaluate(view, ("read", "reset"), resolved, u=.25, budget=budget())
    assert draft == plan(view, ("reset", "read", "read"), u=.25)
    data = draft.content.as_json()
    assert data["candidates"] == ["read", "reset"]
    assert data["expected_cost"] == [0., 0.]
    assert data["J"] == pytest.approx(fixed("T16", "J"), abs=1e-9)
    expected_q = [float(F(*p)) for p in fixed("T16", "q")]
    assert data["q_pi"] == pytest.approx(expected_q, abs=1e-9)
    assert data["chosen"] == "read"
    for name, expected in (("J_bounds", fixed("T16", "J")), ("q_pi_bounds", expected_q)):
        for (lo, hi), value in zip(data[name], expected):
            assert lo-4e-14 <= value <= hi+4e-14 and hi-lo <= 1e-9
    for c, i, j in zip(data["expected_cost"], data["information"], data["J"]):
        assert j == c-i
    weights = [math.exp(-j) for j in data["J"]]
    assert data["q_pi"] == pytest.approx([w/sum(weights) for w in weights], abs=4e-14)


@pytest.mark.parametrize("horizon", (2, 3), ids=("original_H2", "T16B_H3"))
def test_t16_two_report_policy_matches_terminal_enumeration_and_recursion(horizon):
    # After the first full observation, only random adds ln2 at each stage.
    # Its softmax probability is 1/2, hence each remaining stage adds ln2/2.
    # H=3 gives root weights 4:4:2 and mean information (9/5)ln2.
    expected = fixed("T16", "tree") if horizon == 2 else {
        "candidates": ["random", "read", "reset"],
        "J": [-2*math.log(2), -2*math.log(2), -math.log(2)],
        "q": [F(2, 5), F(2, 5), F(1, 5)],
        "terminal_information": float(F(9, 5))*math.log(2)}
    d = declaration(("random", "read", "reset"), kernels={"random": FAIR, "read": I, "reset": C})
    r = rig(d, H=horizon*NS)
    from sui.agent import plan
    data = plan(view_of(r), tuple(d["choices"]), u=.25).content.as_json()
    assert data["candidates"] == expected["candidates"]
    assert data["J"] == pytest.approx(expected["J"], abs=1e-9)
    assert data["q_pi"] == pytest.approx(expected["q"], abs=1e-9)
    assert sum(p*i for p, i in zip(data["q_pi"], data["information"])) == pytest.approx(
        expected["terminal_information"], abs=1e-9)


def test_r2_known_point_law_keeps_exact_moments_and_two_step_prediction():
    values = fixed("R2", "B")
    kernel = [[F(*p) for p in row] for row in values]
    d = declaration(kernels={"a": kernel}, observed=False, initial=(F(1), F(0)))
    r, root, node, certificate = root_case(d, H=2*NS)
    moment = api("action_joint").parameter_moment(root, parameter="B", action="a",
        powers=((2, 0), (0, 0)), budget=budget())
    assert_bounds(moment, F(*fixed("R2", "B00_squared")), exact=True)
    for step, expected_key in ((0, "one_step"), (1, "two_steps")):
        atoms = advance(node, command(r, "a", reading_ns=step*NS, stage=step),
                        certificate, deadline=2*NS)
        assert len(atoms) == 1  # hidden transitions grouped into the same constant record
        node = atoms[0].child
        target = next(t for t in reversed(node.targets) if t.position == "completion")
        expected = {(str(i),): F(*p) for i, p in enumerate(fixed("R2", expected_key))}
        assert_distribution(api("action_joint").target_marginal(node.belief, (target,), budget=budget()), expected)
        assert_bounds(potential(root, node, certificate), 0.)


def test_r4_q_zero_matches_t15_exact_integrated_discrete_evidence():
    """Full R4 is the learned T15 fixture, scheduled for stage1b, never xfailed."""
    d = declaration(("a0", "a1"))
    d["learnable"] = ["a0", "a1"]
    for a in d["actions"]:
        d["a"][a] = table([[1, 1], [1, 1]])
        d["effects"][a]["B"] = {"kind": "dirichlet", "values": table([[1, 1], [1, 1]])}
    r, _, node, certificate = root_case(d, H=6*NS)
    probability = F(1)
    for index, (a, y) in enumerate(zip((0, 1, 0, 0, 1, 0), (1, 0, 1, 1, 0, 1))):
        atoms = advance(node, command(r, "a"+str(a), reading_ns=index*NS, stage=index),
                        certificate, deadline=6*NS)
        matching = [atom for atom in atoms if outcome_of(atom) == str(y)]
        assert len(matching) == 1
        probability *= matching[0].probability.exact
        node = matching[0].child
    assert probability == F(*fixed("R4", "evidence"))
    assert_bounds(node.belief.log_evidence, math.log(float(probability)))
