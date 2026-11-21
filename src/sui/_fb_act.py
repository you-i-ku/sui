"""引受けと一歩 (紙 F-b §6-10 K36 決定 3〜8・11〜14・K36-a)。

選択 S が保存されたら、同じ採用の系列でその根が今の引受けより後に続く時だけ引受け (`sui.fb.intention/1`) を保存し、
方策 (モデルの policies) の entry の節から進める。execute の節では固定の像 E を作って一歩の要求
(`sui.fb.execute_step_requested/1`) と仕事 (`ExecuteStep`) を置き、行う係が入場して家の人の口 `perform` に E を渡すと、
家の人が宣言 (`sui.fb.execution_declaration/1`) を見て行い、結果のメモ (`sui.fb.execution_result/1`) を自分で残す (Z55)。
結果が保存されたら、観測のセルから次の節を決める (end で終わり、choose は未接続で止まる、決定 8)。結果を見立てへ通すのは
更新の計画 (`_fb_update`) で、受け身の観測との順は決定 12 で決める。

行う一歩の宣言の無い起動では引き受けない (選んだところで止まる、K35 までの形)。同じ過程の中だけ (決定 7)。
"""

from dataclasses import dataclass as _dataclass, field as _field

from . import f as _f
from . import fb as _fb
from . import fb_contracts as _c
from ._fb_boot import Step as _Step, _front, _record, _work_id
from ._fb_wire import dumps as _dumps, encode as _encode
from .ids import RefKind as _RefKind
from .records import Decided as _Decided, Payload as _Payload, Role as _Role

# 行う一歩の観測の合法な組 (呼んだ 3 つ、K36-a (エ))。語は取りに行きと同じ (K25・K26)
_CALLED = {"taken": {"result": "taken", "source_called": True},
           "empty": {"result": "empty", "source_called": True},
           "unavailable_called": {"result": "unavailable", "source_called": True}}


def symbol_of(value):
    """観測の値 {result, source_called} → 語 (呼んだ 3 つのどれでもなければ None)。"""
    for name, legal in _CALLED.items():
        if hasattr(value, "items") and dict(value) == legal and type(value["source_called"]) is bool:
            return name
    return None


@_dataclass
class Execution:
    """一歩 1 つ: 節・その節の何回目か・固定の像 E (要求の Publish で固定)・その仕事の WorkId。"""
    node: str
    occurrence: int
    trigger: object                  # (Point, slot): 引受け、または前の一歩の結果
    args: object = None              # ExecutionArgs (要求を作った時に固定)
    work_id: str | None = None
    next_handled: bool = False       # 結果から次の節を決めた


@_dataclass
class Intention:
    """引受け 1 つ (選択 S 1 つ)。steps は `_fb_boot.advance` が 1 点ずつ保存する記録の列。"""
    boot: object                     # BootPlan
    think: object                    # 選択を作った ThinkPlan
    selection: str
    evaluated: str
    selected: object                 # f.Selected
    rank: int                        # 選択の根が頼る採用の系列の位置 (最初の評価は -1)
    previous: str | None             # 置き換える前の引受け (保存済みの Point)
    steps: list = _field(default_factory=list)
    points: dict = _field(default_factory=dict)
    missing: list = _field(default_factory=list)
    executions: list = _field(default_factory=list)
    replaced_by: object = None       # 置き換えた Intention
    withheld: bool = False           # 記録は保存したが、置き換える時に食い違いが見えていたので使わない (K36-b (ス))
    applied: bool = False            # 記録の保存を受けて、置き換えるかを決めた
    outcome: str = "running"         # running / ended / stopped
    reason: str = ""
    node: str | None = None


@_dataclass
class ActPlan:
    boot: object
    intentions: list = _field(default_factory=list)
    seen: set = _field(default_factory=set)     # 引受けを判断した選択 S の Point
    conflicts: list = _field(default_factory=list)   # (選択 S, 理由): 比べられない根・同じ根の別の選択 (決定 7)


# --- 宣言とモデルを読む ---

def declaration(boot):
    """起動の宣言の行う一歩の宣言 (ExecutionDeclaration)。無ければ None。"""
    execution = boot.declaration.execution
    return execution.value if execution is not None and isinstance(execution.value, _fb.ExecutionDeclaration) else None


def _document(state, model):
    return state.ledger.record(model).body.content.as_json()["document"]


def _nodes(state, model, policy):
    """方策 policy (PolicyRef) の (entry, 節の id → 節)。読めなければ None。"""
    try:
        policies = _document(state, model)["policies"]
        found = [p for p in policies if p["id"] == policy.args["id"]]
        if len(found) != 1:
            return None
        return found[0]["entry"], {n["id"]: n for n in found[0]["nodes"]}
    except (KeyError, TypeError):
        return None


def kernel(state, model, kid):
    """モデルの核 kid (JSON)。無ければ None。"""
    try:
        found = [k for k in _document(state, model)["kernels"] if k["id"] == kid]
    except (KeyError, TypeError):
        return None
    return found[0] if len(found) == 1 else None


def _matrix(outcome):
    from fractions import Fraction
    return [[Fraction(*x) if isinstance(x, (list, tuple)) else Fraction(x) for x in row] for row in outcome["matrix"]]


def classify(state, boot, model, kid):
    """核 kid を段 4 で行えるか (決定 5): ("no_effect", "") / ("observe", "") / ("unconnected", 理由)。
    宣言した無作用 = 核の和が単位行列で、outcome が観測を出さず所要 0。行える観測の一歩 = outcome の行列がどれも対角で
    所要 0、各 outcome の観測が呼んだ 3 つの組のどれかで、宣言のセルがその核の outcome をちょうど 1 回ずつ覆い、セルの
    観測値とそのセルの outcome の観測値が一致する。それ以外 (状態を変える・所要を持つ・観測を返さない・4 組で読めない) は
    未接続 (S6)。"""
    decl = declaration(boot)
    k = kernel(state, model, kid)
    if decl is None or k is None:
        return "unconnected", "kernel_unknown"
    outcomes = k["outcomes"]
    if any(o["elapsed_ns"] != 0 for o in outcomes):
        return "unconnected", "duration"
    matrices = [_matrix(o) for o in outcomes]
    n = len(matrices[0])
    diagonal = all(m[i][j] == 0 for m in matrices for i in range(n) for j in range(n) if i != j)
    if kid in decl.no_effect:
        identity = all(sum(m[i][j] for m in matrices) == (1 if i == j else 0) for i in range(n) for j in range(n))
        if identity and all(o["evidence"] is None for o in outcomes):
            return "no_effect", ""
        return "unconnected", "no_effect_not_identity"
    if not diagonal:
        return "unconnected", "state_change"
    if any(o["evidence"] is None for o in outcomes):
        return "unconnected", "no_observation"
    if any(symbol_of(o["evidence"]["value"]) is None or o["evidence"]["kind"] != "measurement" for o in outcomes):
        return "unconnected", "outside_symbols"
    cells = decl.cells.get(kid)
    if not cells:
        return "unconnected", "cells_missing"
    covered = [name for cell in cells for name in cell.outcomes]
    if sorted(covered) != sorted(o["id"] for o in outcomes):
        return "unconnected", "cells_partition"
    by_id = {o["id"]: o for o in outcomes}
    for cell in cells:
        if cell.observation.kind != "measurement" or symbol_of(cell.observation.value) is None:
            return "unconnected", "cells_symbols"
        if any(_dumps(_f._encode(by_id[name]["evidence"]["value"])) != _dumps(_f._encode(cell.observation.value))
               for name in cell.outcomes):
            return "unconnected", "cells_symbols"
    if kid not in decl.actors:
        return "unconnected", "actor_undeclared"
    return "observe", ""


def cell_outcomes(boot, kid, value):
    """宣言のセルのうち、観測値 value を読むセルの outcome の id (無ければ None = 読み方が無い)。"""
    decl = declaration(boot)
    for cell in (decl.cells.get(kid, ()) if decl is not None else ()):
        if _dumps(_f._encode(cell.observation.value)) == _dumps(_f._encode(value)):
            return tuple(cell.outcomes)
    return None


# --- 見つける・引き受ける (決定 7) ---

def _update_plan(state, boot):
    return next((p for p in state.updates.values() if p.boot is boot), None)


def _chain(state, boot):
    plan = _update_plan(state, boot)
    return plan.chain if plan is not None else []


def _rank(state, think):
    """選択の根が頼る採用の系列の位置 = 評価が実際に読んだ根 (o の境界に見える最新の採用、K36-c ⑤。通知の cause ではない)。
    事前の根 (まだ採用が無い時に固めた評価) は -1。系列に無い採用は None (比べられない)。"""
    from ._fb_update import adoptions
    root = think.points.get("root")
    if root is None:
        return -1
    order = adoptions(state, think.boot)   # 保存の確認待ちの採用も含む並び (考える側の根と同じ数え方)
    return order.index(root) if root in order else None


def _act_plan(state, boot):
    for number, plan in state.plans.items():
        if plan is boot:
            if number not in state.acting:
                state.acting[number] = ActPlan(boot=boot)
            return state.acting[number]
    return None


def active(act):
    """今の引受け (記録を保存した、置き換えられていない最後のもの)。無ければ None。"""
    live = [i for i in act.intentions if i.replaced_by is None and not i.withheld and "intention" in i.points]
    return live[-1] if live else None


def _pending(act):
    """引受けの記録をまだ保存していない、置き換えられていない引受け (高々 1 つ)。"""
    return [i for i in act.intentions if i.replaced_by is None and "intention" not in i.points]


def _discover(state) -> None:
    """保存した選択 S から引受けを置く。同じ採用の系列で根が今の引受けより後に続く選択だけが置き換える。遅れて保存された
    古い根の選択・比べられない根の選択は事実として残し、引き受けない (到着順で勝者を作らない)。比べる相手は使える引受け
    だけ (今の引受けと、記録をまだ保存していない食い違いの無い引受け)。まだ保存していない引受けと比べて見送った選択は、
    決まりではないので次の回にもう一度比べる (保存の順で結果を変えない、決定 7・レビュー R11)。"""
    for think in list(state.thinking.values()):
        s = think.points.get("S")
        if s is None or getattr(think, "selected", None) is None or declaration(think.boot) is None:
            continue
        act = _act_plan(state, think.boot)
        if act is None or s in act.seen:
            continue
        if _held(state, think):
            act.seen.add(s)
            continue   # 食い違いの見えた選択は使わない (新しい使用、R1・R7)。今の引受けはそのまま (食い違いは消えない)
        if _starting(state, act):
            # 行う側の開始処理の途中 (使える選択を確保してから、その一歩の入場か一歩を作らない結末・使用の禁止まで) は、
            # 新しい選択で開始の対象を差し替えない。決まりではないので次の回にもう一度比べる (K36-c-a ③)
            continue
        rank = _rank(state, think)
        current = active(act)
        usable = [p for p in _pending(act) if not held_back(state, p)]   # 食い違いの見えた保存待ちは使えない (R11)
        tops = [i for i in (current, *usable) if i is not None]
        top = max(tops, key=lambda i: i.rank) if tops else None
        if rank is None or top is not None and rank == top.rank:
            # 比べられない根・同じ根の別の選択: 到着順で勝者を作らず、食い違いとして公開する (決定 7・K36-a (ウ))
            act.seen.add(s)
            act.conflicts.append((s, "incomparable_root" if rank is None else "same_root"))
            continue
        if top is not None and rank < top.rank:
            # 遅れて保存された古い根の選択: 事実として残し、今の引受けを巻き戻さない (決定 7)。比べた相手がまだ保存して
            # いない引受けなら、決まりではないので次の回にもう一度比べる (R11)
            if top is current:
                act.seen.add(s)
            continue
        act.seen.add(s)
        intention = Intention(boot=think.boot, think=think, selection=s, evaluated=think.points["EV"],
                              selected=think.selected, rank=rank,
                              previous=current.points.get("intention") if current is not None else None)
        intention.steps = [_intention_step()]
        for older in usable:
            older.replaced_by = intention   # 記録をまだ保存していない古い引受けは作らない (食い違いの見えたものは
            # 置き換えでなく食い違いで止まる = 保存されたら withheld、表示は selection_conflict、レビュー R13)
        # 今の引受けを置き換えるのは、新しい引受けの記録を保存した時 (それまで、食い違いが見えれば今のまま、R7)
        act.intentions.append(intention)


def _entered(state, intention) -> bool:
    """その引受けの一歩のどれかが入場した (開始処理が入場で終わった)。"""
    return any(e.work_id is not None and e.work_id in state.works and state.works[e.work_id].ticket_used
               for e in intention.executions)


def _starting(state, act) -> bool:
    """開始処理の途中の引受けがあるか (K36-c-a ③): 置き換えられておらず、使える (食い違いが見えていない・withheld でない)
    引受けのうち、まだ最初の一歩が入場しておらず、一歩を作らない結末 (ended / stopped) にもなっていないもの。"""
    for i in act.intentions:
        if i.replaced_by is not None or i.withheld or i.outcome != "running" or held_back(state, i):
            continue
        if not _entered(state, i):
            return True
    return False


def _held(state, think) -> bool:
    from ._fb_bind import clashed_reports
    from ._fb_think import _belief_blocked, conflicts
    return bool(conflicts(state, think, unconfirmed=True, chain=True)) \
        or _belief_blocked(state, think, clashed_reports(state))


def held_back(state, intention) -> bool:
    """選択を作った考える過程に食い違いが見えている (保存の確認待ちの報告も数える)、またはその評価が読んだ見立てが
    食い違った原報告に頼っている。一歩はその選択の新しい使用なので、引受け・一歩の要求を作らず、まだ入場していない一歩を
    入場させない (紙 F-b :888「新しい使用では新しい食い違いを検査」、K36 レビュー R1)。入場した一歩の結果は残す。"""
    return _held(state, intention.think)


def _intention_step():
    def build(state, intention):
        from ._fb_core import Slot
        if intention.replaced_by is not None or held_back(state, intention):
            return None   # 保存する前に置き換えられた引受け・食い違いの見えた選択の引受けは作らない
        ledger = state.ledger
        uses = {intention.selection} | ({intention.previous} if intention.previous else set())
        content = {"selection": intention.selection, "evaluated": intention.evaluated,
                   "previous": intention.previous}
        body = _Decided(inputs=tuple(ledger.record(p).id for p in sorted(uses)), content=_Payload.json(content),
                        contract=_c.INTENTION)
        return Slot(contract=_c.INTENTION, record=_record(state, body, _RefKind.DECISION, _Role.MODEL),
                    parents=_front(ledger, uses))
    return _Step(name="intention", build=build)


# --- 方策の進み (決定 8) ---

def _enter_node(state, intention, node_id, trigger) -> None:
    """節 node_id に着いた: execute なら一歩を足し、end で終わり、choose は未接続で止まる。"""
    perception = intention.boot.declaration.perception.value
    found = _nodes(state, perception.model, intention.selected.choice.policy)
    if found is None:
        intention.outcome, intention.reason = "stopped", "policy_unknown"
        return
    _entry, nodes = found
    node = nodes.get(node_id)
    intention.node = node_id
    if node is None:
        intention.outcome, intention.reason = "stopped", "node_unknown"
    elif node["kind"] == "end":
        intention.outcome, intention.reason = "ended", ""
    elif node["kind"] == "choose":
        intention.outcome, intention.reason = "stopped", "choose_unconnected"
    elif node["kind"] == "execute":
        occurrence = sum(1 for e in intention.executions if e.node == node_id)
        execution = Execution(node=node_id, occurrence=occurrence, trigger=trigger)
        intention.executions.append(execution)
        intention.steps.append(_request_step(execution, node["kernel"]))
    else:
        intention.outcome, intention.reason = "stopped", "node_kind"


def _request_step(execution, kid):
    drafted = {}

    def build(state, intention):
        from ._fb_core import Slot
        boot = intention.boot
        d, origin = boot.d, boot.points["origin"]
        reading = boot.points.get("execution")
        if reading is None or intention.points.get("intention") is None or held_back(state, intention):
            return None
        initial = boot.declaration.initial
        execution_allocation = boot.declaration.execution.value.allocation
        perception = boot.declaration.perception.value
        selected = intention.selected
        chain = _chain(state, boot)
        point = intention.points["intention"]
        args = _fb.ExecutionArgs(
            selection=intention.selection, evaluated=intention.evaluated, root_key=selected.root.root_key,
            draw=selected.root.draw_point, intention=point, policy=selected.choice.policy, node=execution.node,
            occurrence=execution.occurrence, action=selected.choice,
            kernel=_f.KernelRef(name="finite_kernel", version="1", args={"id": kid}), u=kid,
            model=perception.model, reading=reading, prior=chain[-1] if chain else None)
        stage = "execute:" + point + ":" + execution.node + ":" + str(execution.occurrence)
        trigger_point, trigger_slot = execution.trigger if execution.trigger is not None else (point, "intention")
        inputs = {intention.selection, intention.evaluated, point, perception.model, reading, origin, d,
                  trigger_point} | ({args.draw} if args.draw else set()) | ({args.prior} if args.prior else set())
        desc = _fb.Desc(
            work_id=_work_id(d, initial.slot, "execute_step", stage),
            process=_fb.BootSlot(declaration=d, slot=initial.value.process_slot),
            trigger=frozenset({_fb.Trigger(point=trigger_point, slot=trigger_slot)}),
            purpose="execute_step", stage_slot=stage, reader=origin, method=_c.EXECUTE_STEP,
            output_contract=_c.EXECUTION_RESULT, args=args, input_points=frozenset(inputs), numerical_view=None,
            # 一歩は行う割当を使う (考える割当と分ける。選んだ過程への帰属は process のまま、K36-c ①・⑥)
            allocation=_fb.BootSlot(declaration=d, slot=execution_allocation.slot),
            permissions=frozenset({_fb.BootSlot(declaration=d, slot=initial.slot),
                                   _fb.BootSlot(declaration=d, slot=execution_allocation.slot),
                                   _fb.BootSlot(declaration=d, slot=boot.declaration.execution.slot)}))
        drafted["desc"] = desc
        ledger = state.ledger
        body = _Decided(inputs=tuple(ledger.record(p).id for p in sorted(inputs)),
                        content=_Payload.json({"desc": _encode(desc)}), contract=_c.EXECUTE_STEP_REQUESTED)
        return Slot(contract=_c.EXECUTE_STEP_REQUESTED, record=_record(state, body, _RefKind.DECISION, _Role.MODEL),
                    parents=_front(ledger, inputs))

    def prepared(state, intention, cid):
        from ._fb_core import add_work, freeze
        desc = drafted["desc"]
        execution.args, execution.work_id = freeze(desc.args), desc.work_id
        add_work(state, _fb.ExecuteStep(request=cid, desc=desc), intention.boot.declaration.scope.value)

    return _Step(name="request:" + execution.node + ":" + str(execution.occurrence), build=build, on_prepared=prepared)


def result_of(state, execution):
    """その一歩の結果のメモ: (受付, 保存した Point | None)。まだ公開されていなければ (None, None)。"""
    row = state.works.get(execution.work_id) if execution.work_id is not None else None
    if row is None:
        return None, None
    for number, _r in row.reports:
        receipt = state.receipts.get(number)
        if receipt is not None and isinstance(receipt.envelope.event, _fb.ExecutionReport):
            slot = receipt.slots[0]
            return receipt, slot.entry.cid if slot.entry is not None else None
        if receipt is None and number in state.acquired:
            return "published", None
    return None, None


def _after_result(state, intention, execution) -> None:
    """一歩の結果が保存されたら、観測から次の節を決める (決定 8)。置き換えられた引受けの方策は進めない (決定 7)。"""
    receipt, point = result_of(state, execution)
    if point is None or execution.next_handled:
        return
    execution.next_handled = True
    if intention.replaced_by is not None:
        return
    report = receipt.envelope.event
    perception = intention.boot.declaration.perception.value
    found = _nodes(state, perception.model, intention.selected.choice.policy)
    if found is None:
        intention.outcome, intention.reason = "stopped", "policy_unknown"
        return
    node = found[1][execution.node]
    kid = node["kernel"]
    if report.outcome == "no_effect":
        k = kernel(state, perception.model, kid)
        names = tuple(o["id"] for o in k["outcomes"])
    elif report.outcome == "observed":
        names = cell_outcomes(intention.boot, kid, report.value)
        if names is None:
            intention.outcome, intention.reason = "stopped", "exception_reading_missing"
            return
    else:   # 未接続・行っていない: 一歩の理由の語で名指しして止まる (K36-a (エ)、K36-b (ク))
        intention.outcome, intention.reason = "stopped", report.reason or report.outcome
        return
    targets = {node["next"].get(name) for name in names}
    if len(targets) != 1 or None in targets:
        intention.outcome, intention.reason = "stopped", "next_unknown"
        return
    _enter_node(state, intention, targets.pop(), (point, "previous_step"))


def advance(state) -> None:
    """引受けと一歩の計画を進める (settle のロックの中)。"""
    from ._fb_boot import advance as _advance
    _discover(state)
    for act in state.acting.values():
        for intention in act.intentions:
            if "intention" in intention.points and intention.node is None and intention.outcome == "running" \
                    and intention.replaced_by is None and intention.applied and not intention.withheld:
                perception = intention.boot.declaration.perception.value
                found = _nodes(state, perception.model, intention.selected.choice.policy)
                if found is None:
                    intention.outcome, intention.reason = "stopped", "policy_unknown"
                else:
                    _enter_node(state, intention, found[0], None)
            _advance(state, intention)
            if "intention" in intention.points and intention.replaced_by is None and not intention.applied:
                # 引受けの記録を保存した: ここで前の引受けを置き換える (決定 7、R7)。置き換えは新しい引受けの使用なので、
                # この時に食い違いが見えていれば置き換えず、新しい引受けは使わない (記録は事実として残る、K36-b (ス))
                intention.applied = True
                if held_back(state, intention):
                    intention.withheld = True
                else:
                    for older in act.intentions:
                        if older is not intention and older.replaced_by is None and not older.withheld \
                                and "intention" in older.points and older.rank < intention.rank:
                            older.replaced_by = intention
            for execution in list(intention.executions):
                _after_result(state, intention, execution)


# --- 入場の門 (決定 7・同じ時に 1 歩) ---

def _execution_of(state, work_id):
    for act in state.acting.values():
        for intention in act.intentions:
            for execution in intention.executions:
                if execution.work_id == work_id:
                    return intention, execution
    return None, None


def blocking(state, row) -> tuple:
    """まだ入場していない一歩の仕事が何で止められているかの名指し (公開の状態の blocked_by、⑤ の窓の発見 2): 置き換えた
    引受け (保存前なら計画の名札) / 食い違いの見えた選択 / 行っている途中のほかの一歩の要求。止められていなければ空。"""
    if row.ticket_used or row.work.desc.purpose != "execute_step":
        return ()
    intention, _execution = _execution_of(state, row.work.desc.work_id)
    if intention is None:
        return ()
    if intention.replaced_by is not None:
        newer = intention.replaced_by
        return (newer.points.get("intention") or _fb.Unsaved(plan="intention:" + newer.selection),)
    if held_back(state, intention):
        return (intention.selection,)
    return tuple(other.work.request for other in state.works.values()
                 if other is not row and other.work.desc.purpose == "execute_step" and other.ticket_used
                 and not other.stopped)


def blocked(state, row) -> bool:
    """まだ入場していない一歩の仕事で、その引受けが置き換えられている (入場前の置き換え)、選択に食い違いが見えている
    (R1)、またはほかの一歩が行われている途中 (行う手は同時に 1 歩)。"""
    if row.ticket_used or row.work.desc.purpose != "execute_step":
        return False
    intention, _execution = _execution_of(state, row.work.desc.work_id)
    if intention is None or intention.replaced_by is not None or held_back(state, intention):
        return True
    return any(other is not row and other.work.desc.purpose == "execute_step" and other.ticket_used
               and not other.stopped for other in state.works.values())


# --- 家の人の口 perform (決定 3・5・13、K36-a (エ)) ---

def perform(state, ctx, row, execution_args):
    """係が渡した E を、その仕事の要求の E と全照合してから、宣言を見て行い、結果のメモを家の人が残す。"""
    from ._fb_core import _envelopes, _publish, wire
    with state.lock:
        ctx._require_live()
        work = row.work
        if not isinstance(work, _fb.ExecuteStep):
            raise RuntimeError("only an execute_step work port can perform")
        if wire(execution_args) != wire(work.desc.args):
            raise _fb.FbInputError(reason="shape", field="/execution")
        if ctx.performed:
            raise RuntimeError("this step has already been performed")
        ctx.performed = True
        intention, _execution = _execution_of(state, work.desc.work_id)
        boot = intention.boot
        E = work.desc.args
        try:
            entered = ctx._reading_at(row.entered_ns)
        except RuntimeError:   # 時計の出どころを名指せない: 呼ぶ前の不足 (K36-a (エ)、レビュー R2)。読みを補わない
            entered = None
        kind, reason = classify(state, boot, E.model, E.u)
        actor_name = declaration(boot).actors.get(E.u) if kind == "observe" else None
        actor = state.actors.get(actor_name) if actor_name is not None else None
        if entered is None:
            kind, reason, actor_name = "not_performed", "clock_source_unavailable", None
        elif kind == "observe" and actor is None:
            kind, reason = "not_performed", "actor_missing:" + actor_name
    item, value, outcome = None, None, kind
    if kind == "observe":
        outcome = "observed"
        try:
            returned = actor.perform(E)   # 鍵の外で (相手は待たせうる)
        except Exception as exc:   # 呼んだ・例外になった: これも観測 (決定 13)。やり直さない
            value, reason = dict(_CALLED["unavailable_called"]), type(exc).__name__
        else:
            if returned is None:
                value = dict(_CALLED["empty"])
            elif type(returned) is _fb.SourceItem:
                item, value = returned, dict(_CALLED["taken"])
            else:   # 形の合わない戻り値は取れなかった (K23-a (オ) と同じ線)
                value, reason = dict(_CALLED["unavailable_called"]), "not_a_source_item"
    with state.lock:
        from ._fb_core import mono_ns
        finished = ctx._reading(entered.source) if entered is not None else None
        raw = raw_id = None
        if item is not None:
            from ._fb_core import freeze
            from ._fb_shape import check_event
            raw = freeze(_fb.Received(route_epoch="actor:" + actor_name, media_type=item.media_type, data=item.data,
                                      claims=item.claims))
            try:
                check_event(raw)
            except _fb.FbInputError:
                raw, item = None, None
                value, reason = dict(_CALLED["unavailable_called"]), "not_saveable"
            else:
                raw_id = state.ids.new(_RefKind.OBSERVATION)
        report = _fb.ExecutionReport(work=work.desc.work_id, execution=E, value=value, outcome=outcome, reason=reason,
                                     entered=entered, finished=finished, received=raw_id, actor=actor_name)
        events = (raw, report) if raw is not None else (report,)
        envelopes = _envelopes(state, events, finished.reading.time_ns if finished is not None else mono_ns(state.clock))
        if raw is not None:
            state.raw_ids[envelopes[0].number] = raw_id
        state.acquired[envelopes[-1].number] = wire(envelopes[-1])   # 窓口が perform の封筒と見分ける (Z55)
        _publish(state, envelopes)
        row.reports.extend((e.number, e.received_ns) for e in envelopes)
    symbol = symbol_of(value) if value is not None else None
    return _fb.ExecutionResult(outcome=outcome, reason=reason, source_called=True if value is not None else None,
                               result_symbol=symbol, item=item)


# --- 公開の状態 (意味 8〜10) ---

def intention_statuses(state) -> tuple:
    out = []
    for act in state.acting.values():
        for intention in act.intentions:
            point = intention.points.get("intention")
            if point is None:
                continue
            replaced = intention.replaced_by
            out.append(_fb.IntentionStatus(point=point, selection=intention.selection,
                                           active=replaced is None and not intention.withheld,
                                           replaced_by=replaced.points.get("intention") if replaced else None))
    return tuple(out)


def policy_statuses(state) -> tuple:
    out = []
    for act in state.acting.values():
        for intention in act.intentions:
            if "intention" not in intention.points:
                continue   # 引受けの記録の保存前は方策の表示に出さない (開始処理の確保中、K36-c-b (ウ))
            outcome, reason = intention.outcome, intention.reason
            # 一度も今の引受けにならなかった引受けで食い違いが見えたものは、置き換えより食い違いを先に見せる (レビュー R14):
            # 記録をまだ保存していなければ方策の表示に出さず (K36-b (ヌ))、保存していれば selection_conflict (K36-b (ニ))
            # 開始処理の途中 (最初の一歩がまだ入場していない) で食い違いが見えた引受けも、原因を公開する (K36-c-a ③)
            if (not intention.applied or intention.withheld or not _entered(state, intention))                     and held_back(state, intention):
                outcome, reason = "stopped", "selection_conflict"
            elif intention.replaced_by is not None and outcome == "running":
                outcome, reason = "withdrawn", "replaced"
            out.append(_fb.PolicyStatus(selection=intention.selection, intention=intention.points.get("intention"),
                                        policy=intention.selected.choice.policy, node=intention.node,
                                        outcome=outcome, reason=reason))
    return tuple(out)


def execution_statuses(state) -> tuple:
    from . import _fb_update
    out = []
    for act in state.acting.values():
        for intention in act.intentions:
            for execution in intention.executions:
                if execution.args is None:
                    continue
                row = state.works.get(execution.work_id)
                receipt, point = result_of(state, execution)
                outcome, reason, retryable, called, symbol = "requested", "", True, None, None
                if receipt is not None and receipt != "published":
                    report = receipt.envelope.event
                    called = True if report.value is not None else False
                    symbol = symbol_of(report.value) if report.value is not None else None
                if row is not None and not row.ticket_used and intention.replaced_by is not None:
                    outcome, reason, retryable = "blocked", "replaced", False
                elif receipt is None:
                    outcome = "entered" if row is not None and row.ticket_used else "requested"
                elif point is None:
                    outcome, reason = "waiting_storage", "result"
                else:
                    report = receipt.envelope.event
                    retryable = False
                    outcome, reason = report.outcome, report.reason
                    if report.outcome == "observed":
                        outcome, reason, retryable = _fb_update.execution_reading(state, intention.boot, point, report)
                out.append(_fb.ExecutionStatus(execution=execution.args, request=row.work.request if row else None,
                                               result=point, outcome=outcome, reason=reason, retryable=retryable,
                                               source_called=called, result_symbol=symbol))
    return tuple(out)
