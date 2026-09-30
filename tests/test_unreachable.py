"""S4dの届かない所要。N1・N2とmodel.4の信念の往復。"""

from dataclasses import FrozenInstanceError, replace
import json
import math

import numpy as np
import pytest

from sui.model import GenerativeModel, model_from_json, model_json, model_ref


NS = 1_000_000_000


def _n5_rig(a, D, kind):
    from types import SimpleNamespace
    from sui.agent import Agent
    from sui.ids import SequentialIds
    from sui.ledger import Ledger, SequentialSalts
    from sui.loop import boot
    from sui.records import Producer
    from worlds import HandHistory
    model = GenerativeModel(states=tuple(f"s{i}" for i in range(len(D))),
        outcomes=("o0", "o1"), actions=tuple(a), a=a, D=np.array(D),
        learnable=frozenset(), log_C=np.log([.5, .5]), gamma=1.,
        Q=np.array([[-1., 1.], [1., -1.]]) if kind in ("changing", "hand") else None,
        durations={name: ((0., 1.),) for name in a} if kind in ("durations", "hand") else {},
        measures={name: "report" for name in a} if kind in ("durations", "hand") else {})
    agent = Agent(model=model, lineage="n5")
    clock, ids, ledger = HandHistory().clock, SequentialIds(prefix="n5"), Ledger(salts=SequentialSalts())
    membrane = Producer(component="test.n5", code_version="1")
    boot(agent, clock=clock, ids=ids, ledger=ledger, membrane=membrane)
    return SimpleNamespace(model=model, agent=agent, clock=clock, ids=ids, ledger=ledger, membrane=membrane)


def _n5_ban_and_check(r, forbidden):
    from sui.agent import plan
    from sui.ids import RefKind
    from sui.lookahead import NoAdmissibleCandidate
    from sui.records import Record, Preference, Payload, Role
    from sui.s4d_contracts import PREFERENCE
    record = Record(id=r.ids.new(RefKind.PREFERENCE), at=r.clock.now(), writer=Role.MODEL,
        producer=r.agent.producer, body=Preference(basis=(), contract=PREFERENCE,
            content=Payload.json({"kind": "item", "rule": {"name": "table", "version": "1"},
                "args": {"feature": {"name": "candidate_outcome", "version": "1"}, "probs": [["o0", 1.]]}})))
    r.ledger.append(record, r.agent.frontier)
    r.agent.adopt(r.ledger, clock=r.clock, ids=r.ids)
    view = r.agent.view(now_ns=0, observed_ns=0)
    data = plan(view, ("probe", "safe"), u=.5).content.as_json()
    assert data["expected_cost"] == data["J"] == (["+inf", 0.] if forbidden else [0., 0.])
    if forbidden:
        assert data["q_pi"] == [0., 1.]
        with pytest.raises(NoAdmissibleCandidate):
            plan(view, ("probe",), u=.5)
    else:
        assert plan(view, ("probe",), u=.5).content.as_json()["q_pi"] == [1.]


@pytest.mark.parametrize("kind", ["static", "durations"])
@pytest.mark.parametrize("tiny", [0., 1e-200])
def test_n5_positive_likelihood_support_survives_probability_underflow(kind, tiny):
    """Aの確率が約1e-400でも禁止は+∞。本当に0の結果は禁じない。"""
    r = _n5_rig({"probe": np.array([[1e200], [tiny]]), "safe": np.array([[1.], [0.]])}, [1.], kind)
    _n5_ban_and_check(r, tiny > 0)


@pytest.mark.parametrize("kind", ["static", "durations", "changing", "hand"])
@pytest.mark.parametrize("pending", [False, True])
@pytest.mark.parametrize("rare_prior", [0., .5])
def test_n5_posterior_support_survives_two_synchronous_observations(kind, pending, rare_prior):
    """事後qが0に丸まっても、まれな状態の禁止と進行中の正の枝を残す。"""
    from sui.loop import run_step
    from worlds import ScriptedWorld
    r = _n5_rig({"sense": np.array([[1., 1e-200], [0., 1.]]),
                 "probe": np.eye(2), "safe": np.array([[1., 1.], [0., 0.]])},
                [1. - rare_prior, rare_prior], kind)
    world = ScriptedWorld({"sense": ["o0", "o0"]})
    for _ in range(2):
        step = run_step(r.agent, world, ("sense",), u=.5, clock=r.clock, ids=r.ids,
                        ledger=r.ledger, membrane=r.membrane)
    assert step.belief.body.content.as_json()["q"] == [1., 0.]
    assert r.agent.view().reading.n["sense"].tolist() == [2, 0]
    if pending:
        r.agent.decide(("probe",), u=.5, clock=r.clock, ids=r.ids, ledger=r.ledger, now_mono_ns=0)
        r.agent.adopt(r.ledger, clock=r.clock, ids=r.ids)
        assert list(r.agent.view().reading.pending.values()) == ["probe"]
    _n5_ban_and_check(r, rare_prior > 0)


def _duration_model(points=((1., .3), (3., .2), (None, .5)), **changes):
    values = dict(states=("s0", "s1"), outcomes=("o0", "o1"), actions=("look",),
        a={"look": np.array([[1., 0.], [0., 1.]])}, learnable=frozenset(),
        D=np.array([.5, .5]), log_C=np.array([0., -1000.]), gamma=1.,
        durations={"look": points}, measures={"look": "report"})
    values.update(changes)
    return GenerativeModel(**values)


def _canonical(data):
    return json.dumps(data, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


@pytest.mark.parametrize("points,expected", [
    (((None, 1.),), ((None, 1.),)),
    (((0., .5), (None, .5)), ((0., .5), (None, .5))),
    (((None, .5), (3., .2), (1., .3)), ((1., .3), (3., .2), (None, .5))),
])
def test_n1_none_is_a_duration_atom_and_model4_roundtrips(points, expected):
    """Noneだけも許し、有限の点の後にnullを符号化して完全に戻す。"""
    model = _duration_model(points)
    encoded = model_json(model)
    data = json.loads(encoded)
    assert data["scheme"] == "sui.model.4"
    assert data["durations"]["look"] == [list(point) for point in expected]
    assert model.durations["look"] == expected
    restored = model_from_json(encoded)
    assert restored.durations == model.durations
    assert model_json(restored) == encoded
    assert model_ref(restored) == model_ref(model)


@pytest.mark.parametrize("points", [
    ((None, .5), (None, .5)), ((None, 0.), (1., 1.)),
    ((None, -.5), (1., 1.5)), ((None, math.nan),), ((None, math.inf),),
    ((None, .8),), ((None, 1.1),), ((None, True),), ((None, 1),),
    ((0., .2), (1e-10, .3), (None, .5)),
    ((math.inf, .5), (None, .5)), ((math.nan, .5), (None, .5)),
    ((-1., .5), (None, .5)), ((1e308, .5), (None, .5)),
    ((True, .5), (None, .5)), (), None,
])
def test_n1_invalid_unreachable_distributions_are_rejected(points):
    """Noneの重複・不正な確率・有限点の不正・分布自体のNoneを拒む。"""
    with pytest.raises(ValueError):
        _duration_model(points)


def test_n1_none_and_rounded_zero_are_distinct_and_owned():
    """Noneを0nsと混ぜず、元の辞書を変えても読み取り専用のモデルを保つ。"""
    source = {"look": ((None, .5), (1e-10, .5))}
    model = _duration_model(durations=source)
    source.clear()
    assert model.durations["look"] == ((1e-10, .5), (None, .5))
    with pytest.raises(TypeError):
        model.durations["look"] = ((None, 1.),)
    with pytest.raises(FrozenInstanceError):
        model.durations = {}


def test_n1_finite_duration_encoding_keeps_s4c_bytes():
    """Noneのないmodel.3は固定した正準JSONとバイト一致する。"""
    model = _duration_model(((3., .2), (1., .8)))
    expected = (
        b'{"D":[0.5,0.5],"Q":null,"a":{"look":[[1.0,0.0],[0.0,1.0]]},'
        b'"actions":["look"],"arrivals":{},"durations":{"look":[[1.0,0.8],[3.0,0.2]]},'
        b'"gamma":1.0,"learnable":[],"log_C":[0.0,-1000.0],'
        b'"measures":{"look":"report"},"outcomes":["o0","o1"],'
        b'"scheme":"sui.model.3","states":["s0","s1"]}'
    )
    assert model_json(model) == expected
    assert model_json(model_from_json(expected)) == expected


@pytest.mark.parametrize("scheme", ["sui.model.1", "sui.model.2"])
def test_n1_without_duration_keeps_old_scheme(scheme):
    Q = None if scheme == "sui.model.1" else np.array([[-.5, .5], [.5, -.5]])
    model = _duration_model(durations={}, measures={}, Q=Q)
    encoded = model_json(model)
    assert json.loads(encoded)["scheme"] == scheme
    assert "durations" not in json.loads(encoded)
    assert model_json(model_from_json(encoded)) == encoded


@pytest.mark.parametrize("change", ["null_first", "reverse_finite", "model3_with_none",
    "model4_without_none", "unknown_scheme", "missing_measures", "extra_key", "trailing_space"])
def test_n1_noncanonical_model4_is_rejected(change):
    """nullの位置と版の意味を含む正準形を検査し、勝手に修復しない。"""
    data = json.loads(model_json(_duration_model()))
    if change == "null_first":
        data["durations"]["look"] = [[None, .5], [1., .3], [3., .2]]
    elif change == "reverse_finite":
        data["durations"]["look"] = [[3., .2], [1., .3], [None, .5]]
    elif change == "model3_with_none":
        data["scheme"] = "sui.model.3"
    elif change == "model4_without_none":
        data["durations"]["look"] = [[1., 1.]]
    elif change == "unknown_scheme":
        data["scheme"] = "sui.model.5"
    elif change == "missing_measures":
        del data["measures"]
    elif change == "extra_key":
        data["unreachable"] = True
    encoded = _canonical(data) + (b" " if change == "trailing_space" else b"")
    with pytest.raises(ValueError):
        model_from_json(encoded)


def test_n1_none_in_any_action_selects_model4_and_preserves_other_fields():
    model = _duration_model(((1., 1.),))
    model = replace(model, actions=("look", "wait"),
        a={"look": model.a["look"], "wait": np.array([[1., 1.], [1., 1.]])},
        learnable=frozenset({"wait"}),
        durations={"look": ((1., 1.),), "wait": ((None, 1.),)},
        measures={"look": "start", "wait": "report"})
    encoded = model_json(model)
    assert json.loads(encoded)["scheme"] == "sui.model.4"
    restored = model_from_json(encoded)
    assert restored.measures == model.measures
    assert restored.learnable == {"wait"}
    assert np.array_equal(restored.log_C, [0., -1000.])
    assert restored.gamma == 1.
    assert model_json(restored) == encoded


@pytest.mark.parametrize("strict", [False, True])
def test_n2_remaining_keeps_none_in_normalization(strict):
    """仕様の固定値。Noneを落とすと有限点の重みが1になり失敗する。"""
    from sui.inference import remaining
    actual = remaining(((NS, .3), (3 * NS, .2), (None, .5)), 2 * NS, strict=strict)
    assert tuple(ns for ns, _ in actual) == (3 * NS, None)
    np.testing.assert_allclose([p for _, p in actual],
        [.2857142857142857, .7142857142857143], atol=1e-15, rtol=0)


@pytest.mark.parametrize("strict", [False, True])
def test_n2_only_none_remaining_is_not_a_violation(strict):
    from sui.inference import remaining
    assert remaining(((NS, .5), (None, .5)), 2 * NS, strict=strict) == ((None, 1.),)
    assert remaining(((None, 1.),), 100 * NS, strict=strict) == ((None, 1.),)


def test_n2_root_keeps_equality_and_tree_excludes_it():
    """総所要を返す。2秒ちょうどの点は根だけ残し、木ではNoneだけ。"""
    from sui.inference import remaining
    duration = ((2 * NS, .5), (None, .5))
    assert remaining(duration, 2 * NS) == duration
    assert remaining(duration, 2 * NS, strict=False) == duration
    assert remaining(duration, 2 * NS, strict=True) == ((None, 1.),)
    assert remaining(duration, NS, strict=True) == duration


@pytest.mark.parametrize("strict", [False, True])
def test_n2_finite_only_distribution_keeps_s4c_weights(strict):
    from sui.inference import remaining
    points = ((NS, .2), (3 * NS, .2), (4 * NS, .6))
    actual = remaining(points, 2 * NS, strict=strict)
    assert tuple(ns for ns, _ in actual) == (3 * NS, 4 * NS)
    np.testing.assert_allclose([p for _, p in actual], [.25, .75], atol=1e-15, rtol=0)
    assert remaining(points, 0, strict=strict) == points


@pytest.mark.parametrize("strict,unseen", [(False, 2 * NS), (True, NS)])
def test_n2_no_remaining_finite_point_raises(strict, unseen):
    from sui.inference import ModelViolation, remaining
    with pytest.raises(ModelViolation):
        remaining(((NS, 1.),), unseen, strict=strict)


def test_n2_zero_duration_is_inclusive_only_at_root():
    from sui.inference import remaining
    points = ((0, .5), (None, .5))
    assert remaining(points, 0) == points
    assert remaining(points, 0, strict=True) == ((None, 1.),)


def test_model4_belief_declaration_is_explicit_and_registerable():
    from sui.contracts import ContractBook, ContractRef
    from sui.s4d_contracts import BELIEF, DECLARATIONS
    assert BELIEF == ContractRef("sui.s4d.belief", "1")
    book = ContractBook()
    for declaration in DECLARATIONS:
        book.register(declaration)
        assert book.get(declaration.ref) == declaration
    assert "sui.model.4" in book.get(BELIEF).meaning
    assert "None" in book.get(BELIEF).meaning


@pytest.mark.parametrize("changing,learnable", [(False, False), (False, True), (True, False)])
@pytest.mark.parametrize("measure", ["start", "report"])
def test_model4_belief_records_restore_without_counting_unreachable(changing, learnable, measure):
    """Noneだけの手から届いた結果も読む。新しい信念の全欄を親から再現する。"""
    from sui.agent import Agent
    from sui.ledger import Ledger, SequentialSalts
    from sui.s4d_contracts import BELIEF, DECLARATIONS
    from worlds import HandHistory, _hand_model
    changes = {"duration": ((None, 1.),), "measure": measure}
    if not changing:
        changes["Q"] = None
    if learnable:
        changes["learnable"] = frozenset({"look"})
    model = _hand_model(**changes)
    history = HandHistory()
    history.boot()
    attempt = history.start()
    history.observe(attempt, "o0", 2)
    ledger = Ledger(salts=SequentialSalts())
    for record in history.records:
        ledger.append(record, ledger.heads())
    subject = Agent(model=model, lineage="unreachable")
    saved = subject.adopt(ledger, clock=history.clock, ids=history.ids)
    assert saved.body.contract == BELIEF
    content = saved.body.content.as_json()
    assert set(content) == {"model", "states", "outcomes", "q", "a", "n", "unread", "time", "arrivals"}
    assert content["n"]["look"] == [1, 0, 0]
    assert content["unread"] == []
    assert not subject._reading.pending
    meaning = next(c.meaning for c in DECLARATIONS if c.ref == BELIEF)
    assert all(key in meaning for key in content)
    cid = ledger.entries_of(saved.id)[0].cid
    restored = Agent.restore(model=model_from_json(model_json(model)), lineage="unreachable",
                             ledger=ledger, belief=cid)
    assert restored._belief.body.contract == BELIEF
    assert restored._belief.body.content == saved.body.content
    assert restored.frontier == subject.frontier
    assert np.array_equal(restored.q, subject.q)
    assert np.array_equal(restored.counts("look"), subject.counts("look"))


def test_model4_belief_contract_rejects_old_hand_contract():
    from sui.agent import Agent
    from sui.clock import FakeClock
    from sui.ids import Ref, RefKind, SequentialIds
    from sui.ledger import Ledger, SequentialSalts
    from sui.s4_contracts import HAND_BELIEF
    model = _duration_model(((None, 1.),))
    subject = Agent(model=model, lineage="unreachable")
    ledger = Ledger(salts=SequentialSalts())
    saved = subject.belief_record(clock=FakeClock(run=Ref(RefKind.RUN, "r")),
                                 ids=SequentialIds(), ledger=ledger)
    wrong = replace(saved, body=replace(saved.body, contract=HAND_BELIEF))
    other = Ledger(salts=SequentialSalts())
    entry = other.append(wrong, ())
    with pytest.raises(ValueError, match="incompatible contract"):
        Agent.restore(model=model, lineage="unreachable", ledger=other, belief=entry.cid)
