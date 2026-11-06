"""信念の更新の入口 U (`sui.f_update2.compute_finite_update`) の試験。段 3 の最初の輪の 3 本目。

U が読むのは読み手の `record(point)` だけなので、記録の束を手で並べた小さな読み手で確かめる
(窓口・台帳を通す道は 4 本目の公開の入口からの試験)。答え合わせは紙 F-b の CE1 (:3497)。
"""

from fractions import Fraction as F
from hashlib import sha256
from types import SimpleNamespace

import pytest

from sui import f, fb_contracts as c, f_update2 as u
from sui._f_handles import require_issued
from sui.contracts import ContractRef
from sui.ids import Ref, RefKind

RUN = Ref(RefKind.RUN, "run-1")
MODEL_CONTRACT = ContractRef("test.model", "1")
FIRST = {"joint": [[4, 5], [1, 5]], "evidence_mass": [5, 32]}
SECOND = {"joint": [[8, 9], [1, 9]], "evidence_mass": [9, 128]}
DOUBLE = {"joint": [[16, 17], [1, 17]], "evidence_mass": [17, 512]}
CE1_ROWS = (
    ((0, 0, 0), F(1, 8), F(1, 64)), ((0, 0, 1), F(1, 8), F(3, 64)),
    ((0, 1, 0), F(1, 8), F(3, 64)), ((0, 1, 1), F(1, 8), F(9, 64)),
    ((1, 0, 0), F(1, 8), F(3, 64)), ((1, 0, 1), F(1, 8), F(9, 64)),
    ((1, 1, 0), F(1, 8), F(9, 64)), ((1, 1, 1), F(1, 8), F(27, 64)),
)


def point(label):
    return "sha256:" + sha256(label.encode()).hexdigest()


def enc(value):
    return f._encode(value)


def plain(value):
    if hasattr(value, "items"):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    return value


def interval(start, end):
    return f.MeasurementInterval(clock=RUN, start_ns=start, end_ns=end, closure="(start,end]")


class Reader:
    """記録の束。U は `record(point)` の body.contract と body.content.as_json() だけを読む。"""

    def __init__(self):
        self.records = {}

    def put(self, label, contract, content):
        self.records[point(label)] = SimpleNamespace(body=SimpleNamespace(
            contract=contract, content=SimpleNamespace(as_json=lambda content=content: content)))
        return point(label)

    def record(self, cid):
        return self.records[cid]


PROCESS = {"declaration": point("boot"), "slot": "sensing"}


def world(*, initial=((1, 2), (1, 2))):
    """CE1 の世界: モデル・法則・読み方・測る要求 K と、重なる 2 つの「到着なし」の報告とその結びつき B。"""
    r = Reader()
    model = r.put("model", MODEL_CONTRACT, {"document": {"initial": [list(q) for q in initial]}})
    route = r.put("route", ContractRef("sui.f.route_config", "1"), {})
    k = r.put("k", c.SEGMENT_REQUESTED, {"desc": {"process": PROCESS}})
    law = r.put("law", c.FINITE_JOINT_COUNT_LAW, {
        "model": model, "extends": None, "carrier_by_state": ["a", "b"],
        "channels": [{"id": "arrivals", "process": PROCESS, "route_configs": [route],
                      "domain": enc(interval(0, 3))}],
        "rows": [{"marks": [{"channel": "arrivals", "time_ns": i + 1, "count": n} for i, n in enumerate(bits) if n],
                  "mass": [enc(a), enc(b)]} for bits, a, b in CE1_ROWS],
        "frame_relation": "independent_given_carrier"})
    reading = r.put("reading", c.OBSERVATION_PLAN_2, plan_content(model, law))
    for name, (start, end) in {"1": (0, 2), "2": (1, 3)}.items():
        claim(r, "report" + name, k, "slot" + name, interval(start, end))
        binding(r, "b" + name, k, point("report" + name), route)
    return r, SimpleNamespace(model=model, route=route, k=k, law=law, reading=reading)


def plan_content(model, law, *, meaning=c.NO_ARRIVAL, channel="arrivals"):
    return {"model": model,
            "projection": {"contract": enc(c.FINITE_SEGMENT_PROJECTION), "args": {
                "frame": None, "claims": [{"meaning": enc(meaning), "law": law, "channel": channel}],
                "time_projection": {"contract": enc(c.SEGMENT_VALUE_ONLY), "args": {}}}},
            "generation": {"contract": enc(c.BOOTSTRAP_GENERATION), "args": {"scope": "whole_window"}}}


def claim(r, label, k, item_slot, span, *, contract=c.NO_ARRIVAL, kind="no_arrival"):
    value = f.CoverageClaim(route_epoch="route-A", interval=span, kind=kind, contract=contract, evidence=())
    return r.put(label, c.SEGMENT_REPORT, {"segment": k, "item_slot": item_slot,
                                           "item": {"kind": "claim", "value": enc(value)}})


def binding(r, label, k, report, route):
    return r.put(label, c.SEGMENT_BINDING, {"segment": k, "report": report, "route": route,
                                            "reading_contract": enc(c.FINITE_SEGMENT_PROJECTION)})


def request(r, label, w, bindings, *, prior=None, reading=None, purpose="belief_update",
            method=c.FINITE_UPDATE_COMPUTE):
    uses = [{"binding": point(b), "reading": w.reading if reading is None else reading} for b in bindings]
    return r.put(label, c.WORK_REQUESTED, {"desc": {
        "purpose": purpose, "method": enc(method), "reader": point("origin"),
        "args": {"model": w.model, "prior": prior, "observations": uses},
        "numerical_view": {"boundary": sorted([w.model, w.law]),
                           "environment": {"reader_view_key": "view-" + label, "registry_key": None}}}})


def compute(r, q):
    return u.compute_finite_update(q, reader=r, registry=f.builtin_f_registry(), evidence=None)


def adopt(r, label, w, q, issued, *, previous=None):
    """発行物から R* と A* を保存する (窓口の代わり)。"""
    result = r.put("R-" + label, c.UPDATE_RESULT, {"request": q, "result": plain(issued.result),
                                                    "application_digest": issued.application_digest})
    return r.put("A-" + label, c.BELIEF_ADOPTED, {"origin": point("origin"), "model": w.model, "previous": previous,
                                                   "request": q, "result": result, "acquisition": point("G-" + label)})


def two_updates():
    r, w = world()
    q1 = request(r, "q1", w, ["b1"])
    first = compute(r, q1)
    a1 = adopt(r, "1", w, q1, first)
    q2 = request(r, "q2", w, ["b2"], prior=a1)
    return r, w, q1, first, a1, q2


def test_ce1_first_update_from_the_models_initial_belief():
    """採用がまだ無い (prior=None) 1 回目は、モデルの initial から (4/5, 1/5; 5/32)。"""
    r, w = world()
    q1 = request(r, "q1", w, ["b1"])
    issued = compute(r, q1)
    assert isinstance(issued, u.IssuedUpdate) and issued.request == q1
    assert plain(issued.result) == FIRST


def test_ce1_second_update_replays_the_adopted_series_and_counts_the_overlap_once():
    """前の採用からの 2 回目は (8/9, 1/9; 9/128)。重なりを二重に数えた値にも、2 回目を落とした値にもならない。"""
    r, w, q1, first, a1, q2 = two_updates()
    second = compute(r, q2)
    assert isinstance(second, u.IssuedUpdate) and second.request == q2
    assert plain(second.result) == SECOND
    assert plain(second.result) not in (FIRST, DOUBLE)
    assert second.application_digest != first.application_digest


def test_prior_none_ignores_any_earlier_adoption():
    """prior=None の要求は、台帳に採用があっても initial から計算する (前の結果を勝手に拾わない)。"""
    r, w, q1, first, a1, q2 = two_updates()
    fresh = request(r, "fresh", w, ["b2"])
    assert plain(compute(r, fresh).result) == FIRST   # E2 単独も 2 点の到着なしで同じ値


def test_same_claim_delivered_again_is_a_numerical_noop():
    """同じ原 Claim (同じ segment・item_slot) の別の結びつき B は新しい出来事にしない。"""
    r, w, q1, first, a1, q2 = two_updates()
    binding(r, "b1-again", w.k, point("report1"), w.route)
    again = request(r, "again", w, ["b1-again"], prior=a1)
    issued = compute(r, again)
    assert plain(issued.result) == FIRST
    assert issued.application_digest == first.application_digest


def test_two_observations_in_one_request_equal_two_requests():
    r, w = world()
    both = request(r, "both", w, ["b1", "b2"])
    assert plain(compute(r, both).result) == SECOND


def test_initial_belief_is_read_from_the_model_record():
    """initial を変えると結果が変わる (定数を返していない)。(1/4, 3/4) からの 1 回目は (4/7, 3/7; 7/64)。"""
    r, w = world(initial=((1, 4), (3, 4)))
    issued = compute(r, request(r, "q", w, ["b1"]))
    assert plain(issued.result) == {"joint": [[4, 7], [3, 7]], "evidence_mass": [7, 64]}


def test_issued_update_is_bound_to_request_view_and_registry_and_cannot_be_forged():
    r, w = world()
    q1 = request(r, "q1", w, ["b1"])
    issued = compute(r, q1)
    require_issued(issued, u.IssuedUpdate)
    assert issued.numerical_view == u.FixedViewValue(
        boundary=frozenset({w.model, w.law}), reader_view_key="view-q1", registry_key=None)
    from sui._f_world import registry_view_key
    assert issued.registry_key == registry_view_key(f.builtin_f_registry())
    with pytest.raises(TypeError):
        u.IssuedUpdate(request=q1, result=issued.result, application_digest=issued.application_digest,
                       numerical_view=issued.numerical_view, registry_key=issued.registry_key)


def test_saved_result_that_differs_from_recomputation_is_rejected():
    """前の採用が指す R* の値が作り直しと違えば、その上に更新を積まない。"""
    r, w, q1, first, a1, q2 = two_updates()
    r.put("R-1", c.UPDATE_RESULT, {"request": q1, "result": DOUBLE,
                                   "application_digest": first.application_digest})
    out = compute(r, q2)
    assert isinstance(out, u.Rejected) and out.request == q2
    assert [i.code for i in out.issues] == ["result_mismatch"]
    assert out.issues[0].evidence == frozenset({point("R-1")})


def test_saved_result_of_another_request_is_rejected():
    r, w, q1, first, a1, q2 = two_updates()
    r.put("R-1", c.UPDATE_RESULT, {"request": point("someone-else"), "result": plain(first.result),
                                   "application_digest": first.application_digest})
    assert [i.code for i in compute(r, q2).issues] == ["result_mismatch"]


def test_adoption_that_does_not_continue_its_requests_prior_is_rejected():
    r, w, q1, first, a1, q2 = two_updates()
    second = compute(r, q2)
    a2 = adopt(r, "2", w, q2, second, previous=None)   # 正しくは previous=a1
    q3 = request(r, "q3", w, ["b1"], prior=a2)
    assert [i.code for i in compute(r, q3).issues] == ["result_mismatch"]
    good = adopt(r, "2", w, q2, second, previous=a1)
    assert plain(compute(r, request(r, "q3", w, ["b1"], prior=good)).result) == SECOND


@pytest.mark.parametrize("change, code", [
    ("reading_model", "observation_binding_mismatch"),
    ("reading_channel", "observation_binding_mismatch"),
    ("unknown_meaning", "missing_contract"),
    ("claim_kind", "missing_contract"),
    ("frame_item", "missing_contract"),
    ("law_extends", "missing_contract"),
    ("claim_outside_domain", "shape"),
    ("binding_outside", "unresolved_reference"),
    ("binding_wrong_kind", "reference_kind"),
])
def test_wrong_records_are_rejected_with_a_reason(change, code):
    """正しくない記録は成功にも例外にもせず、理由つきの Rejected にする。最も近い合法の形 (world()) は通る。"""
    r, w = world()
    bindings, reading = ["b1"], None
    if change == "reading_model":
        reading = r.put("other-reading", c.OBSERVATION_PLAN_2, plan_content(point("other-model"), w.law))
    elif change == "reading_channel":
        reading = r.put("other-reading", c.OBSERVATION_PLAN_2, plan_content(w.model, w.law, channel="elsewhere"))
    elif change == "unknown_meaning":
        claim(r, "report1", w.k, "slot1", interval(0, 2), contract=c.COUNT_EXACTLY_ONE, kind="count_exactly_one")
        reading = r.put("other-reading", c.OBSERVATION_PLAN_2,
                        plan_content(w.model, w.law, meaning=c.COUNT_EXACTLY_ONE))
    elif change == "claim_kind":
        claim(r, "report1", w.k, "slot1", interval(0, 2), kind="count_exactly_one")
    elif change == "frame_item":
        r.put("report1", c.SEGMENT_REPORT, {"segment": w.k, "item_slot": "slot1", "item": {"kind": "frame", "value": {}}})
    elif change == "law_extends":
        law = dict(r.record(w.law).body.content.as_json(), extends=point("older-law"))
        r.put("law", c.FINITE_JOINT_COUNT_LAW, law)
    elif change == "claim_outside_domain":
        claim(r, "report1", w.k, "slot1", interval(0, 4))
    elif change == "binding_outside":
        bindings = ["nowhere"]
    elif change == "binding_wrong_kind":
        r.put("b1", c.SEGMENT_REPORT, {})
    out = compute(r, request(r, "q", w, bindings, reading=reading))
    assert isinstance(out, u.Rejected) and [i.code for i in out.issues] == [code]
    assert isinstance(compute(*legal_request()), u.IssuedUpdate)


def legal_request():
    r, w = world()
    return r, request(r, "q", w, ["b1"])


def test_same_claim_read_as_a_different_predicate_is_a_conflict():
    """同じ原 Claim を、区間の違う別の命題として 2 回足さない (CL-APPLY)。"""
    r, w = world()
    claim(r, "report1-other", w.k, "slot1", interval(1, 3))   # 同じ (segment, item_slot)、別の区間
    binding(r, "b1-other", w.k, point("report1-other"), w.route)
    out = compute(r, request(r, "q", w, ["b1", "b1-other"]))
    assert isinstance(out, u.Rejected) and [i.code for i in out.issues] == ["measurement_conflict"]


@pytest.mark.parametrize("change", ["missing", "other_contract", "other_purpose", "other_method"])
def test_non_update_request_is_an_entrance_error_not_a_verdict(change):
    """更新の要求として構成できない入力は、三枝に写さず入口の例外にする。"""
    r, w = world()
    if change == "missing":
        q = point("nowhere")
    elif change == "other_contract":
        q = r.put("q", c.SEGMENT_REQUESTED, {"desc": {}})
    elif change == "other_purpose":
        q = request(r, "q", w, ["b1"], purpose="evaluation")
    else:
        q = request(r, "q", w, ["b1"], method=c.EVALUATE_FROM_DRAW)
    with pytest.raises(f.FInputError):
        compute(r, q)
