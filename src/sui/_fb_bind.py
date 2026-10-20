"""区間の報告の結びつき B (紙 F-b §2-5-7・§2-5-9・§6-8、段 1)。

測る仕事の口から来て保存した原報告のうち、有限の範囲を持つ 5 枝に、要求 k・route の実適用・
Started・時計・証拠を照合して `sui.fb.segment_binding/1` を作る。照合できなければ B を作らず、
対象つきの不足を持つ (原報告と測定は続く)。B は対応の記録で、Support・被覆・射影は段 3。
"""

from . import f as _f
from . import fb as _fb
from . import fb_contracts as _c
from ._fb_boot import _clock_source, _front, _record, fixed_view
from ._fb_wire import dumps as _dumps, encode as _encode
from .ids import RefKind as _RefKind
from .records import Observed as _Observed, Payload as _Payload, Role as _Role

_BRANCHES = (_f.MeasurementFrame, _f.Gap, _f.MeasurementUnavailable, _f.CoverageClaim, _f.CoverageUnproved)
# この版が意味を知る Claim の契約と kind (§2-5-19 の初回の 2 つ)。未知は missing_contract
_CLAIMS = {_c.NO_ARRIVAL: "no_arrival", _c.COUNT_EXACTLY_ONE: "count_exactly_one"}
# この版が B に写せる読み方の契約 (§6-8 B1)
_READINGS = (_c.FINITE_SEGMENT_PROJECTION,)


class _Hold(Exception):
    """B を作らない理由。kind は PendingStatus.kind。"""

    def __init__(self, kind, reason):
        super().__init__(reason)
        self.kind, self.reason = kind, reason


def _route(state, route_point):
    """k の route (route_config の Point) を宣言した Boot の口と、その実適用の読み。"""
    for plan in state.plans.values():
        for route_slot in plan.declaration.routes:
            if plan.points.get("route_config:" + route_slot.slot) == route_point:
                return route_slot.value, plan.applied[route_slot.slot]
    return None, None


def _contains(interval, ns) -> bool:
    lo = interval.start_ns <= ns if interval.closure.startswith("[") else interval.start_ns < ns
    hi = ns <= interval.end_ns if interval.closure.endswith("]") else ns < interval.end_ns
    return lo and hi


def _interval(item):
    if isinstance(item, _f.MeasurementFrame):
        return item.measurement_interval
    if isinstance(item, _f.MeasurementUnavailable):
        return item.requested_interval
    return item.interval


def _resolve(state, refs) -> frozenset:
    """原報告の evidence (Ref) を保存済みの記録の Point へ (§6-8 B7)。名札の写しで済ませない。"""
    out = set()
    for ref in refs:
        entries = state.ledger.entries_of(ref)
        if len(entries) != 1:
            raise _Hold("awaiting_evidence", f"evidence:{ref}")
        out.add(entries[0].cid)
    return frozenset(out)


def _reports(state, row):
    """同じ仕事の口から来て保存済みの、この k を名指す報告を論理の報告ごとにまとめる (§6-8 B2、紙 329〜340)。
    鍵は Frame が MeasurementId、境界 (started・ended・route_applied) が種類、名前の無い枝が item_slot
    (CMP-04〜08)。同じ鍵で中身が違えば食い違い、
    同じ中身は再配送で、受付の順の最初を代表にする (CID の順で選ばない)。受信 r の条件は代表でなく
    全配送に当てる (_first_r)。"""
    groups = {}
    for number, r in row.reports:
        receipt = state.receipts.get(number)
        if receipt is None or receipt.slots[0].entry is None:
            continue
        event = receipt.envelope.event
        if not (isinstance(event, _fb.SegmentReport) and event.segment == row.work.request):
            continue   # 仕事の口から来ても別の k を名乗る報告は結びつけない (原報告は残る)
        item = event.item
        if isinstance(item, _f.MeasurementFrame):
            key = ("frame", _dumps(_encode(item.measurement_id)))
        elif isinstance(item, _fb.SegmentBoundary):
            key = ("boundary", item.kind)
        elif isinstance(item, _fb.RouteAppliedItem):
            key = ("boundary", "route_applied")
        else:
            key = ("slot", event.item_slot)
        groups.setdefault(key, []).append((receipt.index, receipt.slots[0].entry.cid, r, event))
    # 代表は受付の順の最初 (Post の順ではない、R18)
    return {key: [entry[1:] for entry in sorted(group, key=lambda e: e[0])] for key, group in groups.items()}


def _clashes(reports) -> dict:
    """Clashes(X) の affected: (k, 論理の鍵) → 理由 (紙 §2-4-3「食い違いの判定は状態の関数」、
    §2-4-10 (9) の CL-SAME・CL-SEQ・CL-MEASUREMENT)。reports = [(k, 鍵ごとの配送)]。代表でなく
    保存済みの全配送で数え、受付の順に依らない。重なる鍵の理由は CL-SEQ・CL-MEASUREMENT・CL-SAME の順。"""
    same, seq, measurement = set(), {}, {}
    for k, groups in reports:
        for key, group in groups.items():
            if not _same(group):
                same.add((k, key))   # CL-SAME
            if key[0] != "frame":
                continue
            for _cid, _r, event in group:
                item = event.item
                seq.setdefault((k, item.route_epoch, item.sample_seq), set()).add((k, key))   # CL-SEQ
                found = measurement.setdefault(key[1], (set(), set()))   # CL-MEASUREMENT: 区間をまたぐ同じ MeasurementId
                found[0].add(k)
                found[1].add(_dumps(_encode(item)))
    out = {pair: "report:identity" for pair in same}
    for mid, (segments, contents) in measurement.items():
        if len(segments) > 1 and len(contents) > 1:
            out.update({(k, ("frame", mid)): "frame:measurement" for k in segments})
    out.update({pair: "frame:sample_seq" for pairs in seq.values() if len(pairs) > 1 for pair in pairs})
    return out


def _first_r(group) -> int:
    """論理の報告の受信 r の条件に使う読み: 配送のうち最も早い r (全配送で条件を満たすのと同じ)。"""
    return min(r for _cid, r, _event in group)


def _same(group) -> bool:
    return len({_dumps(_encode(event.item)) for _cid, _r, event in group}) == 1


def _started(state, row, groups, source):
    """代表の Started (Point, 読みの ns)。無ければ None。読みはホストが観測した入場より前・
    自分の受信 r より後であってはならない (B6)。"""
    group = groups.get(("boundary", "started"))
    if not group:
        return None
    if not _same(group):
        raise _Hold("conflict", "started:twice")
    cid, _r, event = group[0]
    r = _first_r(group)
    item = event.item
    if item.work != row.work.desc.work_id:
        raise _Hold("conflict", "started:work")
    reading = item.reading
    if not isinstance(reading, _fb.ReadingClock):
        raise _Hold("awaiting_evidence", "started:reading_unavailable")
    if reading.source != source or reading.reading.run != state.clock.run:
        raise _Hold("conflict", "started:clock")
    ns = reading.reading.time_ns
    if row.entered_ns is None or ns < row.entered_ns or ns > r:
        raise _Hold("conflict", "started:time")
    return cid, ns


def _check_window(state, interval, r, *, future_ok):
    """有限の区間の時計 (同じ run)・端の順・完了窓 end ≤ 原報告の受信 r (未来の窓を許す枝を除く)。"""
    if interval.clock != state.clock.run or interval.start_ns > interval.end_ns:
        raise _Hold("conflict", "interval:clock")
    if not future_ok and interval.end_ns > r:
        raise _Hold("conflict", "interval:after_receipt")


def _check_branch(state, item, r, started_ns, applied_ns, config):
    """報告の種類ごとの route・時刻・契約の条件 (§2-5-7 の表 744〜752 行)。"""
    epochs = {item.route_epoch}
    if isinstance(item, _f.MeasurementFrame):
        epochs.add(item.measurement_id.route_epoch)
        if item.gap is not None:
            epochs.add(item.gap.route_epoch)
    # 実適用した受け口の設定と同じ route の報告だけ (R03)。設定の照合は正準の bytes で (R14)
    applied = state.routes.get(config.route_epoch)
    if epochs != {config.route_epoch} or applied is None \
            or _dumps(_f._encode(applied[0])) != _dumps(_f._encode(config)):
        raise _Hold("conflict", "route:epoch")
    interval = _interval(item)
    _check_window(state, interval, r, future_ok=isinstance(item, _f.CoverageUnproved))
    if isinstance(item, _f.MeasurementFrame):
        if item.gap is not None:   # 内包の Gap にも同じ時計と完了窓の条件 (R17)
            _check_window(state, item.gap.interval, r, future_ok=False)
        actual = item.actual_time
        if not isinstance(actual, _f.ClockReading):
            raise _Hold("awaiting_evidence", "frame:actual_time")   # r・窓端で補わない
        if actual.run != state.clock.run or not _contains(interval, actual.time_ns) \
                or actual.time_ns < started_ns or actual.time_ns < applied_ns:
            raise _Hold("conflict", "frame:actual_time")
    elif isinstance(item, _f.CoverageClaim):
        if _CLAIMS.get(item.contract) != item.kind:
            raise _Hold("missing_contract", "claim:contract")
        # 窓全体の主張: 測り始めと設定の実効が窓の始まり以前
        if started_ns > interval.start_ns or applied_ns > interval.start_ns:
            raise _Hold("conflict", "claim:window")


def _plan(state, row, report, r, event, groups, source):
    k, route_point = row.work.request, row.work.desc.args.route
    route, applied_ns = _route(state, route_point)
    if route is None or route.reading_contract is None:
        raise _Hold("missing_contract", "reading_contract")
    if route.reading_contract not in _READINGS:
        raise _Hold("missing_contract", "reading_contract")
    if source is None:
        raise _Hold("awaiting_evidence", "clock")
    started = _started(state, row, groups, source)
    if started is None:
        raise _Hold("awaiting_evidence", "started")
    started_point, started_ns = started
    item = event.item
    _check_branch(state, item, r, started_ns, applied_ns, route.config)
    refs = tuple(getattr(item, "evidence", ()))
    if isinstance(item, _f.MeasurementFrame) and item.gap is not None:
        refs += tuple(item.gap.evidence)   # 内包の Gap の証拠も解決する (R09)
    evidence = _resolve(state, refs)
    # 論理の鍵 (§6-8 B2): 同じ証拠を固定した作り直しは同じ B。全内容の照合は台帳の write が行う
    key = _dumps({"report": report, "reading": _encode(route.reading_contract), "route": route_point,
                  "evidence": sorted(evidence), "started": started_point, "clock": [source]})
    if key in state.bindings:
        return
    boundary = frozenset({k, report, route_point, started_point, source, *evidence})
    view = fixed_view(state, boundary)
    content = {"segment": k, "report": report, "route": route_point,
               "reading_contract": _encode(route.reading_contract), "evidence": sorted(evidence),
               # B3: applied は G2 の実適用を照合した route_config。Ongoing の有限の報告は ended を要らない
               "generation": {"applied": route_point, "started": started_point, "ended": None},
               "clock": [source], "view": _encode(view)}
    from ._fb_core import Slot, mono_ns
    body = _Observed(route="fb", content=_Payload.json(content), contract=_c.SEGMENT_BINDING,
                     received_ns=mono_ns(state.clock))
    slot = Slot(contract=_c.SEGMENT_BINDING, record=_record(state, body, _RefKind.OBSERVATION, _Role.MEMBRANE),
                parents=_front(state.ledger, {k, report, route_point, started_point, source, *evidence}))
    slot.prepared = state.ledger.prepare(slot.record, slot.parents)
    state.bindings[key] = slot


def bind(state) -> None:
    """保存済みの 5 枝の原報告を照合して B を計画し、1 点ずつ保存する。不足は binding_missing に。"""
    from ._fb_core import save
    source = _clock_source(state)
    rows = [(row, _reports(state, row)) for row in state.works.values() if isinstance(row.work, _fb.MeasureSegment)]
    clashes = _clashes([(row.work.request, groups) for row, groups in rows])
    for row, groups in rows:
        for key, group in groups.items():
            reason = clashes.get((row.work.request, key))
            if reason is not None:
                # 食い違いの鍵の報告はどれも結びつけない。境界も有限の報告の有無に関わらず示す
                for cid, _r, _event in group:
                    state.binding_missing[cid] = _Hold("conflict", reason)
                continue
            if not isinstance(group[0][2].item, _BRANCHES):
                continue
            report, _r, event = group[0]
            r = _first_r(group)
            try:
                _plan(state, row, report, r, event, groups, source)
            except _Hold as hold:
                state.binding_missing[report] = hold
            else:
                state.binding_missing.pop(report, None)
    for slot in state.bindings.values():
        save(state, slot)
