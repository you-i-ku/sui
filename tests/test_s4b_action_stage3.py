"""S4b v0.21 T17--T24, finite-support clock/dispatch laws, public APIs only.

All common settings in spec :300 apply: known laws except explicit chi tests,
no arrivals, cost0/gamma1/u1/4, report/post, inclusive physical H. The tick
scenarios use width1s/phase0 and integer H, so the horizon boundary is the
specified true time. Auxiliary first-job work is known random work, not a DP.
The 'probe' is an actual pending identity job declared at the ROOT, not an
extra report invented solely to add a target. act completes outside H there.
No learned B/Theta; hidden delays and work samples are not information targets.
"""
from copy import deepcopy
from fractions import Fraction as F
import json
import math

import pytest

from s4b_action_cases import (C, FAIR, FLIP, I, NS, api, assert_bounds, assert_distribution,
    budget, command, declaration, delay, fixed, rational, root_case, table)
from s4b_action_time_cases import FactWorld, marginal, potential, reference, targets


def atoms(points):
    return {"given": [], "rows": [{"when": [], "points": [
        ["+inf" if time is None else rational(time), rational(weight)] for time, weight in points]}]}


def by_mode(values):
    return {"given": ["mode"], "rows": [{"when": [mode], "points": law["rows"][0]["points"]}
                                             for mode, law in values.items()]}


def assert_evidence(node, expected):
    assert node.belief.evidence_kind == "mass"
    assert_bounds(node.belief.log_evidence, math.log(float(expected)))


def scenario(number, *, read=False):
    """Full T17--T23 model declarations, including the initial/root jobs.

    idle is the initial mode; first completion changes idle->ready. act's
    dispatch changes to flow (or stopped in T23). Initial jobs therefore have
    zero think/receipt/chi while the later decision has the specified kernels.
    """
    pending_probe = number in (17, 18, 19, 21)
    names = ("first", "act", "probe") if pending_probe else ("first", "act")
    initial = (F(1, 2), F(1, 2)) if number in (17, 20, 21, 22) else (1, 0)
    kernels = {a: I for a in names}
    if number in (19, 22):
        kernels["act"] = [[0, 0], [1, 1]]
    elif number == 23:
        kernels["act"] = FAIR
    d = declaration(names, kernels=kernels, observed=False, initial=initial)
    modes = ("idle", "ready", "flow", "stopped")
    zero = [[0., 0.], [0., 0.]]
    q = 4*math.log(2) if number in (17, 18, 21) else (4/3)*math.log(2) if number == 23 else 0.
    d["activity"] = {"modes": list(modes), "initial_given_state": [table([[1, 1]])[0]]+
        [table([[0, 0]])[0] for _ in range(3)],
        "Q_by_mode": {m: [[-q, 0.], [q, 0.]] if m == "flow" else deepcopy(zero) for m in modes},
        "calendar": [{"at_s": [5, 4], "mode": "flow"}] if number == 23 else []}
    for a in names:
        d["effects"][a]["mode_on_dispatch"] = {m: m for m in modes}
        d["effects"][a]["mode_on_completion"] = {m: m for m in modes}
    d["effects"]["first"]["mode_on_completion"]["idle"] = "ready"
    d["effects"]["act"]["mode_on_dispatch"] = {m: "stopped" if number == 23 else "flow" for m in modes}
    rates = {a: (1, 1) for a in names}
    first_work = [(NS, F(1))]
    if number in (17, 21):
        first_work, rates["first"] = [(3*NS//4, F(1))], (3, 1)
    elif number == 18:
        first_work = [(NS//4, F(1, 2)), (5*NS//4, F(1, 2))]
    elif number == 19:
        first_work = [(NS//4, F(1, 2)), (9*NS//4, F(1, 2))]
    elif number in (20, 22):
        first_work, rates["first"] = [(2*NS, F(1))], (2, 1)
    elif number == 23:
        first_work = [(NS, F(1, 2)), (2*NS, F(1, 2))]
        d["a"]["first"] = table(I)
    d["work"]["first"]["points"] = [[w, rational(p)] for w, p in first_work]
    d["work"]["act"]["points"] = [[100*NS if pending_probe or number == 20 else NS, [1, 1]]]
    d["completion"]["candidates"] = [[[rational(v) for v in rates[a]] for a in names]]
    d["completion"]["max_speed"] = rational(max(v for pair in rates.values() for v in pair))
    H = {17: 12*NS, 18: 13*NS, 19: 3*NS, 20: 9*NS//4, 21: 12*NS, 22: 13*NS//4, 23: 13*NS//4}[number]
    if pending_probe:
        d["work"]["probe"]["points"] = [[H, [1, 1]]]
        if read:
            d["a"]["probe"] = table(I)
    elif read:
        d["a"]["act"] = table(I)
    threshold = {17: 11*NS, 18: 12*NS, 19: NS, 20: 0, 21: 11*NS, 22: 9*NS//4, 23: 9*NS//4}[number]
    d["choices"]["act"]["reservation"]["not_before_ns"] = threshold
    think = atoms(((10, F(1, 2)), (F(21, 2), F(1, 2)))) if number == 18 else delay(F(10) if number in (17, 21) else F(0))
    d["execution"]["think"] = by_mode({m: delay() if m == "idle" else think for m in modes})
    d["execution"]["receipt"] = by_mode({m: delay(F(1, 4) if number in (20, 22, 23) and m != "idle" else 0) for m in modes})
    late_delay = atoms(((F(1, 4), F(1, 2)), (F(3, 4), F(1, 2)))) if number in (17, 18) else delay()
    chi = by_mode({m: late_delay if m == "ready" else delay() for m in modes})
    if number == 21:
        chi = {"given": ["state", "mode"], "rows": [{"when": [s, m], "points": [[
            rational(F(1, 4) if s == "0" else F(3, 4)) if m == "ready" else [0, 1], [1, 1]]]}
            for s in ("0", "1") for m in modes]}
    d["execution"]["chi"]["candidates"][0]["delay"] = chi
    if number in (17, 18, 19, 21):
        d["clock"]["candidates"][0].update(kind="tick", width_ns=NS, phase_ns=[0, 1])
    if number == 20:
        d["execution"]["confirmations"]["dispatch"] = delay()
    return d, H, pending_probe


def history(number, *, read=False, outcome="0", flip_act=False):
    d, H, has_probe = scenario(number, read=read)
    if flip_act:
        d["effects"]["act"]["B"]["values"] = table(FLIP)
    w = FactWorld(d)
    first_cmd, first = w.start("first", 0, position=0)
    if number == 20:
        w.confirmation("dispatch", first_cmd, first, 0)
    probe = w.start("probe", 0, position=1)[1] if has_probe else None
    root, cert = w.root(H)
    first_reading = NS if number == 18 else 2*NS if number in (20, 22, 23) else 0
    report = w.report(first, first_reading, outcome="0")
    registered = targets(report)
    parent = w.node(registered=registered)
    rd = 10*NS if number in (17, 21) else 11*NS if number == 18 else first_reading
    cmd, attempt = w.start("act", rd, stage=1)
    if number == 20:
        w.confirmation("dispatch", cmd, attempt, 9*NS//4)
        child = w.node(controls=(cmd,), registered=registered)
        return root, cert, parent, child
    second = w.report(probe if has_probe else attempt, H, outcome=outcome)
    child = w.node(controls=(cmd,), registered=registered+targets(second))
    return root, cert, parent, child


@pytest.mark.parametrize("number,flip_act", ((17, False), (21, False), (21, True)),
                         ids=("T17_independent", "T21_correlated", "S301_T21_flip"))
def test_t17_t21_waiting_preserves_joint_state_delay_reference(number, flip_act):
    root, cert, parent, child = history(number, flip_act=flip_act)
    query = (parent.targets[-1], child.targets[-1])
    # Flip makes U=0 stay at1; U=1 flips to0 at11.75, with survival1/2
    # until12. The wrong state0 delay sends at11.25, giving survival1/8.
    expected = ({("0", "1"): F(1, 2), ("1", "0"): F(1, 4), ("1", "1"): F(1, 4)}
                if flip_act else {tuple(key): F(*value)
                    for key, value in fixed("T"+str(number), "joint_U_Z").items()})
    assert_distribution(marginal(child, query), expected, exact=False)
    assert_distribution(reference(root, child, query, cert), expected, exact=False)
    assert_evidence(parent, F(1))
    assert_evidence(child, F(1))
    assert_bounds(potential(root, parent, cert), 0.)
    assert_bounds(potential(root, child, cert), fixed("T"+str(number), "information"))


@pytest.mark.parametrize("read,outcome", ((False, "0"), (True, "0"), (True, "1")))
def test_t18_auxiliary_work_does_not_become_information_and_reading_Z_has_correct_KL(read, outcome):
    root, cert, parent, child = history(18, read=read, outcome=outcome)
    assert_bounds(potential(root, parent, cert), 0.)
    prior = {("0", "0"): F(5, 16), ("0", "1"): F(11, 16)}
    query = (parent.targets[-1], child.targets[-1])
    assert_distribution(reference(root, child, query, cert), prior, exact=False)
    posterior = {( "0", outcome): F(1)} if read else prior
    assert_distribution(marginal(child, query), posterior, exact=False)
    assert_evidence(parent, F(1, 2))  # only the auxiliary first work sample is selected
    assert_evidence(child, F(1, 2)*prior["0", outcome] if read else F(1, 2))
    expected = -math.log(float(prior["0", outcome])) if read else 0.
    assert_bounds(potential(root, child, cert), expected)
    # Both conditional KL values, weighted by 5/16 and 11/16, give T18's h2.
    mean = -sum(float(p)*math.log(float(p)) for p in prior.values())
    assert mean == pytest.approx(fixed("T18", "read_increment"), abs=3e-15)


def test_t19_late_root_world_is_sent_and_does_not_create_information():
    root, cert, parent, child = history(19)
    query = (parent.targets[-1], child.targets[-1])
    expected = {("0", "1"): F(1)}
    assert_distribution(reference(root, child, query, cert), expected)
    assert_distribution(marginal(child, query), expected)
    assert_evidence(parent, F(1, 2))
    assert_evidence(child, F(1, 2))
    assert_bounds(potential(root, parent, cert), 0.)
    assert_bounds(potential(root, child, cert), fixed("T19", "send_increment"))


@pytest.mark.parametrize("number,read", ((17, False), (18, False), (18, True),
                                       (19, False), (21, False)))
def test_pending_probe_branches_match_manual_history_reference_and_information(number, read):
    """§3-10-4: branches must produce the ROOT's probe, not act's completion.

    The manual history is only a second public route. Expectations below
    come from T17/T18/T19/T21's independent laws, not either route's output.
    """
    root, cert, parent, manual = history(number, read=read)
    H = {17: 12*NS, 18: 13*NS, 19: 3*NS, 21: 12*NS}[number]
    measure = api("action_lookahead").branches(parent, manual.controls[0], deadline_ns=H,
                                               certificate=cert, budget=budget())
    assert_bounds(measure.total_mass, F(1))
    prior = ({tuple(k): F(*v) for k, v in fixed("T"+str(number), "joint_U_Z").items()}
             if number in (17, 21) else
             {("0", "0"): F(5, 16), ("0", "1"): F(11, 16)} if number == 18 else
             {("0", "1"): F(1)})
    expected_probabilities = {"0": F(5, 16), "1": F(11, 16)} if read else {"0": F(1)}
    assert len(measure.atoms) == len(expected_probabilities)
    seen = set()
    weighted_lower = weighted_upper = 0.
    for atom in measure.atoms:
        reports = [r for r in atom.records
                   if getattr(getattr(r.body, "contract", None), "name", None) == "sui.s4b.action_report"]
        assert len(reports) == 1  # act's work=100s, outside H
        report = reports[0]
        data = report.body.content.as_json()
        outcome = data["outcome"]
        assert outcome in expected_probabilities and outcome not in seen
        seen.add(outcome)
        assert data["measurement_reading_ns"] == data["completion_reading_ns"] == H
        assert report.body.received_ns == H
        # The generated report belongs to the already running probe attempt.
        assert str(report.body.caused_by) == manual.targets[-1].attempt
        assert atom.child.trigger == targets(report)[-1]
        assert_bounds(atom.probability, expected_probabilities[outcome])
        assert all(t in atom.child.targets for t in parent.targets)
        assert len(atom.child.targets) == len(parent.targets)+2
        assert {(t.position, t.side) for t in atom.child.targets if t not in parent.targets} == {
            ("measurement", "post"), ("completion", "post")}
        query = (parent.targets[-1], targets(report)[-1])
        posterior = {("0", outcome): F(1)} if read else prior
        info_expected = -math.log(float(expected_probabilities[outcome])) if read else 0.
        hand_root, hand_cert, hand_parent, hand_child = history(number, read=read, outcome=outcome)
        for base, scope, child, child_query in ((root, cert, atom.child, query),
                (hand_root, hand_cert, hand_child, (hand_parent.targets[-1], hand_child.targets[-1]))):
            assert_distribution(reference(base, child, child_query, scope), prior, exact=False)
            assert_distribution(marginal(child, child_query), posterior, exact=False)
            assert_bounds(potential(base, child, scope), info_expected)
        info = potential(root, atom.child, cert)
        weighted_lower += atom.probability.lower*info.lower
        weighted_upper += atom.probability.upper*info.upper
    assert seen == set(expected_probabilities)
    expected_total = fixed("T18", "read_increment") if read else 0.
    assert weighted_lower-1e-12 <= expected_total <= weighted_upper+1e-12
    assert weighted_upper-weighted_lower <= 2e-9


def test_t20_clock_readings_are_evidence_not_reference_controls_or_new_targets():
    root, cert, parent, child = history(20)
    assert child.targets == parent.targets
    assert_evidence(parent, F(1, 2))
    assert_evidence(child, F(1, 2))
    assert_distribution(marginal(child, (parent.targets[-1],)), {("1",): F(1)})
    assert_distribution(reference(root, child, (parent.targets[-1],), cert),
                        {("0",): F(1, 2), ("1",): F(1, 2)})
    assert_bounds(potential(root, parent, cert), fixed("T20", "information"))
    assert_bounds(potential(root, child, cert), fixed("T20", "information"))


def test_t22_reservation_keeps_old_label_marginal_and_prevents_endogenous_replay():
    root, cert, parent, child = history(22)
    query = (parent.targets[-1], child.targets[-1])
    expected = {tuple(k): F(*v) for k, v in fixed("T22", "reference_X_Z").items()}
    assert_distribution(reference(root, child, query, cert), expected)
    assert_distribution(marginal(child, query), {("1", "1"): F(1)})
    assert_evidence(parent, F(1, 2))
    assert_evidence(child, F(1, 2))
    # Same old label before/after extending controls (projective consistency).
    for node in (parent, child):
        assert_distribution(reference(root, node, (parent.targets[-1],), cert),
                            {("0",): F(1, 2), ("1",): F(1, 2)})
    assert_bounds(potential(root, parent, cert), fixed("T22", "parent"))
    assert_bounds(potential(root, child, cert), fixed("T22", "child"))


@pytest.mark.parametrize("read,outcome", ((False, "0"), (True, "0"), (True, "1")))
def test_t23_waiting_then_independent_reset_extends_joint_information_without_kappa(read, outcome):
    root, cert, parent, child = history(23, read=read, outcome=outcome)
    query = (parent.targets[-1], child.targets[-1])
    expected = {tuple(k): F(*v) for k, v in fixed("T23", "reference_V_Z").items()}
    assert_distribution(reference(root, child, query, cert), expected, exact=False)
    posterior = {("0", outcome): F(1)} if read else {("0", "0"): F(1, 2), ("0", "1"): F(1, 2)}
    assert_distribution(marginal(child, query), posterior, exact=False)
    assert_evidence(parent, F(1, 4))  # P(R=2)*P(V=0)=1/2*1/2; R itself is not a target
    assert_evidence(child, F(1, 8) if read else F(1, 4))
    assert_bounds(potential(root, parent, cert), fixed("T23", "parent"))
    assert_bounds(potential(root, child, cert), fixed("T23", "read_child" if read else "constant_child"))


def chi_fixture(*, tick=False, split=False, noisy=False, known=False):
    d = declaration(("act",), kernels={"act": I}, initial=(1, 0), observed=False)
    d["work"]["act"]["points"] = [[100*NS, [1, 1]]]
    d["execution"]["confirmations"]["dispatch"] = delay()
    if tick:
        d["clock"]["candidates"][0].update(kind="tick", width_ns=NS, phase_ns=[0, 1])
    if noisy:
        laws = [(F(1, 2), atoms(((F(1, 4), F(3, 4)), (F(3, 4), F(1, 4))))),
                (F(1, 2), atoms(((F(1, 4), F(1, 4)), (F(3, 4), F(3, 4)))))]
    elif known:
        laws = [(F(1), atoms(((F(1, 4), F(1, 2)), (F(3, 4), F(1, 2)))))]
    else:
        laws = ([(F(1, 5), delay(F(1, 4))), (F(3, 10), delay(F(1, 4))), (F(1, 2), delay(F(3, 4)))]
                if split else [(F(1, 2), delay(F(1, 4))), (F(1, 2), delay(F(3, 4)))])
    d["execution"]["chi"]["candidates"] = [{"weight": rational(weight), "delay": law} for weight, law in laws]
    return d


@pytest.mark.parametrize("tick,split", ((False, False), (True, False), (False, True), (True, True)))
def test_t24_chi_learning_and_duplicate_candidate_split_merge(tick, split):
    w = FactWorld(chi_fixture(tick=tick, split=split))
    root, cert = w.root(2*NS)
    cmd, attempt = w.start("act", 0)
    w.confirmation("dispatch", cmd, attempt, 0 if tick else NS//4)
    node = w.node(controls=(cmd,))
    assert_evidence(node, F(1) if tick else F(1, 2))
    weights = api("action_joint").hypothesis_weights(node.belief, parameter="chi", budget=budget())
    expected = ((F(1, 5), F(3, 10), F(1, 2)) if split else (F(1, 2), F(1, 2))) if tick else (
        (F(2, 5), F(3, 5), F(0)) if split else (F(1), F(0)))
    assert len(weights) == len(expected)
    for actual, target in zip(weights, expected):
        assert_bounds(actual, target, exact=True)
    assert_bounds(potential(root, node, cert), fixed("T24", "same_tick_information" if tick else "exact_information"))


def test_t24_chi_learning_and_duplicate_candidate_split_merge_delayed_confirmation():
    """S307: dispatch=.25 and receipt=1 select chi=.25, delay=.75.

    Each has prior mass1/2, so evidence=1/4, posterior chi=(1,0).
    Receipt alone also permits chi=.75, delay=.25: evidence1/2, fair chi.
    """
    d = chi_fixture()
    d["execution"]["confirmations"]["dispatch"] = atoms(
        ((F(1, 4), F(1, 2)), (F(3, 4), F(1, 2))))
    w = FactWorld(d)
    cmd, attempt = w.start("act", 0)
    payload = {"command": json.loads(api("dispatch").command_json(cmd)),
        "run": str(w.h.clock.run), "reading_ns": NS//4,
        "point": {"name": "test.named-send-point", "version": "1"}}
    w.observe("dispatch", attempt, NS, payload)
    node = w.node(controls=(cmd,))
    assert_evidence(node, F(1, 4))
    weights = api("action_joint").hypothesis_weights(node.belief, parameter="chi", budget=budget())
    assert len(weights) == 2
    for actual, expected in zip(weights, (F(1), F(0))):
        assert_bounds(actual, expected, exact=True)


def test_known_chi_does_not_count_the_entropy_of_an_individual_delay_draw():
    w = FactWorld(chi_fixture(known=True))
    root, cert = w.root(2*NS)
    cmd, attempt = w.start("act", 0)
    w.confirmation("dispatch", cmd, attempt, NS//4)
    node = w.node(controls=(cmd,))
    assert_evidence(node, F(1, 2))
    assert_bounds(potential(root, node, cert), 0.)


@pytest.mark.parametrize("redelivery", ("same_id", "same_source"))
def test_chi_source_id_redelivery_does_not_square_the_notification_likelihood(redelivery):
    w = FactWorld(chi_fixture(noisy=True))
    root, cert = w.root(2*NS)
    cmd, attempt = w.start("act", 0)
    observation = w.confirmation("dispatch", cmd, attempt, NS//4, source_id="one-physical-confirmation")
    if redelivery == "same_id":
        records = tuple(w.records)+(observation,)
    else:
        w.observe("dispatch", attempt, NS//4, observation.body.content.as_json(),
                  source_id=observation.body.source_id)
        records = tuple(w.records)
    node = w.node(controls=(cmd,), records=records)
    assert_evidence(node, F(1, 2))
    weights = api("action_joint").hypothesis_weights(node.belief, parameter="chi", budget=budget())
    assert len(weights) == 2
    for actual, expected in zip(weights, (F(3, 4), F(1, 4))):
        assert_bounds(actual, expected, exact=True)
    expected_info = math.log(2)+sum(float(p)*math.log(float(p)) for p in (F(3, 4), F(1, 4)))
    assert_bounds(potential(root, node, cert), expected_info)


def test_chi_source_id_redelivery_does_not_square_the_notification_likelihood_delayed_tick():
    """S310: floor(dispatch)=0, floor(receipt)=1 give likelihoods3/4,1/4.

    chi=.25 needs delay1.25; chi=.75 needs delay.5. Evidence=1/2,
    posterior=(3/4,1/4), also after same-source redelivery. Squaring the
    likelihoods would give evidence5/16 and posterior=(9/10,1/10).
    """
    d = chi_fixture(tick=True)
    d["execution"]["confirmations"]["dispatch"] = atoms(
        ((F(1, 2), F(1, 4)), (F(5, 4), F(3, 4))))
    w = FactWorld(d)
    cmd, attempt = w.start("act", 0)
    payload = {"command": json.loads(api("dispatch").command_json(cmd)),
        "run": str(w.h.clock.run), "reading_ns": 0,
        "point": {"name": "test.named-send-point", "version": "1"}}
    confirmations = []
    for _ in range(2):
        confirmations.append(w.observe("dispatch", attempt, NS, payload,
            source_id="one-delayed-physical-confirmation"))
        node = w.node(controls=(cmd,))
        assert_evidence(node, F(1, 2))
        weights = api("action_joint").hypothesis_weights(node.belief, parameter="chi", budget=budget())
        assert len(weights) == 2
        for actual, expected in zip(weights, (F(3, 4), F(1, 4))):
            assert_bounds(actual, expected, exact=True)
    assert confirmations[0].id != confirmations[1].id
    assert confirmations[0].body.source_id == confirmations[1].body.source_id


def test_old_report_label_does_not_collide_with_new_start_post_at_same_clock_reading():
    d = declaration(("first", "act"), kernels={"first": I, "act": [[0, 1], [1, 0]]})
    d["a"]["act"] = table(C)
    d["effects"]["act"]["measure"] = {"at": "start", "side": "post"}
    w = FactWorld(d)
    _, first = w.start("first", 0, stage=0)
    root, cert = w.root(2*NS)
    old_report = w.report(first, NS, outcome="0")
    parent = w.node(registered=targets(old_report))
    cmd, attempt = w.start("act", NS, stage=1)
    new_report = w.observe("action_report", attempt, 2*NS, {"outcome": "0", "effect_notice": None,
        "measurement_reading_ns": NS, "completion_reading_ns": 2*NS})
    child = w.node(controls=(cmd,), registered=parent.targets+targets(new_report))
    query = (parent.targets[-1], targets(new_report)[0])
    assert_distribution(reference(root, child, query, cert),
                        {("0", "1"): F(1, 2), ("1", "0"): F(1, 2)})
    assert_distribution(marginal(child, query), {("0", "1"): F(1)})
    assert_bounds(potential(root, parent, cert), math.log(2))
    assert_bounds(potential(root, child, cert), math.log(2))


@pytest.mark.parametrize("where", ("receipt", "chi"))
@pytest.mark.parametrize("deadline", (NS, 2*NS))
def test_finite_waiting_and_permanent_nonsend_mass_normalize_without_inventing_reports(where, deadline):
    d = declaration(("act",), kernels={"act": [[0, 0], [1, 1]]}, initial=(1, 0), observed=False)
    law = atoms(((F(0), F(1, 2)), (F(1), F(1, 4)), (None, F(1, 4))))
    if where == "receipt":
        d["execution"]["receipt"] = law
    else:
        d["execution"]["chi"]["candidates"][0]["delay"] = law
    r, root, node, cert = root_case(d, H=deadline)
    measure = api("action_lookahead").branches(node, command(r, "act"), deadline_ns=deadline,
                                               certificate=cert, budget=budget())
    assert_bounds(measure.total_mass, F(1), exact=True)
    masses = {}
    weighted_lower = weighted_upper = 0.
    for atom in measure.atoms:
        reports = [record for record in atom.records
                   if getattr(getattr(record.body, "contract", None), "name", None) == "sui.s4b.action_report"]
        assert len(reports) <= 1
        reading = reports[0].body.content.as_json()["completion_reading_ns"] if reports else None
        assert reading not in masses  # identical visible nonarrival paths must be grouped
        masses[reading] = atom.probability.exact
        if not reports:
            assert atom.child.targets == ()
            label = api("action_types").FixedLabel(time_s=F(deadline, NS), causal_stage=0,
                                                   causal_position=0, side="post")
            # At H=1, half of missing reports have dispatched at1 and half
            # never dispatch. At H=2, the only missing branch is permanent.
            p1 = F(1, 2) if deadline == NS else F(0)
            assert_distribution(marginal(atom.child, (label,)), {("0",): 1-p1, ("1",): p1})
        else:
            # Unconditional controlled reference retains the never-sent 1/4.
            query = (atom.child.targets[-1],)
            assert_distribution(reference(root, atom.child, query, cert),
                                {("0",): F(1, 4), ("1",): F(3, 4)})
            assert_distribution(marginal(atom.child, query), {("1",): F(1)})
        info = potential(root, atom.child, cert)
        assert_bounds(info, math.log(4/3) if reports else 0.)
        weighted_lower += float(atom.probability.exact)*info.lower
        weighted_upper += float(atom.probability.exact)*info.upper
    assert masses == ({NS: F(1, 2), None: F(1, 2)} if deadline == NS
                      else {NS: F(1, 2), 2*NS: F(1, 4), None: F(1, 4)})
    expected_total = float(F(1, 2) if deadline == NS else F(3, 4))*math.log(4/3)
    assert weighted_lower-1e-12 <= expected_total <= weighted_upper+1e-12
    assert weighted_upper-weighted_lower <= 2e-9
