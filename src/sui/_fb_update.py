"""信念の更新 (紙 F-b §6-2・§6-4・§6-10 J1〜J9・K1〜K13、段 3)。

δ (`sui.fb.saved_segment_update/1`) 1 つにつき更新の計画を 1 つ持つ。口の route_config と時計の source の
保存の後に法則 law と読み方 reading を作り (K3)、保存した原 Claim の結びつき B ごとに義務 O-03 を持つ (J1)。
義務ごとに、ホストの監視の記録 (K4) → 入力の取得 (K5) → 更新要求 Q* (K6) → 仕事 Wu → 終わりの記録 T →
結果 R* (K8) → 結果の取得 → 採用 A* か Stale (K9) を 1 点ずつ保存する。同じ (origin, model) の系列では、前の
義務の採用の判断が保存を確認されるまで次の Q* を作らない (K13: 確実に Stale になる要求を作らない、
前の採用が「無い」を確認待ちから決めない)。

新しい使用 (監視の記録・入力と結果の取得・Q*・Wu の入場・R*・A*・継続) は全部 1 つの門 `gate` を通る (§6-10 G6):
その使用の出発点から U/UE の辺で取った UseKeys (`_fb_uses`) と、ホストが受け取った配送の Clashes を毎回の settle で
照合する。T と準備済みの記録の保存は止めない。
"""

from dataclasses import dataclass as _dataclass, field as _field

from . import f as _f
from . import fb as _fb
from . import fb_contracts as _c
from . import f_contracts as _fc
from ._fb_boot import Step as _Step, _clock_source, _front, _record, advance as _advance, \
    fixed_view as _fixed_view
from ._fb_wire import dumps as _dumps, encode as _encode
from .ids import RefKind as _RefKind
from .records import Decided as _Decided, Observed as _Observed, Payload as _Payload, \
    Prediction as _Prediction, Role as _Role

_MEANINGS = {(_c.NO_ARRIVAL.name, _c.NO_ARRIVAL.version): "no_arrival",
             (_c.COUNT_EXACTLY_ONE.name, _c.COUNT_EXACTLY_ONE.version): "count_exactly_one"}


@_dataclass
class Obligation:
    """義務 O-03 (J1): 鍵は (δ の宣言の位置と契約・process・origin・原報告・役割・belief_update)。B の CID・
    Xnum・前の採用は鍵に入れない。steps は 1 点ずつ保存する記録、final はこの更新の目的の結末。"""
    report: str
    binding: str
    steps: list = _field(default_factory=list)
    points: dict = _field(default_factory=dict)
    desc: object = None          # Wu の Desc (Q* の Publish で固定)
    done: bool = False           # Wu の終わりを処理した
    final: str | None = None     # adopted / stale / rejected / insufficient / failure / unknown / issued:*
    response: str = "none"       # 意味 3 の確定返答
    blocked: bool = False        # 門が食い違いで止めた (Clashes は増えるだけなので、一度止まれば戻らない)
    candidate: object = None     # Q* の Desc の候補 (門の出発点と build で同じものを使う)


@_dataclass
class UpdatePlan:
    boot: object                 # BootPlan
    initial: object              # InitialProcess
    slot: str                    # initial の宣言の位置
    args: dict                   # δ の args (K2)
    steps: list = _field(default_factory=list)
    points: dict = _field(default_factory=dict)
    missing: list = _field(default_factory=list)
    obligations: dict = _field(default_factory=dict)   # 原報告の Point → Obligation (受付の順)
    monitor_captures: dict = _field(default_factory=dict)   # B の Point → 監視の工場の控え (MonitorCapture)


def _hold(plan, reason) -> None:
    if reason not in plan.missing:
        plan.missing.append(reason)


def _check_args(boot, args):
    """K2 の形。合わなければ理由。法則の値の意味 (正規化・channel の対応) は U が検査する。"""
    if not isinstance(args, dict) and not hasattr(args, "items"):
        return "delta:args"
    if set(args) != {"route", "law", "claims", "generation"}:
        return "delta:args"
    if not any(r.slot == args["route"] for r in boot.declaration.routes):
        return "delta:route"
    law = args["law"]
    if set(law) != {"carrier_by_state", "channels", "rows"} or not law["channels"]:
        return "delta:law"
    for channel in law["channels"]:
        if set(channel) != {"id", "route_slots", "domain"} \
                or not set(channel["route_slots"]) <= {r.slot for r in boot.declaration.routes}:
            return "delta:law"
    if not args["claims"] or any(set(e) != {"meaning", "channel"} for e in args["claims"]):
        return "delta:claims"
    if set(args["generation"]) != {"scope"}:
        return "delta:generation"
    return None


def _plain(value):
    """凍った写し (mappingproxy・tuple) を JSON の値へ。"""
    if hasattr(value, "items"):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def _ready(state, plan):
    """law と reading を作る前提: 口の route_config・時計の source・origin が保存済み。"""
    source = _clock_source(state)
    names = [ch_slot for ch in plan.args["law"]["channels"] for ch_slot in ch["route_slots"]]
    configs = [plan.boot.points.get("route_config:" + name) for name in names]
    if source is None or plan.boot.points.get("origin") is None or None in configs:
        return None
    return source


def _law_step():
    def build(state, plan):
        from ._fb_core import Slot
        source = _ready(state, plan)
        if source is None:
            return None
        d, routes = plan.boot.d, {r.slot: r.value for r in plan.boot.declaration.routes}
        law = plan.args["law"]
        configs = sorted({plan.boot.points["route_config:" + n] for ch in law["channels"] for n in ch["route_slots"]})
        channels = [{"id": ch["id"],
                     "process": _encode(_fb.BootSlot(declaration=d, slot=routes[ch["route_slots"][0]].process_slot)),
                     "route_configs": sorted(plan.boot.points["route_config:" + n] for n in ch["route_slots"]),
                     "domain": {"clock": _f._encode(state.clock.run), **ch["domain"]}} for ch in law["channels"]]
        content = {"model": plan.initial.model, "extends": None, "carrier_by_state": law["carrier_by_state"],
                   "channels": channels, "rows": law["rows"], "frame_relation": "independent_given_carrier"}
        ledger = state.ledger
        basis = tuple(ledger.record(p).id for p in (plan.initial.model, d, *configs, source))
        body = _Prediction(target="count_law", about=(ledger.record(plan.initial.model).id,), basis=basis,
                           content=_Payload.json(content), contract=_c.FINITE_JOINT_COUNT_LAW)
        return Slot(contract=_c.FINITE_JOINT_COUNT_LAW, record=_record(state, body, _RefKind.PREDICTION, _Role.MODEL),
                    parents=_front(ledger, {d, *configs, source}))
    return _Step(name="law", build=build)


def _reading_step():
    def build(state, plan):
        from ._fb_core import Slot
        law = plan.points["law"]
        claims = [{"meaning": e["meaning"], "law": law, "channel": e["channel"]} for e in plan.args["claims"]]
        content = {"model": plan.initial.model,
                   "projection": {"contract": _f._encode(_c.FINITE_SEGMENT_PROJECTION),
                                  "args": {"frame": None, "claims": claims,
                                           "time_projection": {"contract": _f._encode(_c.SEGMENT_VALUE_ONLY),
                                                               "args": {}}}},
                   "generation": {"contract": _f._encode(_c.BOOTSTRAP_GENERATION), "args": plan.args["generation"]}}
        ledger = state.ledger
        law_slot = next(s.slot for s in plan.steps if s.name == "law")
        body = _Prediction(target="observation_plan", about=(ledger.record(plan.initial.model).id,),
                           basis=(ledger.record(plan.initial.model).id, ledger.record(law).id),
                           content=_Payload.json(content), contract=_c.OBSERVATION_PLAN_2)
        return Slot(contract=_c.OBSERVATION_PLAN_2, record=_record(state, body, _RefKind.PREDICTION, _Role.MODEL),
                    parents=law_slot.parents)
    return _Step(name="reading", build=build)


def _plan(state, boot):
    initial_slot = boot.declaration.initial
    initial = initial_slot.value
    method = initial.derivation.method
    if method.contract != _c.SAVED_SEGMENT_UPDATE:
        return None
    plan = UpdatePlan(boot=boot, initial=initial, slot=initial_slot.slot, args=_plain(method.args))
    reason = _check_args(boot, plan.args)
    if reason is not None:
        _hold(plan, reason)
    else:
        plan.steps = [_law_step(), _reading_step()]
    return plan


# --- 義務ごとの記録 ---

def _measure_row(state, segment):
    for row in state.works.values():
        if isinstance(row.work, _fb.MeasureSegment) and row.work.request == segment:
            return row
    return None


def _claim_span(state, report):
    item = state.ledger.record(report).body.content.as_json()["item"]
    return item["value"]["interval"]


def _monitor_step(ob):
    def build(state, plan_ob):
        """K4: ホストが自分で観測したことだけ。入場の M の読みと、今 M を読んだ時に行が入場済みで停止して
        いないこと。仕事の Started・monitored の申告・原報告の区間からは作らない。"""
        from ._fb_core import Slot, mono_ns
        plan, ob = plan_ob
        binding = state.ledger.record(ob.binding).body.content.as_json()
        row = _measure_row(state, binding["segment"])
        source = _clock_source(state)
        if row is None or source is None:
            return None
        if row.entered_ns is None or row.stopped:
            _hold(plan, "monitor:" + ("stopped" if row.stopped else "not_entered"))
            return None
        observed = mono_ns(state.clock)
        if observed < _claim_span(state, ob.report)["end_ns"]:
            return None   # 区間の終わりの後の読みを待つ
        # 工場の捕捉 (HostMonitorObservation の元): segment は仕事表の行の要求、route はその行が保持した実適用の操作の
        # 保存 Point から取る。保存した B・Claim から写さない (正本 v1.3.7)。入場の時刻は EW の entered_ns[entry_index]
        from .f_update2 import MonitorCapture
        application = next((a for a in state.route_applications.values() if a.operation is row.route_operation), None)
        if application is None or application.publication is None:
            _hold(plan, "monitor:route_application")
            return None
        capture = MonitorCapture(execution_occurrence=row.execution, entry_index=len(row.entries) - 1,
                                 segment=row.work.request, work=row.work.desc.work_id,
                                 route_operation=row.route_operation, route=application.publication, clock_source=source,
                                 observed_reading=_f.ClockReading(run=state.clock.run, time_ns=observed))
        state.host_monitors.append(capture)
        plan.monitor_captures[ob.binding] = capture
        content = {"segment": capture.segment, "work": capture.work, "route": capture.route,
                   "clock": source, "entered_ns": row.entries[capture.entry_index], "observed_ns": observed}
        body = _Observed(route="fb", content=_Payload.json(content), contract=_c.MONITOR_SPAN, received_ns=observed)
        return Slot(contract=_c.MONITOR_SPAN, record=_record(state, body, _RefKind.OBSERVATION, _Role.MEMBRANE),
                    parents=_front(state.ledger, {capture.segment, source}))

    def prepared(state, plan_ob, cid):
        plan, ob = plan_ob
        plan.monitor_captures[ob.binding].publication = cid
    # ホスト自身の観測の記録: T-G6 に新しい使用の行は無い (門を呼ばない)
    return _Step(name="monitor", build=build, on_prepared=prepared)


def _acquire_steps(prefix, contents_of):
    """K5: 取得の操作。ホストが origin について内容を台帳から実際に読み、その時の M の読み a を EA に残し、
    clock_reading と content_acquired を保存する。読みは最初に作った時に固定する (再試行で読み直さない)。"""
    def build_reading(state, plan_ob):
        from ._fb_core import Slot, mono_ns
        plan, ob = plan_ob
        source = _clock_source(state)
        contents = contents_of(plan, ob)
        if source is None or contents is None:
            return None
        for point in contents:
            state.ledger.record(point)   # 本文を実際に読む (無ければ KeyError で止まる)
        a = mono_ns(state.clock)
        from .f_update2 import AcquisitionObservation
        state.acquisitions.append(AcquisitionObservation(origin=plan.boot.points["origin"],
                                                         contents=frozenset(contents), acquired_ns=a,
                                                         run=getattr(state.clock, "run", None)))
        ob.points[prefix + ":contents"] = tuple(sorted(contents))
        value = _f.FClockReadingFact(source=source, reading=_f.ClockReading(run=state.clock.run, time_ns=a))
        body = _Observed(route="fb", content=_Payload.json(_f._encode(value)), contract=_fc.CLOCK_READING,
                         received_ns=a)
        return Slot(contract=_fc.CLOCK_READING, record=_record(state, body, _RefKind.OBSERVATION, _Role.MEMBRANE),
                    parents=_front(state.ledger, {source, *contents}))

    def build_acquired(state, plan_ob):
        from ._fb_core import Slot, mono_ns
        plan, ob = plan_ob
        origin, contents, clock = plan.boot.points["origin"], ob.points[prefix + ":contents"], ob.points[prefix + ":a"]
        value = _f.ContentAcquired(origin=origin, contents=contents, clock=clock)
        body = _Observed(route="fb", content=_Payload.json(_f._encode(value)), contract=_fc.CONTENT_ACQUIRED,
                         received_ns=mono_ns(state.clock))
        return Slot(contract=_fc.CONTENT_ACQUIRED, record=_record(state, body, _RefKind.OBSERVATION, _Role.MEMBRANE),
                    parents=_front(state.ledger, {origin, *contents, clock}))

    def uses_reading(state, pair):
        """取得の門 (G6): 取得する記録を、その契約の取得の用途で。実際の本文の取得と EA への追加より前。
        B にはこの義務の読み方との対の文脈 (生成の契約) を添える (条件 generation・support_required)。"""
        from ._fb_uses import Reader, reading_context, starts_of
        contents = contents_of(pair.plan, pair.ob)
        if contents is None:
            return None
        reader = Reader(state.ledger)
        subjects, contexts = {}, {}
        for point in contents:
            contract = reader.contract_of(point)
            subjects.setdefault(contract, []).append(point)
            if contract == "sui.fb.segment_binding/1" and "reading" in pair.plan.points:
                contexts[point] = reading_context(reader, pair.plan.points["reading"])
        return starts_of("更新結果の本文を取得する" if prefix == "out" else "原入力の本文を取得する", subjects,
                         contexts=contexts)

    def uses_acquired(state, pair):
        """取得の記録 G の作成の門: 保存予定の全内容を持つ候補 (保存した G を実取得の代わりにしない)。"""
        from ._fb_uses import Candidate, starts_of
        plan, ob = pair
        if prefix + ":a" not in ob.points:
            return None
        from ._fb_uses import Reader, reading_context
        contents = ob.points[prefix + ":contents"]
        value = _f.ContentAcquired(origin=plan.boot.points["origin"], contents=contents, clock=ob.points[prefix + ":a"])
        reader = Reader(state.ledger)
        contexts = tuple((p, reading_context(reader, plan.points["reading"])) for p in contents
                         if "reading" in plan.points and reader.contract_of(p) == "sui.fb.segment_binding/1")
        candidate = Candidate(contract=_fc.CONTENT_ACQUIRED, content=_f._encode(value), use="acquire", contexts=contexts)
        return starts_of("取得の記録を作る", {"sui.f.content_acquired/1": candidate})

    return [_Step(name=prefix + ":a", build=build_reading, uses=uses_reading),
            _Step(name=prefix + ":G", build=build_acquired, uses=uses_acquired)]


def _deliveries(state) -> list:
    """窓口の新しい使用の配送 (G5): 保存済みの原報告と、ホストが実際に受け取って持っている Post 済み・受け付け済みの
    配送。どれもその仕事の口 (札を取って入場した口) から来たもので、保存の段に関わらず数える (無いことを許可の
    根拠にしない)。"""
    from ._fb_core import PlannedWork
    from ._fb_uses import Reader, delivery
    queued = {e.number: e for e in state.queue}
    reader = Reader(state.ledger)
    out = []
    for row in state.works.values():
        if isinstance(row.work, PlannedWork):
            continue
        for number, _r in row.reports:
            receipt = state.receipts.get(number)
            envelope = receipt.envelope if receipt is not None else queued.get(number)
            found = delivery(envelope.event, row.work, reader) if envelope is not None else None
            if found is not None:
                out.append(found)
    return out


def _start_key(start):
    """門の出発点の列を、計算の結果を引くための鍵に (Candidate は内容の正準 bytes で)。"""
    from ._fb_uses import Candidate
    from ._fb_wire import dumps
    if isinstance(start, Candidate):
        return ("candidate", start.contract, dumps(start.content), start.use, start.basis, start.about,
                dumps(list(start.contexts)), start.parents)
    if len(start) > 2:
        return (start[0], start[1], dumps(start[2]))
    return start


def _pending_starts(state) -> list:
    """次の settle で門を通りそうな出発点の列 (読むだけ。外れても害は無い: 門は無ければその場で計算する)。
    更新の計画の各義務の次の歩・保存した Q*・採用した A*・入場前の Wu・継続の過程。"""
    from ._fb_core import PlannedWork
    from ._fb_think import continuation_starts, enter_starts
    out = []

    def next_step(steps, pair):
        step = next((s for s in steps if s.slot is None), None)
        if step is None or step.uses is None or step.name.startswith("T:"):
            return
        try:
            starts = step.uses(state, pair)
        except Exception:   # 前提が揃っていない読み。門はその場で判定する (wait)
            return
        if starts:
            out.append(list(starts))

    for plan in state.updates.values():
        for ob in plan.obligations.values():
            if ob.desc is not None:
                if "Q" in ob.points:
                    out.append([(ob.points["Q"], "update")])
                if ob.final == "adopted" and "A" in ob.points:
                    out.append([(ob.points["A"], "belief")])
                row = state.works.get(ob.desc.work_id)
                if row is not None and not isinstance(row.work, PlannedWork) and not row.ticket_used:
                    for stage in ("開始", "入場"):
                        try:
                            out.append(_enter_starts(state, row, stage))
                        except Exception:   # 要求がまだ読めない (保存前)。門はその場で wait
                            pass
            if not ob.blocked:   # desc の無い義務 (最初の Q* を作る前の歩) も覆う (FB3-LOCK-R6)
                next_step(ob.steps, _Pair(plan, ob))
    for plan in state.thinking.values():
        if plan.round and "cause" in plan.points and "cg" in plan.points:
            out.append(continuation_starts(state, plan))
        next_step(plan.steps, plan)
        for wid in (plan.wg, *(desc.work_id for desc in plan.descs.values())):
            row = state.works.get(wid)
            if row is not None and not isinstance(row.work, PlannedWork) and not row.ticket_used:
                for stage in ("開始", "入場"):
                    try:
                        starts = enter_starts(state, row, stage)
                    except Exception:   # 要求がまだ読めない (保存前)
                        continue
                    if starts:
                        out.append(starts)
    return out


def _enter_starts(state, row, stage="入場"):
    """Wu の開始・入場の門の出発点 (G6-START-Q・G6-WU-ENTER): 保存した Q* を実行の用途で (用途は要求の本文の purpose から)。"""
    from ._fb_uses import Reader, starts_of
    return starts_of("仕事の開始を確保する" if stage == "開始" else "更新の仕事へ入る",
                     {"sui.fb.work_requested/1": row.work.request}, reader=Reader(state.ledger))


def precompute(state) -> None:
    """門の重い計算をロックの外で (G6 の最後の行、LOCK-R5)。入力 (台帳の版・配送の版・配送の集合・出発点) は
    ロックの中で固定し、閉包・索引・比較はロックの外で行い、結果を版つきで置く。gate は版が合う時だけ使い、
    合わなければ計算し直す (途中で条件が変われば古い許可を使わない)。settle を呼ぶスレッドだけが台帳に書くので、
    ロックの外の台帳の読みは固定した入力の読みになる。"""
    from . import _fb_uses as uses
    with state.lock:
        ledger_version, delivery_version = state.ledger_version, state.delivery_version
        deliveries = _deliveries(state)
        groups = _pending_starts(state)
        cache = state.gate_cache
    fresh = cache is not None and cache["ledger"] == ledger_version
    from ._fb_core import evidence
    reader = cache["reader"] if fresh else uses.Reader(state.ledger, evidence(state))
    keys = dict(cache["keys"]) if fresh else {}
    for starts in groups:
        key = tuple(_start_key(s) for s in starts)
        if key in keys and not isinstance(keys[key], Exception):
            continue   # 解決できなかった出発点は毎回の settle で読み直す (保存の確認待ちが解けても台帳の版は進まない)
        try:
            keys[key] = uses.use_keys(reader, starts)
        except (uses.Unresolved, uses.Unsupported, uses.Malformed, uses.Mismatch) as exc:
            keys[key] = exc
        except uses.LEDGER_READ_ERRORS as exc:   # 台帳の読みの故障 (保存の確認待ちの本文など): wait (記録が読めるまで)
            keys[key] = uses.Unresolved(str(exc))
        except Exception as exc:   # noqa: BLE001 — 読み手の実装の故障: wait に潰さず、門の判定 error:<型> として見える所へ (Z28)
            keys[key] = exc
    clashes = uses.clashes(deliveries)
    with state.lock:
        state.gate_cache = {"ledger": ledger_version, "reader": reader, "keys": keys,
                            "delivery": delivery_version, "clashes": clashes}


def gate_fresh(state, starts, decide):
    """ロックを持たない呼び手 (仕事の口の入場) の門 (G6 の最後の行、FB3-LOCK-R6): 入力 (版・配送) をロックの中で
    固定し、閉包と比較をロックの外で計算し、最後にロックの中で版が同じ時だけ decide(verdict) を同じ歩で行う。版が
    進んでいれば計算し直す (古い許可を使わない)。何度も進めば諦めて None (呼び手は保留)。"""
    from . import _fb_uses as uses
    from ._fb_core import evidence
    for _attempt in range(3):
        with state.lock:
            versions = (state.ledger_version, state.delivery_version)
            deliveries = _deliveries(state)
        try:
            keys = uses.use_keys(uses.Reader(state.ledger, evidence(state)), starts)
            verdict = "blocked" if keys & uses.clashes(deliveries) else "open"
        except Exception as exc:   # noqa: BLE001 — 分類は _verdict (wait / undetermined / unsupported / mismatch / error:<型>)
            verdict = _verdict(exc)
        with state.lock:
            if (state.ledger_version, state.delivery_version) == versions:
                return decide(verdict)
    return None


def _verdict(exc) -> str:
    """読み手の例外 → 門の判定。wait = 要る参照がまだ無い・台帳の読みの故障 / undetermined = 表の未確定に届いた /
    unsupported = 規則の無い契約・形 / mismatch = T-REF の assert が確定して落ちた / error:<型> = 読み手の実装の故障
    (wait に潰して黙って待たない、Z28)。"""
    from . import _fb_uses as uses
    if isinstance(exc, uses.Undetermined):
        return "undetermined"
    if isinstance(exc, uses.Unresolved) or isinstance(exc, uses.LEDGER_READ_ERRORS):
        return "wait"
    if isinstance(exc, uses.Mismatch):
        return "mismatch"
    if isinstance(exc, (uses.Unsupported, uses.Malformed)):
        return "unsupported"
    return "error:" + type(exc).__name__


HOLD_LABELS = {"unsupported": "missing_contract", "undetermined": "undetermined", "mismatch": "mismatch"}


def hold_label(verdict) -> str | None:
    """門が止めた理由の保留の名 (`<歩>:uses:<名>`)。open / blocked / wait / stale は None。"""
    if verdict in HOLD_LABELS:
        return HOLD_LABELS[verdict]
    if verdict.startswith("error:"):
        return verdict
    return None


def gate(state, starts) -> str:
    """新しい使用の門 (G6): open / blocked (UseKeys と Clashes が交わる) / wait (要る参照がまだ無い) /
    undetermined (閉包が表の未確定の規則に届いた: 必要な依存が未解決、FB3-R01-R6) / unsupported (規則の無い契約・用途)。食い違いが無いことだけを許可にしない: 要る参照と前の状態は各歩の
    build が別に確かめる。呼ぶ側はロックを持つ。閉包は台帳の版が、Clashes は配送の版が precompute の時と同じなら
    その結果を使い、違えばここで計算し直す (古い許可を使わない)。"""
    from . import _fb_uses as uses
    cache = state.gate_cache
    key = tuple(_start_key(s) for s in starts)
    if cache is None or cache["ledger"] != state.ledger_version or key not in cache["keys"]:
        # 台帳の版が違う (precompute の後に書き込みが進んだ) か、precompute が覆わなかった出発点: 重い閉包をロックの
        # 中で計算し直さず、この使用を保留して外で再計算する (G6 の最後の行、FB3-LOCK-R6)。settle は stale を見て
        # precompute からやり直す
        state.gate_stale = True
        return "stale"
    keys = cache["keys"][key]
    if isinstance(keys, Exception):
        return _verdict(keys)
    if cache["delivery"] != state.delivery_version:
        # 配送だけが進んだ: 最後の関連の配送の照合は同じ歩の中で (G6「最後の関連の配送・…・公開を同じ状態の 1 歩に」)
        cache["clashes"], cache["delivery"] = uses.clashes(_deliveries(state)), state.delivery_version
    return "blocked" if keys & cache["clashes"] else "open"


def _block(plan, ob) -> None:
    """門が止めた: まだ作っていない後続を作らない。作った記録は消さない (準備済みの記録の保存は続く)。"""
    ob.blocked = True
    _hold(plan, "update:conflict")
    decided = any(step.name == "decide" and step.slot is not None for step in ob.steps)
    if ob.final is None and not decided:
        ob.final = ob.response = "conflict"


def _allowed(state, plan, ob, step) -> bool:
    if step.name.startswith("T:"):
        return True   # 最初の終わりの記録 T は診断の保存 (REF-4 の禁止を横流ししない)
    if ob.blocked:
        return False
    starts = step.uses(state, _Pair(plan, ob)) if step.uses is not None else None
    if starts is None:
        return True   # 前提がまだ保存されていない (build が None を返して待つ)
    verdict = gate(state, starts)
    if verdict == "blocked":
        _block(plan, ob)
    elif hold_label(verdict) is not None:
        _hold(plan, "update:uses:" + hold_label(verdict))
    return verdict == "open"   # wait・stale は作らない (stale は settle が外で計算し直して同じ回にもう一度通す)


def _series(plan):
    return [ob for ob in plan.obligations.values() if ob.desc is not None]


def _head(plan):
    """前の採用 (K9・K13): 系列の採用の判断が全部保存を確認済みなら最後の A* (無ければ None)。確認待ち・
    未保存の判断があれば "wait" (無いことを許可にしない)。"""
    head = None
    for ob in _series(plan):
        step = next((s for s in ob.steps if s.name == "decide"), None)
        if ob.final is None:
            return "wait"
        if step is not None and step.slot is not None and step.slot.entry is None:
            return "wait"
        if ob.final == "adopted":
            head = ob.points["A"]
    return head


def _obligation_key(plan, ob):
    """義務 O-03 の鍵 (J1、正本 delta_request_protocol.obligation_key)。B の CID・Xnum・前の採用は入れない。"""
    d = plan.boot.d
    return {"delta": {"declaration": d, "slot": plan.initial.derivation.slot},
            "delta_contract": _encode(_c.SAVED_SEGMENT_UPDATE),
            "process": {"declaration": d, "slot": plan.initial.process_slot},
            "origin": plan.boot.points["origin"], "raw_report": ob.report, "role": "trigger",
            "purpose": "belief_update"}


def _group_names(plan, members):
    """群の名前 (identifier_binding v1): stage_slot は群の全員の鍵と順の正準 bytes の hash、work_id は群の鍵の集合と
    stage_slot の hash。1 つの原報告を代表にしない (旧 "update:" + 原報告 をやめた)。Q の CID・選択の札・prior・Xnum は入れない。"""
    import hashlib
    d = plan.boot.d
    head = {"delta": {"declaration": d, "slot": plan.initial.derivation.slot},
            "delta_contract": _encode(_c.SAVED_SEGMENT_UPDATE),
            "process": {"declaration": d, "slot": plan.initial.process_slot},
            "origin": plan.boot.points["origin"], "purpose": "belief_update"}
    keys = [_obligation_key(plan, ob) for ob in members]
    stage = "update:" + hashlib.sha256(_dumps({"domain": "sui.fb.delta_group_stage/1", **head,
                                                "members": keys})).hexdigest()
    work = {"domain": "sui.fb.delta_work/1", "delta": head["delta"], "delta_contract": head["delta_contract"],
            "purpose": "belief_update", "obligations": sorted(keys, key=_dumps), "stage_slot": stage}
    return stage, "sui.fb.work:" + hashlib.sha256(_dumps(work)).hexdigest()


def _receipt_order(state, report):
    """原報告をホストが実際に受け取った順 (EH: 受信の M の読みと封筒の番号)。分からなければ None (CID の順で代えない)。"""
    for number, receipt in state.receipts.items():
        if any(slot.entry is not None and slot.entry.cid == report for slot in receipt.slots):
            return (receipt.envelope.received_ns, number)
    return None


def _stage3_choice(state, plan):
    """段 3 の仮の選び方 (正本 delta_request_protocol.stage3_profile `sui.fb.stage3_single_report_selection/1`、F-c で外す):
    母集団 = この δ の義務のうち未発行で入力の揃ったもの。K13 で塞がれていれば何も選ばない。そうでなければ EH の受信の順で
    最初の 1 つだけを群にし、残りは後に回す (片づけない)。受信の順が分からない義務があれば選ばない (型つきの不足)。
    一般の許可の検査には 1 件ずつを持ち込まない (この関数は発行の窓口だけが呼ぶ)。"""
    if _head(plan) == "wait":
        return None
    eligible = [ob for ob in plan.obligations.values()
                if ob.desc is None and "monitor" in ob.points and "in:G" in ob.points]
    if not eligible:
        return None
    ordered = [(_receipt_order(state, ob.report), ob) for ob in eligible]
    if any(order is None for order, _ob in ordered):
        _hold(plan, "delta:receipt_order")
        return None
    population = {ob.report for ob in eligible}
    chosen = min(ordered, key=lambda pair: pair[0])[1]
    groups, deferred = [[chosen.report]], sorted(population - {chosen.report})
    # 分割の検査 (partition): 群と後回しで母集団をちょうど 1 回ずつ覆う
    if sorted([r for g in groups for r in g] + deferred) != sorted(population):
        _hold(plan, "delta:partition")
        return None
    return chosen


def _q_desc(state, plan, ob, prior):
    """Q* の Desc (K6)。外側 inputs・input_points・Xnum の境界は、認証する側 (U) と同じ紙の表 T-A2
    (`f_update2.mandatory`) から導く (§6-10 A2): 観測の閉包と、前の採用の系列 (A*・Q*・R*・G とその証拠、前の Q* の
    C・I)。Support の証拠 (この義務の監視の記録) は X の中から選ぶので別に足す (REF-6)。"""
    from .f_update2 import mandatory
    d, initial = plan.boot.d, plan.initial
    origin, reading = plan.boot.points["origin"], plan.points["reading"]
    stage, work_id = _group_names(plan, [ob])
    slots = {"process": {"declaration": d, "slot": initial.process_slot},
             "allocation": {"declaration": d, "slot": initial.allocation.slot},
             "permissions": [{"declaration": d, "slot": initial.derivation.slot},
                             {"declaration": d, "slot": initial.allocation.slot}]}
    # 作る側の Desc はまだ input_points を持たない (これから導く集合そのもの)。宣言は空で表に当てる
    partial = {"desc": {"method": _encode(_c.FINITE_UPDATE_COMPUTE), "output_contract": _encode(_c.UPDATE_RESPONSE),
                        "reader": origin, "trigger": [{"point": ob.report, "slot": "trigger"}], "input_points": [], **slots,
                        "args": {"model": initial.model, "prior": prior,
                                 "observations": [{"binding": ob.binding, "reading": reading}]}}}
    inputs = set(mandatory(state.ledger, None, partial)) | {ob.points["monitor"]}
    return _fb.Desc(
        work_id=work_id,
        process=_fb.BootSlot(declaration=d, slot=initial.process_slot),
        trigger=frozenset({_fb.Trigger(point=ob.report, slot="trigger")}),
        purpose="belief_update", stage_slot=stage, reader=origin,
        method=_c.FINITE_UPDATE_COMPUTE, output_contract=_c.UPDATE_RESPONSE,
        args=_fb.UpdateArgs(model=initial.model, prior=prior,
                            observations=(_fb.ObservationUse(binding=ob.binding, reading=reading),),
                            budget=initial.update_budget),
        input_points=frozenset(inputs), numerical_view=_fixed_view(state, frozenset(inputs)),
        allocation=_fb.BootSlot(declaration=d, slot=initial.allocation.slot),
        permissions=frozenset({_fb.BootSlot(declaration=d, slot=initial.derivation.slot),
                               _fb.BootSlot(declaration=d, slot=initial.allocation.slot)}))


def _q_step(ob):
    def uses(state, pair):
        """Q* の作成の門の出発点: 版つきの要求の候補 (G6-Q-CREATE)。前の採用の確認待ちなら候補を作らない
        (作るのは確認の後。T-G6 に「待つ間に見る」操作は無いので門も呼ばない)。"""
        from ._fb_uses import Candidate, starts_of
        plan, ob = pair
        if "monitor" not in ob.points or "in:G" not in ob.points:
            return None
        if ob.desc is None and _stage3_choice(state, plan) is not ob:
            ob.candidate = None
            return None   # 段 3 の仮の選び方が今この義務を選んでいない (後回し。片づけない)
        prior = _head(plan)
        if prior == "wait":
            ob.candidate = None
            return None
        ob.candidate = _q_desc(state, plan, ob, prior)
        candidate = Candidate(contract=_c.WORK_REQUESTED, content={"desc": _encode(ob.candidate)}, use="update")
        return starts_of("更新要求を作る", {"sui.fb.work_requested/1": candidate})

    def build(state, plan_ob):
        from ._fb_core import Slot
        plan, ob = plan_ob
        desc = ob.candidate
        if desc is None or _head(plan) != desc.args.prior:
            return None
        ob.desc = desc
        ledger = state.ledger
        ob.points["uses"] = desc.input_points
        body = _Decided(inputs=tuple(ledger.record(p).id for p in sorted(desc.input_points)),
                        content=_Payload.json({"desc": _encode(desc)}), contract=_c.WORK_REQUESTED)
        prior = desc.args.prior
        parents = {ob.report, ob.binding, desc.args.observations[0].reading, ob.points["monitor"],
                   desc.reader} | ({prior} if prior is not None else set())
        return Slot(contract=_c.WORK_REQUESTED, record=_record(state, body, _RefKind.DECISION, _Role.MODEL),
                    parents=_front(ledger, parents))

    def prepared(state, plan_ob, cid):
        from ._fb_core import add_work
        plan, ob = plan_ob
        add_work(state, _fb.Compute(request=cid, desc=ob.desc), plan.boot.declaration.scope.value)

    return _Step(name="Q", build=build, on_prepared=prepared, uses=uses)


def _check_issued(state, ob, row, number, outcome):
    """K7: 発行物が factory の発行で、request・result・像・registry が要求と返答に全部合うか。"""
    from ._f_handles import require_issued
    from ._f_world import registry_view_key
    from .f_update2 import IssuedUpdate
    issued = next((item for n, item in row.issued if n == number), None)
    if issued is None:
        return "update:issued:missing"
    try:
        require_issued(issued, IssuedUpdate)
    except (TypeError, _f.FInputError, _f.FReplayMismatch):
        return "update:issued:not_issued"
    view = ob.desc.numerical_view
    if issued.request != ob.points["Q"] or _dumps(_f._encode(issued.result)) != _dumps(_encode(outcome.outputs.value["value"])):
        return "update:issued:target"
    if issued.numerical_view.boundary != view.boundary or issued.numerical_view.reader_view_key != view.reader_view_key \
            or issued.numerical_view.registry_key != view.registry_key or issued.registry_key != registry_view_key(state.registry):
        return "update:issued:view"
    return issued


def _r_step(ob, issued, first):
    def content_of(q):
        view = issued.numerical_view
        return {"request": q, "result": _f._encode(issued.result), "application_digest": issued.application_digest,
                "numerical_view": {"boundary": sorted(view.boundary), "environment": {
                    "reader_view_key": view.reader_view_key, "registry_key": view.registry_key}},
                "registry_key": issued.registry_key}

    def build(state, plan_ob):
        from ._fb_core import Slot
        plan, ob = plan_ob
        ledger = state.ledger
        q = ob.points["Q"]
        # basis は要求と最初の終わりの原報告 (段 2 の math_artifact と同じ形)。basis は R* の祖先 (F-a A-03 の時系列)
        body = _Prediction(target="belief_update", about=(ledger.record(q).id,),
                           basis=(ledger.record(q).id, ledger.record(first).id),
                           content=_Payload.json(content_of(q)), contract=_c.UPDATE_RESULT)
        return Slot(contract=_c.UPDATE_RESULT, record=_record(state, body, _RefKind.PREDICTION, _Role.MODEL),
                    parents=_front(ledger, {q, first}))

    def uses(state, pair):
        """R* の作成の門の出発点 (G6-RESULT-CREATE): 保存予定の全内容を持つ候補 (G1)。basis = Q* と最初の終わり、about = Q*。"""
        from ._fb_uses import Candidate, starts_of
        q = pair.ob.points["Q"]
        candidate = Candidate(contract=_c.UPDATE_RESULT, content=content_of(q), use="generation", basis=(q, first),
                              about=(q,), target="belief_update")
        return starts_of("更新結果を作る", {"sui.fb.update_result/1": candidate})

    return _Step(name="R", build=build, uses=uses)


def _adopt_step():
    def build(state, plan_ob):
        """K9: 比べる前の採用は、この義務より前の系列の判断が全部確認済みの時だけ求まる。同じなら A*、違えば Stale。
        比較と公開は settle のロックの中の 1 つの決定。"""
        from ._fb_core import Slot, mono_ns
        plan, ob = plan_ob
        series = _series(plan)
        earlier = series[:series.index(ob)]
        head = None
        for other in earlier:
            step = next((s for s in other.steps if s.name == "decide"), None)
            if other.final is None or (step is not None and step.slot is not None and step.slot.entry is None):
                return None
            if other.final == "adopted":
                head = other.points["A"]
        ledger = state.ledger
        origin, q, r, g = plan.boot.points["origin"], ob.points["Q"], ob.points["R"], ob.points["out:G"]
        if ob.desc.args.prior == head:
            ob.points["decision"] = "A"
            content = {"origin": origin, "model": plan.initial.model, "previous": head, "request": q,
                       "result": r, "acquisition": g}
            # 外側の inputs は本文が指す実使用の参照 (§2-5-9): origin・model・Q*・R*・G・前の採用
            uses = {origin, plan.initial.model, q, r, g} | ({head} if head else set())
            inputs = tuple(ledger.record(p).id for p in sorted(uses))
            body = _Decided(inputs=inputs, content=_Payload.json(content), contract=_c.BELIEF_ADOPTED)
            return Slot(contract=_c.BELIEF_ADOPTED, record=_record(state, body, _RefKind.DECISION, _Role.MODEL),
                        parents=_front(ledger, {r, g} | ({head} if head else set())))
        ob.points["decision"] = "stale"
        content = {"origin": origin, "request": q, "result": r, "expected_previous": ob.desc.args.prior,
                   "actual_previous": head}
        body = _Observed(route="fb", content=_Payload.json(content), contract=_c.STALE, received_ns=mono_ns(state.clock))
        return Slot(contract=_c.STALE, record=_record(state, body, _RefKind.OBSERVATION, _Role.MEMBRANE),
                    parents=_front(ledger, {r, g}))
    def uses(state, pair):
        """A* の作成の門の出発点 (G6-ADOPTION-CREATE): 採用の候補 (Q*・R*・G・予定の前の採用) を採用の用途で。"""
        from ._fb_uses import Candidate, starts_of
        plan, ob = pair
        if "R" not in ob.points or "out:G" not in ob.points:
            return None
        candidate = Candidate(contract=_c.BELIEF_ADOPTED, use="adopt", content={
            "origin": plan.boot.points["origin"], "model": plan.initial.model, "previous": ob.desc.args.prior,
            "request": ob.points["Q"], "result": ob.points["R"], "acquisition": ob.points["out:G"]})
        return starts_of("採用を作る", {"sui.fb.belief_adopted/1": candidate})

    return _Step(name="decide", build=build, uses=uses)


def _finish(state, plan, ob, row):
    """Wu の論理の終わり (INV-15) から T と、許された後続を計画する。"""
    from ._fb_think import _terminal_step, first_end
    found = first_end(state, row)
    if found is None:
        return
    number, receipt = found
    ob.done = True
    outcome = receipt.envelope.event.outcome
    first = receipt.slots[0].entry.cid
    row.knowledge = ("success" if isinstance(outcome, _fb.WorkOutputs)
                     else "failure" if isinstance(outcome, _fb.WorkFailure) else "unknown")
    ob.steps.append(_terminal_step(state, plan, row, number, receipt))
    if row.knowledge != "success":
        ob.final = ob.response = row.knowledge
        return
    value = outcome.outputs.value
    if outcome.outputs.contract != _c.UPDATE_RESPONSE or not hasattr(value, "items") \
            or set(value) != {"kind", "value"} or value["kind"] not in ("issued", "rejected", "insufficient"):
        ob.final = "issued:shape"
        _hold(plan, "update:response")
        return
    if value["kind"] != "issued":
        ob.final = ob.response = value["kind"]   # U の正常な判定 (C10)。採用に進めない
        return
    issued = _check_issued(state, ob, row, number, outcome)
    if isinstance(issued, str):
        ob.final = issued   # update:issued:missing / not_issued / target / view
        _hold(plan, "update:issued")   # K7 の理由の語
        return
    ob.steps.extend([_r_step(ob, issued, first),
                     *_acquire_steps("out", lambda plan, ob: [ob.points["R"]] if "R" in ob.points else None),
                     _adopt_step()])


def _discover(state, plan):
    """保存した B のうち、δ の口の原 Claim に義務を置く (J1)。扱えない枝は意味の不足として示す。"""
    route = plan.boot.points.get("route_config:" + plan.args["route"])
    meanings = {(e["meaning"]["name"], e["meaning"]["version"]) for e in plan.args["claims"]}
    for slot in state.bindings.values():
        if slot.entry is None:
            continue
        b = slot.record.body.content.as_json()
        if b["route"] != route or b["report"] in plan.obligations:
            continue
        item = state.ledger.record(b["report"]).body.content.as_json()["item"]
        if item["kind"] != "claim":
            _hold(plan, "delta:branch:" + item["kind"])
            continue
        contract = item["value"]["contract"]
        if (contract["name"], contract["version"]) not in meanings:
            _hold(plan, "delta:claim_meaning")
            continue
        ob = Obligation(report=b["report"], binding=slot.entry.cid)
        ob.steps = [_monitor_step(ob), *_acquire_steps(
            "in", lambda plan, ob: [ob.report, ob.binding, ob.points["monitor"], plan.points["law"],
                                    plan.points["reading"]]), _q_step(ob)]
        plan.obligations[b["report"]] = ob


class _Pair:
    """`_fb_boot.advance` に渡す (計画, 義務) の組。steps・points は義務の側。"""

    def __init__(self, plan, ob):
        self.plan, self.ob = plan, ob
        self.steps, self.points = ob.steps, ob.points

    def __iter__(self):
        return iter((self.plan, self.ob))


def advance(state) -> None:
    for number, boot in state.plans.items():
        if boot.declaration.initial is not None and boot.points.get("origin") is not None \
                and number not in state.updates:
            plan = _plan(state, boot)
            if plan is not None:
                state.updates[number] = plan
    for plan in state.updates.values():
        if not plan.steps:
            continue
        _advance(state, plan)
        if "reading" not in plan.points:
            continue
        _discover(state, plan)
        for ob in plan.obligations.values():
            if ob.desc is not None and not ob.done:
                row = state.works.get(ob.desc.work_id)
                if row is not None and isinstance(row.work, _fb.Compute):
                    from ._fb_core import _saved
                    if _saved(state, row.work.request):
                        _finish(state, plan, ob, row)
            # 保存した Q* の依存に食い違いが見えたら、まだ作っていない後続を作らない (T は作る。準備済みの記録の
            # 保存は続ける)。後続の歩は各々の出発点で同じ門を通る
            if not ob.blocked and ob.final is None and "Q" in ob.points \
                    and gate(state, [(ob.points["Q"], "update")]) == "blocked":
                _block(plan, ob)
            # 採用した A* も、その後に依存の食い違いが見えたら新しい使用 (継続の記録・評価の信念) で使えない。
            # 表示は届いた時刻 (継続を開く前か後か) によらず同じ状態の関数で出す
            if not ob.blocked and ob.final == "adopted" and "A" in ob.points \
                    and gate(state, [(ob.points["A"], "belief")]) == "blocked":
                _block(plan, ob)
            _advance(state, _Pair(plan, ob), build=lambda step, plan=plan, ob=ob: _allowed(state, plan, ob, step))
            decision = ob.points.get("decision")
            if decision is not None and ob.final is None and ob.points.get("decide") is not None:
                ob.final = "adopted" if decision == "A" else "stale"
                ob.points[decision] = ob.points["decide"]
            if ob.final == "adopted" and not ob.points.get("continued"):
                _continue(state, plan, ob)


def _continue(state, plan, ob) -> None:
    """K10: continuation が reuse_candidates/1 の時だけ、A* をきっかけに次の評価を作る。「採用したら必ず
    考え直す」の規則ではなく、宣言した差し替えられる方法 (D7)。"""
    from ._fb_think import open_continuation
    method = plan.initial.continuation
    if method is None:
        ob.points["continued"] = "none"
        return
    if method.contract != _c.REUSE_CANDIDATES or _plain(method.args) != {}             or plan.initial.generator.contract != _c.MODEL_OPERATIONS:
        _hold(plan, "continuation:method")
        ob.points["continued"] = "missing"
        return
    # 開くこと自体は記録を作らない。継続の過程の全部の記録は、きっかけの A* の閉包を毎回見る門を通る
    # (`_fb_think._root_blocked`、Z4)。開く所に別の門を重ねない
    if open_continuation(state, plan.boot, ob.points["A"]):
        ob.points["continued"] = "opened"


def referenced_predictions(state, fixed) -> frozenset:
    """固定根 fixed の祖先の記録が型つきの参照 (Decided の inputs・Prediction の about/basis) で指す派生物
    (Prediction) の閉包。評価の準備の Xnum の境界に直接足す (Prediction は出来事の祖先に入らないので、足さないと
    F-a の compiler の参照の展開が像の外に出る。段 3 では Q* の inputs の law・reading、A* の inputs の R*)。
    窓口の控えでなく、祖先の記録から毎回導く。"""
    ledger = state.ledger
    out, pending = set(), list(ledger.ancestors(frozenset(fixed)))
    seen = set()
    while pending:
        cid = pending.pop()
        if cid in seen:
            continue
        seen.add(cid)
        body = ledger.record(cid).body
        for ref in (*getattr(body, "inputs", ()), *getattr(body, "about", ()), *getattr(body, "basis", ())):
            for entry in ledger.entries_of(ref):
                if not entry.is_event and entry.cid not in out:
                    out.add(entry.cid)
                    pending.append(entry.cid)
    return frozenset(out)


def blocked(state, row, stage="入場") -> bool:
    """Wu の開始の門 (G6-START-Q): 保存した Q* を実行の用途で (ロックの中、precompute の結果だけ。stale なら今は開始しない)。
    入場は `entrance` で (ロックの外で計算し同一歩で照合)。"""
    if row.ticket_used:
        return False
    for plan in state.updates.values():
        for ob in plan.obligations.values():
            if ob.desc is not None and ob.desc.work_id == row.work.desc.work_id:
                return ob.blocked or gate(state, _enter_starts(state, row, stage)) != "open"
    return False


def entrance(state, row):
    """Wu の入場の門の材料: (出発点, ロックの中で見る安い条件)。この仕事の義務が無ければ None (門の対象外)。"""
    for plan in state.updates.values():
        for ob in plan.obligations.values():
            if ob.desc is not None and ob.desc.work_id == row.work.desc.work_id:
                return _enter_starts(state, row, "入場"), (lambda: ob.blocked)
    return None


# --- 表示 (意味 3・4・6) ---

def reading_statuses(state) -> tuple:
    out = []
    for plan in state.updates.values():
        origin = plan.boot.points.get("origin")
        for ob in plan.obligations.values():
            if ob.desc is None:
                continue
            target = ob.points.get("R")
            reached = "adopted" if ob.final == "adopted" else "acquired" if "out:G" in ob.points \
                else "generated" if target is not None else "none"
            basis = tuple(p for p in (ob.points.get("Q"), target, ob.points.get("A"), ob.points.get("stale"))
                          if p is not None)
            out.append(_fb.ReadingStatus(
                target=target if target is not None else ob.points.get("Q", _fb.Unsaved(plan=ob.desc.work_id)),
                reader=origin, reached=reached, response=ob.response if ob.response in (
                    "rejected", "insufficient", "failure", "unknown") else "none",
                adopted=ob.points.get("A"), stale=ob.points.get("stale"), selected=None,
                evidence=_fb.StatusBasis(view=None, basis=basis)))
    return tuple(out)


def pending_statuses(state) -> tuple:
    out = []
    for plan in state.updates.values():
        for reason in plan.missing:
            kind = "missing_contract" if reason.startswith("delta:") else "awaiting_evidence"
            out.append(_fb.PendingStatus(kind=kind, target=None, contract=_c.SAVED_SEGMENT_UPDATE, reason=reason,
                                         evidence=_fb.StatusBasis(view=None, basis=(plan.boot.d,))))
    return tuple(out)


def purpose_statuses(state) -> tuple:
    """意味 6: O-03 は Q* の保存で解消 (handled)、更新の目的の未達 (結果が来ない・不足・拒否・Stale) は別 (J9-c)。"""
    out = []
    for plan in state.updates.values():
        for ob in plan.obligations.values():
            if ob.final in (None, "adopted"):
                continue
            out.append(_fb.PurposeStatus(
                obligation=ob.report, o_id="O-03", condition="handle", role="belief_update",
                process=_fb.BootSlot(declaration=plan.boot.d, slot=plan.initial.process_slot),
                reader=plan.boot.points.get("origin"), target=ob.points.get("Q", ob.report), part=None,
                handled="Q" in ob.points, handed_to=None, unmet=True,
                evidence=_fb.StatusBasis(view=None, basis=tuple(p for p in (ob.report, ob.points.get("Q")) if p))))
    return tuple(out)
