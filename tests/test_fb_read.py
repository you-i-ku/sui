"""K26 / K26-a / K26-b / K26-c / K26-d / K26-e, F-b v0.93 :3530-3539.

K26-a resolves the nine API proposals: typed observation_models on Boot /2,
separate Prediction/MODEL records, and a reader taking that model's Point.
Existing F-a kernels/cells are values, not manufactured FiniteObservation handles.

K26-b fixes provenance as origin/declared_at/value and the Prediction target.
The saved-model test checks all of it against independently specified Boot slots.
Boot /2 construction is shared with skeleton; no local factory patch is needed.

All acquisition Frames come from the real public acquire(), called by a TEST
worker script. This does not count as production SourceMeasurer repetition.
Negative fixtures add public worker reports or remove records from the reader's
scope; they do not edit production code or fabricate a successful acquisition.
The product-of-paths oracle below is independent of production F arithmetic.
"""

from copy import deepcopy
from dataclasses import fields, replace
from fractions import Fraction as Q
from itertools import product
from types import SimpleNamespace

import pytest

from sui import f, fb, fb_contracts as c
from sui.ids import Ref, RefKind
from test_fb_skeleton import contract, point, slot, source
from test_fb_stage1 import RealRig, entry_from_header, wire
from sui.clock import FakeClock
from sui.records import Decided, Observed, Payload, Prediction, Role, WriterNotAllowed
from test_fb_measure import (
    AcquireRig, RAW, ROUTE, acquire1_api, acquire1_item,
    acquire1_started, acquire1_expected_frame,
)


T, E, U, M = "taken", "empty", "unavailable_called", "unavailable_missing"
SYMBOLS = (T, E, U, M)
MODEL = contract("sui.fb.acquisition_observation_model")
PROJECTION = contract("sui.fb.acquisition_result_projection")
CONTROL = contract("sui.fb.acquisition_control_table")
INDEPENDENCE = contract("sui.fb.state_independent_control_selection")
TIME = contract("sui.f.value_only")
MODEL_SLOT = "acquisition-model"


def read1_api():
    """Resolve K26-a names/fields per test; never fail module collection."""
    missing = [name for owner, names in (
        (fb, ("read_acquisition_sequence", "AcquisitionReadResult", "AcquisitionReadItem",
              "AcquisitionObservationModel", "AcquisitionControl")),
        (c, ("ACQUISITION_RESULT_PROJECTION", "ACQUISITION_OBSERVATION_MODEL")),
    ) for name in names if not hasattr(owner, name)]
    if "observation_models" not in {field.name for field in fields(fb.BootDeclaration)}:
        missing.append("BootDeclaration.observation_models")
    if c.BOOT_DECLARATION != replace(contract("sui.fb.boot_declaration"), version="2"):
        missing.append("BOOT_DECLARATION/2")
    assert not missing, "K26-a public names/fields missing: " + ", ".join(missing)
    assert c.ACQUISITION_RESULT_PROJECTION == PROJECTION
    assert c.ACQUISITION_OBSERVATION_MODEL == MODEL
    return SimpleNamespace(read=fb.read_acquisition_sequence,
        Result=fb.AcquisitionReadResult, Item=fb.AcquisitionReadItem,
        Model=fb.AcquisitionObservationModel, Control=fb.AcquisitionControl)


def read1_symbol(symbol):
    return {"result": "unavailable" if symbol in (U, M) else symbol,
            "source_called": symbol != M}


def read1_model(matrices, *, states=("H", "L"), schedule=("a",) * 4, groups=None, elapsed=None):
    """matrices[control][outcome] uses arrival ROW / departure COLUMN (public F type)."""
    api = read1_api()
    groups = groups or {symbol: (symbol,) for symbol in SYMBOLS}
    reverse = {outcome: symbol for symbol, outcomes in groups.items() for outcome in outcomes}
    kernels, cells = {}, {}
    for control, outcomes in matrices.items():
        assert all(sum((Q(matrix[row][col]) for matrix in outcomes.values()
                       for row in range(len(states))), Q(0)) == 1 for col in range(len(states)))
        kernels[control] = f.FiniteKernel(id=control, outcomes=tuple(
            f.FiniteOutcome(id=name, elapsed_ns=(elapsed or {}).get(name, 0),
                evidence=f.EvidenceEmission(slot="acquisition", kind="measurement",
                    value=read1_symbol(reverse[name]), measurement_contract=c.ACQUISITION_RESULT_SAMPLING),
                available=f.AvailabilityChange(reveal=(), computation=None), completion=True,
                matrix=tuple(tuple(Q(x) for x in row) for row in matrix))
            for name, matrix in outcomes.items()))
        cells[control] = tuple(f.ObservationCell(id=symbol,
            observation=f.ObservationValue(kind="measurement", value=read1_symbol(symbol)),
            outcomes=tuple(names)) for symbol, names in groups.items())
    controls = tuple(matrices)
    uniform = tuple(Q(1, len(controls)) for _ in controls)
    declaration = api.Model(route_slot="route", states=tuple(states),
        controls=tuple(api.Control(id=name, kernel=kernels[name], cells=cells[name]) for name in controls),
        control_rule=fb.MethodCall(contract=CONTROL, args={"schedule": [[name] for name in schedule]}),
        independence=fb.MethodCall(contract=INDEPENDENCE,
            args={"weights_by_initial_state": [wire(uniform) for _ in states]}),
        projection=PROJECTION, time_projection=TIME)
    return SimpleNamespace(states=tuple(states), kernels=kernels, cells=cells, declaration=declaration)


def read1_static(weights=None, *, controls=("a",), schedule=("a",) * 4):
    weights = weights or {T: (Q(1, 2), Q(1, 4)), E: (Q(1, 4), Q(1, 4)),
                          U: (Q(1, 8), Q(1, 8)), M: (Q(1, 8), Q(3, 8))}
    matrices = {name: {symbol: ((p[0], 0), (0, p[1])) for symbol, p in weights.items()}
                for name in controls}
    return read1_model(matrices, schedule=schedule)


def read1_branching():
    # T has two indistinguishable outcomes; both also move the hidden state.
    z = ((0, 0), (0, 0))
    return read1_model({"a": {
        "T0": ((Q(1, 4), Q(1, 8)), (0, 0)),
        "T1": ((0, 0), (Q(1, 2), Q(1, 8))),
        E: ((Q(1, 4), 0), (0, Q(3, 4))), U: z, M: z,
    }}, groups={T: ("T0", "T1"), E: (E,), U: (U,), M: (M,)})


def read1_quiet():
    # H: P(box size 0,1,2)=(1/4,1/4,1/2); L=(1/2,1/4,1/4).
    # After the first probe only the remaining queue size q0/q1 is needed.
    states = ("H", "L", "q0", "q1")
    z = [[Q(0) for _ in states] for _ in states]
    taken, empty = deepcopy(z), deepcopy(z)
    taken[2][0], taken[3][0] = Q(1, 4), Q(1, 2)
    taken[2][1], taken[3][1] = Q(1, 4), Q(1, 4)
    empty[2][0], empty[2][1] = Q(1, 4), Q(1, 2)
    empty[2][2], taken[2][3] = Q(1), Q(1)
    return read1_model({"a": {T: taken, E: empty, U: z, M: z}}, states=states)


def read1_enumerate(model, symbols, controls):
    """Sum every terminal state AND every outcome path, not a matrix-product clone."""
    assert len(symbols) == len(controls)
    choices = []
    for control, symbol in zip(controls, symbols):
        cell, = (cell for cell in model.cells[control] if cell.id == symbol)
        choices.append(tuple(out for out in model.kernels[control].outcomes if out.id in cell.outcomes))
    answer = []
    for initial in range(len(model.states)):
        mass = Q(0)
        for states in product(range(len(model.states)), repeat=len(symbols)):
            for outcomes in product(*choices):
                term, previous = Q(1), initial
                for arrival, outcome in zip(states, outcomes):
                    term *= outcome.matrix[arrival][previous]
                    previous = arrival
                mass += term
        answer.append(mass)
    return tuple(answer)


def read1_posterior(prior, likelihood):
    joint = tuple(p * l for p, l in zip(prior, likelihood))
    total = sum(joint, Q(0))
    assert total > 0
    return tuple(x / total for x in joint)


@pytest.fixture
def make_read1():
    rigs = []

    def make(model, symbols, *, times=None, advance=0, data=RAW, reason="external failure",
             declaration=True, initial=True, extra_models=(), second_route_epoch=None):
        read1_api()
        symbols = tuple(symbols)
        assert M not in symbols or all(x == M for x in symbols)
        times = tuple(times or (100 + i * 100 for i in range(len(symbols))))
        assert len(times) == len(symbols) and list(times) == sorted(times)

        def script(rig, work, ctx):
            acquire1_started(rig, work, ctx)
            acquired_items = []
            for symbol, after in zip(symbols, times):
                rig.clock.set(after - (advance if symbol != M else 0))
                if symbol == T:
                    acquired_items.append(replace(acquire1_item(api), data=data))
                rig.source.items = tuple(acquired_items)
                rig.source.mode = "missing" if symbol == M else "raises" if symbol == U else "taken"
                a = ctx.acquire()  # TEST script, not production repeated acquisition.
                assert a.outcome == read1_symbol(symbol)["result"]
            assert rig.release.wait(30)

        api = acquire1_api()
        rig = AcquireRig(api, mode="missing" if M in symbols else "taken",
                         script=script, tick=0, advance=advance,
                         segments=1 if second_route_epoch is None else 2,
                         second_route_epoch=ROUTE if second_route_epoch is None else second_route_epoch)
        rigs.append(rig)
        child_before = rig.read_stored(rig.model_point)
        declared_models = () if not declaration else (
            slot(MODEL_SLOT, c.ACQUISITION_OBSERVATION_MODEL, model.declaration),
            *(slot(f"{MODEL_SLOT}-{i}", c.ACQUISITION_OBSERVATION_MODEL, extra.declaration)
              for i, extra in enumerate(extra_models, 2)))
        rig.boot_input = replace(rig.boot_input, declaration=replace(rig.boot_input.declaration,
            initial=rig.boot_input.declaration.initial if initial else None, observation_models=declared_models))
        # The imported test rig posted its default Boot but has not run it.
        # Construct our public host with the declared Boot; no private queue edit.
        rig.host = fb.FThreadHost(ledger=rig.ledger, clock=rig.clock, workers=rig.workers,
            registry=rig.registry, launcher=rig.launcher,
            sources=None if M in symbols else {ROUTE: rig.source})
        read_source = rig.source.read

        def external_read(cursor):
            try:
                return read_source(cursor)
            except OSError:
                raise OSError(reason) from None

        rig.source.read = external_read
        rig.host.post(fb.ClockDeclared(declaration=replace(source(), run=rig.clock.run,
            measurement=contract("sui.f.simulated_clock"))))
        rig.host.post(rig.boot_input)
        rig.until(lambda: bool(rig.facts(c.BOOT_DECLARATION)) and len(rig.facts(MODEL)) == len(declared_models))
        if symbols:
            rig.launch("measure_segment")
            rig.wait_returns(len(symbols))
        calls = tuple(sorted(rig.calls, key=lambda call: call.sequence))
        frames, raws = [], []
        cursor = 0
        for seq, (call, symbol, after) in enumerate(zip(calls, symbols, times)):
            raw, (_, frame) = rig.saved_pair(call)
            frames.append(frame)
            raws.append(raw[1] if raw else None)
            assert call.sequence == seq and call.acquired.cursor == cursor
            assert call.acquired.after.reading.time_ns == frame.received_ns == after
            assert frame.value["item"]["value"]["value"]["value"]["source_called"] is (symbol != M)
            cursor += symbol == T
        boot, = rig.facts(c.BOOT_DECLARATION)
        assert boot.contract == replace(contract("sui.fb.boot_declaration"), version="2")
        assert boot.value["observation_models"] == wire(declared_models)
        assert boot.value["environment"] == wire(rig.boot_input.declaration.environment)
        models = tuple(rig.facts(c.ACQUISITION_OBSERVATION_MODEL))
        rig.no_belief_update()
        return SimpleNamespace(rig=rig, model=model, calls=calls, frames=tuple(frames), raws=tuple(raws),
            symbols=symbols, times=times, boot=boot, models=models,
            model_record=models[0] if len(models) == 1 else None,
            declared_models=declared_models, child_before=child_before)

    yield make
    for rig in reversed(rigs):
        rig.close()


def read1_read(scene, *, records=None, through=None, run=None, epoch=ROUTE):
    api = read1_api()
    result = api.read(scene.rig.records() if records is None else records,
        model=scene.model_record.cid if scene.model_record is not None else point("undeclared-acquisition-model"),
        run=scene.rig.clock.run if run is None else run,
        route_epoch=epoch, through_seq=len(scene.calls) - 1 if through is None else through)
    assert isinstance(result, api.Result)
    return result


def read1_ok(result, scene, expected, *, kind="read", length=None):
    assert result.kind == kind and result.reason is None
    assert result.initial_states == scene.model.states
    assert result.likelihood == tuple(map(Q, expected))
    assert len(result.observations) == (len(scene.calls) if length is None else length)


def read1_unreadable(result, reason):
    assert result.kind == "unreadable" and result.reason == reason
    assert result.likelihood is None  # No invented empty/unavailable probability.


def read1_extra_frame(scene, seq=0, *, change=None):
    call = scene.calls[seq]
    frame = acquire1_expected_frame(scene.rig, call, scene.raws[seq])
    frame = change(frame) if change is not None else frame
    event = fb.SegmentReport(segment=call.work.request, item_slot=f"reader-extra:{seq}", item=frame)
    call.port.post(event)
    scene.rig.until(lambda: any(r.value == wire(event) for r in scene.rig.reports("frame")))
    extra, = (r for r in scene.rig.reports("frame") if r.value == wire(event))
    return extra


def test_read1_projection_contract_has_a_separate_public_entry():
    """:4022-4027: new K26 entry, not a fabricated F-a FiniteObservation."""
    api = read1_api()
    assert callable(api.read) and c.ACQUISITION_RESULT_PROJECTION == PROJECTION


def test_read1_typed_boot_models_and_version_match_K26a():
    """K26-a(a)(c): no bootstrap/kernel_contract fields on the typed model value."""
    api = read1_api()
    assert {field.name for field in fields(api.Model)} == {
        "route_slot", "states", "controls", "control_rule", "independence", "projection", "time_projection"}
    assert {field.name for field in fields(api.Control)} == {"id", "kernel", "cells"}
    assert "observation_models" in {field.name for field in fields(fb.BootDeclaration)}
    assert c.BOOT_DECLARATION == replace(contract("sui.fb.boot_declaration"), version="2")


@pytest.mark.parametrize("initial", [False, True], ids=["initial-none", "initial-present"])
def test_read1_boot_saves_each_slotted_model_as_an_independent_prediction(make_read1, initial):
    """K26-a(a): two equal values in distinct Boot slots still yield two MODEL records.

    about/basis resolve to the saved Boot via its Record.id, as existing
    Prediction contracts do. New predictions never become causal parents.
    K26-b(a) fixes target and all three saved provenance/value fields.
    """
    model = read1_static()
    scene = make_read1(model, (), initial=initial, extra_models=(model,))
    assert (scene.rig.boot_input.declaration.initial is not None) == initial
    assert tuple(s.slot for s in scene.declared_models) == (MODEL_SLOT, f"{MODEL_SLOT}-2")
    assert all(s.contract == MODEL and s.value == model.declaration for s in scene.declared_models)
    assert len(scene.models) == len({m.cid for m in scene.models}) == len({m.record_id for m in scene.models}) == 2
    assert scene.boot.contract == replace(contract("sui.fb.boot_declaration"), version="2")
    assert scene.boot.value["observation_models"] == wire(scene.declared_models)
    by_slot = {saved.value["declared_at"]["slot"]: saved for saved in scene.models}
    assert set(by_slot) == {declared.slot for declared in scene.declared_models}
    declared_values = {item["slot"]: item["declaration"]["value"]
                       for item in scene.boot.value["observation_models"]}
    for declared in scene.declared_models:
        expected_value = wire(declared.value)
        assert expected_value == declared_values[declared.slot]
        assert by_slot[declared.slot].value == {
            "origin": "bootstrap",
            "declared_at": wire(fb.BootSlot(declaration=scene.boot.cid, slot=declared.slot)),
            "value": expected_value,
        }
    for saved in scene.models:
        record = scene.rig.read_stored(saved.cid)[2]
        assert saved.cid != scene.boot.cid and isinstance(record.body, Prediction)
        assert record.writer == Role.MODEL and record.id.kind == RefKind.PREDICTION
        assert record.body.contract == MODEL
        assert record.body.target == "acquisition_observation_model"
        assert record.body.about == (scene.boot.record_id,)
        assert record.body.basis == (scene.boot.record_id,)
    predictions = {m.cid for m in scene.models}
    for cid, header in scene.rig.entry_store.load():
        assert not predictions.intersection(entry_from_header(cid, header).parents)
    assert scene.rig.read_stored(scene.rig.model_point) == scene.child_before
    scene.rig.no_belief_update()


def test_read1_saving_a_model_without_initial_is_neither_acquisition_nor_belief_adoption(make_read1):
    """K26-a(a): model declaration is independent of initial/derivation and is not an observation."""
    scene = make_read1(read1_static(), (), initial=False)
    assert scene.rig.boot_input.declaration.initial is None
    assert len(scene.models) == 1 and scene.model_record.cid != scene.boot.cid
    assert scene.rig.source.calls == [] and scene.rig.calls == [] and scene.rig.workers.entries == []
    assert not scene.rig.facts(c.RECEIVED) and not scene.rig.reports("frame")
    assert not scene.rig.requests("candidate_generation")
    assert scene.rig.read_stored(scene.rig.model_point) == scene.child_before
    scene.rig.no_belief_update()


@pytest.mark.parametrize("symbol", SYMBOLS)
def test_read1_four_legal_results_keep_source_called_and_raw_identity(make_read1, symbol):
    """(a), :4052/:4082: unavailable_called and unavailable_missing are different observations."""
    model = read1_static()
    scene = make_read1(model, (symbol,))
    expected = {T: (Q(1, 2), Q(1, 4)), E: (Q(1, 4), Q(1, 4)),
                U: (Q(1, 8), Q(1, 8)), M: (Q(1, 8), Q(3, 8))}[symbol]
    result = read1_read(scene)
    read1_ok(result, scene, expected)
    observation, = result.observations
    assert isinstance(observation, read1_api().Item)
    assert (observation.sample_seq, observation.cursor, observation.result, observation.source_called) == (
        0, 0, read1_symbol(symbol)["result"], symbol != M)
    assert observation.measurement_id == acquire1_expected_frame(scene.rig, scene.calls[0], scene.raws[0]).measurement_id
    assert observation.before == scene.calls[0].acquired.before and observation.after == scene.calls[0].acquired.after
    assert observation.frame == scene.frames[0].cid
    assert observation.received == (scene.raws[0].cid if symbol == T else None)
    assert observation.received_id == (scene.raws[0].record_id if symbol == T else None)


def test_read1_sequence_uses_sample_order_and_explicit_end_not_record_order(make_read1):
    """(a): T,E,U,T keeps cursors 0,1,1,1; prefix ignores later Frames."""
    scene = make_read1(read1_static(), (T, E, U, T))
    records = dict(reversed(tuple(scene.rig.records().items())))
    result = read1_read(scene, records=records)
    read1_ok(result, scene, (Q(1, 128), Q(1, 512)))
    assert tuple(o.sample_seq for o in result.observations) == (0, 1, 2, 3)
    assert tuple(o.cursor for o in result.observations) == (0, 1, 1, 1)
    assert tuple(o.result for o in result.observations) == (T, E, "unavailable", T)
    prefix = read1_read(scene, records=records, through=0)
    read1_ok(prefix, scene, (Q(1, 2), Q(1, 4)), length=1)
    assert not set(prefix.used_records).intersection(r.cid for r in scene.frames[1:])


def test_read1_zero_received_empty_and_failure_have_different_likelihoods(make_read1):
    """:4019/:4081: H E=3/8,U=1/8; L E=1/8,U=3/8; posterior 3/4 vs 1/4."""
    model = read1_static({T: (Q(1, 2), Q(1, 2)), E: (Q(3, 8), Q(1, 8)),
                          U: (Q(1, 8), Q(3, 8)), M: (0, 0)})
    empty, failed = make_read1(model, (E,)), make_read1(model, (U,))
    assert not empty.rig.facts(c.RECEIVED) and not failed.rig.facts(c.RECEIVED)
    e, u = read1_read(empty), read1_read(failed)
    read1_ok(e, empty, (Q(3, 8), Q(1, 8)))
    read1_ok(u, failed, (Q(1, 8), Q(3, 8)))
    assert read1_posterior((Q(1, 2),) * 2, e.likelihood) == (Q(3, 4), Q(1, 4))
    assert read1_posterior((Q(1, 2),) * 2, u.likelihood) == (Q(1, 4), Q(3, 4))


def test_read1_path_enumeration_sums_hidden_terminal_states_and_cell_outcomes(make_read1):
    """(b): TT=(5/16,1/8); resetting states or choosing one of T0/T1 gives a different answer."""
    model = read1_branching()
    expected = read1_enumerate(model, (T, T), ("a", "a"))
    assert expected == (Q(5, 16), Q(1, 8))
    scene = make_read1(model, (T, T))
    read1_ok(read1_read(scene), scene, expected)


def test_read1_equal_counts_with_different_order_remain_distinct(make_read1):
    """:4087: TE=(7/16,1/8), ET=(3/16,3/16); count=1 is insufficient here."""
    model = read1_branching()
    te, et = make_read1(model, (T, E)), make_read1(model, (E, T))
    assert read1_enumerate(model, (T, E), ("a", "a")) == (Q(7, 16), Q(1, 8))
    assert read1_enumerate(model, (E, T), ("a", "a")) == (Q(3, 16), Q(3, 16))
    read1_ok(read1_read(te), te, (Q(7, 16), Q(1, 8)))
    read1_ok(read1_read(et), et, (Q(3, 16), Q(3, 16)))


def test_read1_two_failures_keep_the_shared_failure_state(make_read1):
    """:4088: G->B on failure with 1/4, B persists; UU=(1/4,1), not (1/16,1)."""
    z = ((0, 0), (0, 0))
    model = read1_model({"a": {T: ((Q(3, 4), 0), (0, 0)), E: z,
        U: ((0, 0), (Q(1, 4), 1)), M: z}}, states=("G", "B"))
    expected = read1_enumerate(model, (U, U), ("a", "a"))
    assert expected == (Q(1, 4), Q(1))
    scene = make_read1(model, (U, U))
    read1_ok(read1_read(scene), scene, expected)


def test_read1_fixed_quiet_four_probe_experiment_reduces_to_exact_A_law(make_read1):
    """(c), :4042-4047/:4083: fixed n,u,r,I and inverse-image sum, then posterior.

    Enumerate all T/E words; quiet size 0/1/2 permits only EEEE/TEEE/TTEE.
    An unrelated Received inside I is excluded from T_{u,I} and used records.
    """
    model, times = read1_quiet(), (100, 200, 300, 400)
    words = tuple(product((T, E), repeat=4))
    exact_A = {0: (Q(1, 4), Q(1, 2), Q(1), Q(0)),
               1: (Q(1, 4), Q(1, 4), Q(0), Q(1)),
               2: (Q(1, 2), Q(1, 4), Q(0), Q(0)),
               3: (Q(0),) * 4, 4: (Q(0),) * 4}
    independent = {word: read1_enumerate(model, word, ("a",) * 4) for word in words}
    for count in range(5):
        assert tuple(sum((v[s] for word, v in independent.items() if word.count(T) == count), Q(0))
                     for s in range(4)) == exact_A[count]
    scenes = [make_read1(model, word, times=times) for word in words]
    by_count = {count: [Q(0)] * 4 for count in range(5)}
    for word, scene in zip(words, scenes):
        marker = fb.Received(route_epoch=ROUTE, media_type="text/plain", data=b"not-from-acquire", claims={})
        scene.rig.host.post(marker)
        scene.rig.until(lambda: any(r.value == wire(marker) for r in scene.rig.facts(c.RECEIVED)))
        extra, = (r for r in scene.rig.facts(c.RECEIVED) if r.value == wire(marker))
        result = read1_read(scene)
        expected = independent[word]
        read1_ok(result, scene, expected, kind="model_zero" if not any(expected) else "read")
        assert extra.cid not in result.used_records
        # I=(0,400]; r_i were fixed before generating ANY alternative word.
        count = sum(symbol == T and 0 < ns <= 400 for symbol, ns in zip(word, times))
        for state, mass in enumerate(result.likelihood):
            by_count[count][state] += mass
        if word == (T, T, E, E):
            prior = (Q(1, 2), Q(1, 2), Q(0), Q(0))
            assert read1_posterior(prior, result.likelihood) == (Q(2, 3), Q(1, 3), Q(0), Q(0))
            assert read1_posterior(prior, exact_A[2]) == read1_posterior(prior, result.likelihood)
    assert {count: tuple(mass) for count, mass in by_count.items()} == exact_A


def test_read1_independent_TE_is_not_the_probability_of_count_one(make_read1):
    """:4047/:4086: TE=(3/16,1/4); sum(TE,ET)=(3/8,1/2), not TE alone."""
    model = read1_static({T: (Q(3, 4), Q(1, 2)), E: (Q(1, 4), Q(1, 2)), U: (0, 0), M: (0, 0)})
    scenes = [make_read1(model, word, times=(100, 200)) for word in ((T, E), (E, T))]
    results = [read1_read(scene) for scene in scenes]
    for result, scene in zip(results, scenes):
        read1_ok(result, scene, (Q(3, 16), Q(1, 4)))
    count_one = tuple(sum((r.likelihood[s] for r in results), Q(0)) for s in range(2))
    assert count_one == (Q(3, 8), Q(1, 2)) and count_one != results[0].likelihood
    assert read1_posterior((Q(1, 2),) * 2, count_one) == (Q(3, 7), Q(4, 7))


@pytest.mark.parametrize("first,controls,expected", [
    (T, ("a", "b"), (Q(1, 2), Q(1, 4))),
    (E, ("a", "c"), (Q(1, 2), Q(3, 4))),
])
def test_read1_adaptive_controls_fix_actual_u_for_enumeration_not_for_A(make_read1, first, controls, expected):
    """:4043/:4048/:4084: after T choose always-T b, after E choose always-E c.

    Adaptive count-one has mass 0; fixing (a,b) gives count-one mass 1/2 in H.
    This test compares L with fixed actual u only, never the adaptive A event.
    """
    model = read1_static({T: (Q(1, 2), Q(1, 4)), E: (Q(1, 2), Q(3, 4)), U: (0, 0), M: (0, 0)},
                         controls=("a", "b", "c"))
    b = read1_static({T: (1, 1), E: (0, 0), U: (0, 0), M: (0, 0)}, controls=("b",))
    cc = read1_static({T: (0, 0), E: (1, 1), U: (0, 0), M: (0, 0)}, controls=("c",))
    for other in (b, cc):
        name = next(iter(other.kernels))
        model.kernels[name], model.cells[name] = other.kernels[name], other.cells[name]
        model.declaration = replace(model.declaration,
            controls=tuple(control if control.id != name else other.declaration.controls[0]
                           for control in model.declaration.controls))
    model.declaration = replace(model.declaration, control_rule=fb.MethodCall(contract=CONTROL,
        args={"first": ["a"], "after": {T: ["b"], E: ["c"], U: ["b"], M: ["c"]}}))
    symbols = (first, first)
    assert read1_enumerate(model, symbols, controls) == expected
    scene = make_read1(model, symbols)
    result = read1_read(scene)
    read1_ok(result, scene, expected)
    assert result.controls == controls


def test_read1_selection_probabilities_are_not_factors_in_L(make_read1):
    """:4039/:4089: state-invariant pi(a)=1/5 vs 4/5 changes no likelihood."""
    scenes = []
    for p in (Q(1, 5), Q(4, 5)):
        model = read1_static(controls=("a", "b"))
        model.declaration = replace(model.declaration, independence=fb.MethodCall(contract=INDEPENDENCE,
            args={"weights_by_initial_state": [wire((p, 1-p))] * 2}))
        scenes.append(make_read1(model, (T, E)))
    for scene in scenes:
        read1_ok(read1_read(scene), scene, (Q(1, 8), Q(1, 16)))


@pytest.mark.parametrize("fault", ["missing-basis", "state-dependent", "ambiguous-control"])
def test_read1_unproved_or_unrecoverable_control_is_insufficient(make_read1, fault):
    """:4055/:4084-4085/:4090: independence and actual control recovery are separate obligations."""
    model = read1_static(controls=("a", "b"))
    if fault == "missing-basis":
        model.declaration = replace(model.declaration, independence=fb.MethodCall(contract=INDEPENDENCE, args={}))
    elif fault == "state-dependent":
        model.declaration = replace(model.declaration, independence=fb.MethodCall(contract=INDEPENDENCE, args={
            "weights_by_initial_state": [wire((Q(1, 4), Q(3, 4))), wire((Q(3, 4), Q(1, 4)))]}))
    else:
        model.declaration = replace(model.declaration,
            control_rule=fb.MethodCall(contract=CONTROL, args={"schedule": [["a"], ["a", "b"]]}))
    scene = make_read1(model, (T, E))
    read1_unreadable(read1_read(scene), "control_ambiguous" if fault == "ambiguous-control"
                     else "control_independence_unproved")


@pytest.mark.parametrize("member", ["middle-frame", "last-frame", "raw"])
def test_read1_missing_required_record_is_not_an_observation(make_read1, member):
    """(d), :4062/:4091: explicit 0..through includes even the missing tail."""
    scene = make_read1(read1_static(), (T, E, T))
    missing = {"middle-frame": scene.frames[1], "last-frame": scene.frames[2], "raw": scene.raws[0]}[member]
    records = scene.rig.records()
    del records[missing.cid]
    read1_unreadable(read1_read(scene, records=records), "missing_record")


@pytest.mark.parametrize("selector", ["run", "route_epoch"])
def test_read1_other_run_or_route_cannot_fill_the_requested_sequence(make_read1, selector):
    scene = make_read1(read1_static(), (T,))
    kwargs = {"run": Ref(kind=RefKind.RUN, value="different-run")} if selector == "run" else {"epoch": "different-route"}
    read1_unreadable(read1_read(scene, **kwargs), "missing_record")


def test_read1_absent_bootstrap_model_is_missing_declaration(make_read1):
    scene = make_read1(read1_static(), (T,), declaration=False)
    assert scene.declared_models == () and scene.models == ()
    read1_unreadable(read1_read(scene), "missing_declaration")


@pytest.mark.parametrize("fault", ["overlap", "uncovered"])
def test_read1_observation_cells_must_partition_kernel_outcomes(make_read1, fault):
    """:2660: overlap is not independent evidence; incomplete coverage is not a valid probability."""
    model = read1_static()
    control = model.declaration.controls[0]
    cells = list(control.cells)
    if fault == "overlap":
        cells[1] = replace(cells[1], outcomes=cells[1].outcomes + (T,))
    else:
        cells.pop()
    model.declaration = replace(model.declaration, controls=(replace(control, cells=tuple(cells)),))
    scene = make_read1(model, (T,))
    read1_unreadable(read1_read(scene), "shape")


@pytest.mark.parametrize("result_kind", [T, E])
def test_read1_illegal_result_source_called_pair_is_shape_not_unavailable(make_read1, result_kind):
    """:4052/:4082: T,false and E,false cannot be generated by acquire; inject a public report."""
    scene = make_read1(read1_static(), (result_kind,))
    extra = read1_extra_frame(scene, change=lambda frame: replace(frame,
        value={**frame.value, "source_called": False}))
    records = scene.rig.records()
    del records[scene.frames[0].cid]  # Only the malformed delivery is in this reader's scope.
    assert extra.cid in records
    read1_unreadable(read1_read(scene, records=records), "shape")


def test_read1_same_ns_same_bytes_and_reread_do_not_merge_or_reapply(make_read1):
    """:2662/:4092: two equal-byte/equal-time acquisitions have distinct names/MIDs; reread is pure."""
    scene = make_read1(read1_static(), (T, T), times=(100, 100))
    assert scene.raws[0].record_id != scene.raws[1].record_id
    assert scene.raws[0].value == scene.raws[1].value
    duplicate = read1_extra_frame(scene)
    first, again = read1_read(scene), read1_read(scene)
    read1_ok(first, scene, (Q(1, 4), Q(1, 16)))
    assert again == first
    assert len({o.measurement_id for o in first.observations}) == 2
    assert tuple(o.received_id for o in first.observations) == tuple(r.record_id for r in scene.raws)
    assert first.observations[0].frame in (scene.frames[0].cid, duplicate.cid)


def test_read1_changed_same_measurement_is_conflict_not_zero_or_missing(make_read1):
    scene = make_read1(read1_static(), (T,))
    read1_extra_frame(scene, change=lambda frame: replace(frame, value={**frame.value, "result": {"kind": "empty"}}))
    read1_unreadable(read1_read(scene), "conflict")


def test_read1_value_only_rejects_a_declared_within_cell_time_difference(make_read1):
    """:4093: two T outcomes with different times make the omitted time informative in the model."""
    model = read1_branching()
    control = model.declaration.controls[0]
    outcomes = list(control.kernel.outcomes)
    outcomes[1] = replace(outcomes[1], elapsed_ns=17)
    model.declaration = replace(model.declaration,
        controls=(replace(control, kernel=replace(control.kernel, outcomes=tuple(outcomes))),))
    scene = make_read1(model, (T,))
    read1_unreadable(read1_read(scene), "time_projection_unproved")


def test_read1_unmodeled_actual_delay_is_not_silently_a_control_or_model_counterexample(make_read1):
    """:4030/:4071: actual before/after remain visible; no undeclared environment time law is invented."""
    model = read1_static()
    fast = make_read1(model, (T,), advance=0)
    slow = make_read1(model, (T,), advance=50)
    for scene in (fast, slow):
        result = read1_read(scene)
        read1_ok(result, scene, (Q(1, 2), Q(1, 4)))
        assert result.observations[0].before == scene.calls[0].acquired.before
        assert result.observations[0].after == scene.calls[0].acquired.after


@pytest.mark.parametrize("zero", ["one-state", "whole-model"])
def test_read1_zero_likelihood_is_distinct_from_unreadable(make_read1, zero):
    """:4040/:4094: (0,1/2) is valid read; (0,0) is explicit model_zero, not missing records."""
    taken = (0, Q(1, 2)) if zero == "one-state" else (0, 0)
    model = read1_static({T: taken, E: (1-taken[0], 1-taken[1]), U: (0, 0), M: (0, 0)})
    scene = make_read1(model, (T,))
    read1_ok(read1_read(scene), scene, taken, kind="read" if zero == "one-state" else "model_zero")


def test_read1_payload_bytes_and_failure_reason_are_not_observation_values(make_read1):
    """:4060: result/source_called only; raw bytes and diagnostic reason are opaque."""
    model = read1_static()
    scenes = [(make_read1(model, (T,), data=data), (Q(1, 2), Q(1, 4))) for data in (b"alpha", b"beta")]
    scenes += [(make_read1(model, (U,), reason=reason), (Q(1, 8), Q(1, 8)))
               for reason in ("permission denied", "unrelated failure")]
    for scene, expected in scenes:
        read1_ok(read1_read(scene), scene, expected)


def test_read1_common_purity_child_unchanged_and_versioned_footprint(make_read1):
    """Common :4056: physical store + input Records unchanged, no child adoption, exact provenance names."""
    scene = make_read1(read1_static(), (T, E))
    records = scene.rig.records()
    before_input = deepcopy(records)
    before_store = scene.rig.storage_snapshot()
    before_preparations = tuple(scene.rig.ledger.preparations)
    result = read1_read(scene, records=records)
    read1_ok(result, scene, (Q(1, 8), Q(1, 16)))
    assert records == before_input and scene.rig.storage_snapshot() == before_store
    assert tuple(scene.rig.ledger.preparations) == before_preparations
    scene.rig.no_belief_update()
    required = {scene.model_record.cid, *(r.cid for r in scene.frames), scene.raws[0].cid}
    assert required <= set(result.used_records) <= set(records)
    assert scene.model_record.cid != scene.boot.cid
    assert {MODEL, PROJECTION, CONTROL, INDEPENDENCE, TIME,
            c.ACQUISITION_RESULT_SAMPLING} <= set(result.contracts)
    assert len(result.used_records) == len(set(result.used_records))


@pytest.mark.parametrize("args", [
    {"schedule": 1},
    {"schedule": [1, ["a"]]},
    {"first": 1, "after": {symbol: ["a"] for symbol in SYMBOLS}},
    {"first": ["a"], "after": 1},
    {"first": ["a"], "after": {symbol: 1 for symbol in SYMBOLS}},
], ids=["schedule-scalar", "schedule-row-scalar", "first-scalar",
        "after-scalar", "after-row-scalar"])
def test_read1_malformed_control_table_is_shape_not_an_exception(make_read1, args):
    """K26-d(a): malformed JSON-shaped control args return unreadable/shape.

    A scalar schedule/row or first/after must not leak TypeError or become a
    valid control. Two empty acquisitions exercise the selected after branch.
    """
    model = read1_static()
    model.declaration = replace(model.declaration,
        control_rule=fb.MethodCall(contract=CONTROL, args=args))
    scene = make_read1(model, (E, E))
    assert scene.model_record.value["value"]["control_rule"]["args"] == args
    read1_unreadable(read1_read(scene), "shape")


def read1_post_raw_candidate(scene, *, epoch=ROUTE, foreign_run=False, ns=None):
    """Save a real Received through Post, optionally from another public host/run."""
    event = fb.Received(route_epoch=epoch, media_type="text/plain",
                        data=b"reader-candidate", claims={})
    if not foreign_run:
        if ns is not None:
            scene.rig.clock.set(ns)
        scene.rig.host.post(event)
        scene.rig.until(lambda: any(r.value == wire(event) for r in scene.rig.facts(c.RECEIVED)))
        fact, = (r for r in scene.rig.facts(c.RECEIVED) if r.value == wire(event))
        return fact, scene.rig.read_stored(fact.cid)[2]
    other = RealRig(connect=False)
    try:
        clock = FakeClock(run=Ref(kind=RefKind.RUN, value="read1-foreign-run"),
                          mono_ns=scene.times[0] if ns is None else ns)
        host = fb.FThreadHost(ledger=other.ledger, clock=clock,
                             workers=other.workers, registry=other.registry)
        host.post(event)
        assert host.keep_running(lambda _status: bool(other.facts(c.RECEIVED)), timeout=5)
        fact, = other.facts(c.RECEIVED)
        record = other.read_stored(fact.cid)[2]
        assert record.at.run != scene.rig.clock.run
        return fact, record
    finally:
        other.close()


def read1_save_raw_name_collision(scene, *, other_contract=False):
    """A second public Ledger can save a different Record with the same Record.id.

    This adds a stored raw candidate to the reader scope, never a fabricated
    successful acquisition or a mutation of a previously saved Record.
    """
    original = scene.rig.read_stored(scene.raws[0].cid)[2]
    assert isinstance(original.body, Observed) and original.body.contract == c.RECEIVED
    if other_contract:
        body = replace(original.body, contract=contract("test.read1.other-observed"))
        assert replace(body, contract=c.RECEIVED) == original.body
    else:
        body = replace(original.body,
            content=Payload.json(wire(fb.Received(route_epoch=ROUTE,
                media_type="text/plain", data=b"different-candidate", claims={}))))
    other = RealRig(connect=False)
    try:
        saved = other.ledger.append(replace(original, body=body), ())
        record = other.read_stored(saved.cid)[2]
        assert saved.cid != scene.raws[0].cid and record.id == original.id
        assert record.body != original.body
        return saved.cid, record
    finally:
        other.close()


@pytest.mark.parametrize("fault,reason", [
    ("missing", "missing_record"),
    ("duplicate-received", "conflict"),
    ("duplicate-other-contract", "conflict"),
    ("wrong-contract", "conflict"),
    ("other-route", "conflict"),
    ("other-run", "conflict"),
    ("received-time", "conflict"),
])
def test_read1_taken_raw_name_checks_all_candidates_and_correspondence(make_read1, fault, reason):
    """K26-d(b): resolve Record.id over ALL records before checking Received.

    Ignoring a same-name non-Received, or accepting another route/run/time,
    must fail conflict; only zero named records is missing_record.
    K26-e: the contract-only candidate keeps the original body, route, run,
    received_ns and Record fields. A Prediction with no received_ns is not a
    single-condition contrast, so the former not-observed fixture is removed.
    """
    scene = make_read1(read1_static(), (T,))
    read1_ok(read1_read(scene), scene, (Q(1, 2), Q(1, 4)))
    records = scene.rig.records()
    raw = scene.raws[0]
    target_id = raw.record_id
    if fault == "missing":
        del records[raw.cid]
    elif fault.startswith("duplicate-"):
        cid, record = read1_save_raw_name_collision(scene,
            other_contract=fault == "duplicate-other-contract")
        records[cid] = record
    elif fault == "wrong-contract":
        cid, record = read1_save_raw_name_collision(scene, other_contract=True)
        original = records.pop(raw.cid)
        assert replace(record.body, contract=c.RECEIVED) == original.body
        assert replace(record, body=original.body) == original
        records[cid] = record
    else:
        candidate, record = read1_post_raw_candidate(scene,
            epoch="other-route" if fault == "other-route" else ROUTE,
            foreign_run=fault == "other-run",
            ns=scene.times[0] + 1 if fault == "received-time" else scene.times[0])
        target_id = candidate.record_id
        records[candidate.cid] = record
        assert isinstance(record.body, Observed) and record.body.contract == c.RECEIVED
        assert (candidate.value["route_epoch"] == ROUTE) == (fault != "other-route")
        assert (record.at.run == scene.rig.clock.run) == (fault != "other-run")
        assert (record.body.received_ns == scene.times[0]) == (fault != "received-time")
    extra = read1_extra_frame(scene, change=lambda frame: replace(frame,
        value={**frame.value, "result": {"kind": "taken", "received": str(target_id)}}))
    records[extra.cid] = scene.rig.read_stored(extra.cid)[2]
    del records[scene.frames[0].cid]
    candidates = [record for record in records.values() if record.id == target_id]
    assert len(candidates) == (0 if fault == "missing" else 2 if fault.startswith("duplicate-") else 1)
    for candidate in candidates:
        assert isinstance(candidate.body, Observed)
        assert candidate.at.run == (record.at.run if fault == "other-run" else scene.rig.clock.run)
        assert candidate.body.received_ns == scene.times[0] + (fault == "received-time")
        assert candidate.body.content.as_json()["route_epoch"] == (
            "other-route" if fault == "other-route" else ROUTE)
    # A collision must be detected regardless of Mapping insertion order, even
    # when one named candidate has another contract. No record content is edited.
    for scope in (records, dict(reversed(tuple(records.items())))):
        read1_unreadable(read1_read(scene, records=scope), reason)


@pytest.mark.parametrize("fault", [
    "closure-right-open", "closure-left-open", "closure-both-open",
    "interval-clock-run", "actual-time-run", "actual-time-end", "reversed-bounds",
])
def test_read1_frame_time_fields_must_agree_with_K25_shape(make_read1, fault):
    """K26-d(c): each saved time-field inconsistency is unreadable/shape.

    Accepting any wrong closure/run/end or start>end as read/model_zero fails;
    this compares saved fields only, without assuming an environment delay law.
    """
    scene = make_read1(read1_static(), (E,), advance=50)
    foreign = Ref(kind=RefKind.RUN, value="read1-wrong-frame-clock")

    def change(frame):
        interval = frame.measurement_interval
        assert interval.start_ns == 50 and interval.end_ns == 100
        assert interval.clock == frame.actual_time.run == scene.rig.clock.run
        if fault.startswith("closure-"):
            closure = {"closure-right-open": "[start,end)",
                       "closure-left-open": "(start,end]",
                       "closure-both-open": "(start,end)"}[fault]
            return replace(frame, measurement_interval=replace(interval, closure=closure))
        if fault == "interval-clock-run":
            return replace(frame, measurement_interval=replace(interval, clock=foreign))
        if fault == "actual-time-run":
            return replace(frame, actual_time=replace(frame.actual_time, run=foreign))
        if fault == "actual-time-end":
            return replace(frame, actual_time=replace(frame.actual_time, time_ns=101))
        assert fault == "reversed-bounds"
        return replace(frame, measurement_interval=replace(interval, start_ns=101))

    extra = read1_extra_frame(scene, change=change)
    records = scene.rig.records()
    del records[scene.frames[0].cid]
    assert extra.cid in records
    read1_unreadable(read1_read(scene, records=records), "shape")


def test_read1_empty_observation_cell_is_shape_not_model_zero(make_read1):
    """K26-d(d): normalized one-outcome kernel, covered once, but an empty E cell.

    Treating an empty declared cell as a zero-probability legal observation
    incorrectly returns model_zero instead of unreadable/shape.
    """
    model = read1_model({"a": {T: ((1, 0), (0, 1))}}, groups={T: (T,), E: ()})
    control, = model.declaration.controls
    assert {cell.id: cell.outcomes for cell in control.cells} == {T: (T,), E: ()}
    assert tuple(out.id for out in control.kernel.outcomes) == (T,)
    scene = make_read1(model, (E,))
    read1_unreadable(read1_read(scene), "shape")


@pytest.mark.parametrize("symbols,seq,cursor", [
    ((E,), 0, 1),
    ((T, E), 1, 0),
    ((T, T), 1, 2),
    ((E, T), 1, 1),
    ((U, T), 1, 1),
    ((M, M), 1, 1),
], ids=["first-not-zero", "taken-did-not-advance", "taken-advanced-twice",
        "empty-advanced", "unavailable-called-advanced", "unavailable-missing-advanced"])
def test_read1_source_cursor_continuity_is_conflict(make_read1, symbols, seq, cursor):
    """K26-e(a): change only cursor in one otherwise identical saved Frame.

    Ignoring the first zero or advancing by anything but one after taken, or
    advancing after empty/either unavailable, must not yield a valid likelihood.
    """
    model = read1_static()
    scene = make_read1(model, symbols)
    expected = read1_enumerate(model, symbols, ("a",) * len(symbols))
    read1_ok(read1_read(scene), scene, expected)
    correct = sum(symbol == T for symbol in symbols[:seq])
    assert cursor != correct

    def change(frame):
        assert frame.value["cursor"] == correct
        return replace(frame, value={**frame.value, "cursor": cursor})

    extra = read1_extra_frame(scene, seq, change=change)
    original = scene.frames[seq].value
    changed = deepcopy(extra.value)
    changed["item_slot"] = original["item_slot"]  # Separate delivery, same measurement.
    changed["item"]["value"]["value"]["value"]["cursor"] = correct
    assert changed == original
    records = scene.rig.records()
    del records[scene.frames[seq].cid]
    read1_unreadable(read1_read(scene, records=records), "conflict")


@pytest.mark.parametrize("site,bad", [
    ("unused-schedule", 1),
    ("unused-schedule", "a"),
    ("unused-schedule", ["a", 1]),
    (T, 1), (U, 1), (M, 1),
    (T, "a"), (T, ["a", 1]),
    ("first", "a"), ("first", [1]), ("first", ["a", 1]),
], ids=["unused-schedule-scalar", "unused-schedule-string", "unused-schedule-nonstring-member",
        "unselected-taken", "unselected-unavailable-called", "unselected-unavailable-missing",
        "unselected-after-string", "unselected-after-nonstring-member",
        "first-string", "first-nonstring-member", "first-mixed-members"])
def test_read1_control_table_validates_every_row_before_selection(make_read1, site, bad):
    """K26-e(b): exactly one row/branch/first fails the string-sequence shape.

    Checking only used rows, iterating a bare string as a candidate list, or
    reporting ambiguity before detecting a non-string member must fail here.
    """
    model = read1_static()
    if site == "unused-schedule":
        args, symbols = {"schedule": [["a"], bad]}, (E,)
        repaired = {"schedule": [["a"], ["a"]]}
    else:
        args = {"first": ["a"], "after": {symbol: ["a"] for symbol in SYMBOLS}}
        repaired = deepcopy(args)
        if site == "first":
            args["first"] = bad
        else:
            assert site != E  # The two actual observations are E,E.
            args["after"][site] = bad
        symbols = (E, E)
    assert args != repaired
    model.declaration = replace(model.declaration,
        control_rule=fb.MethodCall(contract=CONTROL, args=args))
    scene = make_read1(model, symbols)
    assert scene.model_record.value["value"]["control_rule"]["args"] == args
    read1_unreadable(read1_read(scene), "shape")


@pytest.mark.parametrize("site,candidates", [
    ("schedule", ["a", "a"]), ("schedule", ["not-declared"]),
    ("after", ["a", "a"]), ("after", ["not-declared"]),
], ids=["unused-schedule-ambiguous", "unused-schedule-unknown",
        "unselected-after-ambiguous", "unselected-after-unknown"])
def test_read1_unused_control_rows_do_not_require_unique_known_candidates(make_read1, site, candidates):
    """K26-e(b): shape is global, but count/name resolution applies only to used rows.

    Rejecting an unused, well-shaped ambiguous/unknown row is over-validation;
    actual controls remain a and E or EE has L=(1/4,1/4) or (1/16,1/16).
    """
    model = read1_static()
    if site == "schedule":
        args, symbols, expected = {"schedule": [["a"], candidates]}, (E,), (Q(1, 4), Q(1, 4))
    else:
        args = {"first": ["a"], "after": {symbol: ["a"] for symbol in SYMBOLS}}
        args["after"][T] = candidates
        symbols, expected = (E, E), (Q(1, 16), Q(1, 16))
    model.declaration = replace(model.declaration,
        control_rule=fb.MethodCall(contract=CONTROL, args=args))
    scene = make_read1(model, symbols)
    result = read1_read(scene)
    read1_ok(result, scene, expected)
    assert result.controls == ("a",) * len(symbols)


@pytest.mark.parametrize("delta", [Q(1, 4), Q(-1, 4)], ids=["column-sum-five-fourths", "column-sum-three-fourths"])
def test_read1_kernel_column_sum_must_be_one(make_read1, delta):
    """K26-e(c): only one departure column loses normalization; no negative entries.

    Skipping normalization, checking only another column, or normalizing the
    supplied kernel silently must not turn this declaration into valid L.
    """
    model = read1_static()
    control, = model.declaration.controls
    outcomes = list(control.kernel.outcomes)
    chosen = next(i for i, outcome in enumerate(outcomes) if outcome.id == T)
    matrix = outcomes[chosen].matrix
    outcomes[chosen] = replace(outcomes[chosen],
        matrix=((matrix[0][0] + delta, matrix[0][1]), matrix[1]))
    assert all(x >= 0 for outcome in outcomes for row in outcome.matrix for x in row)
    sums = tuple(sum((outcome.matrix[row][col] for outcome in outcomes
                      for row in range(2)), Q(0)) for col in range(2))
    assert sums == (1 + delta, 1)
    model.declaration = replace(model.declaration,
        controls=(replace(control, kernel=replace(control.kernel, outcomes=tuple(outcomes))),))
    scene = make_read1(model, (T,))
    read1_unreadable(read1_read(scene), "shape")


@pytest.mark.parametrize("fault", ["contract", "body-kind"])
def test_read1_model_point_requires_observation_prediction(make_read1, fault):
    """K26-e(c): correct payload, Boot provenance, MODEL writer and route; one wrong gate.

    Ignoring the contract or requiring only MODEL without Prediction must fail.
    A new Record identity matches the body's public kind; no saved record is edited.
    """
    scene = make_read1(read1_static(), (T,))
    read1_ok(read1_read(scene), scene, (Q(1, 2), Q(1, 4)))
    original = scene.rig.read_stored(scene.model_record.cid)[2]
    assert isinstance(original.body, Prediction) and original.writer == Role.MODEL
    if fault == "contract":
        body = replace(original.body, contract=contract("test.read1.not-observation-model"))
        kind = RefKind.PREDICTION
        assert replace(body, contract=MODEL) == original.body
    else:
        body = Decided(inputs=original.body.basis, content=original.body.content, contract=MODEL)
        kind = RefKind.DECISION
        assert not isinstance(body, Prediction) and body.contract == original.body.contract
    candidate = replace(original, id=Ref(kind=kind, value=f"read1-model-{fault}"), body=body)
    assert candidate.at == original.at and candidate.writer == Role.MODEL
    assert candidate.body.content == original.body.content
    saved = scene.rig.ledger.append(candidate, (scene.boot.cid,))
    result = read1_api().read(scene.rig.records(), model=saved.cid,
        run=scene.rig.clock.run, route_epoch=ROUTE, through_seq=0)
    read1_unreadable(result, "missing_declaration")


@pytest.mark.parametrize("writer", [Role.MEMBRANE, Role.INTERPRETER])
def test_read1_non_model_prediction_is_rejected_at_public_record_boundary(writer):
    """K26-e(o): the public Record boundary owns the writer requirement.

    Record rejects non-MODEL Prediction (test_records.py WRITERS/R2). This
    closes CG-K26E-MODEL-WRITER; the reader must not add an unreachable guard.
    """
    rig = RealRig(connect=False)
    try:
        record = rig.record(Prediction(target="acquisition_observation_model", about=(), basis=(),
            content=Payload.json({}), contract=MODEL), RefKind.PREDICTION, Role.MODEL)
        with pytest.raises(WriterNotAllowed):
            replace(record, writer=writer)
    finally:
        rig.close()


def test_read1_model_route_slot_must_match_the_complete_requested_sequence(make_read1):
    """K26-e(c): both Boot routes exist, but the model names B while the complete series is A.

    Checking slot existence alone, or ignoring its route_epoch, must fail this
    missing_declaration test. Run, raw, Frame and every model condition agree.
    """
    model = read1_static()
    model.declaration = replace(model.declaration, route_slot="route-2")
    scene = make_read1(model, (T,), second_route_epoch="read1-other-route")
    routes = {r.slot: r.value.config.route_epoch for r in scene.rig.boot_input.declaration.routes}
    assert routes == {"route": ROUTE, "route-2": "read1-other-route"}
    assert routes[model.declaration.route_slot] != ROUTE
    assert scene.frames[0].value["item"]["value"]["route_epoch"] == ROUTE
    assert scene.raws[0].value["route_epoch"] == ROUTE
    read1_unreadable(read1_read(scene), "missing_declaration")


@pytest.mark.parametrize("initial", [False, True], ids=["initial-none", "initial-present"])
def test_read1_saved_observation_models_have_only_boot_as_causal_parent(make_read1, initial):
    """K26-e(c): inspect physical entry parents, independently of about/basis JSON.

    Missing Boot or adding clock/model/route/another Prediction as a parent must
    fail even if the payload provenance and all numerical fields are correct.
    """
    model = read1_static()
    scene = make_read1(model, (), initial=initial, extra_models=(model,))
    headers = dict(scene.rig.entry_store.load())
    assert len(scene.models) == 2
    for saved in scene.models:
        entry = entry_from_header(saved.cid, headers[saved.cid])
        assert entry.parents == frozenset({scene.boot.cid})
