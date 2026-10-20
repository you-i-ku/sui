"""段 1 のホストの受付・起動の計画・仕事の開始 (紙 F-b §2-4-2・§2-5-3・§6-5)。commit 前のレビュー
(Codex `sui-fb-stage1-review` 1 通目) の反例 R01・R02・R05〜R08・R10・R11 を公開の入口から確かめる。
負例ごとに、最も近い合法例を隣に置く。
"""

from dataclasses import replace

import pytest

from sui import f, fb
from sui import fb_contracts as c
from sui.contracts import ContractRef
from test_fb_skeleton import DeclaredNeed, DeclaredWorkerMethod, WitnessLauncher, boot, contract, source
from test_fb_stage1 import RealRig, accept_and_save, make_rig, pump_window


def declare_clock(rig):
    clock_event = fb.ClockDeclared(declaration=replace(source(), run=rig.clock.run))
    accept_and_save(rig, rig.envelope(100, clock_event, 10), c.CLOCK_NOTICE, 1)  # §6-9 K1


def with_model(rig, event):
    return replace(event, declaration=replace(event.declaration, initial=replace(event.declaration.initial,
        value=replace(event.declaration.initial.value, model=rig.model_point))))


def pending(rig):
    return [(p.kind, p.reason) for p in rig.host.window.status().pending]


def settle_twice(rig):
    rig.host.window.settle()
    rig.host.window.settle()


@pytest.fixture
def rig():
    result = make_rig(initial=True)
    try:
        yield result
    finally:
        result.workers.release.set()


# --- R02: 受付の後に呼出し元が可変の値を変えても、受け付けた中身で進む ---

def test_boot_args_changed_after_accept_do_not_reach_qgen(rig):
    declare_clock(rig)
    args = {}
    event = with_model(rig, boot(True))
    initial = event.declaration.initial
    event = replace(event, declaration=replace(event.declaration, initial=replace(initial, value=replace(
        initial.value, generator=fb.MethodCall(contract=initial.value.generator.contract, args=args)))))
    rig.host.window.accept(rig.envelope(101, event, 11))
    args["unexpected"] = 1   # 受付の後の変更
    pump_window(rig, lambda: len(rig.facts(c.CANDIDATE_REQUEST)) == 1)
    assert rig.facts(c.CANDIDATE_REQUEST)[0].value["desc"]["args"]["generator_args"] == {}


def test_same_number_with_changed_claims_is_a_host_fault(rig):
    claims = {"sender_id": "same"}
    event = fb.Received(route_epoch="r", media_type="text/plain", data=b"x", claims=claims)
    rig.host.window.accept(rig.envelope(7, event, 11))
    rig.host.window.accept(rig.envelope(7, event, 11))   # 同じ中身の再提示は合法
    claims["sender_id"] = "other"
    with pytest.raises(fb.FbHostFault):
        rig.host.window.accept(rig.envelope(7, event, 11))


# --- R01: route_config の保存は、ホストの受け口の表への実適用と一緒 ---

def test_route_config_is_applied_to_the_host_routes(rig):
    declare_clock(rig)
    rig.set_clock(150)
    event = boot(False)
    rig.host.window.accept(rig.envelope(101, event, 11))
    pump_window(rig, lambda: len(rig.facts(c.SEGMENT_REQUESTED)) == 1)
    config = event.declaration.routes[0].value.config
    (saved,) = rig.facts(contract("sui.f.route_config"))
    assert rig.host._state.routes[config.route_epoch] == (config, 150)
    # 和型の包み {kind, value} (F-a A:29、段 2 で F-a が読めない形だったと分かった)
    assert saved.value["effective_from"] == {"kind": "clock", "value": {"run": str(rig.clock.run), "time_ns": 150}}


@pytest.mark.parametrize("same,ok", ((True, True), (False, False)))
def test_two_boots_cannot_apply_different_configs_to_one_route(rig, same, ok):
    declare_clock(rig)
    first = boot(False)
    rig.host.window.accept(rig.envelope(101, first, 11))
    pump_window(rig, lambda: len(rig.facts(c.SEGMENT_REQUESTED)) == 1)
    route = first.declaration.routes[0]
    config = route.value.config if same else replace(route.value.config, version="2")
    second = replace(first, declaration=replace(first.declaration, routes=(
        replace(route, value=replace(route.value, config=config)),)))
    rig.host.window.accept(rig.envelope(102, second, 12))
    settle_twice(rig)
    assert len(rig.facts(contract("sui.f.route_config"))) == (2 if ok else 1)
    assert (("missing_contract", "route:route:epoch_conflict") in pending(rig)) is not ok


# --- R08・R10・R11: 宣言の照合 ---

def test_ambiguous_slot_is_not_used(rig):
    declare_clock(rig)
    event = boot(False)
    route = event.declaration.routes[0]
    other = replace(route, value=replace(route.value, config=replace(route.value.config, route_epoch="route-B")))
    bad = replace(event, declaration=replace(event.declaration, routes=(route, other)))
    rig.host.window.accept(rig.envelope(101, bad, 11))
    settle_twice(rig)
    assert not rig.facts(c.SEGMENT_REQUESTED) and rig.host.window.status().works == ()
    assert ("missing_contract", "slot:ambiguous:route") in pending(rig)
    # 合法例: 位置の名前が違えば 2 本とも計画される (割当の slot も別にする)
    good_other = replace(other, slot="route-2", value=replace(other.value, process_slot="sensing-2",
        allocation=replace(other.value.allocation, slot="sensing-allocation-2")))
    good = replace(event, declaration=replace(event.declaration, routes=(route, good_other)))
    rig.host.window.accept(rig.envelope(102, good, 12))
    pump_window(rig, lambda: len(rig.facts(c.SEGMENT_REQUESTED)) == 2)
    assert len(rig.host.window.status().works) == 2


@pytest.mark.parametrize("name,ok", (("sui.fb.resource_scope", True), ("test.unknown_scope", False)))
def test_scope_contract_name_is_checked(rig, name, ok):
    declare_clock(rig)
    event = boot(False)
    scope = replace(event.declaration.scope, contract=ContractRef(name=name, version="1"))
    rig.host.window.accept(rig.envelope(101, replace(event, declaration=replace(event.declaration, scope=scope)), 11))
    settle_twice(rig)
    assert len(rig.facts(c.SEGMENT_REQUESTED)) == (1 if ok else 0)
    assert (("missing_contract", "scope") in pending(rig)) is not ok


@pytest.mark.parametrize("args,ok", (({}, True), ({"unexpected": 1}, False)))
def test_generator_args_are_checked_by_the_declared_args_contract(rig, args, ok):
    declare_clock(rig)
    event = with_model(rig, boot(True))
    initial = event.declaration.initial
    event = replace(event, declaration=replace(event.declaration, initial=replace(initial, value=replace(
        initial.value, generator=fb.MethodCall(contract=initial.value.generator.contract, args=args)))))
    rig.host.window.accept(rig.envelope(101, event, 11))
    pump_window(rig, lambda: len(rig.facts(contract("sui.f.knowledge_origin"))) == 1)
    settle_twice(rig)
    assert len(rig.facts(c.CANDIDATE_REQUEST)) == (1 if ok else 0)
    assert (("missing_contract", "initial:args") in pending(rig)) is not ok


# --- R07: Need の実装の一時の失敗で仕事の行を失わない ---

class FlakyNeed(DeclaredNeed):
    def __init__(self):
        self.calls = 0

    def __call__(self, *, args, input, context):
        self.calls += 1
        if self.calls == 1:
            raise OSError("test: need implementation temporarily failed")
        return super().__call__(args=args, input=input, context=context)


def registry_with(need):
    declarations, implementations = [], []
    for name, kind, callback, input_contract, output in (
        ("test.need", "method", need, c.NEED_INPUT, c.QUANTITY_VALUE),
        ("test.sampling", "measurement", DeclaredWorkerMethod(), contract("test.fixed_input"), c.SEGMENT_REPORT),
        ("test.clock", "clock", DeclaredWorkerMethod(), contract("test.fixed_input"), contract("sui.f.clock_reading")),
        ("test.loss", "measurement", DeclaredWorkerMethod(), contract("test.fixed_input"), c.SEGMENT_REPORT),
    ):
        declaration = f.CapabilityDeclaration(kind=kind, ref=contract(name),
            args_contract=ContractRef(name="sui.f.args.empty", version="1"), input_contract=input_contract,
            output_contract=output, dependencies=(), conditions=())
        declarations.append(declaration)
        implementations.append(f.CapabilityImplementation(kind=kind, ref=declaration.ref,
            implementation=callback, identity="sui.fb.tests.host/1:" + name))
    return f.make_f_registry(declarations=tuple(declarations), implementations=tuple(implementations))


def test_transient_need_failure_keeps_the_row_and_retries():
    rig = RealRig(connect=False)
    rig.registry = registry_with(FlakyNeed())
    rig.host = fb.FThreadHost(ledger=rig.ledger, clock=rig.clock, workers=rig.workers, registry=rig.registry)
    declare_clock(rig)
    rig.host.window.accept(rig.envelope(101, boot(False), 11))
    pump_window(rig, lambda: len(rig.facts(c.SEGMENT_REQUESTED)) == 1)
    (work,) = rig.host.window.status().works
    assert work.phase == "pending"
    rig.host.rebuild_window()
    rig.host.window.settle()
    (work,) = rig.host.window.status().works
    assert rig.host.window.drain() == (rig.host._state.works[work.work_id].work,)
    assert not [p for p in rig.host.window.status().pending if p.reason.startswith("need:")]


# --- R05・R06: 占有の確保は 1 件ずつ照合し直し、重複の起動の終わりで解放しない ---

def test_claims_recheck_fit_one_by_one():
    launcher = WitnessLauncher("launched")   # 本体は試験が呼ぶまで走らない
    rig = make_rig(initial=True, launcher=launcher)
    try:
        declare_clock(rig)
        event = with_model(rig, boot(True))
        one = fb.QuantityValue(contract=c.SEATS, value=1)
        rig.host.window.accept(rig.envelope(101, replace(event, declaration=replace(event.declaration,
            capacity=one)), 11))
        pump_window(rig, lambda: len(rig.facts(c.CANDIDATE_REQUEST)) == 1)
        assert len(rig.host.window.drain()) == 2   # 両方とも単独なら席 1 に入る
        rig.host.run_until(lambda status: bool(launcher.attempts), timeout=2)
        held = [w.held.value for w in rig.host.window.status().works if w.held is not None]
        assert held == [1] and len(launcher.attempts) == 1
    finally:
        rig.workers.release.set()


class LyingLauncher:
    """1 回目は not_started と答えるが本体を持っておく。2 回目は launched。本体は試験が呼ぶ。"""

    def __init__(self):
        self.bodies = []

    def launch(self, work_id, body):
        self.bodies.append(body)
        return "not_started" if len(self.bodies) == 1 else "launched"


def test_duplicate_launch_ending_does_not_release_the_running_work():
    import threading
    launcher = LyingLauncher()
    rig = make_rig(launcher=launcher)
    try:
        declare_clock(rig)
        rig.host.window.accept(rig.envelope(101, boot(False), 11))
        pump_window(rig, lambda: len(rig.facts(c.SEGMENT_REQUESTED)) == 1)
        rig.workers.hold = True
        rig.host.run_until(lambda status: len(launcher.bodies) == 2, timeout=2)
        second = threading.Thread(target=launcher.bodies[1])
        second.start()
        rig.host.run_until(lambda status: status.works[0].phase == "running", timeout=2)
        launcher.bodies[0]()   # 開始札を取れない重複の起動が終わる
        (work,) = rig.host.window.status().works
        assert work.phase == "running" and not work.stop_confirmed and work.held is not None
        rig.workers.release.set()
        second.join(3)
        (work,) = rig.host.window.status().works
        assert work.stop_confirmed and work.held is None
    finally:
        rig.workers.release.set()


# --- 2 周目のレビュー (R12〜R15・R19) ---

def test_second_call_of_the_same_body_does_not_release():
    import threading
    launcher = WitnessLauncher("launched")
    rig = make_rig(launcher=launcher)
    try:
        declare_clock(rig)
        rig.host.window.accept(rig.envelope(101, boot(False), 11))
        pump_window(rig, lambda: len(rig.facts(c.SEGMENT_REQUESTED)) == 1)
        rig.workers.hold = True
        rig.host.run_until(lambda status: bool(launcher.attempts), timeout=2)
        body = launcher.attempts[0][1]
        first = threading.Thread(target=body)
        first.start()
        rig.host.run_until(lambda status: status.works[0].phase == "running", timeout=2)
        body()   # 同じ本体の 2 度目の呼出し
        (work,) = rig.host.window.status().works
        assert work.phase == "running" and not work.stop_confirmed and work.held is not None
        rig.workers.release.set()
        first.join(3)
        assert rig.host.window.status().works[0].stop_confirmed
    finally:
        rig.workers.release.set()


def test_old_launch_ending_without_entry_keeps_the_new_claim():
    launcher = LyingLauncher()
    rig = make_rig(launcher=launcher)
    try:
        declare_clock(rig)
        rig.host.window.accept(rig.envelope(101, boot(False), 11))
        pump_window(rig, lambda: len(rig.facts(c.SEGMENT_REQUESTED)) == 1)
        rig.host.run_until(lambda status: len(launcher.bodies) == 2, timeout=2)
        rig.workers.run = lambda work, ctx: None   # 古い起動は入場せずに終わる
        launcher.bodies[0]()
        (work,) = rig.host.window.status().works
        assert work.phase == "starting" and work.held is not None
        launcher.bodies[1]()   # 今の占有を持つ起動が入場せずに終わる → 開始待ちへ
        (work,) = rig.host.window.status().works
        assert work.phase == "pending" and work.held is None
    finally:
        rig.workers.release.set()


def test_claims_changed_between_post_and_accept_are_not_saved(rig):
    claims = {"sender_id": "same"}
    rig.host.post(fb.Received(route_epoch="r", media_type="text/plain", data=b"x", claims=claims))
    claims["sender_id"] = "other"
    rig.host.run_until(lambda status: len(rig.facts(c.RECEIVED)) == 1, timeout=2)
    assert rig.facts(c.RECEIVED)[0].value["claims"] == {"sender_id": "same"}


def test_drained_work_cannot_be_changed_from_outside(rig):
    declare_clock(rig)
    rig.host.window.accept(rig.envelope(101, with_model(rig, boot(True)), 11))
    pump_window(rig, lambda: len(rig.facts(c.CANDIDATE_REQUEST)) == 1)
    compute = next(w for w in rig.host.window.drain() if isinstance(w, fb.Compute))
    with pytest.raises(TypeError):
        compute.desc.args.generator_args["unexpected"] = 1


@pytest.mark.parametrize("value", (True, 1))
def test_true_and_one_are_different_contents(rig, value):
    event = fb.Received(route_epoch="r", media_type="text/plain", data=b"x", claims={"flag": True})
    rig.host.window.accept(rig.envelope(7, event, 11))
    again = replace(event, claims={"flag": value})
    if value is True:
        rig.host.window.accept(rig.envelope(7, again, 11))
    else:
        with pytest.raises(fb.FbHostFault):
            rig.host.window.accept(rig.envelope(7, again, 11))


@pytest.mark.parametrize("value,ok", ((True, True), (1, False)))
def test_route_args_true_and_one_conflict(rig, value, ok):
    declare_clock(rig)
    first = boot(False)
    route = first.declaration.routes[0]

    def with_args(event, flag):
        return replace(event, declaration=replace(event.declaration, routes=(replace(route, value=replace(
            route.value, config=replace(route.value.config, args={"flag": flag}))),)))
    rig.host.window.accept(rig.envelope(101, with_args(first, True), 11))
    pump_window(rig, lambda: len(rig.facts(c.SEGMENT_REQUESTED)) == 1)
    rig.host.window.accept(rig.envelope(102, with_args(first, value), 12))
    settle_twice(rig)
    assert len(rig.facts(contract("sui.f.route_config"))) == (2 if ok else 1)


def test_allocation_of_another_boot_is_not_borrowed():
    launcher = WitnessLauncher("launched")
    rig = make_rig(launcher=launcher)
    try:
        declare_clock(rig)
        event = boot(False)
        route = event.declaration.routes[0]
        zero = replace(route.value.allocation, value=replace(route.value.allocation.value,
            amount=fb.QuantityValue(contract=c.SEATS, value=0)))
        first = replace(event, declaration=replace(event.declaration, routes=(
            replace(route, value=replace(route.value, allocation=zero)),)))
        rig.host.window.accept(rig.envelope(101, first, 11))
        pump_window(rig, lambda: len(rig.facts(c.SEGMENT_REQUESTED)) == 1)
        assert rig.host.window.drain() == ()   # 割当 0 に Need 1 は入らない
        other = replace(event, declaration=replace(event.declaration, routes=(replace(route, value=replace(
            route.value, config=replace(route.value.config, route_epoch="route-B"))),)))
        rig.host.window.accept(rig.envelope(102, other, 12))
        pump_window(rig, lambda: len(rig.facts(c.SEGMENT_REQUESTED)) == 2)
        rig.host.run_until(lambda status: bool(launcher.attempts), timeout=2)
        configs = {x.value["config"]["route_epoch"]: x.cid for x in rig.facts(contract("sui.f.route_config"))}
        rows = {r.work.desc.args.route: r for r in rig.host._state.works.values()}
        zero_row, other_row = rows[configs["route-A"]], rows[configs["route-B"]]
        # 割当 0 の Boot の仕事は、同じ名前の slot を持つ別の Boot の割当を借りない
        assert zero_row.phase == "pending" and zero_row.held is None
        assert other_row.held is not None and len(launcher.attempts) == 1
    finally:
        rig.workers.release.set()


def test_process_slot_is_a_declared_position(rig):
    declare_clock(rig)
    event = boot(False)
    route = event.declaration.routes[0]
    bad = replace(event, declaration=replace(event.declaration, routes=(
        replace(route, value=replace(route.value, process_slot="scope")),)))
    rig.host.window.accept(rig.envelope(101, bad, 11))
    settle_twice(rig)
    assert not rig.facts(c.SEGMENT_REQUESTED)
    assert ("missing_contract", "slot:ambiguous:scope") in pending(rig)


def test_same_named_allocation_of_another_boot_does_not_block():
    launcher = WitnessLauncher("launched")
    rig = make_rig(launcher=launcher)
    try:
        declare_clock(rig)
        event = boot(False)
        route = event.declaration.routes[0]
        rig.host.window.accept(rig.envelope(101, event, 11))
        pump_window(rig, lambda: len(rig.facts(c.SEGMENT_REQUESTED)) == 1)
        rig.host.run_until(lambda status: len(launcher.attempts) == 1, timeout=2)
        other = replace(event, declaration=replace(event.declaration, routes=(replace(route, value=replace(
            route.value, config=replace(route.value.config, route_epoch="route-B"))),)))
        rig.host.window.accept(rig.envelope(102, other, 12))
        # 別の Boot の同じ名前の割当 (席 1) の占有は、この Boot の割当に数えない
        assert rig.host.run_until(lambda status: len(launcher.attempts) == 2, timeout=2)
        assert all(w.held is not None for w in rig.host.window.status().works)
    finally:
        rig.workers.release.set()


# --- 3 周目のレビュー (R20・R21): 席の持ち主と、H の原本との照合 ---

class AnsweringLauncher:
    """いつも同じ答えを返し、本体を持っておく。本体は試験が遅れて呼ぶ。"""

    def __init__(self, answer):
        self.answer, self.bodies = answer, []

    def launch(self, work_id, body):
        self.bodies.append(body)
        return self.answer


@pytest.mark.parametrize("answer,enters", (("not_started", False), ("unknown", True)))
def test_late_body_enters_only_while_its_launch_holds_the_claim(answer, enters):
    launcher = AnsweringLauncher(answer)
    rig = make_rig(launcher=launcher)
    try:
        declare_clock(rig)
        rig.host.window.accept(rig.envelope(101, boot(False), 11))
        pump_window(rig, lambda: len(rig.facts(c.SEGMENT_REQUESTED)) == 1)
        rig.host.run_until(lambda status: bool(launcher.bodies), timeout=2)
        (work,) = rig.host.window.status().works
        # not_started は開始待ちに戻って占有を返す。unknown は占有を持ったまま
        assert (work.phase, work.held is None) == (("pending", True) if not enters else ("starting", False))
        launcher.bodies[0]()   # 起動の係が遅れて本体を呼ぶ
        (work,) = rig.host.window.status().works
        assert len(rig.workers.entries) == (1 if enters else 0)
        assert work.stop_confirmed is enters
        if not enters:
            assert work.phase == "pending" and work.held is None
    finally:
        rig.workers.release.set()


def test_old_launch_cannot_take_the_ticket_of_the_new_claim():
    launcher = LyingLauncher()
    rig = make_rig(launcher=launcher)
    try:
        declare_clock(rig)
        rig.host.window.accept(rig.envelope(101, boot(False), 11))
        pump_window(rig, lambda: len(rig.facts(c.SEGMENT_REQUESTED)) == 1)
        rig.host.run_until(lambda status: len(launcher.bodies) == 2, timeout=2)
        launcher.bodies[0]()   # not_started と答えた古い起動の本体。札はまだ使われていない
        (work,) = rig.host.window.status().works
        assert rig.workers.entries == [] and work.phase == "starting" and work.held is not None
        launcher.bodies[1]()   # 今の占有を持つ起動は入れる
        (work,) = rig.host.window.status().works
        assert len(rig.workers.entries) == 1 and work.stop_confirmed and work.held is None
    finally:
        rig.workers.release.set()


class ReentrantLauncher:
    """1 回目: 本体をその場で呼び (入場せずに戻る)、次の起動が占有を取ってから not_started と答える。"""

    def __init__(self):
        self.bodies, self.host = [], None

    def launch(self, work_id, body):
        self.bodies.append(body)
        if len(self.bodies) > 1:
            return "launched"
        body()
        self.host.run_until(lambda status: len(self.bodies) >= 2, timeout=2)
        return "not_started"


def test_late_not_started_answer_keeps_the_new_claim():
    launcher = ReentrantLauncher()
    rig = make_rig(launcher=launcher)
    launcher.host = rig.host
    try:
        declare_clock(rig)
        rig.host.window.accept(rig.envelope(101, boot(False), 11))
        pump_window(rig, lambda: len(rig.facts(c.SEGMENT_REQUESTED)) == 1)
        rig.workers.run = lambda work, ctx: None   # 1 回目の本体は入場せずに戻る
        rig.host.run_until(lambda status: len(launcher.bodies) >= 2, timeout=2)
        (work,) = rig.host.window.status().works
        assert len(launcher.bodies) == 2 and work.phase == "starting" and work.held is not None
        del rig.workers.run
        launcher.bodies[1]()
        assert len(rig.workers.entries) == 1 and rig.host.window.status().works[0].stop_confirmed
    finally:
        rig.workers.release.set()


@pytest.mark.parametrize("change", ("none", "data", "true_one", "r"))
def test_first_accept_must_match_the_posted_envelope(rig, change):
    event = fb.Received(route_epoch="r", media_type="text/plain", data=b"x", claims={"flag": True})
    rig.set_clock(50)
    rig.host.post(event)
    (queued,) = [x for x in rig.host.window.status().receipts if x.state == "received"]
    rig.set_clock(60)
    other = {"none": event, "data": replace(event, data=b"y"), "r": event,
             "true_one": replace(event, claims={"flag": 1})}[change]
    envelope = fb.Envelope(number=queued.envelope, event=other,
                           received_ns=queued.received_ns + (1 if change == "r" else 0))
    if change == "none":
        rig.host.window.accept(envelope)
    else:
        with pytest.raises(fb.FbHostFault):
            rig.host.window.accept(envelope)
    # H の原本は列に残り、保存されるのは Post した中身と r だけ
    assert rig.host.run_until(lambda status: len(rig.facts(c.RECEIVED)) == 1, timeout=2)
    (saved,) = rig.facts(c.RECEIVED)
    assert saved.value["data"] == list(b"x") and saved.value["claims"]["flag"] is True
    assert saved.received_ns == queued.received_ns == 50


class EnteredThenDenyingLauncher:
    """本体を別のスレッドで走らせ、札を取って入場したのを見てから not_started と答える。"""

    def __init__(self):
        self.workers, self.threads = None, []

    def launch(self, work_id, body):
        import threading
        import time
        thread = threading.Thread(target=body)
        thread.start()
        self.threads.append(thread)
        while not self.workers.entries:
            time.sleep(0.001)
        return "not_started"


def test_not_started_after_entry_does_not_return_the_work_to_pending():
    launcher = EnteredThenDenyingLauncher()
    rig = make_rig(launcher=launcher)
    launcher.workers = rig.workers
    try:
        declare_clock(rig)
        rig.host.window.accept(rig.envelope(101, boot(False), 11))
        pump_window(rig, lambda: len(rig.facts(c.SEGMENT_REQUESTED)) == 1)
        rig.workers.hold = True
        rig.host.run_until(lambda status: bool(launcher.threads), timeout=2)
        (work,) = rig.host.window.status().works
        # 札を取って本体が動いている: 嘘の not_started で開始待ちに戻さず、占有も手放さない
        assert work.phase == "running" and work.held is not None and len(launcher.threads) == 1
        rig.workers.release.set()
        launcher.threads[0].join(3)
        assert rig.host.window.status().works[0].stop_confirmed
    finally:
        rig.workers.release.set()
