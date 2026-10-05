"""S4b v0.19 §3-8: finite-time public evaluation versus continuous rulers.

T9 remains in test_s4b_action_stage1a.py, unchanged, and is judged in stage 2.
T10: known Q, fixed work, explicit dispatch, report/post, H=2s inclusive.
T11: existing mathematical CompletionKernel; this does not certify a runtime
model.8 action evaluator. One-jump values below are derived from T~Exp(log 2),
not taken from either the old or the new production kernel.
"""
from fractions import Fraction as F
import math

import pytest

from s4b_action_cases import (I, NS, api, assert_bounds, assert_distribution,
    budget, command, declaration, fixed, load_model, rational, rig, root_case,
    table, view_of)


def absorbing(rate):
    return [[-rate, 0.], [rate, 0.]]


def activity(d, *, start=0, flow=math.log(2)):
    d["activity"] = {"modes": ["idle", "active"],
        "initial_given_state": [list(map(rational, (1, 1))), list(map(rational, (0, 0)))],
        "Q_by_mode": {"idle": absorbing(start), "active": absorbing(flow)}, "calendar": []}
    for e in d["effects"].values():
        e["mode_on_dispatch"] = {"idle": "active", "active": "active"}
        e["mode_on_completion"] = {"idle": "idle", "active": "active"}


@pytest.mark.parametrize("elapsed,expected", ((F(1, 2), 1-2**(-.5)), (F(1), .5)))
def test_t10_active_Q_changes_intermediate_state_not_just_endpoint(elapsed, expected):
    d = declaration(kernels={"a": I}, initial=(1, 0), observed=False)
    activity(d)
    d["choices"]["a"]["reservation"]["not_before_ns"] = NS
    r, root, _, cert = root_case(d, H=2*NS)
    label = api("action_types").FixedLabel(time_s=1+elapsed, causal_stage=0,
                                            causal_position=0, side="post")
    current = api("action_types").ActionNode(belief=root, controls=(command(r, "a"),),
                                            targets=(), terminal=False, trigger=None)
    ref = api("action_reference").reference_target(root, current, (label,),
                                                  certificate=cert, budget=budget())
    actual = api("action_reference").reference_state_marginal(ref, budget=budget())
    assert_distribution(actual, {("0",): 1-expected, ("1",): expected}, exact=False)


def test_t10_finite_public_branches_carry_transition_error_to_information():
    d = declaration(kernels={"a": I}, initial=(1, 0))
    activity(d)
    d["choices"]["a"]["reservation"]["not_before_ns"] = NS
    r, root, node, cert = root_case(d, H=2*NS)
    measure = api("action_lookahead").branches(node, command(r, "a"), deadline_ns=2*NS,
                                               certificate=cert, budget=budget())
    assert_bounds(measure.total_mass, 1.)
    assert len(measure.atoms) == 2
    weighted = 0.
    for atom in measure.atoms:
        assert_bounds(atom.probability, .5)
        value = api("action_reference").information_potential(root, atom.child,
                                                              certificate=cert, budget=budget())
        assert_bounds(value, math.log(2))
        weighted += (atom.probability.lower+atom.probability.upper)/2 * (value.lower+value.upper)/2
    assert weighted == pytest.approx(math.log(2), abs=2e-9)


def progress_spec():
    return api("progress").CompletionSpec(name="progress", version="1", actions=("a",),
        states=("slow", "fast"), work_unit="unit", time_unit="second", speed_unit="unit/second",
        candidates=(((F(1), F(2)),),), weights=(F(1),), share="all_actions", max_speed=F(2))


def test_t11_progress_keeps_accumulated_work_when_speed_changes():
    p = api("progress")
    path = (p.ProgressSegment(F(1, 2), "slow"), p.ProgressSegment(None, "fast"))
    # Work already consumed = 1/2; the remaining 3/2 takes 3/4 second.
    point = p.completion(progress_spec(), "a", 0, F(2), path)
    assert point.elapsed == F(*fixed("T11", "completion_s")) == F(5, 4)
    kernel = p.completion_kernel(progress_spec(), "a", 0, path, atoms=((2, F(1)),))
    assert kernel.atoms == ((F(5, 4), F(1)),)
    assert kernel.densities == () and kernel.mass == 1
    assert kernel.unreachable_work_mass == kernel.infinite_work_mass == 0


def test_progress_atom_density_and_infinite_work_remain_different_parts():
    p = api("progress")
    path = (p.ProgressSegment(F(1, 2), "slow"), p.ProgressSegment(None, "fast"))
    # W has atom 2 (1/4), density 1/8 on [0,4] (1/2), and infinity (1/4).
    # Push forward by accumulated work: density multiplies by current speed.
    kernel = p.completion_kernel(progress_spec(), "a", 0, path,
        atoms=((2, F(1, 4)), (p.INFINITE_WORK, F(1, 4))),
        densities=(p.DensityPiece(F(0), F(4), F(1, 8)),))
    assert kernel.atoms == ((F(5, 4), F(1, 4)),)
    assert kernel.densities == (p.DensityPiece(F(0), F(1, 2), F(1, 8)),
                                p.DensityPiece(F(1, 2), F(9, 4), F(1, 4)))
    assert kernel.infinite_work_mass == F(1, 4)
    assert kernel.unreachable_work_mass == 0 and kernel.mass == 1


@pytest.mark.parametrize("h", (F(1, 4), F(3, 4), F(1)))
def test_one_jump_accelerating_ruler_separates_nonarrival_atom_and_density(h):
    # T~Exp(log2), speeds 1->2, W=1: R=1/2+T/2 for T<1;
    # T>=1 contributes an atom at R=1 with mass1/2.
    kernel = api("joint_stage2").OneJumpKernel(q=math.log(2), work=1, speeds=(1, 2))
    window = kernel.window(h)
    continuous = 0. if h <= F(1, 2) else 1-2**(-min(1., 2*float(h)-1))
    atom = .5 if h >= 1 else 0.
    miss = 1-continuous-atom
    assert window.mass == pytest.approx(1, abs=3e-14)
    assert window.continuous_mass == pytest.approx(continuous, abs=3e-14)
    assert window.not_arrived_mass == pytest.approx(miss, abs=3e-14)
    assert sum(math.exp(a.log_mass) for a in window.atoms) == pytest.approx(atom, abs=3e-14)
    assert kernel.density(F(3, 4)) == pytest.approx(math.sqrt(2)*math.log(2), abs=3e-14)
    assert kernel.density(F(1, 4)) == kernel.density(F(5, 4)) == 0


def test_one_jump_slowing_ruler_uses_absolute_jacobian_and_closed_deadline():
    # speeds 2->1: R=1-T (0<T<1/2); no jump before1/2 is an atom there.
    kernel = api("joint_stage2").OneJumpKernel(q=math.log(2), work=1, speeds=(2, 1))
    at = kernel.window(F(1, 2))
    assert sum(math.exp(a.log_mass) for a in at.atoms) == pytest.approx(2**(-.5), abs=3e-14)
    assert at.continuous_mass == 0
    assert at.not_arrived_mass == pytest.approx(1-2**(-.5), abs=3e-14)
    mid = kernel.window(F(3, 4))
    assert mid.continuous_mass == pytest.approx(2**(-.25)-2**(-.5), abs=3e-14)
    assert mid.not_arrived_mass == pytest.approx(1-2**(-.25), abs=3e-14)
    assert kernel.density(F(3, 4)) == pytest.approx(math.log(2)*2**(-.25), abs=3e-14)


@pytest.mark.parametrize("kind", ("state_dependent_progress", "response_wait", "uniform_clock_phase"))
def test_continuous_public_input_stops_honestly_instead_of_returning_only_atoms(kind):
    d = declaration(kernels={"a": I}, initial=(1, 0), observed=False)
    if kind == "state_dependent_progress":
        d["activity"]["Q_by_mode"]["idle"] = absorbing(math.log(2))
        d["completion"]["candidates"] = [[[[1, 1], [2, 1]]]]
        d["completion"]["max_speed"] = [2, 1]
    elif kind == "response_wait":
        d["effects"]["a"].update(family={"name": "response-wait", "version": "1"},
            response_rate_s=[1., 1.], progress_start="response")
    else:
        d["clock"]["candidates"][0].update(kind="tick", width_ns=NS, phase_ns="uniform")
        d["activity"]["Q_by_mode"]["idle"] = absorbing(math.log(2))
        d["completion"]["candidates"] = [[[[1, 1], [2, 1]]]]
        d["completion"]["max_speed"] = [2, 1]
        # A threshold in the next bin yields a genuinely continuous boundary.
        d["choices"]["a"]["reservation"]["not_before_ns"] = NS
    r = rig(d, H=2*NS)
    view = view_of(r)
    from sui.preference import current, resolve
    resolved = resolve(current(view.preferences), view)
    entry, types = api("action_entry"), api("action_types")
    support = entry.certify_action_scope(view, ("a",), resolved, budget=budget())
    assert support.status == "incomplete"
    assert support.reason in {"continuous_branches", "continuous_timing", "latent_label_envelope"}
    with pytest.raises(types.ActionIncomplete) as caught:
        entry.public_evaluate(view, ("a",), resolved, u=.25, budget=budget())
    assert caught.value.reason == support.reason
