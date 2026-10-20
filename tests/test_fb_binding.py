"""区間の報告の結びつき B (紙 F-b §6-8、段 1)。公開の Boot・仕事の口・settle から確かめる。

期待値は試験で与えた時刻 (入場・Started・報告の受信 r・実適用) から決める。B を内部へ注入しない。
負例ごとに、最も近い合法例を隣に置く (同じ形で 1 か所だけ違う)。
"""

from dataclasses import replace
from itertools import permutations
from threading import Event

import pytest

from sui import f, fb
from sui import fb_contracts as c
from test_fb_skeleton import boot, contract, segment_items, source
from test_fb_stage1 import accept_and_save, make_rig, pump_window, wire

ENTER, APPLIED = 200, 100   # 仕事の入場の M の読み / route の実適用 (Boot を受けた時の時計)


@pytest.fixture
def rig():
    result = make_rig()
    try:
        yield result
    finally:
        result.workers.release.set()


def install(rig, reading=c.FINITE_SEGMENT_PROJECTION):
    event = boot(False)
    route = event.declaration.routes[0]
    event = replace(event, declaration=replace(event.declaration, routes=(
        replace(route, value=replace(route.value, reading_contract=reading)),)))
    rig.boot_input = event
    clock_event = fb.ClockDeclared(declaration=replace(source(), run=rig.clock.run))
    accept_and_save(rig, rig.envelope(100, clock_event, 10), c.CLOCK_NOTICE, 1)  # §6-9 K1
    rig.host.window.accept(rig.envelope(101, event, 11))
    pump_window(rig, lambda: len(rig.facts(c.SEGMENT_REQUESTED)) == 1)
    rig.source = rig.facts(contract("sui.clock.source"))[0].cid


def interval(rig, start, end):
    return f.MeasurementInterval(clock=rig.clock.run, start_ns=start, end_ns=end, closure="(start,end]")


def started(rig, ns, slot="start"):
    return lambda work: fb.SegmentReport(segment=work.request, item_slot=slot, item=fb.SegmentBoundary(
        kind="started", work=work.desc.work_id, reason="test start", evidence=(),
        reading=fb.ReadingClock(source=rig.source, reading=f.ClockReading(run=rig.clock.run, time_ns=ns))))


def frame(rig, start, end, actual, slot="frame"):
    item = replace(segment_items()["frame"], measurement_interval=interval(rig, start, end),
                   actual_time=f.ClockReading(run=rig.clock.run, time_ns=actual))
    return lambda work: fb.SegmentReport(segment=work.request, item_slot=slot, item=item)


def branch(rig, tag, start, end, slot=None, **changes):
    item = segment_items()[tag]
    field = "requested_interval" if tag == "measurement_unavailable" else "interval"
    item = replace(item, **{field: interval(rig, start, end), "evidence": (), **changes})
    return lambda work: fb.SegmentReport(segment=work.request, item_slot=slot or tag, item=item)


def measure(rig, steps):
    """steps = [(時計の ns, 報告を作る関数)]。測る仕事の口から順に報告する。Event は試験の合図を待つ。"""
    def action(work, ctx, witness):
        rig.work = work
        for step in steps:
            if isinstance(step, Event):
                assert step.wait(3), "test gate not released"
                continue
            ns, make = step
            rig.set_clock(ns)
            witness.report(ctx, make(work))
    rig.set_clock(ENTER)
    rig.workers.action = action


def report_cid(rig, slot):
    found = [x.cid for x in rig.facts(c.SEGMENT_REPORT) if x.value["item_slot"] == slot]
    assert len(found) == 1
    return found[0]


def held(status, cid):
    return [(p.kind, p.reason) for p in status.pending if p.target == cid]


def run_until(rig, reached):
    assert rig.host.run_until(lambda status: reached(status), timeout=3), "witness not reached"


def settled(rig, slot, count):
    """slot の報告が保存され、B が count 個になるか、その報告に不足が付くまで回す。"""
    def reached(status):
        try:
            cid = report_cid(rig, slot)
        except AssertionError:
            return False
        return len(rig.facts(c.SEGMENT_BINDING)) == count or bool(held(status, cid))
    run_until(rig, reached)
    return report_cid(rig, slot)


def bindings(rig):
    return rig.facts(c.SEGMENT_BINDING)


def test_frame_binding_content_and_parents(rig):
    install(rig)
    measure(rig, [(210, started(rig, 210)), (230, frame(rig, 215, 225, 220))])
    frame_cid = settled(rig, "frame", 1)
    (b,) = bindings(rig)
    k = rig.facts(c.SEGMENT_REQUESTED)[0].cid
    route = rig.facts(contract("sui.f.route_config"))[0].cid
    start = report_cid(rig, "start")
    assert b.value["segment"] == k and b.value["report"] == frame_cid and b.value["route"] == route
    assert b.value["reading_contract"] == wire(c.FINITE_SEGMENT_PROJECTION)
    assert b.value["generation"] == {"applied": route, "started": start, "ended": None}
    assert b.value["clock"] == [rig.source] and b.value["evidence"] == []
    # Front: route は k の祖先、時計源は route の祖先なので消える
    assert b.parents == frozenset({k, frame_cid, start})
    assert set(b.value["view"]["boundary"]) == {k, frame_cid, route, start, rig.source}
    assert held(rig.host.window.status(), frame_cid) == []


def test_started_arriving_later_binds_on_a_later_settle(rig):
    install(rig)
    gate = Event()
    # 実際の開始 210 の Started が、同じ仕事の口から保存だけ後で届く
    measure(rig, [(230, frame(rig, 215, 225, 220)), gate, (240, started(rig, 210))])
    frame_cid = settled(rig, "frame", 1)
    assert not bindings(rig)
    assert held(rig.host.window.status(), frame_cid) == [("awaiting_evidence", "started")]
    gate.set()
    run_until(rig, lambda status: len(bindings(rig)) == 1)
    assert bindings(rig)[0].value["generation"]["started"] == report_cid(rig, "start")
    assert held(rig.host.window.status(), frame_cid) == []


@pytest.mark.parametrize("start_ns,ok", ((ENTER, True), (ENTER - 1, False)))
def test_started_before_the_observed_entry_is_not_bound(rig, start_ns, ok):
    """過去に偽った Started (ホストが観測した入場より前) を結びつけない。"""
    install(rig)
    measure(rig, [(210, started(rig, start_ns)), (230, frame(rig, 215, 225, 220))])
    frame_cid = settled(rig, "frame", 1)
    assert len(bindings(rig)) == (1 if ok else 0)
    assert held(rig.host.window.status(), frame_cid) == ([] if ok else [("conflict", "started:time")])


@pytest.mark.parametrize("end,ok", ((230, True), (231, False)))
def test_completion_window_uses_the_report_receipt(rig, end, ok):
    """end ≤ 原報告の受信 r (230)。B を作る時刻が後でも緩めない。"""
    install(rig)
    measure(rig, [(210, started(rig, 210)), (230, frame(rig, 215, end, 220))])
    frame_cid = settled(rig, "frame", 1)
    rig.set_clock(500)
    rig.host.window.settle()
    assert len(bindings(rig)) == (1 if ok else 0)
    assert held(rig.host.window.status(), frame_cid) == ([] if ok else [("conflict", "interval:after_receipt")])


@pytest.mark.parametrize("actual,ok", ((210, True), (209, False)))
def test_frame_actual_time_not_before_started(rig, actual, ok):
    install(rig)
    measure(rig, [(210, started(rig, 210)), (230, frame(rig, 200, 225, actual))])
    frame_cid = settled(rig, "frame", 1)
    assert len(bindings(rig)) == (1 if ok else 0)
    assert held(rig.host.window.status(), frame_cid) == ([] if ok else [("conflict", "frame:actual_time")])


@pytest.mark.parametrize("start,ok", ((210, True), (209, False)))
def test_no_arrival_claim_needs_the_whole_window_after_started(rig, start, ok):
    install(rig)
    measure(rig, [(210, started(rig, 210)), (230, branch(rig, "claim", start, 225))])
    claim = settled(rig, "claim", 1)
    assert len(bindings(rig)) == (1 if ok else 0)
    assert held(rig.host.window.status(), claim) == ([] if ok else [("conflict", "claim:window")])


def test_unknown_claim_contract_is_missing_not_guessed(rig):
    install(rig)
    measure(rig, [(210, started(rig, 210)),
                  (230, branch(rig, "claim", 215, 225, contract=contract("test.unknown_claim")))])
    claim = settled(rig, "claim", 1)
    assert not bindings(rig)
    assert held(rig.host.window.status(), claim) == [("missing_contract", "claim:contract")]


@pytest.mark.parametrize("tag,ok", (("coverage_unproved", True), ("measurement_unavailable", False),
                                    ("gap", False)))
def test_only_unproved_may_name_a_future_window(rig, tag, ok):
    install(rig)
    measure(rig, [(210, started(rig, 210)), (230, branch(rig, tag, 215, 260))])
    cid = settled(rig, tag, 1)
    assert len(bindings(rig)) == (1 if ok else 0)
    assert held(rig.host.window.status(), cid) == ([] if ok else [("conflict", "interval:after_receipt")])


def test_past_gap_is_bound_without_a_started_before_its_window(rig):
    """過去の Gap に「今の Started が窓の始まり以前」を課さない。"""
    install(rig)
    measure(rig, [(210, started(rig, 210)), (230, branch(rig, "gap", 150, 205))])
    settled(rig, "gap", 1)
    assert len(bindings(rig)) == 1


def test_undeclared_reading_contract_keeps_measuring_without_binding(rig):
    install(rig, reading=None)
    measure(rig, [(210, started(rig, 210)), (230, frame(rig, 215, 225, 220))])
    frame_cid = settled(rig, "frame", 1)
    assert not bindings(rig) and len(rig.facts(c.SEGMENT_REPORT)) == 2
    assert held(rig.host.window.status(), frame_cid) == [("missing_contract", "reading_contract")]


def test_report_naming_the_segment_from_outside_is_saved_but_not_bound(rig):
    install(rig)
    measure(rig, [(210, started(rig, 210))])
    run_until(rig, lambda status: len(rig.facts(c.SEGMENT_REPORT)) == 1)
    rig.set_clock(230)
    rig.host.post(frame(rig, 215, 225, 220, slot="outside")(rig.work))
    run_until(rig, lambda status: len(rig.facts(c.SEGMENT_REPORT)) == 2)
    rig.host.window.settle()
    assert not bindings(rig)
    assert held(rig.host.window.status(), report_cid(rig, "outside")) == []


def test_evidence_refs_resolve_to_saved_points(rig):
    install(rig)
    saved = rig.facts(contract("sui.clock.source"))[0]
    missing = replace(saved.record_id, value=saved.record_id.value + "-missing")
    measure(rig, [(210, started(rig, 210)),
                  (230, branch(rig, "gap", 215, 225, slot="good", evidence=(saved.record_id,))),
                  (231, branch(rig, "gap", 215, 225, slot="bad", evidence=(missing,)))])
    settled(rig, "bad", 1)
    run_until(rig, lambda status: len(bindings(rig)) == 1 and held(status, report_cid(rig, "bad")))
    (b,) = bindings(rig)
    assert b.value["report"] == report_cid(rig, "good") and b.value["evidence"] == [saved.cid]
    assert held(rig.host.window.status(), report_cid(rig, "bad")) == [("awaiting_evidence", f"evidence:{missing}")]


def test_rebuilding_the_window_does_not_rebind(rig):
    install(rig)
    measure(rig, [(210, started(rig, 210)), (230, frame(rig, 215, 225, 220))])
    settled(rig, "frame", 1)
    before = bindings(rig)
    rig.host.rebuild_window()
    rig.set_clock(300)
    rig.host.window.settle()
    rig.host.window.settle()
    assert bindings(rig) == before


# --- commit 前のレビュー (Codex `sui-fb-stage1-review` 1 通目) の R03・R04・R09 ---

@pytest.mark.parametrize("epoch,ok", (("route-A", True), ("route-B", False)))
def test_report_of_another_route_is_not_bound(rig, epoch, ok):
    install(rig)
    item = replace(segment_items()["frame"], route_epoch=epoch,
                   measurement_interval=interval(rig, 215, 225),
                   actual_time=f.ClockReading(run=rig.clock.run, time_ns=220))
    measure(rig, [(210, started(rig, 210)),
                  (230, lambda work: fb.SegmentReport(segment=work.request, item_slot="frame", item=item))])
    frame_cid = settled(rig, "frame", 1)
    assert len(bindings(rig)) == (1 if ok else 0)
    assert held(rig.host.window.status(), frame_cid) == ([] if ok else [("conflict", "route:epoch")])


@pytest.mark.parametrize("second_slot,ok", (("other", True), ("same", False)))
def test_same_slot_with_different_branches_is_a_conflict(rig, second_slot, ok):
    install(rig)
    measure(rig, [(210, started(rig, 210)), (230, branch(rig, "gap", 215, 225, slot="same")),
                  (231, branch(rig, "measurement_unavailable", 215, 225, slot=second_slot))])
    run_until(rig, lambda status: len(rig.facts(c.SEGMENT_REPORT)) == 3
              and (len(bindings(rig)) == 2 or len(status.pending) == 2))
    assert len(bindings(rig)) == (2 if ok else 0)
    if not ok:
        assert sorted(p.reason for p in rig.host.window.status().pending) == ["report:identity"] * 2


def test_redelivered_started_is_one_logical_report(rig):
    install(rig)
    measure(rig, [(210, started(rig, 210)), (215, started(rig, 210, slot="start-again")),
                  (230, frame(rig, 215, 225, 220))])
    settled(rig, "frame", 1)
    (b,) = bindings(rig)
    assert b.value["generation"]["started"] == report_cid(rig, "start")   # 受付の順の最初


@pytest.mark.parametrize("resolvable", (True, False))
def test_frame_inner_gap_evidence_is_resolved(rig, resolvable):
    install(rig)
    saved = rig.facts(contract("sui.clock.source"))[0]
    ref = saved.record_id if resolvable else replace(saved.record_id, value=saved.record_id.value + "-missing")
    gap = replace(segment_items()["gap"], interval=interval(rig, 215, 218), evidence=(ref,))
    item = replace(segment_items()["frame"], measurement_interval=interval(rig, 215, 225), gap=gap,
                   actual_time=f.ClockReading(run=rig.clock.run, time_ns=220))
    measure(rig, [(210, started(rig, 210)),
                  (230, lambda work: fb.SegmentReport(segment=work.request, item_slot="frame", item=item))])
    frame_cid = settled(rig, "frame", 1)
    if resolvable:
        assert bindings(rig)[0].value["evidence"] == [saved.cid]
    else:
        assert not bindings(rig)
        assert held(rig.host.window.status(), frame_cid) == [("awaiting_evidence", f"evidence:{ref}")]


# --- 2 周目のレビュー (R16〜R18) ---

@pytest.mark.parametrize("second_seq,ok", ((1, True), (0, False)))
def test_same_sample_seq_naming_two_measurements_is_a_conflict(rig, second_seq, ok):
    install(rig)
    base = segment_items()["frame"]

    def make(seq, origin, slot):
        mid = replace(base.measurement_id, origin=replace(base.measurement_id.origin, value=origin), sample_seq=seq)
        item = replace(base, sample_seq=seq, measurement_id=mid, measurement_interval=interval(rig, 215, 225),
                       actual_time=f.ClockReading(run=rig.clock.run, time_ns=220))
        return lambda work: fb.SegmentReport(segment=work.request, item_slot=slot, item=item)
    measure(rig, [(210, started(rig, 210)), (230, make(0, "origin-1", "f1")), (231, make(second_seq, "origin-2", "f2"))])
    run_until(rig, lambda status: len(rig.facts(c.SEGMENT_REPORT)) == 3
              and (len(bindings(rig)) == 2 or len(status.pending) == 2))
    assert len(bindings(rig)) == (2 if ok else 0)
    if not ok:
        assert sorted(p.reason for p in rig.host.window.status().pending) == ["frame:sample_seq"] * 2


@pytest.mark.parametrize("gap_interval,ok", (((215, 218, "run"), True), ((218, 215, "run"), False),
                                             ((215, 218, "other"), False)))
def test_frame_inner_gap_window_and_clock(rig, gap_interval, ok):
    install(rig)
    start, end, run = gap_interval
    clock = rig.clock.run if run == "run" else replace(rig.clock.run, value="another-run")
    gap = replace(segment_items()["gap"], evidence=(),
                  interval=f.MeasurementInterval(clock=clock, start_ns=start, end_ns=end, closure="(start,end]"))
    item = replace(segment_items()["frame"], measurement_interval=interval(rig, 215, 225), gap=gap,
                   actual_time=f.ClockReading(run=rig.clock.run, time_ns=220))
    measure(rig, [(210, started(rig, 210)),
                  (230, lambda work: fb.SegmentReport(segment=work.request, item_slot="frame", item=item))])
    frame_cid = settled(rig, "frame", 1)
    assert len(bindings(rig)) == (1 if ok else 0)
    assert held(rig.host.window.status(), frame_cid) == ([] if ok else [("conflict", "interval:clock")])


def test_representative_is_the_first_accepted_delivery(rig):
    install(rig)
    gate = Event()
    measure(rig, [(210, started(rig, 210)), gate])
    rig.workers.action, action = None, rig.workers.action

    def keep_ctx(work, ctx, witness):
        rig.ctx = ctx
        action(work, ctx, witness)
    rig.workers.action = keep_ctx
    run_until(rig, lambda status: len(rig.facts(c.SEGMENT_REPORT)) == 1)
    event = frame(rig, 215, 225, 220)(rig.work)
    rig.set_clock(230)
    rig.ctx.post(event)
    rig.set_clock(231)
    rig.ctx.post(event)   # 同じ Frame の再配送
    queued = [x for x in rig.host.window.status().receipts if x.state == "received"]
    assert len(queued) == 2
    # Post の逆順で受け付ける
    for item in reversed(queued):
        rig.host.window.accept(fb.Envelope(number=item.envelope, event=event, received_ns=item.received_ns))
        rig.host.window.settle()
    (b,) = bindings(rig)
    second = [x.cid for x in rig.facts(c.SEGMENT_REPORT) if x.received_ns == 231]
    assert b.value["report"] == second[0]
    gate.set()


# --- 3 周目のレビュー (R20・R22): 結びつきは保存した報告の集まりで決まり、受付の順に依らない ---

def stash(rig):
    """測る仕事に入場させ、その口を持ったまま止めておく。報告の Post と受付の順は試験が選ぶ。"""
    gate = Event()
    measure(rig, [gate])
    action = rig.workers.action

    def keep(work, ctx, witness):
        rig.ctx = ctx
        action(work, ctx, witness)
    rig.workers.action = keep
    run_until(rig, lambda status: hasattr(rig, "work"))
    return gate


def deliver(rig, posts, order):
    """posts = [(r, 報告を作る関数)] を仕事の口から Post し、order の順で全部受け付けてから settle する。"""
    events = []
    for r, make in posts:
        rig.set_clock(r)
        events.append(make(rig.work))
        rig.ctx.post(events[-1])
    queued = sorted((x for x in rig.host.window.status().receipts if x.state == "received"),
                    key=lambda x: x.envelope)
    assert [x.received_ns for x in queued] == [r for r, _ in posts]
    rig.set_clock(max(r for r, _ in posts) + 10)
    for i in order:
        rig.host.window.accept(fb.Envelope(number=queued[i].envelope, event=events[i],
                                           received_ns=queued[i].received_ns))
    for _ in range(3):
        rig.host.window.settle()


def outcome(rig):
    """論理の報告 (item_slot) ごとに: 結びついた slot と、不足の (slot, 理由)。"""
    slots = {x.cid: x.value["item_slot"] for x in rig.facts(c.SEGMENT_REPORT)}
    bound = sorted({slots[b.value["report"]] for b in bindings(rig)})
    pending = sorted({(slots[p.target], p.reason) for p in rig.host.window.status().pending if p.target in slots})
    return bound, pending


def measured(rig, origin, seq, slot, mid_seq=None, epoch="route-A"):
    base = segment_items()["frame"]
    mid = replace(base.measurement_id, origin=replace(base.measurement_id.origin, value=origin),
                  sample_seq=seq if mid_seq is None else mid_seq, route_epoch=epoch)
    item = replace(base, route_epoch=epoch, sample_seq=seq, measurement_id=mid,
                   measurement_interval=interval(rig, 215, 225),
                   actual_time=f.ClockReading(run=rig.clock.run, time_ns=220))
    return lambda work: fb.SegmentReport(segment=work.request, item_slot=slot, item=item)


SEQ = "frame:sample_seq"


def scene(rig, name):
    """(posts, 期待する結果)。負例の隣に、1 か所だけ違う合法例を置く。"""
    a0, b1 = measured(rig, "origin-a", 0, "a0"), measured(rig, "origin-b", 1, "b1")
    a1 = measured(rig, "origin-a", 1, "a1", mid_seq=0)   # a0 と同じ MeasurementId で sample_seq だけ違う
    return {
        # R22: a1 が b1 と同じ sample_seq を指す。代表に縮めず全配送で数える
        "seq": ([(211, started(rig, 210)), (230, a0), (231, a1), (232, b1)],
                ([], [("a0", SEQ), ("a1", SEQ), ("b1", SEQ)])),
        "seq_legal": ([(211, started(rig, 210)), (230, a0), (231, b1), (232, a0)], (["a0", "b1"], [])),
        # 別の route の同じ sample_seq は排他の単位が違う (route の照合で止まるだけ)
        "seq_other_route": ([(211, started(rig, 210)), (230, measured(rig, "origin-b", 0, "z0", epoch="route-z")),
                             (231, a0)], (["a0"], [("z0", "route:epoch")])),
        # 完了窓 end ≤ r は届いた全配送で (最も早い r)。後の再配送で通さない
        "window": ([(211, started(rig, 210)), (224, frame(rig, 215, 225, 220)), (240, frame(rig, 215, 225, 220))],
                   ([], [("frame", "interval:after_receipt")])),
        "window_legal": ([(211, started(rig, 210)), (226, frame(rig, 215, 225, 220)),
                          (240, frame(rig, 215, 225, 220))], (["frame"], [])),
        # Started の読み ≤ 自分の受信 r も全配送で
        "started": ([(211, started(rig, 212)), (213, started(rig, 212)), (230, frame(rig, 215, 225, 220))],
                    ([], [("frame", "started:time")])),
        "started_legal": ([(212, started(rig, 212)), (213, started(rig, 212)), (230, frame(rig, 215, 225, 220))],
                          (["frame"], [])),
    }[name]


SCENES = {"seq": 4, "seq_legal": 4, "seq_other_route": 3, "window": 3, "window_legal": 3, "started": 3, "started_legal": 3}


@pytest.mark.parametrize("name,order", [(name, order) for name, n in SCENES.items()
                                        for order in permutations(range(n))])
def test_binding_depends_on_the_saved_reports_not_the_accept_order(rig, name, order):
    install(rig)
    gate = stash(rig)
    posts, expected = scene(rig, name)
    deliver(rig, posts, order)
    assert outcome(rig) == expected
    gate.set()


def test_report_from_a_launch_without_the_ticket_is_not_bound():
    from threading import Thread
    from test_fb_host import LyingLauncher
    launcher = LyingLauncher()
    rig = make_rig(launcher=launcher)
    try:
        install(rig)
        gate = Event()
        measure(rig, [(210, started(rig, 210)), (230, frame(rig, 215, 225, 220)), gate])
        run_until(rig, lambda status: len(launcher.bodies) == 2)
        current = Thread(target=launcher.bodies[1])   # 今の占有を持つ起動
        current.start()
        frame_cid = settled(rig, "frame", 1)
        # not_started と答えた古い起動の本体: 札は取れないが、口から報告を出す
        rig.workers.run = lambda work, ctx: (ctx.enter(), ctx.post(branch(rig, "gap", 212, 218, slot="ghost")(work)))
        rig.set_clock(240)
        launcher.bodies[0]()
        run_until(rig, lambda status: any(x.value["item_slot"] == "ghost" for x in rig.facts(c.SEGMENT_REPORT)))
        for _ in range(3):
            rig.host.window.settle()
        ghost = report_cid(rig, "ghost")   # 原報告としては保存される
        assert [b.value["report"] for b in bindings(rig)] == [frame_cid]
        assert held(rig.host.window.status(), ghost) == []
        gate.set()
        current.join(3)
    finally:
        rig.workers.release.set()


# --- 5 周目のレビュー (R26): 固定長の tuple は要素の数も形 ---

@pytest.mark.parametrize("inner", (False, True))
@pytest.mark.parametrize("seq_range,ok", (((), False), ((7,), False), ((7, 8), True), ((7, 8, 9), False)))
def test_gap_sequence_range_has_exactly_two_ints(rig, inner, seq_range, ok):
    install(rig)
    k = rig.facts(c.SEGMENT_REQUESTED)[0].cid
    gap = replace(segment_items()["gap"], sequence_range=seq_range, evidence=(),
                  interval=interval(rig, 212, 218))
    item = replace(segment_items()["frame"], measurement_interval=interval(rig, 215, 225), gap=gap,
                   actual_time=f.ClockReading(run=rig.clock.run, time_ns=220)) if inner else gap
    envelope = rig.envelope(500, fb.SegmentReport(segment=k, item_slot="x", item=item), 230)
    rig.set_clock(240)
    if ok:
        assert rig.host.window.accept(envelope) is None
    else:
        with pytest.raises(fb.FbInputError) as caught:
            rig.host.window.accept(envelope)
        assert caught.value.reason == "shape" and caught.value.field == "/item"   # 枝の和は和の位置で示す
