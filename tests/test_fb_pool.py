"""K37/K37-c/K37-d v1.76, requests106-109: candidate pool.

Read: F-b K37/K37-a/K37-b and body v2 in full; Z53/Z63/K22/K26/K28,
K36 and its body in full; S4b2 section3-3 in full. No src bodies were read.
Request107 reads K37-c :3576 in full and rereads K22/K28. Semantic references
in Decision/Prediction extend the ledger event-parent closure. Started conflicts
remain pending but are outside acquisition Q* input reports (K28/K22).
Request108 reads all K37-d :3577. R1 uses the ACTUAL updater work reader;
the wider test-only closure is never supplied to the host or its workers.
Malformed Q* contrasts use U's public reader entry with real saved priors/raws.
Request109 adds the unconsumed-old-material contrast for mutation12: a real
evaluation retains its seat until return, A1 arrives while busy, and the pool
changes before that seat is released or the replay adoption exists.

Chosen public spelling (the paper delegates spelling to this test author):
  BeliefCandidate(id, model, observation_model, correspondence)
  CandidateAddition(candidate, pool, decision) -- three saved Points
  BeliefPool(point, model, members, states)
  PoolMember(id, model, prior_weight, law)
  PoolState(candidate, state, target, law)
  PoolBelief(pool, adoption, result, joint, evidence_mass, candidates)
  CandidatePosterior(candidate, weight, conditional)
  CandidateInputError; CandidatePoolError(reason, targets, retryable)
  FThreadHost.add_candidate(*, boot, candidate, alpha, boundary=None)
  FThreadHost.belief_pool(*, boot, boundary=None)
  FThreadHost.pool_belief(*, boot, boundary=None)

boundary is a frozen set of public saved Points; None means freeze the current
causal boundary. Getters do not drive work or mutate storage. `model` is the
resolved direct-sum model-source Point usable by existing F-a readers. State
metadata is in exactly the joint-vector order. `law` is opaque semantic identity,
not the candidate spelling or the model-source record's Point. Exact duplicate
declarations are the alias ruler here, not a general law-equivalence algorithm.
Global zero is diagnosed through the existing rejected/model_falsified update;
it issues no numeric belief. A zero component of a positive whole has weight=0
and conditional=None. A pending replay
raises CandidatePoolError(retryable=True); an unreadable declared dependency or
incomparable additions raises it with retryable=False and names the Points.
K37-c fixes incomparable_additions, unreadable_record and replay_pending;
exception messages remain free. pool_belief returns the latest confirmed
adoption of that pool, not an invented mixture of old belief and new pool.

The API check is per case, before environment creation. It makes absence of the
K37 public surface an explicit red, not a collection/import error. Controls run
the same native K36 rig and the independent oracle. In request107 this copy
contains the K37 implementation; production source bodies remain unread.
Only SourceMeasurer calls acquire. All real computation uses native workers.
"""

from copy import deepcopy
from dataclasses import dataclass, fields, replace
from decimal import Decimal, localcontext
from fractions import Fraction as Q
from inspect import signature, Parameter
from itertools import product
from threading import Event

import pytest

from sui import f, f_contracts as fc, fb, fb_contracts as c, f_update2 as u2
from sui.ids import Ref, RefKind
from sui.records import Prediction, Decided, Observed, Payload, Role
from test_fb_cycle import (CycleRig, NativeEntryObserver, ObservedEntryPort, FixedRecordSaveCut,
    P, EMPTY, I, N, ZERO, HALF, T, E, U, WATCHDOG, world_document,
    passive_declaration, assert_interval, contract, wire, ORDER)
from test_fb_stage1 import entry_from_header
from test_fb_stage2 import ORIGIN
from test_fb_read import read1_symbol
from test_fb_belief import BeliefSnapshotReader, belief1_clone


PUBLIC_FIELDS = {
    "BeliefCandidate": {"id", "model", "observation_model", "correspondence"},
    "CandidateAddition": {"candidate", "pool", "decision"},
    "BeliefPool": {"point", "model", "members", "states"},
    "PoolMember": {"id", "model", "prior_weight", "law"},
    "PoolState": {"candidate", "state", "target", "law"},
    "PoolBelief": {"pool", "adoption", "result", "joint", "evidence_mass", "candidates"},
    "CandidatePosterior": {"candidate", "weight", "conditional"},
}


def pool_api():
    missing = [n for n in (*PUBLIC_FIELDS, "CandidateInputError", "CandidatePoolError")
               if not hasattr(fb, n)]
    missing += ["FThreadHost." + n for n in ("add_candidate", "belief_pool", "pool_belief")
                if not hasattr(fb.FThreadHost, n)]
    assert not missing, "K37 public shape missing: " + ", ".join(missing)
    for name, required in PUBLIC_FIELDS.items():
        assert required <= {x.name for x in fields(getattr(fb, name))}, name
    return fb


@dataclass(frozen=True)
class Component:
    name: str
    prior: tuple
    taken: tuple
    empty: tuple
    targets: tuple = ("A", "B")
    law: str = "base"  # independent EXPECTED equivalence class, never read from sui
    unavailable: tuple | None = None

    def matrix(self, symbol):
        return {T: self.taken, E: self.empty, U: self.unavailable or ZERO}[symbol]


OLD = Component("old", (Q(1, 2), Q(1, 2)), P, EMPTY)
NEW = Component("new", (Q(3, 4), Q(1, 4)),
    ((Q(1, 4), 0), (0, Q(3, 4))), ((Q(3, 4), 0), (0, Q(1, 4))), law="new")
THIRD = Component("third", (Q(1), Q(0)),
    ((Q(2, 3), 0), (0, Q(2, 3))), ((Q(1, 3), 0), (0, Q(1, 3))), law="third")
CE1 = Component("old", (Q(1, 2), Q(1, 2)),
    ((Q(1, 4), 0), (0, Q(1, 16))), ((Q(1, 2), 0), (0, Q(1, 4))),
    unavailable=((Q(1, 4), 0), (0, Q(11, 16))))


def acquisition_for(component):
    observation = passive_declaration(component.taken, component.empty)
    if component.unavailable is not None:
        control, = observation.controls
        sample = control.kernel.outcomes[0]
        extra = replace(sample, id=U, evidence=replace(sample.evidence, value=read1_symbol(U)),
                        matrix=tuple(tuple(Q(x) for x in row) for row in component.unavailable))
        cell = f.ObservationCell(id=U, observation=f.ObservationValue(
            kind="measurement", value=read1_symbol(U)), outcomes=(U,))
        control = replace(control, kernel=replace(control.kernel,
            outcomes=(*control.kernel.outcomes, extra)), cells=(*control.cells, cell))
        observation = replace(observation, controls=(control,))
    return observation


def joint_oracle(components, weights, history):
    """Sum all finite state paths; no call to sui and no posterior reuse.

    history is a common sequence of cells or tuples of per-component matrices.
    Distinct candidates are disjoint blocks: cross-block paths do not exist.
    """
    totals, evidence = {}, []
    for ci, (component, weight) in enumerate(zip(components, weights, strict=True)):
        n = len(component.prior)
        matrices = [component.matrix(h) if isinstance(h, str) else h[ci] for h in history]
        block = [Q(0)] * n
        for start in range(n):
            for path in product(range(n), repeat=len(matrices)):
                p, previous = component.prior[start], start
                for matrix, arrival in zip(matrices, path, strict=True):
                    p *= matrix[arrival][previous]
                    previous = arrival
                block[previous] += p
        evidence.append(sum(block, Q(0)))
        for state, p in zip(("A", "B"), block, strict=True):
            totals[component.name, state] = weight * p
    mass = sum(totals.values(), Q(0))
    joint = None if mass == 0 else {key: p / mass for key, p in totals.items()}
    projections = {}
    for component, weight, z in zip(components, weights, evidence, strict=True):
        if not mass:
            projections[component.name] = (None, None)
        elif not z:
            projections[component.name] = (Q(0), None)
        else:
            projections[component.name] = (weight * z / mass,
                tuple(joint[component.name, s] * mass / (weight * z) for s in ("A", "B")))
    return joint, mass, projections


def information_oracle(components, joint):
    """Information about (law, original target), then one joint soft choice.

    All cells use the SAME raw taken/empty observation. Candidate identifiers
    never become evidence. Aliases have the same law label in this ruler.
    """
    with localcontext() as context:
        context.prec = 80
        def dec(x): return Decimal(x.numerator) / Decimal(x.denominator)
        def entropy(values): return -sum((dec(x) * dec(x).ln() for x in values if x), Decimal(0))
        marginal = {}
        for component in components:
            for s, target in zip(("A", "B"), component.targets, strict=True):
                key = component.law, target
                marginal[key] = marginal.get(key, Q(0)) + joint[component.name, s]
        conditional_entropy = Decimal(0)
        for symbol in (T, E, U):
            post = {}
            for component in components:
                matrix = component.matrix(symbol)
                for j, target in enumerate(component.targets):
                    value = sum((matrix[j][i] * joint[component.name, s]
                                 for i, s in enumerate(("A", "B"))), Q(0))
                    key = component.law, target
                    post[key] = post.get(key, Q(0)) + value
            mass = sum(post.values(), Q(0))
            if mass: conditional_entropy += dec(mass) * entropy(x / mass for x in post.values())
        info = entropy(marginal.values()) - conditional_entropy
        peek = info.exp() / (1 + info.exp())
        return +info, +peek


class PoolRig(CycleRig):
    def __init__(self, *, component=OLD, **kwargs):
        super().__init__(prior=component.prior, peek=component.taken, empty=component.empty,
            passive=component.taken, passive_empty=component.empty,
            exception=component.unavailable, same_target=len(set(component.targets)) == 1, **kwargs)
        models = self.boot_input.declaration.observation_models
        self.boot_input = replace(self.boot_input, declaration=replace(self.boot_input.declaration,
            observation_models=(replace(models[0], value=acquisition_for(component)), *models[1:])))
        self.expected_components = [component]
        self.expected_weights = [Q(1)]
        self._boot_point = None
        if kwargs.get("thinking", True): self.thinking_seats(1, execution=True)

    def start(self):
        super().start()
        self.boot()  # Cache during explicit startup, before add/read/freeze scenes.
        return self

    def direct(self, **kwargs):
        super().direct(**kwargs)
        self.boot()
        return self

    def boot(self):
        if self._boot_point is None:
            self.until(lambda: bool(self.facts(c.BOOT_DECLARATION)))
            boot, = self.facts(c.BOOT_DECLARATION)
            self._boot_point = boot.cid
        return self._boot_point

    def pool(self, *, boundary=None):
        return self.host.belief_pool(boot=self.boot(), boundary=boundary)

    def belief(self, *, boundary=None):
        return self.host.pool_belief(boot=self.boot(), boundary=boundary)

    def save_candidate(self, component, *, missing=None, edit_document=None):
        document, _ = world_document(prior=component.prior, peek=component.taken,
            empty=component.empty, exception=component.unavailable, targets=component.targets)
        if missing == "kernel":
            # Valid finite model that offers only wait, not a malformed kernel.
            document["operations"] = [x for x in document["operations"] if x["id"] == "wait"]
            document["kernels"] = [x for x in document["kernels"] if x["id"] == "wait"]
            document["policies"] = [x for x in document["policies"] if x["id"] == "wait"]
        if missing == "cell":
            # Legal model, but the old execution reading names outcome t, not
            # this newly declared outcome. Never silently assign it to a cell.
            kernel = next(x for x in document["kernels"] if x["id"] == "peek")
            next(x for x in kernel["outcomes"] if x["id"] == "t")["id"] = "unread-t"
            for p in document["policies"]:
                for node in p["nodes"]:
                    if node.get("kernel") == "peek" and "t" in node["next"]:
                        node["next"]["unread-t"] = node["next"].pop("t")
        if edit_document is not None: edit_document(document)
        record = self.record(Prediction(target="k37." + component.name, about=(), basis=(),
            content=Payload.json({"document": document}), contract=contract("sui.f.model_source")),
            RefKind.PREDICTION, Role.MODEL)
        model = self.ledger.append(record, ()).cid
        observation = acquisition_for(component)
        correspondence = {"pairs": [["A", "A"], ["B", "B"]]}
        if missing == "correspondence": correspondence = {"pairs": [["A", "A"]]}
        return fb.BeliefCandidate(id=component.name, model=model,
            observation_model=observation, correspondence=correspondence)

    def add(self, component=NEW, alpha=Q(1, 3), *, candidate=None, boundary=None):
        candidate = candidate or self.save_candidate(component)
        added = self.host.add_candidate(boot=self.boot(), candidate=candidate,
            alpha=alpha, boundary=boundary)
        assert isinstance(added, fb.CandidateAddition)
        self.expected_components.append(component)
        self.expected_weights = [x * (1 - alpha) for x in self.expected_weights] + [alpha]
        return added

    def replay(self):
        # Positive progress is witnessed by a matching pool + a saved adoption.
        pool = self.pool()
        self.exercise_available_updates()
        def ready():
            try: return self.belief().pool == pool.point
            except fb.CandidatePoolError as error:
                if error.retryable: return False
                raise
        self.until(ready)
        answer = self.belief()
        if answer.joint is not None:
            assert answer.adoption is not None and answer.result is not None
        return answer

    def assert_joint(self, history, *, components=None, weights=None, boundary=None):
        components = components or self.expected_components
        weights = self.expected_weights if weights is None else weights
        expected, mass, projections = joint_oracle(components, weights, history)
        pool, actual = self.pool(boundary=boundary), self.belief(boundary=boundary)
        assert isinstance(pool, fb.BeliefPool) and isinstance(actual, fb.PoolBelief)
        assert actual.pool == pool.point and actual.evidence_mass == mass
        names = {component.name for component in components}
        ids = {member.id for member in pool.members}
        old = components[0].name
        assert names - {old} <= ids
        initial, = ids - (names - {old})
        rename = {initial: old, **{name: name for name in names - {old}}}
        assert {rename[x.id]: x.prior_weight for x in pool.members} == dict(zip(
            (x.name for x in components), weights, strict=True))
        keys = [(rename[s.candidate], s.state) for s in pool.states]
        assert len(set(keys)) == len(keys) == 2 * len(components)
        assert set(keys) == {(x.name, s) for x in components for s in ("A", "B")}
        actual_laws = {rename[x.id]: x.law for x in pool.members}
        for state in pool.states:
            component = next(x for x in components if x.name == rename[state.candidate])
            assert state.target == component.targets[("A", "B").index(state.state)]
            assert state.law == actual_laws[component.name]
        if expected is None:
            assert actual.joint is None
        else:
            assert actual.joint is not None
            assert dict(zip(keys, actual.joint, strict=True)) == expected
        assert {rename[x.candidate]: (x.weight, x.conditional) for x in actual.candidates} == projections
        if actual.adoption is not None:
            adopted = self.read_stored(actual.adoption)[2].body.content.as_json()
            assert adopted["result"] == actual.result
            result = self.read_stored(actual.result)[2].body.content.as_json()
            assert result["result"] == {"joint": wire(actual.joint), "evidence_mass": wire(mass)}
            requested = self.read_stored(result["request"])[2].body.content.as_json()
            assert requested["desc"]["args"]["model"] == pool.model
            closure = saved_closure(self, result["request"])
            assert {pool.point, pool.model, *(x.model for x in pool.members)} <= closure
        return actual

    def assert_evaluation(self, selected, history):
        joint, _, _ = joint_oracle(self.expected_components, self.expected_weights, history)
        assert joint is not None
        info, probability = information_oracle(self.expected_components, joint)
        value = self.selected_value(selected)
        assert value.root.gamma == 1 and value.root.preferences == ()
        evaluation = value.evaluation
        assert set(evaluation.candidates) == {"peek", "wait"}
        for i, candidate in enumerate(evaluation.candidates):
            expected_info = info if candidate == "peek" else Decimal(0)
            assert_interval(evaluation.information[i].additional, expected_info)
            assert_interval(evaluation.G[i], -expected_info)
            assert_interval(evaluation.q_star[i], probability if candidate == "peek" else 1 - probability)
        return value

    def selected_model(self, selected):
        """Follow public Selection -> EV -> Ee request -> Ep request -> input.

        FRoot.model_ref is a semantic model digest, not the saved model Point.
        The request input is the public Point whose boundary we are checking.
        """
        evaluated, = [x for x in self.facts(c.EVALUATED) if x.cid == selected.value["evaluated"]]
        ee, = [q for q in self.requests("evaluation") if q.cid == evaluated.value["request"]]
        ep, = [q for q in self.requests("evaluation_prepare")
               if q.cid == ee.value["desc"]["args"]["evaluation_request"]]
        return ep.value["desc"]["args"]["input"]["model"]

    def think(self):
        """Drive offered native work; do not assume Wg is reused across pools.

        K37 requires a common resolved pool, not a particular number of generator
        invocations. The finite ruler has one thinking seat and a nonboundary
        draw, so exactly one next selection is expected.
        """
        before = {s.cid for s in self.facts(c.SELECTION)}
        def selections(): return [s for s in self.facts(c.SELECTION) if s.cid not in before]
        def offers():
            return [(q, body) for stage in ORDER for q in self.requests(stage)
                for wid, body in self.launcher.attempts
                if wid == q.value["desc"]["work_id"] and wid not in self.executed]
        for _ in range(32):  # Test watchdog; no limit added to the host's computation.
            self.until(lambda: bool(selections()) or bool(offers()))
            if selections():
                selected, = selections()
                return selected
            q, body = offers()[0]
            self.invoke(q, body)
        pytest.fail("finite pool ruler did not reach its next selection")


@pytest.fixture
def pools():
    made = []
    def make(**kwargs):
        pool_api()
        rig = PoolRig(**kwargs); made.append(rig); return rig
    yield make
    for rig in reversed(made): rig.close()


def assert_named_error(call, *targets, retryable=False, reason=None):
    with pytest.raises(fb.CandidatePoolError) as error: call()
    assert isinstance(error.value.reason, str) and error.value.reason
    if reason is not None: assert error.value.reason == reason
    assert set(targets) <= set(error.value.targets)
    assert error.value.retryable is retryable
    return error.value


def snapshot_records(rig):
    return {point: rig.read_stored(point) for point in rig.snapshot()}


def assert_unchanged(rig, before):
    for point, raw in before.items(): assert rig.read_stored(point) == raw


def saved_closure(rig, point):
    """Public event parents PLUS Decided.inputs and Prediction.about/basis.

    Semantic refs can be Record.id or entry-name refs (K37-c(9)); neither makes
    a Prediction an event parent. Resolve only references to stored records,
    leaving subject/run identities outside this saved-record closure.
    """
    points = set(rig.snapshot())
    by_id = None
    def resolve(ref):
        nonlocal by_id
        if isinstance(ref, Ref) and ref.value in points: return ref.value
        if by_id is None:
            by_id = {rig.read_stored(p)[2].id: p for p in points}
        return by_id.get(ref)
    seen, pending = set(), [point]
    while pending:
        current = pending.pop()
        if current in seen: continue
        seen.add(current)
        header, _salt, record = rig.read_stored(current)
        pending.extend(entry_from_header(current, header).parents)
        refs = (record.body.inputs if isinstance(record.body, Decided) else
                (*record.body.about, *record.body.basis) if isinstance(record.body, Prediction) else ())
        pending.extend(p for ref in refs if (p := resolve(ref)) is not None)
    return seen


def raw_redelivery_scene(r, clash):
    measurer = fb.SourceMeasurer()
    observer = NativeEntryObserver(measurer)
    r.direct(worker_overrides={"measure_segment": observer})
    r.running.stop = measurer.stop
    r.sense(0, T, begin=True); r.adopt(1)
    measure, = r.requests("measure_segment")
    wid = measure.value["desc"]["work_id"]
    started, issued = next((event, issued) for event, issued in observer.posts[wid]
        if isinstance(event, fb.SegmentReport) and isinstance(event.item, fb.SegmentBoundary)
        and event.item.kind == "started")
    if clash:
        reading = started.item.reading
        started = replace(started, item=replace(started.item, reading=replace(reading,
            reading=replace(reading.reading, time_ns=reading.reading.time_ns + 1))))
    observer.contexts[wid].post(started, issued=None if clash else issued)
    if clash:
        r.until(lambda: any(p.kind == "conflict" for p in r.host.window.status().pending))
    else:
        r.host.run_until(lambda _s: True, timeout=WATCHDOG)
    return r


def test_pool1_oracle_nonuniform_replay_and_two_additions_control():
    history = (T, E, T)
    joint, mass, conditional = joint_oracle((OLD, NEW), (Q(2, 3), Q(1, 3)), history)
    assert mass == Q(25, 384)
    assert joint == {("old", "A"): 0, ("old", "B"): Q(16, 25),
                     ("new", "A"): Q(9, 50), ("new", "B"): Q(9, 50)}
    assert conditional == {"old": (Q(16, 25), (0, 1)), "new": (Q(9, 25), (Q(1, 2), Q(1, 2)))}
    _, mass, conditional = joint_oracle((OLD, NEW, THIRD), (Q(8, 15), Q(4, 15), Q(1, 5)), history)
    assert mass == Q(353, 4320)
    assert [x[0] for x in conditional.values()] == [Q(144, 353), Q(81, 353), Q(128, 353)]


@pytest.mark.parametrize("component", [OLD, CE1], ids=["cycle", "CE1"])
def test_pool1_existing_native_boot_workers_and_raw_history_control(component):
    """Executable master control for the exact helpers used by the red cases."""
    r = PoolRig(thinking=False, component=component)
    try:
        r.start()
        for i, symbol in enumerate((T, E, T)):
            r.sense(i, symbol, begin=i == 0); r.adopt(i + 1)
        r.assert_answer((component.taken, component.empty, component.taken))
        assert len(r.frame_reports()) == 3 and not r.requests("evaluation_prepare")
    finally: r.close()


def test_pool1_existing_native_thinking_target_oracle_control():
    r = PoolRig()
    try:
        r.start(); selected = r.think()
        value = r.assert_evaluation(selected, ())
        assert r.selected_model(selected) == r.model_point
    finally: r.close()


def test_pool1_law_target_information_ruler_control():
    def scalar(p): return ((p, 0), (0, p))
    first = Component("left", (Q(1), Q(0)), scalar(Q(1, 4)), scalar(Q(3, 4)), ("box", "box"), "left-law")
    second = Component("right", first.prior, scalar(Q(3, 4)), scalar(Q(1, 4)), first.targets, "right-law")
    joint, _, _ = joint_oracle((first, second), (Q(1, 2), Q(1, 2)), ())
    information, probability = information_oracle((first, second), joint)
    with localcontext() as context:
        context.prec = 80
        expected = (Decimal(2).ln() + Decimal("0.25") * Decimal("0.25").ln()
                    + Decimal("0.75") * Decimal("0.75").ln())
        assert abs(information - expected) < Decimal("1e-75")
        assert probability > Decimal("0.5")
    alias = replace(second, taken=first.taken, empty=first.empty, law=first.law)
    joint, _, _ = joint_oracle((first, alias), (Q(1, 2), Q(1, 2)), ())
    assert information_oracle((first, alias), joint) == (0, Decimal("0.5"))


@pytest.mark.parametrize("clash", [False, True], ids=["identical", "clash"])
def test_pool1_existing_native_raw_dependency_scene_control(clash):
    r = PoolRig(thinking=False)
    try:
        raw_redelivery_scene(r, clash)
        assert len(r.adoption_chain()) == 1 and len(r.frame_reports()) == 1
        assert any(p.kind == "conflict" for p in r.host.window.status().pending) is clash
    finally: r.close()


def test_pool1_public_surface_and_explicit_alpha():
    pool_api()
    param = signature(fb.FThreadHost.add_candidate).parameters["alpha"]
    assert param.default is Parameter.empty and param.kind == Parameter.KEYWORD_ONLY


def test_pool1_singleton_CE1_is_the_existing_two_observation_answer(pools):
    r = pools(thinking=False, component=CE1).start()
    r.sense(0, T, begin=True); r.adopt(1)
    r.sense(1, E); r.adopt(2)
    actual = r.assert_joint((T, E))
    assert actual.evidence_mass == Q(9, 128)
    assert actual.joint == (Q(8, 9), Q(1, 9))


@pytest.mark.parametrize("history", [(), (T,), (T, E, T)], ids=["prior", "one", "ce1-prefix"])
@pytest.mark.parametrize("thinking", [False, True], ids=["no-thinking", "thinking"])
def test_pool1_singleton_and_reread_keep_joint_mass_information_and_probabilities(pools, history, thinking):
    r = pools(thinking=thinking).start()
    if thinking:
        selected = r.think()
        r.assert_evaluation(selected, ())
    for i, symbol in enumerate(history):
        r.sense(i, symbol, begin=i == 0); r.adopt(i + 1)
        if thinking:
            selected = r.think()
            r.assert_evaluation(selected, history[:i + 1])
    actual = r.assert_joint(history)
    before, boundary = snapshot_records(r), frozenset(r.snapshot())
    assert r.belief(boundary=boundary) == actual
    assert r.pool(boundary=boundary) == r.pool()
    assert snapshot_records(r) == before  # Reading alone adds neither Decision nor observation.
    if thinking: r.assert_evaluation(selected, history)


def test_pool1_addition_is_decision_and_model_not_observation_and_alpha_is_origin_probability(pools):
    r = pools(thinking=False).start(); initial = r.pool()
    candidate = r.save_candidate(NEW)
    before = snapshot_records(r)
    added = r.add(candidate=candidate)
    pool = r.pool()
    assert added.pool == pool.point and pool.point != initial.point
    assert isinstance(r.read_stored(added.pool)[2].body, Prediction)
    assert r.read_stored(added.pool)[2].writer == Role.MODEL
    decision = r.read_stored(added.decision)[2].body
    assert isinstance(decision, Decided)
    assert r.read_stored(added.candidate)[2].body is not None
    # Addition's saved causal references must name its material and old boundary.
    refs = set(decision.inputs)
    assert refs and candidate.model in saved_closure(r, added.decision)
    assert added.candidate in saved_closure(r, added.decision)
    assert not isinstance(r.read_stored(added.decision)[2].body, Observed)
    assert not r.frame_reports() and not r.actor.calls
    r.replay(); r.assert_joint(())
    result = r.read_stored(r.belief().result)[2].body.content.as_json()
    request = r.read_stored(result["request"])[2].body.content.as_json()
    assert request["desc"]["args"]["observations"] == []
    assert added.decision in saved_closure(r, result["request"])
    assert r.expected_weights == [Q(2, 3), Q(1, 3)]
    assert_unchanged(r, before)


@pytest.mark.parametrize("add_before_history", [False, True], ids=["biased-posterior-first", "fresh-origin-first"])
def test_pool1_replay_from_origin_preserves_old_conditional_and_reweights_all_candidates(pools, add_before_history):
    r = pools(thinking=False).start(); old_boundary = None
    if add_before_history: r.add(); r.replay()
    for i, symbol in enumerate((T, E, T)):
        r.sense(i, symbol, begin=i == 0)
        r.adopt(len(r.facts(c.BELIEF_ADOPTED)) + 1)
    if not add_before_history:
        old = r.assert_joint((T, E, T)); old_boundary = frozenset(r.snapshot())
        old_pool = r.pool(); r.add(); r.replay()
        assert r.belief(boundary=old_boundary) == old and r.pool(boundary=old_boundary) == old_pool
    actual = r.assert_joint((T, E, T))
    assert actual.evidence_mass == Q(25, 384)
    r.add(THIRD, Q(1, 5)); r.replay()
    actual = r.assert_joint((T, E, T))
    assert actual.evidence_mass == Q(353, 4320)
    chain = r.adoption_chain()
    assert all(a.value["previous"] == b.cid for b, a in zip(chain, chain[1:]))


@pytest.mark.parametrize("law_differs", [False, True], ids=["same-law-alias", "different-law"])
def test_pool1_law_identity_is_part_of_target_but_candidate_alias_is_not(pools, law_differs):
    def scalar(p): return ((p, 0), (0, p))
    first = Component("old", (Q(1), Q(0)), scalar(Q(1, 4)), scalar(Q(3, 4)), ("box", "box"), "one")
    second = Component("alias", first.prior, scalar(Q(3, 4)) if law_differs else first.taken,
        scalar(Q(1, 4)) if law_differs else first.empty, first.targets, "two" if law_differs else "one")
    r = pools(component=first).start(); r.think()
    r.add(second, Q(1, 2)); r.replay()
    pool = r.pool(); laws = {m.law for m in pool.members}
    assert len(laws) == (2 if law_differs else 1)
    selected = r.think(); r.assert_joint(())
    r.assert_evaluation(selected, ())
    joint, _, _ = joint_oracle((first, second), (Q(1, 2), Q(1, 2)), ())
    info, probability = information_oracle((first, second), joint)
    assert (info > 0 and probability > Decimal("0.5")) if law_differs else (info == 0 and probability == Decimal("0.5"))


def test_pool1_identical_declaration_in_another_record_is_same_law_and_same_predictive_value(pools):
    r = pools().start(); before_selection = r.think()
    old_value = r.selected_value(before_selection)
    alias = replace(OLD, name="alias")
    candidate = r.save_candidate(alias)
    assert candidate.model != r.model_point  # Saved again, not merely the same Point.
    r.add(alias, Q(2, 5), candidate=candidate); r.replay()
    assert len({m.law for m in r.pool().members}) == 1
    r.assert_joint(())
    selected = r.think()
    new_value = r.assert_evaluation(selected, ())
    assert new_value.evaluation.candidates == old_value.evaluation.candidates
    # Compare both to the independent target oracle, not approximate equality alone.
    assert r.selected_model(selected) == r.pool().model


@pytest.mark.parametrize("alpha", [Q(0), Q(1), Q(-1, 5), Q(6, 5)])
def test_pool1_invalid_endpoint_or_outside_alpha_is_rejected_without_saved_effects(pools, alpha):
    r = pools(thinking=False).start(); candidate = r.save_candidate(NEW); r.boot()
    before = snapshot_records(r)
    with pytest.raises(fb.CandidateInputError):
        r.host.add_candidate(boot=r.boot(), candidate=candidate, alpha=alpha)
    assert snapshot_records(r) == before
    assert len(r.pool().members) == 1


@pytest.mark.parametrize("new_explains", [False, True], ids=["whole-still-zero", "recovers-old-whole-zero"])
def test_pool1_zero_evidence_is_distinct_from_a_missing_reading_and_has_no_conditional(pools, new_explains):
    impossible = replace(OLD, taken=ZERO, empty=I)
    r = pools(component=impossible, thinking=False).start()
    r.sense(0, E, begin=True); r.adopt(1)
    previous, = r.adoption_chain()
    r.sense(1, T); r.exercise_available_updates()
    r.until(lambda: any(row.outcome == "rejected" and "model_falsified" in row.reasons
                        for row in r.host.window.status().updates))
    assert [a.cid for a in r.adoption_chain()] == [previous.cid]
    second = NEW if new_explains else replace(NEW, taken=ZERO, empty=I)
    r.add(second)
    if new_explains:
        r.replay(); actual = r.assert_joint((E, T))
        zero, = [x for x in actual.candidates if x.weight == 0]
        assert zero.conditional is None and actual.joint is not None
        assert r.adoption_chain()[-1].value["previous"] == previous.cid
    else:
        r.exercise_available_updates()
        pool = r.pool()
        r.until(lambda: any(row.model == pool.model and row.outcome == "rejected"
            and "model_falsified" in row.reasons for row in r.host.window.status().updates))
        assert [a.cid for a in r.adoption_chain()] == [previous.cid]


def test_pool1_new_zero_evidence_component_has_no_conditional_and_does_not_falsify_whole(pools):
    r = pools(thinking=False).start(); r.start_last_passive(); r.complete_last_passive(T); r.adopt(1)
    impossible = replace(NEW, taken=ZERO, empty=I)
    r.add(impossible); r.replay(); actual = r.assert_joint((T,))
    zero, = [x for x in actual.candidates if x.candidate == impossible.name]
    assert zero.weight == 0 and zero.conditional is None
    assert actual.evidence_mass > 0


def test_pool1_addition_without_new_raw_record_rebuilds_once_and_next_observation_is_separate(pools):
    r = pools(thinking=False).start(); r.sense(0, T, begin=True); r.adopt(1)
    before = tuple(x.cid for x in r.frame_reports())
    added = r.add(); rebuilt = r.replay(); r.assert_joint((T,))
    assert tuple(x.cid for x in r.frame_reports()) == before
    chain = tuple(a.cid for a in r.adoption_chain())
    for _ in range(8):
        assert r.belief().adoption == rebuilt.adoption
        r.host.run_until(lambda _s: True, timeout=WATCHDOG)
    assert tuple(a.cid for a in r.adoption_chain()) == chain
    assert r.read_stored(added.decision)
    r.sense(1, E); r.adopt(len(chain) + 1); r.assert_joint((T, E))


def test_pool1_addition_during_native_source_read_and_new_raw_observation_have_separate_causes(pools):
    r = pools(thinking=False).start(); r.start_last_passive()
    assert len(r.passive.calls) == 1 and not r.frame_reports()
    added = r.add(); rebuilt = r.replay(); r.assert_joint(())
    assert not r.frame_reports()
    r.complete_last_passive(T)
    r.adopt(len(r.adoption_chain()) + 1); r.assert_joint((T,))
    assert r.adoption_chain()[-1].value["previous"] == rebuilt.adoption
    assert r.read_stored(added.decision) and len(r.frame_reports()) == 1


@pytest.mark.parametrize("stage", ["request", "response", "adoption-before_write", "adoption-ack_loss"])
def test_pool1_inflight_old_pool_request_result_and_fixed_adoption_never_rewind_current_pool(pools, stage):
    r = pools(thinking=False)
    observer = NativeEntryObserver(fb.FiniteUpdater(registry=r.registry))
    r.direct(worker_overrides={"belief_update": observer})
    r.start_last_passive(); r.complete_last_passive(T)
    q, _ = r.offered("belief_update")
    fixed = snapshot_records(r)
    gate = observer.hold(q) if stage == "request" else observer.hold_before_post(q)
    r.run_request(q, background=True); assert gate.entered.wait(WATCHDOG)
    cut = None
    try:
        if stage.startswith("adoption-"):
            cut = FixedRecordSaveCut(r, stage.removeprefix("adoption-"), contract_ref=c.BELIEF_ADOPTED)
            gate.release.set(); assert observer.wait_return(q.value["desc"]["work_id"])
            with pytest.raises(cut.Unavailable):
                r.host.run_until(lambda _s: False, timeout=WATCHDOG)
            cut.assert_pending()
        # The add port saves a Decision; it does not require advancing the failed house round.
        added = r.add(); after_add = r.pool()
        assert after_add.point == added.pool
        if cut is not None: cut.restore()
        gate.release.set(); assert observer.wait_return(q.value["desc"]["work_id"])
        r.replay(); r.assert_joint((T,))
        assert r.pool().point == added.pool
        assert_unchanged(r, fixed)
        assert r.read_stored(q.cid)[2].body.content.as_json() == q.value
    finally:
        gate.release.set()
        if cut is not None: cut.restore()


@pytest.mark.parametrize("reverse", [False, True], ids=["left-first", "right-first"])
def test_pool1_incomparable_additions_do_not_win_by_delivery_or_record_order(pools, reverse):
    r = pools(thinking=False).start(); r.boot()
    candidates = [r.save_candidate(NEW), r.save_candidate(THIRD)]
    boundary = frozenset(r.snapshot())
    if reverse: candidates.reverse()
    additions = [r.host.add_candidate(boot=r.boot(), candidate=value, alpha=Q(1, 3), boundary=boundary)
                 for value in candidates]
    assert additions[0].decision != additions[1].decision
    assert_named_error(r.pool, *(a.decision for a in additions), reason="incomparable_additions")
    assert_named_error(r.belief, *(a.decision for a in additions), reason="incomparable_additions")
    assert not r.facts(c.BELIEF_ADOPTED)


def test_pool1_missing_pool_record_names_dependency_instead_of_boot_fallback(pools, monkeypatch):
    r = pools(thinking=False).start(); added = r.add(); r.replay(); before = r.belief()
    normal = r.ledger.record
    def unavailable(point):
        if point == added.pool: raise KeyError(point)
        return normal(point)
    monkeypatch.setattr(r.ledger, "record", unavailable)
    assert_named_error(r.pool, added.pool, reason="unreadable_record")
    assert_named_error(r.belief, added.pool, reason="unreadable_record")
    monkeypatch.setattr(r.ledger, "record", normal)
    assert r.belief() == before


@pytest.mark.parametrize("phase", ["before_write", "ack_loss"])
def test_pool1_saved_addition_with_pending_replay_never_exposes_new_pool_with_old_belief(pools, phase):
    r = pools().start(); r.think(); r.start_last_passive(); r.complete_last_passive(T); r.adopt(1)
    old = r.belief(); old_requests = tuple(q.cid for q in r.requests("evaluation_prepare"))
    added = r.add(); cut = FixedRecordSaveCut(r, phase, contract_ref=c.BELIEF_ADOPTED)
    try:
        with pytest.raises(cut.Unavailable):
            r.exercise_available_updates()
        cut.assert_pending()
        assert_named_error(r.belief, added.pool, retryable=True, reason="replay_pending")
        assert tuple(q.cid for q in r.requests("evaluation_prepare")) == old_requests
        assert r.read_stored(old.adoption)
    finally: cut.restore()
    r.replay(); r.assert_joint((T,))
    selected = r.think(); value = r.assert_evaluation(selected, (T,))
    assert r.selected_model(selected) == r.pool().model


@pytest.mark.parametrize("missing", [None, "kernel", "cell", "correspondence"],
                         ids=["declared-control", "missing-operation", "missing-cell", "missing-correspondence"])
def test_pool1_old_execution_uses_new_candidate_kernel_or_names_missing_reading(pools, missing):
    r = pools().start(); r.think(); _, execution = r.enter_step()
    raw_u, old_model = execution.u, execution.model
    candidate = r.save_candidate(NEW, missing=missing)
    if missing == "correspondence":
        # K39-c: reject at addition, before any new pool/Decision is saved.
        # The candidate fixture's own Prediction was saved before this snapshot.
        before, old_pool = snapshot_records(r), r.pool()
        with pytest.raises(fb.TimeBeliefError) as error: r.add(candidate=candidate)
        assert error.value.reason == "correspondence" and candidate.id in error.value.targets
        assert snapshot_records(r) == before and r.pool() == old_pool
        r.finish_step(0, T)
        assert r.actor.calls[0].u == raw_u and r.actor.calls[0].model == old_model
        assert len(r.facts(contract("sui.fb.execution_result"))) == 1
        r.exercise_available_updates(); r.assert_joint((T,))
        return
    added = r.add(candidate=candidate); r.replay()
    adoptions_before_result = tuple(a.cid for a in r.adoption_chain())
    r.finish_step(0, T)
    assert r.actor.calls[0].u == raw_u and r.actor.calls[0].model == old_model
    results = r.facts(contract("sui.fb.execution_result")); assert len(results) == 1
    if missing is None:
        r.exercise_available_updates(); r.assert_joint((T,))
        r.think()
        _, later = r.enter_step(1)
        assert later.model == r.pool().model and later.model != old_model
        r.finish_step(1, E)
    else:
        r.exercise_available_updates()
        assert_named_error(r.belief, candidate.model)
        assert r.pool().point == added.pool
        assert tuple(a.cid for a in r.adoption_chain()) == adoptions_before_result


@pytest.mark.parametrize("new_commutes", [False, True], ids=["new-block-does-not-commute", "all-blocks-commute"])
def test_pool1_replay_rechecks_overlapping_raw_intervals_in_each_added_block(pools, new_commutes):
    first = replace(OLD, taken=HALF, empty=HALF, targets=("box", "box"))
    r = pools(component=first, overlap="serializable").start()
    r.run("measure_segment", background=True); assert r.passive.gates[0].entered.wait(WATCHDOG)
    r.think(); r.enter_step(); r.sense(0, T); r.finish_step(0, T); r.adopt(2)
    # The old block commutes. Change only the added block's PASSIVE kernel to N;
    # execution's kernel is HALF (commutes) or P (does not commute with N).
    second = replace(NEW, taken=HALF if new_commutes else P,
        empty=HALF if new_commutes else EMPTY, targets=("box", "box"))
    candidate = r.save_candidate(second)
    candidate = replace(candidate, observation_model=passive_declaration(N, ZERO))
    r.add(second, candidate=candidate)
    if new_commutes:
        r.replay()
        r.assert_joint(((HALF, N), (HALF, HALF)))
    else:
        r.exercise_available_updates()
        error = assert_named_error(r.belief, candidate.model)
        assert error.reason == "observation_order_unknown"


def test_pool1_update_thinking_and_next_execution_share_one_boundary_pool(pools):
    r = pools().start(); r.think(); r.add(); r.replay()
    r.assert_evaluation(r.think(), ())
    r.start_last_passive(); r.complete_last_passive(T); r.adopt(len(r.adoption_chain()) + 1)
    r.assert_joint((T,))
    selected = r.think(); value = r.assert_evaluation(selected, (T,))
    pool = r.pool()
    assert r.selected_model(selected) == pool.model
    _, execution = r.enter_step(); assert execution.model == pool.model
    r.finish_step(0, E)
    r.exercise_available_updates(); r.assert_joint((T, E))
    assert r.pool().point == pool.point


@pytest.mark.parametrize("clash", [False, True], ids=["identical-redelivery-control", "raw-started-conflict"])
def test_pool1_started_conflict_stays_pending_but_does_not_block_acquisition_replay(pools, clash):
    r = pools(thinking=False)
    raw_redelivery_scene(r, clash)
    before = snapshot_records(r)
    adopted_before = tuple(a.cid for a in r.adoption_chain())
    added = r.add()
    r.replay(); r.assert_joint((T,))
    assert tuple(a.cid for a in r.adoption_chain()[:-1]) == adopted_before
    assert any(p.kind == "conflict" for p in r.host.window.status().pending) is clash
    assert r.pool().point == added.pool
    assert_unchanged(r, before)


def test_pool1_initial_pool_identity_and_cached_getters_do_not_advance_the_host(pools):
    """K37-c(1), correction C: all later boot/getter calls are pure reads."""
    r = pools().start()
    assert r._boot_point is not None  # The TEST rig cached during explicit startup.
    pool = r.pool()
    member, = pool.members
    assert pool.point == r.boot()
    assert member.id == r.boot_input.declaration.perception.slot
    assert member.model == r.model_point and member.prior_weight == 1
    prior = r.belief()
    assert prior.adoption is None and prior.evidence_mass == 1
    before, launches = snapshot_records(r), tuple(r.launcher.attempts)
    for _ in range(3):
        assert r.boot() == pool.point and r.pool() == pool and r.belief() == prior
    assert snapshot_records(r) == before and tuple(r.launcher.attempts) == launches


def test_pool1_common_kernel_intersection_prunes_operations_and_policies_to_closed_references(pools):
    """K37-c(2): missing peek does not get an invented zero/identity kernel."""
    r = pools().start(); r.think()
    candidate = r.save_candidate(NEW, missing="kernel")
    r.add(candidate=candidate); r.replay(); r.assert_joint(())
    document = r.read_stored(r.pool().model)[2].body.content.as_json()["document"]
    for key in ("kernels", "operations", "policies"):
        assert {item["id"] for item in document[key]} == {"wait"}
    selected = r.think()
    value = r.selected_value(selected)
    assert r.selected_model(selected) == r.pool().model
    assert value.evaluation.candidates == ("wait",)
    assert value.choice.id == "wait" and value.choice.policy.args == {"id": "wait"}
    assert_interval(value.evaluation.q_star[0], Decimal(1))


@pytest.mark.parametrize("field", ["evidence", "available"])
def test_pool1_shared_outcome_id_with_different_metadata_is_not_addable(pools, field):
    """K37-c(2): same outcome spelling is insufficient for a common kernel."""
    r = pools(thinking=False).start(); before = r.pool()
    def edit(document):
        kernel = next(k for k in document["kernels"] if k["id"] == "peek")
        outcome = next(o for o in kernel["outcomes"] if o["id"] == "t")
        if field == "evidence": outcome[field]["value"] = read1_symbol(E)
        else: outcome[field]["computation"] = {"marker": True}
    candidate = r.save_candidate(NEW, edit_document=edit)
    with pytest.raises(fb.CandidateInputError):
        r.host.add_candidate(boot=r.boot(), candidate=candidate, alpha=Q(1, 3))
    assert r.pool() == before


def test_pool1_pool_boundary_replaces_origin_and_reader_then_keeps_them_within_pool(pools):
    """K37-c(3)(5): model/origin/CG agree; passive projection names the pool."""
    r = pools().start(); r.think()
    r.sense(0, T, begin=True); r.adopt(1); r.think()
    previous = r.adoption_chain()[-1]
    old_request = r.read_stored(previous.value["request"])[2].body.content.as_json()
    old_reader = old_request["desc"]["reader"]
    r.add(); rebuilt = r.replay(); selected = r.think()
    pool = r.pool()
    assert r.selected_model(selected) == pool.model
    origins = {x.cid for x in r.facts(ORIGIN) if x.value["model"] == pool.model}
    assert len(origins) == 1
    result = r.read_stored(rebuilt.result)[2].body.content.as_json()
    request = r.read_stored(result["request"])[2].body.content.as_json()
    reader = request["desc"]["reader"]
    assert reader != old_reader
    r.sense(1, E); r.adopt(len(r.adoption_chain()) + 1); r.assert_joint((T, E))
    last = r.adoption_chain()[-1]
    request = r.read_stored(last.value["request"])[2].body.content.as_json()
    assert request["desc"]["reader"] == reader
    uses = request["desc"]["args"]["observations"]
    assert uses
    for use in uses:
        plan = r.read_stored(use["reading"])[2].body.content.as_json()
        args = plan["projection"]["args"]
        assert set(args) == {"pool", "observation_model", "time_projection"}
        assert args["pool"] == pool.point
        assert r.read_stored(args["observation_model"])
        assert args["time_projection"] == {"contract": wire(contract("sui.f.value_only")), "args": {}}
    r.think()
    assert {x.cid for x in r.facts(ORIGIN) if x.value["model"] == pool.model} == origins


def test_pool1_latest_confirmed_belief_stays_visible_while_same_pool_adoption_write_is_pending(pools):
    """K37-c(7): unlike a new pool, this pool already has a confirmed belief."""
    r = pools(thinking=False).start()
    r.sense(0, T, begin=True); r.adopt(1)
    old = r.belief(); r.sense(1, E)
    cut = FixedRecordSaveCut(r, "before_write", contract_ref=c.BELIEF_ADOPTED)
    try:
        with pytest.raises(cut.Unavailable): r.exercise_available_updates()
        cut.assert_pending()
        assert r.belief() == old
    finally: cut.restore()
    r.until(lambda: len(r.adoption_chain()) == 2)
    actual = r.assert_joint((T, E))
    assert actual.pool == old.pool and actual.adoption != old.adoption


def test_pool1_zero_evidence_component_still_requires_its_declared_correspondence(pools):
    """K37-c(6), K39-c: Z=0 cannot excuse a missing correspondence at addition."""
    r = pools(thinking=False).start(); r.start_last_passive(); r.complete_last_passive(T); r.adopt(1)
    previous = tuple(a.cid for a in r.adoption_chain())
    impossible = replace(NEW, taken=ZERO, empty=I)
    candidate = r.save_candidate(impossible, missing="correspondence")
    before, old_pool = snapshot_records(r), r.pool()
    with pytest.raises(fb.TimeBeliefError) as error: r.add(impossible, candidate=candidate)
    assert error.value.reason == "correspondence" and candidate.id in error.value.targets
    assert snapshot_records(r) == before and r.pool() == old_pool
    assert tuple(a.cid for a in r.adoption_chain()) == previous
    r.assert_joint((T,))


def request_for_belief(r, belief):
    result = r.read_stored(belief.result)[2].body.content.as_json()
    request, = [q for q in r.requests("belief_update") if q.cid == result["request"]]
    return request


def public_rounds(r, *, run_generation=False, count=24):
    """Exercise public progress, not a time-based absence assertion.

    No native update is invoked here: replay can intentionally remain pending.
    Available native Wg bodies may run so a missing gate is not hidden by a
    test that leaves a required generation callback uncalled.
    """
    for _ in range(count):
        r.host.run_until(lambda _state: True, timeout=WATCHDOG)
        if run_generation:
            offers = [(q, body) for q in r.requests("candidate_generation")
                for wid, body in r.launcher.attempts
                if wid == q.value["desc"]["work_id"] and wid not in r.executed]
            for q, body in offers: r.invoke(q, body)
    assert r.host.halted is None


def test_pool1_two_additions_without_intermediate_replay_use_the_actual_work_reader(pools):
    """K37-d R1: intermediate pool model must reach the real bounded reader."""
    r = pools(thinking=False)
    updater = NativeEntryObserver(fb.FiniteUpdater(registry=r.registry))
    r.direct(worker_overrides={"belief_update": updater})
    for i, symbol in enumerate((T, E, T)):
        r.sense(i, symbol, begin=i == 0); r.adopt(i + 1)
    old_adoptions = tuple(a.cid for a in r.adoption_chain())
    old_requests = tuple(q.cid for q in r.requests("belief_update"))
    first = r.add(); middle = r.pool()
    second = r.add(THIRD, Q(1, 5))
    assert middle.point == first.pool and second.pool != first.pool
    assert tuple(a.cid for a in r.adoption_chain()) == old_adoptions
    assert tuple(q.cid for q in r.requests("belief_update")) == old_requests
    actual = r.replay(); r.assert_joint((T, E, T))
    assert actual.evidence_mass == Q(353, 4320)
    q = request_for_belief(r, actual)
    ctx = updater.contexts[q.value["desc"]["work_id"]]
    # Observe the production port's reader, without replacing/extending it.
    reader = ctx.reader()
    assert reader.record(middle.model) == r.read_stored(middle.model)[2]
    assert reader.record(first.pool) == r.read_stored(first.pool)[2]
    assert reader.record(second.pool) == r.read_stored(second.pool)[2]


def declare_second_idle_route(r):
    """A legal distinct bootstrap slot, with no allocated source work to run."""
    declaration = r.boot_input.declaration
    main, = declaration.routes
    allocation = main.value.allocation
    allocation = replace(allocation, slot="other-source-allocation", value=replace(
        allocation.value, amount=fb.QuantityValue(contract=c.SEATS, value=0)))
    other = replace(main, slot="other-route", value=replace(main.value,
        config=replace(main.value.config, route_epoch="other-route-epoch"),
        process_slot="other-sensing", allocation=allocation))
    r.boot_input = replace(r.boot_input, declaration=replace(declaration, routes=(main, other)))


@pytest.mark.parametrize("route_slot", ["route", "other-route", "absent-route"],
                         ids=["same-route-control", "another-declared-route", "undeclared-route"])
def test_pool1_candidate_observation_model_must_name_the_observed_route(pools, route_slot):
    """K37-d R2: wrong route is missing meaning, not zero likelihood."""
    r = pools(thinking=False); declare_second_idle_route(r); r.start()
    r.start_last_passive(); r.complete_last_passive(T); r.adopt(1); r.assert_joint((T,))
    previous = tuple(a.cid for a in r.adoption_chain())
    candidate = r.save_candidate(NEW)
    candidate = replace(candidate, observation_model=replace(candidate.observation_model,
        route_slot=route_slot))
    r.add(candidate=candidate)
    if route_slot == "route":
        r.replay(); r.assert_joint((T,))
    else:
        r.exercise_available_updates()
        error = assert_named_error(r.belief)
        assert error.targets and set(error.targets) <= set(r.snapshot())
        assert error.reason != "model_falsified"
        assert tuple(a.cid for a in r.adoption_chain()) == previous


@pytest.mark.parametrize("origin,clash", [("added", True), ("initial", True), ("added", False)],
                         ids=["new-generator-clash", "old-generator-clash-control", "same-report-control"])
def test_pool1_candidate_reuse_checks_its_own_generator_after_pool_change(pools, origin, clash):
    """K37-d R3: Qgen, Wg and CG refer to one generation, not the boot Wg."""
    r = pools().thinking_seats(1, execution=False)
    generator = NativeEntryObserver(fb.CandidateGenerator())
    r.direct(worker_overrides={"candidate_generation": generator})
    r.think()
    initial, = r.requests("candidate_generation")
    r.add(); r.replay(); r.think()
    pool = r.pool()
    generation, = [q for q in r.requests("candidate_generation")
                   if q.value["desc"]["args"]["model"] == pool.model]
    assert generation.cid != initial.cid
    cg, = [cg for cg in r.facts(fc.CANDIDATE_DECLARATION) if cg.value["model"] == pool.model]
    assert generation.record_id in r.read_stored(cg.cid)[2].body.basis
    source = generation if origin == "added" else initial
    generator.late_terminal(source, clash=clash)
    wid = source.value["desc"]["work_id"]
    r.until(lambda: len([p for p in r.facts(c.WORK_REPORT) if p.value["work"] == wid]) == 2)
    if clash:
        r.until(lambda: any(p.kind == "conflict" for p in r.host.window.status().pending))
    activities = {x.activity for x in r.host.window.status().evaluations}
    prepares = {q.cid for q in r.requests("evaluation_prepare")}
    r.start_last_passive(); r.complete_last_passive(T); r.adopt(len(r.adoption_chain()) + 1)
    if origin == "added" and clash:
        public_rounds(r)
        assert {x.activity for x in r.host.window.status().evaluations} == activities
        assert {q.cid for q in r.requests("evaluation_prepare")} == prepares
    else:
        selected = r.think(); r.assert_evaluation(selected, (T,))
        fresh = [q for q in r.requests("evaluation_prepare") if q.cid not in prepares]
        assert fresh and all(q.value["desc"]["args"]["input"]["candidates"] == cg.cid for q in fresh)
    assert len(r.requests("candidate_generation")) == 2


class CandidateReadFaultPort(ObservedEntryPort):
    def read(self, point):
        if point == self.work.desc.args.model and point in self.owner.fail_models:
            self.owner.failed_reads.append((self.work.desc.work_id, point))
            raise OSError("test candidate model read failure")
        return super().read(point)


class CandidateReadFaultObserver(NativeEntryObserver):
    """Native CandidateGenerator owns its terminal; only its read port faults."""
    def __init__(self):
        super().__init__(fb.CandidateGenerator())
        self.fail_models, self.failed_reads = set(), []

    def run(self, work, ctx):
        wid = work.desc.work_id
        self.contexts[wid] = ctx
        done = self.returned.setdefault(wid, Event())
        try: return self.worker.run(work, CandidateReadFaultPort(self, work, ctx))
        finally: done.set()


@pytest.mark.parametrize("fail", [False, True], ids=["successful-generation-control", "failed-generation"])
def test_pool1_failed_generation_after_pool_change_does_not_readmit_the_same_material(pools, fail):
    """K37-d R4: a terminal consumes admission; no retry count is introduced."""
    r = pools().thinking_seats(1, execution=False)
    generator = CandidateReadFaultObserver()
    r.direct(worker_overrides={"candidate_generation": generator}); r.think()
    r.add(); r.replay(); pool = r.pool()
    if fail: generator.fail_models.add(pool.model)
    q = r.request_where("candidate_generation", lambda q: q.value["desc"]["args"]["model"] == pool.model)
    wid = q.value["desc"]["work_id"]
    row, = [x for x in r.host.window.status().evaluations if wid in x.residual]
    # Capture BEFORE the terminal: an immediate erroneous replacement activity
    # must not become part of the expected baseline while waiting for failure.
    activities = {x.activity for x in r.host.window.status().evaluations}
    requests = {q.cid for q in r.requests("candidate_generation")}
    adoptions = tuple(a.cid for a in r.adoption_chain())
    r.run_request(q)
    if fail:
        assert generator.failed_reads == [(wid, pool.model)]
        terminal, = [e for e, _issued in generator.posts[wid] if isinstance(e, fb.WorkFinished)]
        assert isinstance(terminal.outcome, fb.WorkFailure)
        assert terminal.outcome.failure.failure_kind == "execution_error"
        assert terminal.outcome.failure.content["error_type"] == "OSError"
        r.until(lambda: any(x.activity == row.activity and x.outcome == "failure" and not x.counted
                            for x in r.host.window.status().evaluations))
    else:
        r.assert_evaluation(r.think(), ())
        r.until(lambda: any(x.activity == row.activity and not x.counted
                            for x in r.host.window.status().evaluations))
    assert {x.activity for x in r.host.window.status().evaluations} == activities
    assert {q.cid for q in r.requests("candidate_generation")} == requests
    public_rounds(r)
    assert {x.activity for x in r.host.window.status().evaluations} == activities
    assert {q.cid for q in r.requests("candidate_generation")} == requests
    assert tuple(a.cid for a in r.adoption_chain()) == adoptions


def direct_pool_update(r, q, value=None):
    """U-only public call, never a host request/Frame injection.

    R1 deliberately does NOT use this snapshot helper. Here both original and
    malformed Q* read the same complete saved test records; declared input_points
    still bound U's permitted dependencies as in the existing U contrasts.
    """
    cid = q.cid if value is None else belief1_clone(r, q, value)
    records = {p: r.read_stored(p)[2] for p in r.snapshot()}
    return u2.compute_finite_update(cid, reader=BeliefSnapshotReader(records),
                                    registry=r.registry, evidence=None)


def boundary_update_scene(pools):
    r = pools(thinking=False).start()
    r.sense(0, T, begin=True); r.adopt(1)
    r.sense(1, E); r.adopt(2)
    before = r.belief()
    r.add(); r.replay()
    current = r.belief()
    return r, before, current, request_for_belief(r, current)


def test_pool1_U_pool_boundary_requires_the_previous_model_in_its_ancestry(pools):
    """K37-d 08: real descendant prior, same raw prefix, not a made-up A*."""
    r, before, middle, q = boundary_update_scene(pools)
    middle_pool = r.pool()
    r.add(THIRD, Q(1, 5)); r.replay(); future = r.belief()
    assert r.pool().model not in saved_closure(r, middle_pool.point)
    assert len(r.frame_reports()) == 2  # All three priors use precisely T,E.
    # Both contrasts declare the same additional real records. Only prior differs.
    value = deepcopy(q.value)
    points = set(r.snapshot())
    value["desc"]["input_points"] = sorted(set(value["desc"]["input_points"]) | points)
    value["desc"]["numerical_view"]["boundary"] = sorted(
        set(value["desc"]["numerical_view"]["boundary"]) | points)
    assert value["desc"]["args"]["prior"] == before.adoption
    normal = direct_pool_update(r, q, value)
    expected, mass, _ = joint_oracle((OLD, NEW), (Q(2, 3), Q(1, 3)), (T, E))
    assert isinstance(normal, u2.IssuedUpdate)
    names = {m.id: "old" if m.model == r.model_point else m.id for m in middle_pool.members}
    expected_joint = tuple(expected[(names[s.candidate], s.state)] for s in middle_pool.states)
    assert wire(normal.result) == {"joint": wire(expected_joint), "evidence_mass": wire(mass)}
    value["desc"]["args"]["prior"] = future.adoption
    result = direct_pool_update(r, q, value)
    assert isinstance(result, u2.Rejected) and result.issues
    assert all(issue.code != "model_falsified" for issue in result.issues)
    assert r.belief() == future and middle.adoption != future.adoption


@pytest.mark.parametrize("defect", ["omit-prefix", "reverse-prefix"])
def test_pool1_U_pool_replay_requires_the_same_raw_prefix_in_the_same_order(pools, defect):
    """K37-d 09: same valid pool/prior/records; only observations is damaged."""
    r, before, current, q = boundary_update_scene(pools)
    normal = direct_pool_update(r, q)
    assert isinstance(normal, u2.IssuedUpdate)
    value = deepcopy(q.value)
    uses = value["desc"]["args"]["observations"]
    assert len(uses) == 2 and value["desc"]["args"]["prior"] == before.adoption
    value["desc"]["args"]["observations"] = [] if defect == "omit-prefix" else list(reversed(uses))
    result = direct_pool_update(r, q, value)
    assert isinstance(result, u2.Rejected) and result.issues
    assert all(issue.code != "model_falsified" for issue in result.issues)
    assert r.belief() == current


def test_pool1_thinking_waits_for_the_new_pool_adoption_with_a_free_thinking_seat(pools):
    """K37-d 12: delay Wu at launch, not an I/O abort that stops the house."""
    r = pools().thinking_seats(1, execution=False).start(); r.think()
    r.start_last_passive(); r.complete_last_passive(T); r.adopt(1); r.think()
    r.until(lambda: not any(x.counted for x in r.host.window.status().evaluations))
    old = r.belief()
    activities = {x.activity for x in r.host.window.status().evaluations}
    prepares = {q.cid for q in r.requests("evaluation_prepare")}
    launch, blocked = r.launcher.launch, []
    def postpone_update(wid, body):
        if any(q.value["desc"]["work_id"] == wid for q in r.requests("belief_update")):
            blocked.append(wid); return "not_started"
        return launch(wid, body)
    r.launcher.launch = postpone_update
    try:
        r.add(); pool = r.pool()
        public_rounds(r, run_generation=True)
        assert blocked  # A real replay job is waiting, while other house work can progress.
        assert_named_error(r.belief, pool.point, reason="replay_pending", retryable=True)
        assert {q.cid for q in r.requests("evaluation_prepare")} == prepares
        assert not any(x.activity not in activities and x.root_point == old.adoption
                       for x in r.host.window.status().evaluations)
    finally: r.launcher.launch = launch
    rebuilt = r.replay()
    selected = r.think(); r.assert_evaluation(selected, (T,))
    assert rebuilt.adoption != old.adoption and r.selected_model(selected) == pool.model


def test_pool1_unconsumed_old_adoption_waits_for_replay_when_the_thinking_seat_opens(pools):
    """K37-d12/request109: the old A1 is available but has NOT been handed off.

    Keep the actual initial Ee body inside its post-return barrier. Its initial
    selection is already saved, but residual occupancy still holds the only
    thinking seat. This avoids relying on processing an old selection after the
    pool change. No storage fault aborts the house while replay is postponed.
    """
    r = pools().thinking_seats(1, execution=False)
    evaluator = NativeEntryObserver(fb.Evaluator())
    r.direct(worker_overrides={"evaluation": evaluator})
    r.run("candidate_generation")
    first, _ = r.offered("evaluation_prepare")
    r.run_request(first)
    r.run_request(r.draw_for(first))
    evaluation = r.evaluation_for(first)
    wid = evaluation.value["desc"]["work_id"]
    gate = evaluator.hold_post(evaluation, timeout=3 * WATCHDOG)
    launch, blocked = r.launcher.launch, []
    try:
        r.run_request(evaluation, background=True)
        assert gate.entered.wait(WATCHDOG)
        r.until(lambda: len(r.facts(c.SELECTION)) == 1)
        context = first.value["desc"]["args"]["input"]["context"]
        initial, = [x for x in r.host.window.status().evaluations if x.context == context]
        assert initial.root == "prior" and initial.root_point is None
        assert initial.counted and wid in initial.residual

        r.start_last_passive(); r.complete_last_passive(T); r.adopt(1)
        a1, = r.adoption_chain()
        material, = r.host.window.status().thinking_materials
        assert material.latest == a1.cid and material.unevaluated
        assert material.handed != a1.cid
        assert not any(x.root_point == a1.cid for x in r.host.window.status().evaluations)
        assert any(x.activity == initial.activity and x.counted and wid in x.residual
                   for x in r.host.window.status().evaluations)
        prepares = {q.cid for q in r.requests("evaluation_prepare")}
        assert prepares == {first.cid}

        def postpone_replay(work_id, body):
            if any(q.value["desc"]["work_id"] == work_id for q in r.requests("belief_update")):
                blocked.append(work_id); return "not_started"
            return launch(work_id, body)
        r.launcher.launch = postpone_replay
        r.add(); pool = r.pool()
        public_rounds(r, run_generation=True)
        assert blocked
        assert_named_error(r.belief, pool.point, reason="replay_pending", retryable=True)

        gate.release.set()
        assert evaluator.wait_return(wid)
        r.until(lambda: any(x.activity == initial.activity and not x.counted
                            for x in r.host.window.status().evaluations))
        public_rounds(r, run_generation=True)
        assert {q.cid for q in r.requests("evaluation_prepare")} == prepares
        assert not any(x.root_point == a1.cid for x in r.host.window.status().evaluations)
        assert [a.cid for a in r.adoption_chain()] == [a1.cid]
        assert_named_error(r.belief, pool.point, reason="replay_pending", retryable=True)
    finally:
        gate.release.set()
        r.launcher.launch = launch

    rebuilt = r.replay()
    assert rebuilt.adoption != a1.cid
    selected = r.think(); r.assert_evaluation(selected, (T,))
    assert r.selected_model(selected) == pool.model
    fresh, = [q for q in r.requests("evaluation_prepare") if q.cid not in prepares]
    fresh_context = fresh.value["desc"]["args"]["input"]["context"]
    activity, = [x for x in r.host.window.status().evaluations if x.context == fresh_context]
    assert activity.root == "adopted" and activity.root_point == rebuilt.adoption
    assert not any(x.root_point == a1.cid for x in r.host.window.status().evaluations)

