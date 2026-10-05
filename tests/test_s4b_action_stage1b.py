"""S4b v0.19 §3-6 T5/T6/T12--T15/T25, §6-3 stage 1b.

Shared fixture: two states, Q=0, independent initial state/B/Theta, exact clock,
positive known work=1 second, speed=1, zero execution delays unless T25 says
otherwise, start-impulse/2, report/post measurement and completion before the
next action. H includes its endpoint. No root pending work or arrivals; cost=0,
gamma=1, u=1/4 (no policy selection is needed for these forced controls).
B and Theta columns are independently Dir(1,1) ONLY when explicitly made
learnable. Everything else remains known. No oracle imports sui.

The registered-target joint information is tested separately from a law-only
projection (an empty-target ActionNode queried once, never used to continue a
policy or erase the original node's targets). No component entropy is added.
"""
from fractions import Fraction as F
import json
import math

import pytest

from s4b_action_cases import (C, FAIR, FLIP, I, NS, api, assert_bounds,
    assert_distribution, budget, command, declaration, delay, fixed, rig,
    root_case, table)
from s4b_action_stage1b_reference import (ACTIONS, OUTCOMES, beta_product,
    enumerate_paths, evidence, joint_information, noisy_law_information,
    state_marginal, table_moment)


def unknown_B(d, action="a"):
    d["effects"][action]["B"] = {"kind": "dirichlet", "values": table([[1, 1], [1, 1]])}


def unknown_theta(d, action="a"):
    d["learnable"].append(action)
    d["a"][action] = table([[1, 1], [1, 1]])


def report_payload(atom):
    reports = [r.body.content.as_json() for r in atom.records
               if getattr(getattr(r.body, "contract", None), "name", None)
               == "sui.s4b.action_report"]
    assert len(reports) == 1
    return reports[0]


def advance(node, cmd, certificate, deadline):
    result = api("action_lookahead").branches(node, cmd, deadline_ns=deadline,
                                             certificate=certificate, budget=budget())
    assert_bounds(result.total_mass, F(1), exact=True)
    assert sum((a.probability.exact for a in result.atoms), F()) == 1
    # At these fixed times, hidden states/count tables must be combined under
    # the same visible report, not exposed as separate independently known paths.
    reports = [(p["outcome"], p["effect_notice"]) for p in map(report_payload, result.atoms)]
    assert len(reports) == len(set(reports))
    return result.atoms


def select(atoms, *, outcome="0", notice=None):
    matching = [a for a in atoms if (report_payload(a)["outcome"],
                report_payload(a)["effect_notice"]) == (outcome, notice)]
    assert len(matching) == 1
    return matching[0]


def moment(belief, parameter, action, powers):
    return api("action_joint").parameter_moment(belief, parameter=parameter,
        action=action, powers=powers, budget=budget())


def info(root, node, certificate, *, law_only=False):
    if law_only:
        node = api("action_types").ActionNode(belief=node.belief, controls=node.controls,
                                               targets=(), terminal=node.terminal, trigger=node.trigger)
    return api("action_reference").information_potential(root, node,
        certificate=certificate, budget=budget())


def completions(node):
    return tuple(t for t in node.targets if t.position == "completion")


def last_state(node, p1):
    targets = completions(node)
    assert targets
    marginal = api("action_joint").target_marginal(node.belief, (targets[-1],), budget=budget())
    assert_distribution(marginal, {("0",): 1-p1, ("1",): p1})


@pytest.mark.parametrize("outcome", ("0", "1"))
def test_t5_unknown_effect_joint_information_is_not_sum_of_marginals(outcome):
    # D=point0, p=B[1,0]~Beta(1,1), exact Y=S'. Other B column is untouched.
    d = declaration(initial=(1, 0))
    unknown_B(d)
    r, root, node, cert = root_case(d)
    atoms = advance(node, command(r, "a"), cert, NS)
    atom = select(atoms, outcome=outcome)
    assert_bounds(atom.probability, F(1, 2), exact=True)
    child = atom.child
    s = int(outcome)
    last_state(child, F(s))
    for power in (1, 2, 3):
        # p | Y=s ~ Beta(1+s,2-s).
        expected = beta_product(1+s, 2-s, power)
        assert_bounds(moment(child.belief, "B", "a", ((0, 0), (power, 0))), expected, exact=True)
        assert_bounds(moment(child.belief, "B", "a", ((0, 0), (0, power))), F(1, power+1), exact=True)
    assert_bounds(child.belief.log_evidence, math.log(.5))
    assert_bounds(info(root, child, cert), fixed("T5", "joint_information"))
    assert_bounds(info(root, child, cert, law_only=True), fixed("T5", "law_information"))


@pytest.mark.parametrize("outcome", ("0", "1"))
def test_t6_unknown_observation_table_learns_with_known_constant_state(outcome):
    d = declaration(kernels={"a": I}, initial=(1, 0))
    unknown_theta(d)
    r, root, node, cert = root_case(d)
    atom = select(advance(node, command(r, "a"), cert, NS), outcome=outcome)
    assert_bounds(atom.probability, F(1, 2), exact=True)
    last_state(atom.child, F(0))
    for power in (1, 2, 3):
        expected = beta_product(1+int(outcome), 2-int(outcome), power)
        assert_bounds(moment(atom.child.belief, "Theta", "a", ((0, 0), (power, 0))), expected, exact=True)
        assert_bounds(moment(atom.child.belief, "Theta", "a", ((0, 0), (0, power))), F(1, power+1), exact=True)
    assert_bounds(info(root, atom.child, cert), fixed("T6", "theta_information"))
    assert_bounds(info(root, atom.child, cert, law_only=True), fixed("T6", "theta_information"))


def test_t6_constant_record_has_no_information_about_unknown_B():
    d = declaration(initial=(1, 0), observed=False)
    unknown_B(d)
    r, root, node, cert = root_case(d)
    atom = select(advance(node, command(r, "a"), cert, NS))
    assert_bounds(atom.probability, F(1), exact=True)
    assert_bounds(info(root, atom.child, cert, law_only=True), fixed("T6", "constant_B_information"))


def notice_fixture(*, learned=False, abort=False, probe=False):
    """E equals the post state; report outcome is constant, notice is separate.

    yes has likelihood (1/5,4/5) for E=(0,1). A single 'aborted' label has
    likelihood 1 for either E: it reports no success/failure information and
    does not undo the already executed impulse. This specifies the notification
    likelihood; it does not invent an undeclared physical interruption kernel.
    reset is a known extra control used only to predict another trial from 0.
    """
    actions = ("a", "reset") if probe else ("a",)
    kernels = {"a": FAIR, **({"reset": C} if probe else {})}
    d = declaration(actions, kernels=kernels, observed=False, initial=(1, 0))
    if learned:
        unknown_B(d)
    effect = d["effects"]["a"]
    effect["marks"] = {"labels": ["failure", "success"],
        "probability": [table([[1, 1], [0, 0]]), table([[0, 0], [1, 1]])]}
    likelihoods = ((1, 1),) if abort else ((F(1, 5), F(4, 5)), (F(4, 5), F(1, 5)))
    effect["notice"] = {"labels": ["aborted"] if abort else ["yes", "no"],
        "probability": [[table([[v, v], [v, v]]) for v in row] for row in likelihoods]}
    return d


@pytest.mark.parametrize("abort", (False, True), ids=("noisy_success", "uninformative_abort"))
def test_t12_notification_is_likelihood_not_certain_success_or_rollback(abort):
    d = notice_fixture(abort=abort)
    r, root, node, cert = root_case(d)
    label = "aborted" if abort else "yes"
    atom = select(advance(node, command(r, "a"), cert, NS), notice=label)
    expected = F(*fixed("T12", "uninformative_abort" if abort else "success_posterior"))
    assert_bounds(atom.probability, F(1) if abort else F(1, 2), exact=True)
    last_state(atom.child, expected)
    expected_information = 0. if abort else math.log(2)+sum(float(p)*math.log(float(p))
                                                          for p in (F(4, 5), F(1, 5)))
    assert_bounds(info(root, atom.child, cert), expected_information)


def test_t13_noisy_notice_keeps_beta_mixture_moments_prediction_and_joint_information():
    d = notice_fixture(learned=True, probe=True)
    r, root, node, cert = root_case(d, H=3*NS)
    atom = select(advance(node, command(r, "a"), cert, 3*NS), notice="yes")
    assert_bounds(atom.probability, F(1, 2), exact=True)
    child = atom.child
    last_state(child, F(4, 5))
    for power, key in ((1, "mean"), (2, "second")):
        assert_bounds(moment(child.belief, "B", "a", ((0, 0), (power, 0))),
                      F(*fixed("T13", key)), exact=True)
    assert_bounds(moment(child.belief, "B", "a", ((0, 0), (3, 0))), F(17, 50), exact=True)
    assert_bounds(moment(child.belief, "B", "a", ((0, 0), (0, 2))), F(1, 3), exact=True)
    assert_bounds(child.belief.log_evidence, math.log(.5))
    joint = math.log(2)+sum(float(p)*math.log(float(p)) for p in (F(4, 5), F(1, 5)))
    assert_bounds(info(root, child, cert), joint)
    assert_bounds(info(root, child, cert, law_only=True), noisy_law_information())
    # A known reset selects the same input column on the next trial, without
    # adding a trial to B_a. P(next yes)=1/5+(3/5)E[p]=14/25.
    reset = select(advance(child, command(r, "reset", reading_ns=NS, stage=1), cert, 3*NS))
    assert_bounds(reset.probability, F(1), exact=True)
    next_yes = select(advance(reset.child, command(r, "a", reading_ns=2*NS, stage=2), cert, 3*NS), notice="yes")
    assert_bounds(next_yes.probability, F(14, 25), exact=True)


def test_t14_unobserved_trial_preserves_law_and_two_future_successes_are_one_third():
    # a hides its outcome. read observes the current state without changing it.
    # reset returns to 0 before each of two probes of the SAME unknown B column.
    d = declaration(("a", "read", "reset"), kernels={"a": FAIR, "read": I, "reset": C},
                    observed=False, initial=(1, 0))
    unknown_B(d)
    d["a"]["read"] = table(I)
    r, root, node, cert = root_case(d, H=7*NS)
    atom = select(advance(node, command(r, "a"), cert, 7*NS))
    assert_bounds(atom.probability, F(1), exact=True)
    node = atom.child
    last_state(node, F(1, 2))
    for power in (1, 2, 3, 4):
        assert_bounds(moment(node.belief, "B", "a", ((0, 0), (power, 0))), F(1, power+1), exact=True)
    assert_bounds(info(root, node, cert), fixed("T14", "information"))
    assert_bounds(info(root, node, cert, law_only=True), fixed("T14", "information"))
    probability = F(1)
    for step, (action, outcome) in enumerate((("reset", "0"), ("a", "0"), ("read", "1"),
                                             ("reset", "0"), ("a", "0"), ("read", "1")), 1):
        atom = select(advance(node, command(r, action, reading_ns=step*NS, stage=step), cert, 7*NS), outcome=outcome)
        probability *= atom.probability.exact
        node = atom.child
    assert probability == F(*fixed("T14", "next_two_successes")) == F(1, 3)
    assert_bounds(node.belief.log_evidence, math.log(1/3))
    assert_bounds(info(root, node, cert), math.log(3))


@pytest.fixture(scope="module")
def t15_path():
    d = declaration(("a0", "a1"))
    for a in d["actions"]:
        unknown_B(d, a)
        unknown_theta(d, a)
    r, root, node, cert = root_case(d, H=7*NS)
    history = []
    for step, (action, outcome) in enumerate(zip(ACTIONS, OUTCOMES)):
        atom = select(advance(node, command(r, "a"+str(action), reading_ns=step*NS, stage=step),
                              cert, 7*NS), outcome=str(outcome))
        node = atom.child
        history.append((atom, enumerate_paths(ACTIONS[:step+1], OUTCOMES[:step+1])))
    return r, root, cert, history


def test_t15_every_prefix_evidence_and_joint_state_matches_independent_path_enumeration(t15_path):
    r, root, cert, history = t15_path
    previous_evidence = F(1)
    for step, (atom, rows) in enumerate(history, 1):
        current_evidence = evidence(rows)
        assert_bounds(atom.probability, current_evidence/previous_evidence, exact=True)
        assert_bounds(atom.child.belief.log_evidence, math.log(float(current_evidence)))
        targets = completions(atom.child)
        assert len(targets) == step
        marginal = api("action_joint").target_marginal(atom.child.belief, targets, budget=budget())
        assert_distribution(marginal, state_marginal(rows, tuple(range(1, step+1))))
        reference = api("action_reference").reference_target(root, atom.child, targets,
                                                             certificate=cert, budget=budget())
        reference_marginal = api("action_reference").reference_state_marginal(reference, budget=budget())
        assert_distribution(reference_marginal, state_marginal(enumerate_paths(ACTIONS[:step]), tuple(range(1, step+1))))
        previous_evidence = current_evidence
    assert previous_evidence == F(*fixed("T15", "post")["evidence"])


@pytest.mark.parametrize("parameter", ("B", "Theta"))
@pytest.mark.parametrize("action", (0, 1))
@pytest.mark.parametrize("powers", (((1, 0), (0, 0)), ((0, 0), (0, 2)),
    ((2, 0), (1, 0)), ((1, 0), (0, 1)), ((1, 1), (1, 1))),
    ids=("mean_column0", "second_column1", "same_column_product", "cross_columns", "all_cells"))
def test_t15_table_moments_keep_path_mixture_including_cross_column_dependence(t15_path, parameter, action, powers):
    _, _, _, history = t15_path
    atom, rows = history[-1]
    assert_bounds(moment(atom.child.belief, parameter, "a"+str(action), powers),
                  table_moment(rows, parameter, action, powers), exact=True)


@pytest.mark.parametrize("action", (0, 1))
def test_t15_next_prediction_integrates_state_B_and_Theta_together(t15_path, action):
    r, _, cert, history = t15_path
    atom, rows = history[-1]
    atoms = advance(atom.child, command(r, "a"+str(action), reading_ns=6*NS, stage=6), cert, 7*NS)
    for outcome in (0, 1):
        expected = evidence(enumerate_paths(ACTIONS+(action,), OUTCOMES+(outcome,)))/evidence(rows)
        assert_bounds(select(atoms, outcome=str(outcome)).probability, expected, exact=True)


def test_t15_joint_information_uses_posterior_expected_log_likelihood_not_marginal_sum(t15_path):
    _, root, cert, history = t15_path
    for atom, rows in history:
        assert_bounds(info(root, atom.child, cert), joint_information(rows))


@pytest.mark.parametrize("parameter", ("rho", "lambda", "chi"))
def test_stage1b_hypothesis_weights_keep_known_singletons_in_candidate_order(t15_path, parameter):
    _, _, _, history = t15_path
    weights = api("action_joint").hypothesis_weights(history[-1][0].child.belief,
                                                     parameter=parameter, budget=budget())
    assert len(weights) == 1
    assert_bounds(weights[0], F(1), exact=True)


def t25_history(*, learned, checkpoint):
    """One physical impulse: decision/reservation 0s, receipt 1s, dispatch 2s,
    report 3s. Confirmation delays=0, receipt delay=1s, not-before=2s. Q=0.
    Later same-ID/source notifications retain payload and physical readings.
    We query prefixes through read/rebuild, not a plan from a pending root.
    The known-law ruler has a constant report. The separately declared learned
    variant reads S'=1 perfectly, exposing trial counts through Beta moments.
    """
    from sui.agent import read
    from sui.contracts import ContractRef
    from sui.ids import Ref, RefKind
    from sui.records import AttemptStarted, JobOpened, Observed, Payload

    d = declaration(initial=(1, 0), kernels={"a": FLIP}, observed=learned, confirmations=True)
    if learned:
        unknown_B(d)
    d["execution"]["receipt"] = delay(F(1))
    d["choices"]["a"]["reservation"]["not_before_ns"] = 2*NS
    r = rig(d, H=4*NS)
    model, h = r.model, r.h
    root_records = tuple(r.ledger.record(e.cid) for e in r.ledger.entries())
    def snapshot():
        return root_records+tuple(h.records[1:])  # boot already belongs to the ledger
    types = api("action_types")
    decision = types.DecisionReading(run=h.clock.run, reading_ns=0, work="T25",
                                    parents=frozenset(r.agent.frontier))
    cmd = api("dispatch").build_command(model=model, choice="a", decision=decision,
                                        causal_stage=0, causal_position=0)
    control = json.loads(api("dispatch").command_json(cmd))
    cr = lambda name: ContractRef("sui.s4b."+name, "1")
    job_payload = {key: control[key] for key in ("action", "choice", "reservation_rule", "dispatch", "effect")}
    job = h.add(JobOpened(decision=Ref(RefKind.DECISION, "t25"), step=0,
                         content=Payload.json(job_payload), contract=cr("action_job")), 0)
    reservation = {"command": control, "decision_reading": {"run": str(h.clock.run),
        "reading_ns": 0, "work": "T25", "parents": sorted(decision.parents)}}
    attempt = h.add(AttemptStarted(job=job.id, content=Payload.json(reservation),
                                  contract=cr("action_attempt")), 0)
    snapshots = {"attempt": snapshot()}
    common = {"command": control, "run": str(h.clock.run)}
    dispatch = {**common, "reading_ns": 2*NS, "point": {"name": "fixture-dispatch", "version": "1"}}
    payloads = (("reservation", 0, reservation),
                ("receipt", 1, {**common, "reading_ns": NS}),
                ("dispatch", 2, dispatch),
                ("action_report", 3, {"outcome": "1" if learned else "0", "effect_notice": None,
                    "measurement_reading_ns": 3*NS, "completion_reading_ns": 3*NS}))
    for name, seconds, payload in payloads:
        record = h.add(Observed(route="executor", contract=cr(name), content=Payload.json(payload),
            caused_by=attempt.id, source_id="physical-"+name, received_ns=seconds*NS), seconds)
        snapshots["report" if name == "action_report" else name] = snapshot()
    report = record
    snapshots["same_id"] = snapshot()+(report,)
    h.add(Observed(route="executor", contract=cr("action_report"), content=report.body.content,
        caused_by=attempt.id, source_id=report.body.source_id, received_ns=3*NS), 3)
    snapshots["same_source"] = snapshot()
    h.add(Observed(route="executor", contract=cr("dispatch"), content=Payload.json(dispatch),
        caused_by=attempt.id, source_id="new-confirmation-of-same-dispatch", received_ns=2*NS), 3)
    snapshots["new_confirmation"] = snapshot()
    records = snapshots[checkpoint]
    # Public ActionTimeContext uses fact IDs and their explicitly supplied
    # causal ancestry, not sorted IDs or private Agent/Belief state.
    ancestors, seen = {}, set()
    for record in records:
        key = str(record.id)
        if key not in ancestors:
            ancestors[key] = frozenset(seen)
            seen.add(key)
    now = records[-1].at.mono_ns
    # A fact check witnesses receipt AT observed_ns, not merely a record
    # written then. The extra dispatch record is written at 3s but received at
    # 2s; use the report/redelivery actually received at 3s as the witness.
    last_observed = next(r for r in reversed(records)
                         if isinstance(r.body, Observed) and r.body.received_ns == now)
    context = types.ActionTimeContext(run=h.clock.run, now_ns=now, observed_ns=now,
        check_events=({"fact": str(last_observed.id)},), fact_ancestors=ancestors, clock_source=None)
    belief = api("action_entry").rebuild_action_belief(model, read(model, records),
                                                      context=context, budget=budget())
    return belief, types.FixedLabel(time_s=F(now, NS), causal_stage=0, causal_position=0, side="post")


@pytest.mark.parametrize("learned", (False, True), ids=("known_flip", "unknown_B"))
@pytest.mark.parametrize("checkpoint", ("attempt", "reservation", "receipt", "dispatch", "report",
                                        "same_id", "same_source", "new_confirmation"))
def test_t25_confirmations_and_redelivery_do_not_create_B_trials(learned, checkpoint):
    belief, label = t25_history(learned=learned, checkpoint=checkpoint)
    before = checkpoint in ("attempt", "reservation", "receipt")
    reported = checkpoint in ("report", "same_id", "same_source", "new_confirmation")
    p1 = F(0) if before else F(1) if reported or not learned else F(1, 2)
    assert_distribution(api("action_joint").target_marginal(belief, (label,), budget=budget()),
                        {("0",): 1-p1, ("1",): p1})
    for power in (1, 2, 3):
        expected = (beta_product(2, 1, power) if reported else F(1, power+1)) if learned else F(1)
        assert_bounds(moment(belief, "B", "a", ((0, 0), (power, 0))), expected, exact=True)
    # B[1,1] is not sampled; a success is one trial in input column 0.
    assert_bounds(moment(belief, "B", "a", ((0, 0), (0, 2))), F(1, 3) if learned else F(0), exact=True)
    assert_bounds(belief.log_evidence, math.log(.5) if learned and reported else 0.)
